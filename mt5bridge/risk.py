"""Risk/reward math and protocol cap validation, kept independent of any mt5
connection so it's trivially unit-testable."""
import math

from . import config


def compute_lot_for_risk(entry: float, sl: float, risk_usd: float, contract_size: float,
                          volume_min: float, volume_step: float, max_lot: float) -> float:
    """Size the position so that hitting SL loses ~risk_usd, rounded DOWN to the
    broker's volume_step (never up, so we never silently exceed the risk cap)
    and clamped to [volume_min, max_lot]. Replaces the old fixed-lot approach --
    the right lot depends on the SL distance for the instrument/setup at hand."""
    price_distance = abs(entry - sl)
    if price_distance <= 0:
        raise ValueError("entry and sl must differ")
    raw_lot = risk_usd / (price_distance * contract_size)
    steps = math.floor(raw_lot / volume_step + 1e-9)
    lot = steps * volume_step
    lot = max(lot, volume_min)
    lot = min(lot, max_lot)
    return round(lot, 8)


def compute_risk_reward(entry: float, sl: float, tp: float, lot: float, contract_size: float, side: str):
    value_per_point = contract_size * lot
    side = side.upper()
    if side == "BUY":
        risk = (entry - sl) * value_per_point
        reward = (tp - entry) * value_per_point
    elif side == "SELL":
        risk = (sl - entry) * value_per_point
        reward = (entry - tp) * value_per_point
    else:
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    return risk, reward


def validate(risk_usd: float, reward_usd: float, lot: float,
             max_loss_usd: float = config.MAX_LOSS_USD,
             max_profit_usd: float = config.MAX_PROFIT_USD) -> list:
    """Returns a list of human-readable violations of the scalping protocol
    caps; empty list means OK. Caps default to the global ones but callers
    should pass the per-symbol caps (config.max_loss_for/max_profit_for)."""
    errors = []
    if lot > config.MAX_LOT + 1e-9:
        errors.append(f"lot {lot} exceeds MAX_LOT {config.MAX_LOT}")
    if risk_usd <= 0:
        errors.append("computed risk <= 0 (SL on wrong side of entry?)")
    elif risk_usd > max_loss_usd:
        errors.append(f"risk ${risk_usd:.2f} exceeds max loss cap ${max_loss_usd}")
    if reward_usd <= 0:
        errors.append("computed reward <= 0 (TP on wrong side of entry?)")
    elif reward_usd > max_profit_usd:
        errors.append(f"reward ${reward_usd:.2f} exceeds max profit cap ${max_profit_usd}")
    return errors
