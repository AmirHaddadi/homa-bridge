"""Ticks and multi-timeframe candle snapshots. Each public function opens exactly
one mt5 session regardless of how many timeframes are requested."""
from datetime import datetime, timezone

from . import connection, config


def _tf_map(mt5):
    return {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


def _tick(mt5, symbol):
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        raise RuntimeError(f"no tick/symbol info for {symbol}: {mt5.last_error()}")
    return {
        "time": datetime.utcfromtimestamp(tick.time).strftime("%Y-%m-%d %H:%M:%S"),
        "bid": tick.bid,
        "ask": tick.ask,
        "spread_points": info.spread,
        "digits": info.digits,
        "contract_size": info.trade_contract_size,
        "tick_value": info.trade_tick_value,
        "tick_size": info.trade_tick_size,
        "trade_stops_level": info.trade_stops_level,
        "volume_min": info.volume_min,
        "volume_step": info.volume_step,
    }


def _candles(mt5, symbol, timeframe, count):
    tfmap = _tf_map(mt5)
    tf = tfmap.get(timeframe.upper())
    if tf is None:
        raise ValueError(f"unknown timeframe {timeframe!r}, expected one of {list(tfmap)}")
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None:
        raise RuntimeError(f"no candle data for {symbol} {timeframe}: {mt5.last_error()}")
    return [
        {
            "time": datetime.utcfromtimestamp(r["time"]).strftime("%Y-%m-%d %H:%M"),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["tick_volume"]),
        }
        for r in rates
    ]


def get_tick(symbol: str) -> dict:
    with connection.session() as mt5:
        return _tick(mt5, symbol)


def get_candles(symbol: str, timeframe: str = "M5", count: int = config.DEFAULT_CANDLE_COUNT) -> list:
    with connection.session() as mt5:
        mt5.symbol_select(symbol, True)
        return _candles(mt5, symbol, timeframe, count)


def multi_tf_snapshot(symbol: str, timeframes=None, count: int = config.DEFAULT_CANDLE_COUNT) -> dict:
    """One mt5 session, tick + every requested timeframe. This is the function
    to use for top-down (M1->H4) analysis instead of calling get_tick/get_candles
    repeatedly."""
    timeframes = timeframes or config.DEFAULT_TIMEFRAMES
    with connection.session() as mt5:
        mt5.symbol_select(symbol, True)
        snap = {"symbol": symbol, "tick": _tick(mt5, symbol)}
        for tf in timeframes:
            snap[tf] = _candles(mt5, symbol, tf, count)
        return snap


def find_symbols(keywords) -> list:
    """Search all broker symbols for any of the given keywords (case-insensitive
    substring match). Useful for discovering exact broker naming, e.g. NDXUSD!."""
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k.upper() for k in keywords]
    with connection.session() as mt5:
        syms = mt5.symbols_get() or ()
        return [
            {"name": s.name, "visible": s.visible, "path": s.path}
            for s in syms
            if any(k in s.name.upper() for k in keywords)
        ]
