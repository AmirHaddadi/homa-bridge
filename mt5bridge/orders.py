"""All order placement/cancellation/closing. Every entry re-checks capacity and
risk against config caps at execution time (price can drift between a proposal
and confirmation) -- never trust numbers computed earlier in the conversation."""
from . import connection, config, risk

_PENDING_TYPE_NAMES = {"buy_limit", "sell_limit", "buy_stop", "sell_stop"}


def _resolve_type(mt5, order_type: str):
    mapping = {
        "buy": mt5.ORDER_TYPE_BUY,
        "sell": mt5.ORDER_TYPE_SELL,
        "buy_limit": mt5.ORDER_TYPE_BUY_LIMIT,
        "sell_limit": mt5.ORDER_TYPE_SELL_LIMIT,
        "buy_stop": mt5.ORDER_TYPE_BUY_STOP,
        "sell_stop": mt5.ORDER_TYPE_SELL_STOP,
    }
    key = order_type.lower()
    if key not in mapping:
        raise ValueError(f"unknown order type {order_type!r}, expected one of {list(mapping)}")
    return mapping[key]


def _side_of(order_type: str) -> str:
    return "BUY" if order_type.lower().startswith("buy") else "SELL"


def _structure_check(order_type: str, entry: float, tick) -> str | None:
    """Returns an error string if the pending price no longer makes sense
    given the live tick, else None."""
    t = order_type.lower()
    if t == "buy_limit" and tick.ask <= entry:
        return f"ask {tick.ask} already <= buy_limit entry {entry}; structure invalidated"
    if t == "sell_limit" and tick.bid >= entry:
        return f"bid {tick.bid} already >= sell_limit entry {entry}; structure invalidated"
    if t == "buy_stop" and tick.ask >= entry:
        return f"ask {tick.ask} already >= buy_stop entry {entry}; structure invalidated"
    if t == "sell_stop" and tick.bid <= entry:
        return f"bid {tick.bid} already <= sell_stop entry {entry}; structure invalidated"
    return None


def place_pending(symbol: str, order_type: str, entry: float, sl: float, tp: float,
                   lot: float | None = None, comment: str = "scalp-agent",
                   magic: int | None = None, long_term: bool = False) -> dict:
    if order_type.lower() not in _PENDING_TYPE_NAMES:
        return {"ok": False, "reason": f"order_type must be one of {_PENDING_TYPE_NAMES}"}

    if magic is None:
        magic = config.LONG_TERM_MAGIC if long_term else config.MAGIC
    if long_term and comment == "scalp-agent":
        comment = "long-term-swing"

    side = _side_of(order_type)
    with connection.session() as mt5:
        positions = mt5.positions_get() or ()
        orders = mt5.orders_get() or ()
        # Long-term swing tickets are exempt from the scalp capacity cap and do
        # not count toward it (see config.LONG_TERM_MAGIC). The cap is PER SYMBOL:
        # one scalp order/position per instrument, so gold + NDX can run at once.
        if not long_term:
            scalp_open = sum(1 for p in positions
                             if p.magic != config.LONG_TERM_MAGIC and p.symbol == symbol) \
                       + sum(1 for o in orders
                             if o.magic != config.LONG_TERM_MAGIC and o.symbol == symbol)
            if scalp_open >= config.MAX_OPEN_POSITIONS:
                return {
                    "ok": False,
                    "reason": f"MAX_OPEN_POSITIONS reached for {symbol}, cancel/close existing first",
                    "positions": len(positions), "orders": len(orders),
                }

        acc = mt5.account_info()
        term = mt5.terminal_info()
        if not acc or not term or not term.trade_allowed or not acc.trade_allowed or not acc.trade_expert:
            return {"ok": False, "reason": "trading not allowed (terminal/account/expert flag)"}

        sinfo = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if sinfo is None or tick is None:
            return {"ok": False, "reason": f"symbol info unavailable for {symbol}"}

        structure_error = _structure_check(order_type, entry, tick)
        if structure_error:
            return {"ok": False, "reason": structure_error, "bid": tick.bid, "ask": tick.ask}

        if long_term:
            max_loss_usd = config.LONG_TERM_MAX_LOSS_USD
            max_profit_usd = config.LONG_TERM_MAX_PROFIT_USD
        else:
            max_loss_usd = config.max_loss_for(symbol)
            max_profit_usd = config.max_profit_for(symbol)

        if lot is None:
            lot = risk.compute_lot_for_risk(
                entry, sl, max_loss_usd, sinfo.trade_contract_size,
                sinfo.volume_min, sinfo.volume_step, config.MAX_LOT,
            )

        risk_usd, reward_usd = risk.compute_risk_reward(entry, sl, tp, lot, sinfo.trade_contract_size, side)
        errors = risk.validate(risk_usd, reward_usd, lot, max_loss_usd, max_profit_usd)
        if errors:
            return {
                "ok": False, "reason": "; ".join(errors),
                "lot": lot, "risk_usd": risk_usd, "reward_usd": reward_usd,
            }

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot,
            "type": _resolve_type(mt5, order_type),
            "price": entry,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        return {
            "ok": result.retcode == mt5.TRADE_RETCODE_DONE,
            "retcode": result.retcode,
            "broker_comment": result.comment,
            "ticket": result.order,
            "lot": lot,
            "risk_usd": round(risk_usd, 2),
            "reward_usd": round(reward_usd, 2),
            "rr": round(reward_usd / risk_usd, 2) if risk_usd > 0 else None,
            "magic": magic,
            "long_term": long_term,
            "bid": tick.bid, "ask": tick.ask,
        }


def cancel_order(ticket: int) -> dict:
    with connection.session() as mt5:
        result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
        return {
            "ok": result.retcode == mt5.TRADE_RETCODE_DONE,
            "retcode": result.retcode,
            "broker_comment": result.comment,
        }


def modify_position(ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
    """Move the stop-loss / take-profit of an OPEN position (TRADE_ACTION_SLTP).

    Used for trailing a stop to break-even and beyond. Passing None for a level
    keeps the position's current value for that level. A protective trail must
    not loosen risk, so the caller is trusted to pass a sane stop -- this only
    guards against the obvious wrong-side mistake.
    """
    with connection.session() as mt5:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"ok": False, "reason": f"no open position with ticket {ticket}"}
        pos = positions[0]
        new_sl = pos.sl if sl is None else float(sl)
        new_tp = pos.tp if tp is None else float(tp)
        tick = mt5.symbol_info_tick(pos.symbol)
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        if sl is not None and tick is not None:
            if is_buy and new_sl >= tick.bid:
                return {"ok": False, "reason": f"SL {new_sl} not below price {tick.bid} for a long"}
            if not is_buy and new_sl <= tick.ask:
                return {"ok": False, "reason": f"SL {new_sl} not above price {tick.ask} for a short"}
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": pos.ticket,
            "sl": new_sl,
            "tp": new_tp,
        })
        return {
            "ok": result.retcode == mt5.TRADE_RETCODE_DONE,
            "retcode": result.retcode,
            "broker_comment": result.comment,
            "sl": new_sl,
            "tp": new_tp,
            "entry": pos.price_open,
        }


def close_position(ticket: int, deviation: int = 20) -> dict:
    with connection.session() as mt5:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"ok": False, "reason": f"no open position with ticket {ticket}"}
        pos = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if pos.type == mt5.POSITION_TYPE_BUY:
            order_type, price = mt5.ORDER_TYPE_SELL, tick.bid
        else:
            order_type, price = mt5.ORDER_TYPE_BUY, tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": pos.ticket,
            "price": price,
            "deviation": deviation,
            "magic": pos.magic,
            "comment": "scalp-agent-close",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        return {
            "ok": result.retcode == mt5.TRADE_RETCODE_DONE,
            "retcode": result.retcode,
            "broker_comment": result.comment,
            "close_price": price,
        }
