"""Single place that knows how to attach to the already-running MT5 terminal."""
from contextlib import contextmanager

import MetaTrader5 as mt5

from . import config


class ConnectionError(RuntimeError):
    pass


@contextmanager
def session():
    """Yields the initialized mt5 module, shuts down on exit. Connects to the
    already-running terminal instance (never launches a second one)."""
    ok = mt5.initialize(path=config.TERMINAL_PATH, timeout=config.INIT_TIMEOUT_MS)
    if not ok:
        raise ConnectionError(f"mt5.initialize failed: {mt5.last_error()}")
    try:
        yield mt5
    finally:
        mt5.shutdown()
