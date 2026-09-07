"""Account/position/order state queries."""
from . import connection, config


def _tag(row: dict) -> dict:
    row["long_term"] = row.get("magic") == config.LONG_TERM_MAGIC
    return row


def get_state() -> dict:
    with connection.session() as mt5:
        positions = mt5.positions_get() or ()
        orders = mt5.orders_get() or ()
        account = mt5.account_info()
        pos = [_tag(p._asdict()) for p in positions]
        ords = [_tag(o._asdict()) for o in orders]
        return {
            "positions": pos,
            "orders": ords,
            "account": account._asdict() if account else None,
            "scalp_open_count": sum(1 for r in pos + ords if not r["long_term"]),
            "long_term_count": sum(1 for r in pos + ords if r["long_term"]),
        }


def open_count() -> int:
    """Non-long-term positions + pending orders combined (what MAX_OPEN_POSITIONS caps)."""
    s = get_state()
    return s["scalp_open_count"]


def get_deals_for_position(position_ticket: int) -> list:
    """All deals (open + close) belonging to a position ticket -- what you need
    to journal a closed trade (fill price/time, close price/time, profit, reason)."""
    with connection.session() as mt5:
        deals = mt5.history_deals_get(position=position_ticket) or ()
        return [d._asdict() for d in deals]
