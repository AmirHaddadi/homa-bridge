"""Strategy plugin interface.

A strategy is a pure function of a market_data.multi_tf_snapshot() dict (plus
a couple of small context inputs) that returns a signal or None. It NEVER
touches mt5/orders directly -- it only proposes; the system layer
(mt5bridge.orders, the risk caps in mt5bridge.config, and the human
"CONFIRM ENTRY" gate) is what actually executes. This keeps strategies
swappable/addable without touching execution, and keeps them unit-testable
against historical candle data with no live connection.

To add a new strategy: implement `evaluate(snapshot, reference_time=None,
news_blackouts=None) -> dict` with the same return shape as amir_trade's
(see its docstring), then register it in strategies/__init__.py's STRATEGIES
map.
"""

NO_SIGNAL = {"signal": None, "reason": None}


def no_signal(reason: str) -> dict:
    return {"signal": None, "reason": reason}
