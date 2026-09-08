"""'Claude Wolf' (کلاد گرگ وال‌استریت) v1 -- a liquidity-sweep / stop-hunt
reclaim scalp, written from scratch by Claude (the trading agent).

This is deliberately a DIFFERENT idea from amir_trade (which trades shallow
pullback continuation) and it does NOT reuse amir_trade's risk numbers. Its
whole edge is one recurring market micro-event: price pokes just past an
obvious recent swing level to trip resting stop orders, fails to hold there,
and snaps back inside within a candle or two. We fade that failed break in
the direction of the higher-timeframe trend.

Own risk model (nothing inherited):
  - fixed structural risk budget: RISK_USD_CAP (lot sized to it, capped at config.MAX_LOT)
  - fixed reward: TARGET_RR x the actual structural risk
  - a hard time-stop: if neither SL nor TP is touched within TIME_STOP_BARS
    M1 candles, the trade is abandoned (the sweep-reclaim thesis has a short
    shelf life; a scalp that hasn't worked in ~40 minutes is wrong)

Pipeline (H1 -> M5 -> M1):
  1. H1 trend filter        - EMA21 vs EMA55, price on the right side
  2. M5 liquidity level     - the most extreme established swing high/low in a
                              lookback window (excluding the last few bars so
                              it's a level the market has had time to 'see')
  3. M1 sweep + reclaim     - price traded beyond that level in the last few
                              M1 candles, and the just-closed candle closed
                              back inside it, as a real body in the trend
                              direction
  4. Entry                  - a stop order just past the reclaim candle's
                              extreme (only fill if momentum actually follows
                              through)
  5. Risk gate              - SL beyond the sweep wick; if that distance
                              doesn't fit RISK_USD_CAP at the min lot, REJECT
  6. Filters                - session window, volatility-spike guard, and one
                              signal per swept level (burned_legs)

Same contract as every other strategy: proposes a signal dict only, never
touches orders. Execution goes through place_pending() + "CONFIRM ENTRY".
"""
from datetime import datetime, time as dtime

from . import base
from .. import config, risk

NAME = "claude_wolf"

SESSION_START_UTC = dtime(7, 0)    # London open
SESSION_END_UTC = dtime(20, 0)    # into the NY afternoon

# --- own risk model ---
RISK_USD_CAP = 6.0                 # structural risk budget; lot sized to it, capped at config.MAX_LOT
TARGET_RR = 3.0                    # fixed reward multiple of the real risk
MIN_RISK_POINTS = 0.8              # reject setups whose stop is unrealistically tight
TIME_STOP_BARS = 25               # M1 candles; abandon the scalp if unresolved

# --- structure tuning (gold M1/M5), fixed by a 100-day grid search 2026-09-06 ---
LEVEL_LOOKBACK = 36               # M5 bars to search for the swing level
LEVEL_EXCLUDE_RECENT = 3         # ...ignoring the last few (must be established)
SWEEP_WINDOW = 3                  # M1 candles the sweep+reclaim must happen within
MIN_PEN_POINTS = 0.5             # the sweep must pierce the level by at least this (a real hunt)
RECLAIM_STRENGTH = 0.5           # reclaim candle close must be within this fraction of its extreme
SL_BUFFER_POINTS = 0.4
VOL_SPIKE_MULT = 3.5              # M1 range vs recent avg -> stand aside


def _dt(candle) -> datetime:
    return datetime.strptime(candle["time"], "%Y-%m-%d %H:%M")


def _ema(values, period):
    if len(values) < period:
        return None
    e = sum(values[:period]) / period
    k = 2 / (period + 1)
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _h1_bias(h1):
    closes = [c["close"] for c in h1]
    e21, e55 = _ema(closes, 21), _ema(closes, 55)
    if e21 is None or e55 is None:
        return "NEUTRAL"
    last = closes[-1]
    if e21 > e55 and last > e21:
        return "BULLISH"
    if e21 < e55 and last < e21:
        return "BEARISH"
    return "NEUTRAL"


def _liquidity_level(m5, bias):
    window = m5[-(LEVEL_LOOKBACK + LEVEL_EXCLUDE_RECENT):-LEVEL_EXCLUDE_RECENT]
    if len(window) < 10:
        return None
    if bias == "BULLISH":
        return min(c["low"] for c in window)   # sell-side liquidity below
    return max(c["high"] for c in window)      # buy-side liquidity above


def _vol_spike(m1, mult=VOL_SPIKE_MULT, lookback=20):
    if len(m1) < lookback + 1:
        return False
    recent = m1[-(lookback + 1):-1]
    avg = sum(c["high"] - c["low"] for c in recent) / len(recent)
    last = m1[-1]["high"] - m1[-1]["low"]
    return avg > 0 and last > mult * avg


def _sweep_reclaim(m1, level, bias):
    """Look at the last SWEEP_WINDOW M1 candles. Require: at least one wick
    beyond `level`, the just-closed candle back inside as a trend-direction
    body, and return the sweep extreme (for the SL)."""
    zone = m1[-SWEEP_WINDOW:]
    if len(zone) < 3:
        return None
    last = zone[-1]
    rng = last["high"] - last["low"]
    if rng <= 0:
        return None
    if bias == "BULLISH":
        swept = any(c["low"] <= level - MIN_PEN_POINTS for c in zone)
        strong = (last["high"] - last["close"]) <= RECLAIM_STRENGTH * rng
        reclaimed = last["close"] > level and last["close"] > last["open"] and strong
        if not (swept and reclaimed):
            return None
        return min(c["low"] for c in zone)
    else:
        swept = any(c["high"] >= level + MIN_PEN_POINTS for c in zone)
        strong = (last["close"] - last["low"]) <= RECLAIM_STRENGTH * rng
        reclaimed = last["close"] < level and last["close"] < last["open"] and strong
        if not (swept and reclaimed):
            return None
        return max(c["high"] for c in zone)


def evaluate(snapshot: dict, reference_time: datetime = None, news_blackouts: list = None,
             burned_legs: set = None) -> dict:
    m1, m5, h1 = snapshot.get("M1"), snapshot.get("M5"), snapshot.get("H1")
    if not (m1 and m5 and h1):
        return base.no_signal("snapshot missing M1/M5/H1")

    reference_time = reference_time or _dt(m1[-1])
    if not (SESSION_START_UTC <= reference_time.time() <= SESSION_END_UTC):
        return base.no_signal("outside the London-NY window (07:00-20:00 UTC)")

    if news_blackouts and any(s <= reference_time <= e for s, e in news_blackouts):
        return base.no_signal("inside a news blackout window")

    if _vol_spike(m1):
        return base.no_signal("last M1 candle is a volatility spike -- standing aside")

    bias = _h1_bias(h1)
    if bias == "NEUTRAL":
        return base.no_signal("H1 trend is neutral -- no directional edge")

    level = _liquidity_level(m5, bias)
    if level is None:
        return base.no_signal("not enough M5 history to mark a liquidity level")

    sweep_extreme = _sweep_reclaim(m1, level, bias)
    if sweep_extreme is None:
        return base.no_signal("no sweep-and-reclaim of the liquidity level on M1 yet")

    tick_size = snapshot["tick"]["tick_size"]
    contract_size = snapshot["tick"]["contract_size"]
    volume_min = snapshot["tick"]["volume_min"]
    volume_step = snapshot["tick"]["volume_step"]
    # Accept-window at the broker-minimum lot; position risk-sized to the SL
    # distance up to config.MAX_LOT (2026-09-09 sniper regime).
    max_points = RISK_USD_CAP / (contract_size * volume_min)

    trigger = m1[-1]
    leg_id = f"{bias[0]}:{level:.2f}"
    if burned_legs and leg_id in burned_legs:
        return base.no_signal(f"level {leg_id} already produced a stopped-out trade -- not re-signaling")

    if bias == "BULLISH":
        entry = round(trigger["high"] + tick_size, 2)
        sl = round(sweep_extreme - SL_BUFFER_POINTS, 2)
        risk_points = entry - sl
        if not (MIN_RISK_POINTS <= risk_points <= max_points):
            return base.no_signal(
                f"structural risk {risk_points:.2f}pt outside [{MIN_RISK_POINTS}, {max_points:.2f}]pt -- rejecting")
        tp = round(entry + TARGET_RR * risk_points, 2)
        entry_type, side = "buy_stop", "BUY"
    else:
        entry = round(trigger["low"] - tick_size, 2)
        sl = round(sweep_extreme + SL_BUFFER_POINTS, 2)
        risk_points = sl - entry
        if not (MIN_RISK_POINTS <= risk_points <= max_points):
            return base.no_signal(
                f"structural risk {risk_points:.2f}pt outside [{MIN_RISK_POINTS}, {max_points:.2f}]pt -- rejecting")
        tp = round(entry - TARGET_RR * risk_points, 2)
        entry_type, side = "sell_stop", "SELL"

    lot = risk.compute_lot_for_risk(entry, sl, RISK_USD_CAP, contract_size,
                                    volume_min, volume_step, config.MAX_LOT)
    risk_usd = round(risk_points * contract_size * lot, 2)
    reward_usd = round(TARGET_RR * risk_points * contract_size * lot, 2)

    reasoning = (
        f"H1 bias {bias}; M5 liquidity level {level:.2f}; M1 swept to {sweep_extreme:.2f} "
        f"and reclaimed with a {side} body at {trigger['time']}; entry stop past the reclaim "
        f"candle; SL beyond the sweep wick ({risk_points:.2f}pt); fixed TP at {TARGET_RR}R; "
        f"time-stop {TIME_STOP_BARS} M1 bars"
    )
    return {
        "signal": {
            "strategy": NAME,
            "side": side,
            "entry_type": entry_type,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "lot": lot,
            "leg_start": leg_id,
            "risk_usd": risk_usd,
            "reward_usd": reward_usd,
            "time_stop_bars": TIME_STOP_BARS,
            "reasoning": reasoning,
        },
        "reason": None,
    }
