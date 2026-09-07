"""Strategy registry. Each entry maps a CLI-facing name to a module exposing
an `evaluate(snapshot, reference_time=None, news_blackouts=None) -> dict`
function (see strategies/base.py and strategies/amir_trade.py). Add new
strategies here as they're defined -- the system layer (config/orders) never
needs to change to support a new one."""
from . import amir_trade
from . import amir_trade_premium
from . import claude_wolf

STRATEGIES = {
    amir_trade.NAME: amir_trade,
    amir_trade_premium.NAME: amir_trade_premium,
    claude_wolf.NAME: claude_wolf,
}


def get(name: str):
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}, expected one of {list(STRATEGIES)}")
