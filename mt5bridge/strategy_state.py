"""Tiny per-(strategy, symbol) persisted state.

Currently holds exactly one thing: the set of M5 leg start-times that already
produced a stopped-out trade for a given strategy+symbol, so the same failed
leg isn't re-signaled minute after minute (see strategies/amir_trade.py's
leg detection -- a leg keeps the same start time across calls until price
action invalidates it and a new leg is found). Deliberately a plain JSON
file, not a database -- this is a handful of entries per symbol.
"""
import json
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "mt5bridge_state"


def _path(strategy: str, symbol: str) -> Path:
    safe_symbol = symbol.replace("!", "")
    return STATE_DIR / f"{strategy}_{safe_symbol}.json"


def load_burned_legs(strategy: str, symbol: str) -> set:
    p = _path(strategy, symbol)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text()).get("burned_legs", []))


def mark_leg_burned(strategy: str, symbol: str, leg_start: str) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    p = _path(strategy, symbol)
    data = json.loads(p.read_text()) if p.exists() else {"burned_legs": []}
    legs = set(data.get("burned_legs", []))
    legs.add(leg_start)
    data["burned_legs"] = sorted(legs)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
