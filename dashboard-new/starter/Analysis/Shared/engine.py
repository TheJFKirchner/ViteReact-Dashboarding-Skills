"""Runs card functions: picks the card's filters, loads its tables, caches the JSON-safe result."""
from __future__ import annotations

import datetime as dt
import math
import threading
import traceback
from collections import OrderedDict

from . import tables
from .registry import CARDS, discover

_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 5000
state = {"version": 0}


def clean(value):
    """JSON-safe copy: numpy/pandas scalars -> Python, NaN/inf -> None, dates -> ISO strings."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):   # numpy arrays / pandas series
        return clean(value.tolist())
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):     # numpy scalar
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()[:10]
    return value


def card_filters(card_id: str, filters: dict) -> dict:
    """Only the fast filters this card uses, "All" for missing ones."""
    c = CARDS[card_id]
    return {f: str(filters.get(f) or tables.ALL) for f in c.filters}


def clear_cache():
    with _cache_lock:
        _cache.clear()
    state["version"] += 1


def run(card_id: str, filters: dict | None = None) -> dict:
    """{"data", "metrics"} for one card, or {"error"}. Cached per (card, its filter values, data version)."""
    if not CARDS:
        discover()
    if card_id not in CARDS:
        return {"error": f'no Analysis function registered for "{card_id}" (add @card("{card_id}", ...) in Analysis/)'}
    picked = card_filters(card_id, filters or {})
    key = (card_id, tuple(sorted(picked.items())), state["version"])
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    c = CARDS[card_id]
    try:
        m = tables.manifest()
        out = c.fn(tables.Tables(c.tables, picked, m))
        if not isinstance(out, dict) or "data" not in out:
            raise TypeError(f'{c.module}.{c.fn.__name__} must return {{"data": ..., "metrics": {{...}}}}')
        result = clean({"data": out["data"], "metrics": out.get("metrics") or {}})
    except Exception as e:  # noqa: BLE001 - shown on the card
        tb = traceback.extract_tb(e.__traceback__)
        where = next((f"{fr.filename.split('Analysis')[-1].strip(chr(92) + '/')}:{fr.lineno}" for fr in reversed(tb) if "Analysis" in fr.filename and "Shared" not in fr.filename), "")
        return {"error": f"{type(e).__name__}: {e}" + (f" ({where})" if where else "")}
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result
