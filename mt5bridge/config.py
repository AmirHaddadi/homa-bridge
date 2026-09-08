"""Static configuration: connection target, broker/symbol naming, risk protocol caps.

Machine- and account-specific values are read from environment variables (see
``.env.example``); ``run.sh`` auto-loads a git-ignored ``.env`` next to it.
Nothing account-specific or secret is committed to the repository.
"""
import os


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


# Path to the ALREADY-RUNNING MetaTrader 5 terminal (native install or a Wine
# drive_c). The bridge attaches to this instance -- it never launches a second one.
TERMINAL_PATH = _env("MT5_TERMINAL_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
INIT_TIMEOUT_MS = int(_env("MT5_INIT_TIMEOUT_MS", "15000"))

# Informational only -- surfaced in `state` output and logs. The bridge does not
# authenticate; the running terminal is already logged in. Leave blank if unused.
BROKER = {
    "company": _env("MT5_COMPANY", ""),
    "server": _env("MT5_SERVER", ""),
    "login": int(_env("MT5_LOGIN", "0")) or None,
    "currency": _env("MT5_CURRENCY", "USD"),
}

# This broker suffixes symbol names with "!" (e.g. gold is XAUUSD! not XAUUSD).
SYMBOLS = {
    "XAU": "XAUUSD!",
    "GOLD": "XAUUSD!",
    "XAUUSD": "XAUUSD!",
    "NDX": "NDXUSD!",
    "NASDAQ": "NDXUSD!",
    "NDXUSD": "NDXUSD!",
    "EUR": "EURUSD!",
    "EURUSD": "EURUSD!",
}


def resolve_symbol(name: str) -> str:
    """Accept a friendly alias (gold, ndx, ...) or the exact broker symbol and
    return the exact broker symbol name."""
    key = name.upper()
    if key in SYMBOLS:
        return SYMBOLS[key]
    return name if name.endswith("!") else name

# --- Scalping execution protocol (see memory: mt5-scalping-protocol) ---
# 2026-09-09: after the +$123 slipped-TP day the user moved to a sniper regime --
# fewer, sharper entries, position size driven by the SL distance rather than a
# fixed lot. MAX_LOT is now a CEILING (0.03), not the size everything trades at:
# a tight-stop setup can use the full 0.03, a wider one auto-sizes down toward
# 0.01, all landing near the same dollar risk. Per-trade $ risk stays the real
# governor (MAX_LOSS_USD_BY_SYMBOL), enforced in risk.validate.
MAX_LOT = 0.03
MAX_LOSS_USD = 5.0
MAX_PROFIT_USD = 15.0

# Per-symbol overrides of the two caps above. Gold's real pullback/SL structure
# routinely needs more room than $5 (see strategy_amir_trade.md's no-lookahead
# test), so the user explicitly widened it 2026-09-05 -- deliberately, not out
# of fear of a $5 loss.
# 2026-09-08: user raised gold cap to $10 and added an NDX $5 cap for a
# set-and-forget session. Profit caps widened to ~3R so unattended runners can
# reach a real swing target.
# 2026-09-09: sniper regime -- gold per-trade risk tightened $10 -> $8, EURUSD
# added at $5 (was falling through to the $5 default anyway; now explicit).
# Profit caps left as-is: they are ceilings for unattended runners, not targets.
MAX_LOSS_USD_BY_SYMBOL = {"XAUUSD!": 8.0, "NDXUSD!": 5.0, "EURUSD!": 5.0}
MAX_PROFIT_USD_BY_SYMBOL = {"XAUUSD!": 32.0, "NDXUSD!": 20.0}


def max_loss_for(symbol: str) -> float:
    return MAX_LOSS_USD_BY_SYMBOL.get(symbol, MAX_LOSS_USD)


def max_profit_for(symbol: str) -> float:
    return MAX_PROFIT_USD_BY_SYMBOL.get(symbol, MAX_PROFIT_USD)


MAX_OPEN_POSITIONS = 1  # per symbol: positions + pending orders combined, enforced in orders.place_pending
MAGIC = 20260904

# --- Long-term swing exception (see memory: long-term-swing-exception, added 2026-09-08) ---
# The user deposited additional funds and is now running long-term swing positions
# ALONGSIDE the daily scalp book. Orders/positions placed with LONG_TERM_MAGIC are:
#   * tagged separately and EXCLUDED from the MAX_OPEN_POSITIONS count, so they
#     never consume a scalp slot or block a day-trade;
#   * risk-capped at LONG_TERM_MAX_LOSS_USD instead of the scalp $8 gold cap;
#   * NOT profit-capped -- these setups deliberately target 10R+.
# The daily circuit breakers (trade count / daily loss / daily profit) and the
# trade-journal "one open trade" convention do NOT apply to LONG_TERM_MAGIC tickets.
LONG_TERM_MAGIC = 20260908
LONG_TERM_MAX_LOSS_USD = 20.0
LONG_TERM_MAX_PROFIT_USD = 1_000_000.0  # effectively uncapped; 10R+ is the whole point

# Daily circuit breakers (checked by the caller against the day's trade_journal
# before proposing a new setup -- not auto-enforced inside the bridge itself).
# 2026-09-09: sniper regime -- count 5 -> 15, daily loss $15 -> $35, daily
# profit target $50 -> $100. Both dollar figures are hard circuit breakers:
# once the day's REALISED P/L (from trade_journal, floating excluded) crosses
# +$100 or -$35, the agent proposes no further setups until the next session.
DAILY_MAX_TRADES = 15
DAILY_MAX_LOSS_USD = 35.0
DAILY_MAX_PROFIT_USD = 100.0

DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4"]
DEFAULT_CANDLE_COUNT = 30
