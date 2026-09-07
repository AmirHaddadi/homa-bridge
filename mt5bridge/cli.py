"""Single entrypoint for every terminal interaction. Run via run.sh, e.g.:

  ./run.sh state
  ./run.sh tick gold
  ./run.sh analyze gold --tf M1 M5 M15 --count 30
  ./run.sh symbols nas
  ./run.sh place gold --type buy_limit --entry 4433.0 --sl 4430.5 --tp 4440.0
  ./run.sh cancel 104808417
  ./run.sh close 104808417

This replaces writing a new one-off .py script for every request.
"""
import argparse
import json
import sys

from . import state, market_data, orders, config, strategies, strategy_state


def _print(obj):
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def build_parser():
    p = argparse.ArgumentParser(prog="mt5bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("state", help="open positions + pending orders + account info")

    t = sub.add_parser("tick", help="live bid/ask + symbol info")
    t.add_argument("symbol")

    a = sub.add_parser("analyze", help="multi-timeframe candle snapshot")
    a.add_argument("symbol")
    a.add_argument("--tf", nargs="+", default=config.DEFAULT_TIMEFRAMES)
    a.add_argument("--count", type=int, default=config.DEFAULT_CANDLE_COUNT)

    s = sub.add_parser("symbols", help="search broker symbol list by keyword")
    s.add_argument("keywords", nargs="+")

    pl = sub.add_parser("place", help="place a pending order (protocol caps enforced)")
    pl.add_argument("symbol")
    pl.add_argument("--type", required=True, choices=["buy_limit", "sell_limit", "buy_stop", "sell_stop"])
    pl.add_argument("--entry", type=float, required=True)
    pl.add_argument("--sl", type=float, required=True)
    pl.add_argument("--tp", type=float, required=True)
    pl.add_argument("--lot", type=float, default=None,
                     help="omit to auto-size from MAX_LOSS_USD and the SL distance")
    pl.add_argument("--comment", default="scalp-agent")
    pl.add_argument("--long-term", action="store_true", dest="long_term",
                     help="long-term swing exception: separate magic, exempt from "
                          "MAX_OPEN_POSITIONS and scalp caps, risk cap $15, no profit cap")

    c = sub.add_parser("cancel", help="cancel a pending order by ticket")
    c.add_argument("ticket", type=int)

    cl = sub.add_parser("close", help="market-close an open position by ticket")
    cl.add_argument("ticket", type=int)

    h = sub.add_parser("history", help="deal history for a position ticket (for journaling)")
    h.add_argument("ticket", type=int)

    sg = sub.add_parser("signal", help="evaluate a strategy against live data (proposes only, never places orders)")
    sg.add_argument("strategy", choices=list(strategies.STRATEGIES))
    sg.add_argument("symbol")
    sg.add_argument("--count", type=int, default=200)

    bl = sub.add_parser("burn-leg", help="mark a strategy's leg as already stopped-out so it won't be re-signaled")
    bl.add_argument("strategy", choices=list(strategies.STRATEGIES))
    bl.add_argument("symbol")
    bl.add_argument("leg_start", help="the 'leg_start' value from that trade's original signal, e.g. '2026-09-05 14:30'")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.cmd == "state":
        _print(state.get_state())
    elif args.cmd == "tick":
        _print(market_data.get_tick(config.resolve_symbol(args.symbol)))
    elif args.cmd == "analyze":
        _print(market_data.multi_tf_snapshot(config.resolve_symbol(args.symbol), args.tf, args.count))
    elif args.cmd == "symbols":
        _print(market_data.find_symbols(args.keywords))
    elif args.cmd == "place":
        res = orders.place_pending(
            config.resolve_symbol(args.symbol), args.type, args.entry, args.sl, args.tp,
            lot=args.lot, comment=args.comment, long_term=args.long_term,
        )
        _print(res)
        if not res.get("ok"):
            sys.exit(1)
    elif args.cmd == "cancel":
        res = orders.cancel_order(args.ticket)
        _print(res)
        if not res.get("ok"):
            sys.exit(1)
    elif args.cmd == "close":
        res = orders.close_position(args.ticket)
        _print(res)
        if not res.get("ok"):
            sys.exit(1)
    elif args.cmd == "history":
        _print(state.get_deals_for_position(args.ticket))
    elif args.cmd == "signal":
        strat = strategies.get(args.strategy)
        symbol = config.resolve_symbol(args.symbol)
        snapshot = market_data.multi_tf_snapshot(symbol, ["M1", "M5", "M15", "H1"], args.count)
        burned = strategy_state.load_burned_legs(args.strategy, symbol)
        _print(strat.evaluate(snapshot, burned_legs=burned))
    elif args.cmd == "burn-leg":
        symbol = config.resolve_symbol(args.symbol)
        strategy_state.mark_leg_burned(args.strategy, symbol, args.leg_start)
        _print({"ok": True, "strategy": args.strategy, "symbol": symbol, "burned_leg": args.leg_start})


if __name__ == "__main__":
    main()
