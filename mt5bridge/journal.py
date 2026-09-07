"""Trade journal helpers matching the existing trade_journal/YYYY-MM-DD/ convention
(trades.csv + one markdown file per trade). Writing the markdown narrative stays a
manual/LLM step; this module only handles the mechanical CSV append + paths."""
import csv
import os
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL_DIR = os.path.join(PROJECT_ROOT, "trade_journal")

CSV_HEADER = [
    "ticket", "position_id", "symbol", "direction", "entry_time_utc", "entry_price",
    "exit_time_utc", "exit_price", "sl", "tp", "lot", "profit_usd", "close_reason",
    "setup_quality", "rr_planned", "notes",
]


def day_dir(date=None) -> str:
    date = date or datetime.now(timezone.utc).date()
    d = os.path.join(JOURNAL_DIR, date.isoformat())
    os.makedirs(d, exist_ok=True)
    return d


def next_trade_number(date=None) -> int:
    d = day_dir(date)
    existing = [f for f in os.listdir(d) if f.endswith(".md")]
    return len(existing) + 1


def append_csv_row(row: dict, date=None) -> str:
    d = day_dir(date)
    path = os.path.join(d, "trades.csv")
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if is_new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in CSV_HEADER})
    return path


def md_path(ticket, symbol: str, direction: str, date=None) -> str:
    d = day_dir(date)
    n = next_trade_number(date)
    clean_symbol = symbol.rstrip("!")
    return os.path.join(d, f"{n:03d}_{ticket}_{clean_symbol}_{direction.upper()}.md")
