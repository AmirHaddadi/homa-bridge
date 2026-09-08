"""Chart drawing: trend lines, rectangular order blocks, and simple geometry.

The bridge (Python, often running under Wine) cannot create MetaTrader chart
objects itself -- only MQL5 can. So this module keeps a small shape document and
renders it to a flat file that the companion expert ``HomaDraw.mq5`` polls at
~1 Hz and reconciles onto every matching chart:

  * every shape here becomes a chart object named ``HOMA_<id>``;
  * editing a shape (same id) moves/recolours the object in place;
  * a shape removed from the document is deleted from the chart on the next poll;
  * ``HomaDraw`` never touches objects whose name does not start with ``HOMA_``.

State of record is ``mt5bridge_state/homa_shapes.json`` (editable, versionable in
spirit). On every change it is flushed to ``<MT5>/MQL5/Files/homa_draw.tsv`` --
one shape per tab-separated line -- which is what the expert actually reads.

CLI: ``./run.sh draw ob|line|hline|vline|tri|ellipse|text|list|rm|clear ...``
"""
import json
import os
from datetime import datetime
from pathlib import Path

from . import config

STATE_DIR = Path(__file__).resolve().parent.parent / "mt5bridge_state"
STATE_FILE = STATE_DIR / "homa_shapes.json"
RENDER_NAME = "homa_draw.tsv"

# 2 points: rect / trend.  1 point: hline (price) / vline (time) / text / arrow.
# 3 points: triangle / ellipse.
_POINTS_REQUIRED = {
    "rect": 2, "trend": 2, "hline": 1, "vline": 1,
    "text": 1, "arrow": 1, "triangle": 3, "ellipse": 3,
}

_KIND_COLOR = {          # order-block / line semantic colours (R,G,B)
    "bear": "220,70,70",
    "bull": "60,170,110",
    "neutral": "150,150,160",
    "info": "90,160,230",
}


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def _files_dir() -> Path:
    """Resolve the terminal's ``MQL5/Files`` directory (where the expert reads)."""
    env = os.environ.get("MT5_FILES_DIR")
    if env:
        return Path(env)
    try:
        return Path(config.TERMINAL_PATH).parent / "MQL5" / "Files"
    except Exception:
        return STATE_DIR


# --------------------------------------------------------------------------- #
# document load / save
# --------------------------------------------------------------------------- #
def load() -> dict:
    if STATE_FILE.exists():
        raw = STATE_FILE.read_text(encoding="utf-8").strip()
        if raw:
            try:
                doc = json.loads(raw)
                doc.setdefault("shapes", [])
                return doc
            except json.JSONDecodeError:
                pass          # corrupt/half-written -> start clean rather than crash
    return {"shapes": []}


def _mql_time(iso: str | None) -> str:
    """ISO 'YYYY-MM-DD HH:MM' (server time, as `analyze` prints) -> 'YYYY.MM.DD HH:MM'."""
    if not iso:
        return ""
    iso = iso.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(iso, fmt).strftime("%Y.%m.%d %H:%M")
        except ValueError:
            continue
    raise ValueError(f"unrecognised time {iso!r} (want 'YYYY-MM-DD HH:MM')")


def _render_line(s: dict) -> str:
    pts = []
    for t, p in s.get("points", []):
        pts.append(f"{_mql_time(t)},{'' if p is None else p}")
    fields = [
        s["id"], s["type"], s.get("symbol", ""),
        s.get("color", "200,200,200"), str(s.get("width", 1)),
        s.get("style", "solid"),
        "1" if s.get("fill") else "0",
        "1" if s.get("back", True) else "0",
        "1" if s.get("ray_right") else "0",
        str(s.get("font_size", 9)),
        (s.get("text", "") or "").replace("\t", " ").replace("\n", " "),
        ";".join(pts),
    ]
    return "\t".join(fields)


def _atomic_write(path: Path, text: str) -> None:
    """Write UTF-8 via a temp file + rename so a failure never leaves a half file
    (Wine's Python defaults to cp1252 and would otherwise corrupt on non-latin text)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def save(doc: dict) -> dict:
    STATE_DIR.mkdir(exist_ok=True)

    header = ("# id\ttype\tsymbol\tcolor\twidth\tstyle\tfill\tback\tray\tfont"
              "\ttext\tpoints  -- written by mt5bridge.draw, read by HomaDraw.mq5")
    body = "\n".join(_render_line(s) for s in doc["shapes"])
    text = header + "\n" + body + "\n"

    rendered_to, err = None, None
    try:
        d = _files_dir()
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / RENDER_NAME, text)
        rendered_to = str(d / RENDER_NAME)
    except Exception as e:                       # keep JSON state regardless
        err = f"{type(e).__name__}: {e}"
        _atomic_write(STATE_DIR / RENDER_NAME, text)
        rendered_to = str(STATE_DIR / RENDER_NAME)

    _atomic_write(STATE_FILE, json.dumps(doc, indent=2, ensure_ascii=False))

    return {"ok": True, "shapes": len(doc["shapes"]),
            "rendered_to": rendered_to, "render_error": err}


# --------------------------------------------------------------------------- #
# mutation
# --------------------------------------------------------------------------- #
def put(shape: dict) -> dict:
    t = shape.get("type")
    if t not in _POINTS_REQUIRED:
        raise ValueError(f"unknown shape type {t!r}; pick from {sorted(_POINTS_REQUIRED)}")
    need = _POINTS_REQUIRED[t]
    if len(shape.get("points", [])) != need:
        raise ValueError(f"{t} needs exactly {need} point(s), got {len(shape.get('points', []))}")
    if not shape.get("id"):
        raise ValueError("shape needs an id")

    doc = load()
    doc["shapes"] = [s for s in doc["shapes"] if s["id"] != shape["id"]]
    doc["shapes"].append(shape)
    res = save(doc)
    res["id"] = shape["id"]
    return res


def remove(shape_id: str) -> dict:
    doc = load()
    before = len(doc["shapes"])
    doc["shapes"] = [s for s in doc["shapes"] if s["id"] != shape_id]
    res = save(doc)
    res["removed"] = before - len(doc["shapes"])
    return res


def clear(symbol: str | None = None) -> dict:
    doc = load()
    if symbol:
        target = config.resolve_symbol(symbol)
        doc["shapes"] = [s for s in doc["shapes"] if s.get("symbol") != target]
    else:
        doc["shapes"] = []
    return save(doc)


# --------------------------------------------------------------------------- #
# shape builders (thin -- the CLI is the real surface)
# --------------------------------------------------------------------------- #
def _auto_id(prefix: str, symbol: str) -> str:
    n = 1
    ids = {s["id"] for s in load()["shapes"]}
    base = f"{prefix}_{symbol.replace('!', '').lower()}"
    while f"{base}_{n}" in ids:
        n += 1
    return f"{base}_{n}"


def order_block(symbol, t1, p1, t2, p2, kind="bear", shape_id=None, label=None,
                fill=True, width=1) -> dict:
    sym = config.resolve_symbol(symbol)
    return put({
        "id": shape_id or _auto_id(f"ob_{kind}", sym),
        "type": "rect", "symbol": sym,
        "points": [[t1, float(p1)], [t2, float(p2)]],
        "color": _KIND_COLOR.get(kind, _KIND_COLOR["neutral"]),
        "width": width, "style": "solid", "fill": fill, "back": True,
        "text": label or f"{kind.upper()} OB {p1}-{p2}",
    })


def trendline(symbol, t1, p1, t2, p2, kind="info", shape_id=None, label=None,
              width=2, style="solid", ray_right=True) -> dict:
    sym = config.resolve_symbol(symbol)
    return put({
        "id": shape_id or _auto_id("tl", sym),
        "type": "trend", "symbol": sym,
        "points": [[t1, float(p1)], [t2, float(p2)]],
        "color": _KIND_COLOR.get(kind, kind), "width": width, "style": style,
        "back": False, "ray_right": ray_right, "text": label or "",
    })


def hline(symbol, price, kind="neutral", shape_id=None, label=None, style="dash", width=1) -> dict:
    sym = config.resolve_symbol(symbol)
    return put({
        "id": shape_id or _auto_id("hl", sym),
        "type": "hline", "symbol": sym,
        "points": [[None, float(price)]],
        "color": _KIND_COLOR.get(kind, kind), "width": width, "style": style,
        "back": False, "text": label or str(price),
    })
