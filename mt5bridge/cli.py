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

from . import state, market_data, orders, config, strategies, strategy_state, draw


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

    m = sub.add_parser("modify", help="move SL/TP of an open position (trailing to break-even etc.)")
    m.add_argument("ticket", type=int)
    m.add_argument("--sl", type=float, default=None)
    m.add_argument("--tp", type=float, default=None)

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

    _build_draw_parser(sub)

    return p


def _build_draw_parser(sub):
    """`draw` -- push trend lines / order-block rectangles / geometry to the chart
    via the HomaDraw expert. Times are server time, 'YYYY-MM-DD HH:MM' (as `analyze`
    prints). Colours: a kind (bear/bull/neutral/info) or raw 'R,G,B' or 'clrRed'."""
    d = sub.add_parser("draw", help="draw trend lines / order blocks / shapes on the chart")
    ds = d.add_subparsers(dest="draw_cmd", required=True)

    def _common(sp, with_kind=True):
        sp.add_argument("--id", dest="shape_id", default=None, help="stable id (auto if omitted)")
        sp.add_argument("--label", default=None)
        if with_kind:
            sp.add_argument("--kind", default="neutral", help="bear|bull|neutral|info | R,G,B | clrName")
        sp.add_argument("--width", type=int, default=None)
        sp.add_argument("--style", default=None, choices=["solid", "dash", "dot"])

    ob = ds.add_parser("ob", help="rectangular order block: two (time, price) corners")
    ob.add_argument("symbol"); ob.add_argument("t1"); ob.add_argument("p1", type=float)
    ob.add_argument("t2"); ob.add_argument("p2", type=float)
    ob.add_argument("--no-fill", action="store_true")
    _common(ob)

    ln = ds.add_parser("line", help="trend line: two (time, price) anchor points")
    ln.add_argument("symbol"); ln.add_argument("t1"); ln.add_argument("p1", type=float)
    ln.add_argument("t2"); ln.add_argument("p2", type=float)
    ln.add_argument("--no-ray", action="store_true", help="do not extend to the right")
    _common(ln)

    hl = ds.add_parser("hline", help="horizontal price line")
    hl.add_argument("symbol"); hl.add_argument("price", type=float)
    _common(hl)

    vl = ds.add_parser("vline", help="vertical time line")
    vl.add_argument("symbol"); vl.add_argument("time")
    _common(vl)

    for name, npt in (("tri", 3), ("ellipse", 3)):
        g = ds.add_parser(name, help=f"{'triangle' if name=='tri' else 'ellipse'}: {npt} (time, price) points")
        g.add_argument("symbol")
        for i in range(1, npt + 1):
            g.add_argument(f"t{i}"); g.add_argument(f"p{i}", type=float)
        _common(g)

    tx = ds.add_parser("text", help="text note anchored at (time, price)")
    tx.add_argument("symbol"); tx.add_argument("time"); tx.add_argument("price", type=float)
    tx.add_argument("message")
    _common(tx, with_kind=True)
    tx.add_argument("--font-size", type=int, default=10, dest="font_size")

    ds.add_parser("list", help="show the current shape document")
    rm = ds.add_parser("rm", help="remove one shape by id")
    rm.add_argument("shape_id")
    cl = ds.add_parser("clear", help="remove all shapes (or all for one symbol)")
    cl.add_argument("--symbol", default=None)


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
    elif args.cmd == "modify":
        res = orders.modify_position(args.ticket, sl=args.sl, tp=args.tp)
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
    elif args.cmd == "draw":
        _print(_dispatch_draw(args))


_KIND_TO_COLOR = {"bear": "220,70,70", "bull": "60,170,110",
                  "neutral": "150,150,160", "info": "90,160,230"}


def _colour(kind: str) -> str:
    return _KIND_TO_COLOR.get(kind, kind)   # pass raw 'R,G,B' / 'clrName' through


def _dispatch_draw(args):
    dc = args.draw_cmd
    if dc == "list":
        return draw.load()
    if dc == "rm":
        return draw.remove(args.shape_id)
    if dc == "clear":
        return draw.clear(args.symbol)

    sym = config.resolve_symbol(args.symbol)
    kind = getattr(args, "kind", "neutral")

    if dc == "ob":
        return draw.order_block(sym, args.t1, args.p1, args.t2, args.p2, kind=kind,
                                shape_id=args.shape_id, label=args.label,
                                fill=not args.no_fill, width=args.width or 1)
    if dc == "line":
        return draw.trendline(sym, args.t1, args.p1, args.t2, args.p2, kind=kind,
                              shape_id=args.shape_id, label=args.label,
                              width=args.width or 2, style=args.style or "solid",
                              ray_right=not args.no_ray)
    if dc == "hline":
        return draw.hline(sym, args.price, kind=kind, shape_id=args.shape_id,
                          label=args.label, style=args.style or "dash",
                          width=args.width or 1)

    # generic geometry -> draw.put directly
    if dc == "vline":
        shape = {"type": "vline", "points": [[args.time, None]],
                 "text": args.label or ""}
    elif dc in ("tri", "ellipse"):
        npt = 3
        pts = [[getattr(args, f"t{i}"), float(getattr(args, f"p{i}"))] for i in range(1, npt + 1)]
        shape = {"type": "triangle" if dc == "tri" else "ellipse", "points": pts,
                 "text": args.label or "", "fill": False}
    elif dc == "text":
        shape = {"type": "text", "points": [[args.time, float(args.price)]],
                 "text": args.message, "font_size": args.font_size}
    else:
        raise SystemExit(f"unhandled draw command {dc!r}")

    shape["symbol"] = sym
    shape["id"] = args.shape_id or draw._auto_id(dc, sym)
    shape["color"] = _colour(kind)
    if args.width:
        shape["width"] = args.width
    if getattr(args, "style", None):
        shape["style"] = args.style
    return draw.put(shape)


if __name__ == "__main__":
    main()
