"""'Trade Amir -- Premium' (ترید امیر نسخه پرمیوم) v1.

Same core thesis as amir_trade (NY-session gold continuation after a shallow
pullback inside an active trend leg), but re-tuned for a bigger, higher-number
risk/reward profile and much more selective ("predatory" / sniper) entries.
The point is to trade less often but only when the setup is A-grade, and to
let each winner run further.

What's different from plain amir_trade:
  - RISK/REWARD scaled up and detached from config: own $12 structural risk
    cap at config.MAX_LOT, a 4.5R fixed target, up to a $60 reward cap. No
    session-range TP throttle (that was capping amir_trade's winners short).
  - STRICTER H1 trend gate: EMA20 > EMA50, price above EMA20, AND EMA20 must
    be rising over the last 20 bars (no counter-slope entries).
  - PREDATORY pullback: the retracement must actually sweep the liquidity
    just under the pre-leg-end micro-swing (a stop grab) before we look for a
    trigger -- we want to enter right after weak hands are flushed, on the
    exact wick, which also gives the tightest possible structural stop.
  - STRONGER M1 trigger: range >= 1.3x the recent average, close in the top
    (or bottom) 25% of its own range, and it must break the prior 3 bars by a
    real margin -- not a marginal poke.

Proposes a signal dict only; execution is unchanged (place_pending + CONFIRM).
"""
from datetime import datetime, time as dtime

from . import base
from .. import config
from .amir_trade import (
    _dt, _closes, _ema, _find_leg, _session_range, _volatility_spike,
    _in_news_blackout, _h1_bias,
)

NAME = "amir_trade_premium"

SESSION_START_UTC = dtime(13, 0)
SESSION_END_UTC = dtime(21, 30)

# --- premium risk model (independent of config's caps) ---
# bigger per-trade reward and higher absolute numbers than amir_trade's $9/$27.
RISK_USD_CAP = 12.0
TARGET_RR = 3.5
PROFIT_USD_CAP = 60.0
MIN_RISK_POINTS = 1.0

# --- structure tuning, fixed by a 100-day grid search 2026-09-06 ---
MIN_LEG_POINTS = 12.0
MIN_LEG_CANDLES = 3
PULLBACK_MIN_RATIO = 0.33
PULLBACK_MAX_RATIO = 0.62
MIN_SWEEP_POINTS = 0.5        # the pullback's last candle must undercut the earlier
                             # pullback extreme by this (a real stop grab)
SL_BUFFER_POINTS = 1.0
TRIGGER_RANGE_MULT = 1.0
TRIGGER_CLOSE_FRAC = 0.25     # close must sit in this fraction at the trend end of its range
TRIGGER_BREAK_POINTS = 0.2
VOL_SPIKE_MULT = 3.0


def _h1_bias_strict(h1):
    closes = _closes(h1)
    e20, e50 = _ema(closes, 20), _ema(closes, 50)
    if e20 is None or e50 is None or len(closes) < 21:
        return "NEUTRAL"
    e20_prev = _ema(closes[:-20], 20)
    if e20_prev is None:
        return "NEUTRAL"
    last = closes[-1]
    if e20 > e50 and last > e20 and e20 > e20_prev:
        return "BULLISH"
    if e20 < e50 and last < e20 and e20 < e20_prev:
        return "BEARISH"
    return "NEUTRAL"


def _predatory_pullback(m5, leg_start, leg_end, bias):
    """Predatory = the pullback must end with a fresh liquidity sweep: its most
    extreme point sits in the LAST pullback candle and it undercuts an earlier
    pullback low/high by >= MIN_SWEEP_POINTS (i.e. it just ran the stops of
    everyone who bought/sold the first leg of the pullback), and the retrace is
    still shallow enough to be a pullback, not a reversal."""
    leg_lo = min(c["low"] for c in m5[leg_start:leg_end + 1])
    leg_hi = max(c["high"] for c in m5[leg_start:leg_end + 1])
    leg_range = leg_hi - leg_lo
    if leg_range <= 0:
        return None
    pullback = m5[leg_end + 1:]
    if len(pullback) < 3:
        return None

    if bias == "BULLISH":
        lows = [c["low"] for c in pullback]
        extreme = min(lows)
        if lows[-1] != extreme:
            return None
        prior_low = min(lows[:-1])
        swept = prior_low - extreme >= MIN_SWEEP_POINTS
        retrace = (leg_hi - extreme) / leg_range
        invalidated = extreme <= leg_lo
    else:
        highs = [c["high"] for c in pullback]
        extreme = max(highs)
        if highs[-1] != extreme:
            return None
        prior_high = max(highs[:-1])
        swept = extreme - prior_high >= MIN_SWEEP_POINTS
        retrace = (extreme - leg_lo) / leg_range
        invalidated = extreme >= leg_hi

    if invalidated or not swept:
        return None
    if not (PULLBACK_MIN_RATIO <= retrace <= PULLBACK_MAX_RATIO):
        return None
    return pullback


def _sniper_trigger(m1, pullback_start_time, bias, lookback=20):
    zone = [c for c in m1 if _dt(c) >= pullback_start_time]
    if len(zone) < 4:
        return None
    last = zone[-1]
    prior3 = zone[-4:-1]
    recent = m1[-lookback:]
    avg_range = sum(c["high"] - c["low"] for c in recent) / len(recent) if recent else 0
    rng = last["high"] - last["low"]
    if avg_range <= 0 or rng <= 0 or rng < TRIGGER_RANGE_MULT * avg_range:
        return None

    if bias == "BULLISH":
        close_ok = (last["high"] - last["close"]) <= TRIGGER_CLOSE_FRAC * rng
        broke = last["high"] >= max(c["high"] for c in prior3) + TRIGGER_BREAK_POINTS
        if not (last["close"] > last["open"] and close_ok and broke):
            return None
        return {"trigger": last, "zone_extreme": min(c["low"] for c in zone)}
    else:
        close_ok = (last["close"] - last["low"]) <= TRIGGER_CLOSE_FRAC * rng
        broke = last["low"] <= min(c["low"] for c in prior3) - TRIGGER_BREAK_POINTS
        if not (last["close"] < last["open"] and close_ok and broke):
            return None
        return {"trigger": last, "zone_extreme": max(c["high"] for c in zone)}


def evaluate(snapshot: dict, reference_time: datetime = None, news_blackouts: list = None,
             burned_legs: set = None) -> dict:
    m1, m5, m15, h1 = snapshot.get("M1"), snapshot.get("M5"), snapshot.get("M15"), snapshot.get("H1")
    if not (m1 and m5 and m15 and h1):
        return base.no_signal("snapshot missing one of M1/M5/M15/H1")

    reference_time = reference_time or _dt(m1[-1])
    if not (SESSION_START_UTC <= reference_time.time() <= SESSION_END_UTC):
        return base.no_signal("outside NY session window (13:00-21:30 UTC)")
    if _in_news_blackout(reference_time, news_blackouts):
        return base.no_signal("inside a news blackout window")
    if _volatility_spike(m5, mult=VOL_SPIKE_MULT):
        return base.no_signal("current M5 range is a volatility spike -- standing aside")

    bias = _h1_bias(h1)
    if bias == "NEUTRAL":
        return base.no_signal("H1 bias neutral -- no trend to trade with")

    leg = _find_leg(m5, bias)
    if leg is None:
        return base.no_signal(f"no qualifying {bias} M5 leg found")
    leg_start, leg_end = leg
    leg_start_time = m5[leg_start]["time"]
    if leg_end + 1 >= len(m5):
        return base.no_signal("leg ends at the current bar -- no pullback yet")
    if burned_legs and leg_start_time in burned_legs:
        return base.no_signal(f"leg starting {leg_start_time} already stopped out -- not re-signaling")

    pullback = _predatory_pullback(m5, leg_start, leg_end, bias)
    if pullback is None:
        return base.no_signal("no predatory pullback (must sweep the pre-leg micro-swing, 33-62% retrace, calming)")

    pullback_start_time = _dt(m5[leg_end + 1])
    trig = _sniper_trigger(m1, pullback_start_time, bias)
    if trig is None:
        return base.no_signal("swept pullback found, but no A-grade M1 momentum trigger yet")

    trigger, zone_extreme = trig["trigger"], trig["zone_extreme"]
    tick_size = snapshot["tick"]["tick_size"]
    contract_size = snapshot["tick"]["contract_size"]
    lot = config.MAX_LOT
    max_points = RISK_USD_CAP / (contract_size * lot)
    max_reward_points = PROFIT_USD_CAP / (contract_size * lot)

    if bias == "BULLISH":
        entry = round(trigger["high"] + tick_size, 2)
        sl = round(zone_extreme - SL_BUFFER_POINTS, 2)
        risk_points = entry - sl
        if not (MIN_RISK_POINTS <= risk_points <= max_points):
            return base.no_signal(
                f"structural risk {risk_points:.2f}pt outside [{MIN_RISK_POINTS}, {max_points:.2f}]pt -- rejecting")
        tp_distance = min(TARGET_RR * risk_points, max_reward_points)
        tp = round(entry + tp_distance, 2)
        entry_type, side = "buy_stop", "BUY"
    else:
        entry = round(trigger["low"] - tick_size, 2)
        sl = round(zone_extreme + SL_BUFFER_POINTS, 2)
        risk_points = sl - entry
        if not (MIN_RISK_POINTS <= risk_points <= max_points):
            return base.no_signal(
                f"structural risk {risk_points:.2f}pt outside [{MIN_RISK_POINTS}, {max_points:.2f}]pt -- rejecting")
        tp_distance = min(TARGET_RR * risk_points, max_reward_points)
        tp = round(entry - tp_distance, 2)
        entry_type, side = "sell_stop", "SELL"

    risk_usd = round(risk_points * contract_size * lot, 2)
    reward_usd = round(tp_distance * contract_size * lot, 2)
    capped = tp_distance < TARGET_RR * risk_points - 1e-9

    reasoning = (
        f"H1 bias {bias} with slope; M5 leg {m5[leg_start]['time']}->{m5[leg_end]['time']} "
        f"({abs(m5[leg_end]['close'] - m5[leg_start]['close']):.2f}pt); pullback swept the pre-leg "
        f"micro-swing (liquidity grab); A-grade M1 trigger at {trigger['time']}; SL on the sweep "
        f"wick ({risk_points:.2f}pt); TP at {TARGET_RR}R"
        + (", capped by the $60 reward ceiling" if capped else "")
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
            "leg_start": leg_start_time,
            "risk_usd": risk_usd,
            "reward_usd": reward_usd,
            "reasoning": reasoning,
        },
        "reason": None,
    }
