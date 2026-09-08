"""'Trade Amir' (ترید امیر) v1 -- engineered NY-session gold micro-pullback
continuation scalp.

Defined 2026-09-05 after a discretionary backtest of the week 2026-08-31 to
2026-09-04 showed the underlying idea (trade continuation after a shallow
pullback inside an active trend leg, during the NY session, with a tight
structural stop) shows up repeatedly in gold, but that discretionary,
after-the-fact judgment is not a citable edge (hindsight bias). This module
makes the same idea MECHANICAL and precise so it produces the same signal
regardless of who/what is looking at the chart, which is a prerequisite for
an honest future backtest (see trade_journal_convention / the roadmap in
mt5_scalping_protocol memory) and for consistent live execution.

Pipeline (H1 -> M15 -> M5 -> M1), each step gates the next:
  1. H1 bias filter        - only trade with the higher-timeframe trend
  2. M15 session range      - mark the pre-NY-session (00:00-13:00 UTC) high/low
  3. M5 leg + pullback      - find an impulsive leg, then a shallow, orderly
                              retracement (not a reversal) that has calmed down
  4. M1 trigger             - require a real momentum candle back in the trend
                              direction, breaking the pullback's short-term
                              structure, before proposing an entry
  5. Risk gate              - the structural SL must fit inside this trading
                              system's per-trade risk cap (config.max_loss_for
                              the symbol, measured at the broker-minimum lot);
                              if it doesn't, the setup is REJECTED outright
                              rather than widened
  6. Filters                - NY session window, news blackout, and a
                              volatility-spike guard (mechanical version of
                              "that candle is news, stand aside")

This module only proposes a signal dict; it never calls mt5bridge.orders.
Execution still goes through the normal place_pending() + "CONFIRM ENTRY"
flow. The proposed lot is risk-sized from the SL distance (risk.compute_lot_
for_risk), clamped to config.MAX_LOT (2026-09-09 sniper regime: 0.01-0.03).
"""
from datetime import datetime, time as dtime, timedelta

from . import base
from .. import config, risk

NAME = "amir_trade"

SESSION_START_UTC = dtime(13, 0)
SESSION_END_UTC = dtime(21, 30)

# M5 leg/pullback tuning -- tuned to gold's typical NY-session leg sizes seen
# in the 2026-08-31..09-04 backtest (10-50pt legs, 3-5pt structural stops).
MIN_LEG_POINTS = 10.0
MIN_LEG_CANDLES = 3
PULLBACK_MIN_RATIO = 0.30
PULLBACK_MAX_RATIO = 0.55
SL_BUFFER_POINTS = 0.3
TARGET_RR = 3.0
VOL_SPIKE_MULT = 3.0  # M5 candle range vs recent average -> treat as news, stand aside


def _dt(candle) -> datetime:
    return datetime.strptime(candle["time"], "%Y-%m-%d %H:%M")


def _closes(candles):
    return [c["close"] for c in candles]


def _ema(values, period):
    if len(values) < period:
        return None
    e = sum(values[:period]) / period
    k = 2 / (period + 1)
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _h1_bias(h1_candles):
    closes = _closes(h1_candles)
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    if ema20 is None or ema50 is None or not closes:
        return "NEUTRAL"
    last = closes[-1]
    if ema20 > ema50 and last > ema20:
        return "BULLISH"
    if ema20 < ema50 and last < ema20:
        return "BEARISH"
    return "NEUTRAL"


def _session_range(m15_candles, session_date):
    """Pre-session (00:00-13:00 UTC) high/low for session_date, from M15 bars."""
    day_bars = [c for c in m15_candles if _dt(c).date() == session_date
                and _dt(c).time() < SESSION_START_UTC]
    if not day_bars:
        return None, None
    return max(c["high"] for c in day_bars), min(c["low"] for c in day_bars)


def _find_leg(m5_candles, bias):
    """Scan from the most recent bar backward for the latest run of
    >=MIN_LEG_CANDLES consecutive same-direction closes covering
    >=MIN_LEG_POINTS net move, in the bias direction. Returns
    (leg_start_idx, leg_end_idx) into m5_candles, or None."""
    n = len(m5_candles)
    i = n - 1
    while i > 0:
        run_end = i
        j = i
        if bias == "BULLISH":
            while j > 0 and m5_candles[j]["close"] > m5_candles[j - 1]["close"]:
                j -= 1
        else:
            while j > 0 and m5_candles[j]["close"] < m5_candles[j - 1]["close"]:
                j -= 1
        run_start = j
        length = run_end - run_start
        if length >= MIN_LEG_CANDLES - 1:
            net = abs(m5_candles[run_end]["close"] - m5_candles[run_start]["close"])
            if net >= MIN_LEG_POINTS:
                return run_start, run_end
        if run_start == i:
            i -= 1
        else:
            i = run_start - 1
    return None


def _pullback_zone(m5_candles, leg_start, leg_end, bias):
    """After the leg ends, look for a shallow, calming retracement that never
    invalidates the leg (doesn't trade back past the leg's start). Returns the
    pullback candle slice, or None if no orderly pullback is currently sitting
    at the end of the array (i.e. we're not "in the zone" right now)."""
    leg_lo = min(c["low"] for c in m5_candles[leg_start:leg_end + 1])
    leg_hi = max(c["high"] for c in m5_candles[leg_start:leg_end + 1])
    leg_range = leg_hi - leg_lo
    if leg_range <= 0:
        return None

    pullback = m5_candles[leg_end + 1:]
    if len(pullback) < 2:
        return None

    if bias == "BULLISH":
        extreme = min(c["low"] for c in pullback)
        retrace_ratio = (leg_hi - extreme) / leg_range
        invalidated = extreme <= leg_lo
    else:
        extreme = max(c["high"] for c in pullback)
        retrace_ratio = (extreme - leg_lo) / leg_range
        invalidated = extreme >= leg_hi

    if invalidated or not (PULLBACK_MIN_RATIO <= retrace_ratio <= PULLBACK_MAX_RATIO):
        return None

    # Consolidation check: the last 2 candles must be calmer than the leg's
    # average range (a pause, not continued reversal momentum).
    leg_avg_range = sum(c["high"] - c["low"] for c in m5_candles[leg_start:leg_end + 1]) / (leg_end - leg_start + 1)
    if any((c["high"] - c["low"]) >= leg_avg_range for c in pullback[-2:]):
        return None

    return pullback


def _m1_trigger(m1_candles, pullback_start_time, bias, avg_range_lookback=20):
    """The pullback zone's extreme must come from within the M1 candles too
    (used for the SL). The last M1 candle must be a real momentum candle back
    in the trend direction, breaking the high/low of the preceding 3 bars."""
    zone = [c for c in m1_candles if _dt(c) >= pullback_start_time]
    if len(zone) < 4:
        return None
    last = zone[-1]
    prior3 = zone[-4:-1]
    recent = m1_candles[-avg_range_lookback:]
    avg_range = sum(c["high"] - c["low"] for c in recent) / len(recent) if recent else 0
    last_range = last["high"] - last["low"]
    if avg_range <= 0 or last_range < avg_range:
        return None

    if bias == "BULLISH":
        if not (last["close"] > last["open"] and last["high"] > max(c["high"] for c in prior3)):
            return None
        zone_low = min(c["low"] for c in zone)
        return {"trigger": last, "zone_extreme": zone_low}
    else:
        if not (last["close"] < last["open"] and last["low"] < min(c["low"] for c in prior3)):
            return None
        zone_high = max(c["high"] for c in zone)
        return {"trigger": last, "zone_extreme": zone_high}


def _in_news_blackout(t, news_blackouts):
    return bool(news_blackouts) and any(start <= t <= end for start, end in news_blackouts)


def _volatility_spike(m5_candles, mult=VOL_SPIKE_MULT, lookback=20):
    if len(m5_candles) < lookback + 1:
        return False
    recent = m5_candles[-(lookback + 1):-1]
    avg_range = sum(c["high"] - c["low"] for c in recent) / len(recent)
    last_range = m5_candles[-1]["high"] - m5_candles[-1]["low"]
    return avg_range > 0 and last_range > mult * avg_range


def evaluate(snapshot: dict, reference_time: datetime = None, news_blackouts: list = None,
             burned_legs: set = None) -> dict:
    """snapshot: output of market_data.multi_tf_snapshot(symbol, ["M1","M5","M15","H1"], count>=large enough).
    reference_time: the "now" to evaluate at (UTC, naive) -- defaults to the latest M1 candle's time.
    news_blackouts: list of (start_dt, end_dt) UTC windows to avoid, from the day's
                    once-daily ForexFactory mapping (trade_journal/YYYY-MM-DD/news_calendar.md).
    burned_legs: set of M5 candle "time" strings (see strategy_state.load_burned_legs) identifying
                 legs that already produced a stopped-out trade -- those are never re-signaled,
                 since a leg's start time doesn't change across calls until price invalidates it.

    Returns {"signal": None, "reason": "..."} or
            {"signal": {side, entry_type, entry, sl, tp, leg_start, risk_usd, reward_usd, reasoning}, "reason": None}
    """
    m1, m5, m15, h1 = snapshot.get("M1"), snapshot.get("M5"), snapshot.get("M15"), snapshot.get("H1")
    if not (m1 and m5 and m15 and h1):
        return base.no_signal("snapshot missing one of M1/M5/M15/H1")

    reference_time = reference_time or _dt(m1[-1])

    if not (SESSION_START_UTC <= reference_time.time() <= SESSION_END_UTC):
        return base.no_signal("outside NY session window (13:00-21:30 UTC)")

    if _in_news_blackout(reference_time, news_blackouts):
        return base.no_signal("inside a news blackout window")

    if _volatility_spike(m5):
        return base.no_signal("current M5 range is a volatility spike (likely news) -- standing aside")

    bias = _h1_bias(h1)
    if bias == "NEUTRAL":
        return base.no_signal("H1 bias is neutral/choppy -- no trend to trade with")

    leg = _find_leg(m5, bias)
    if leg is None:
        return base.no_signal(f"no qualifying {bias} M5 leg (>= {MIN_LEG_POINTS}pt, >= {MIN_LEG_CANDLES} candles) found")
    leg_start, leg_end = leg
    leg_start_time = m5[leg_start]["time"]

    if burned_legs and leg_start_time in burned_legs:
        return base.no_signal(f"leg starting {leg_start_time} already produced a stopped-out trade -- not re-signaling it")

    pullback = _pullback_zone(m5, leg_start, leg_end, bias)
    if pullback is None:
        return base.no_signal("no orderly pullback (30-55% retrace, calming down) sitting at the current price")

    pullback_start_time = _dt(m5[leg_end + 1])
    trig = _m1_trigger(m1, pullback_start_time, bias)
    if trig is None:
        return base.no_signal("pullback found, but no M1 momentum trigger breaking its short-term structure yet")

    trigger, zone_extreme = trig["trigger"], trig["zone_extreme"]
    tick_size = snapshot["tick"]["tick_size"]
    contract_size = snapshot["tick"]["contract_size"]
    symbol = snapshot.get("symbol", "")
    volume_min = snapshot["tick"]["volume_min"]
    volume_step = snapshot["tick"]["volume_step"]
    max_loss_usd = config.max_loss_for(symbol)
    max_profit_usd = config.max_profit_for(symbol)
    # The widest acceptable stop is the one that still fits the risk cap at the
    # broker-minimum lot; tighter stops just get sized up toward config.MAX_LOT
    # (sniper regime 2026-09-09 -- lot follows the SL distance, see config).
    max_structural_points = max_loss_usd / (contract_size * volume_min)
    max_reward_points = max_profit_usd / (contract_size * volume_min)

    session_hi, session_lo = _session_range(m15, reference_time.date())

    if bias == "BULLISH":
        entry = round(trigger["high"] + tick_size, 2)
        sl = round(zone_extreme - SL_BUFFER_POINTS, 2)
        risk_points = entry - sl
        if risk_points <= 0 or risk_points > max_structural_points:
            return base.no_signal(
                f"structural SL is {risk_points:.2f}pt, exceeds the {max_structural_points:.2f}pt cap "
                f"for ${max_loss_usd} risk at the {volume_min} broker-minimum lot -- rejecting rather than widening the stop"
            )
        tp_distance = min(TARGET_RR * risk_points, max_reward_points)
        if session_hi and session_hi > entry:
            tp_distance = min(tp_distance, session_hi - entry)
        tp = round(entry + tp_distance, 2)
        entry_type = "buy_stop"
    else:
        entry = round(trigger["low"] - tick_size, 2)
        sl = round(zone_extreme + SL_BUFFER_POINTS, 2)
        risk_points = sl - entry
        if risk_points <= 0 or risk_points > max_structural_points:
            return base.no_signal(
                f"structural SL is {risk_points:.2f}pt, exceeds the {max_structural_points:.2f}pt cap "
                f"for ${max_loss_usd} risk at the {volume_min} broker-minimum lot -- rejecting rather than widening the stop"
            )
        tp_distance = min(TARGET_RR * risk_points, max_reward_points)
        if session_lo and session_lo < entry:
            tp_distance = min(tp_distance, entry - session_lo)
        tp = round(entry - tp_distance, 2)
        entry_type = "sell_stop"

    lot = risk.compute_lot_for_risk(entry, sl, max_loss_usd, contract_size,
                                    volume_min, volume_step, config.MAX_LOT)
    risk_usd = round(risk_points * contract_size * lot, 2)
    reward_usd = round(tp_distance * contract_size * lot, 2)
    capped_by_rr_ceiling = tp_distance < TARGET_RR * risk_points - 1e-9

    reasoning = (
        f"H1 bias {bias}; M5 leg {m5[leg_start]['time']}->{m5[leg_end]['time']} "
        f"({abs(m5[leg_end]['close'] - m5[leg_start]['close']):.2f}pt); pullback retrace ok, calming; "
        f"M1 momentum trigger at {trigger['time']} breaking last-3-candle structure; "
        f"SL at pullback extreme {zone_extreme:.2f} +/- buffer; TP at up to {TARGET_RR}x RR"
        + (", capped below full RR by session range or the profit cap" if capped_by_rr_ceiling else "")
    )

    return {
        "signal": {
            "strategy": NAME,
            "side": "BUY" if bias == "BULLISH" else "SELL",
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
