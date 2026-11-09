"""Card registry. Each Analysis topic module registers one function per dashboard card:

    from Shared.registry import card

    @card("s2_revenue_trend", tables=["sales_monthly"], filters=["region"])
    def revenue_trend(t):
        sales = t.sales_monthly            # pandas DataFrame, fast filters already applied
        ...
        return {"data": {...chart-ready...}, "metrics": {"yoy_change": 0.052, ...}}

- tables: the Data tables the card reads (t.<name>); only these are loaded
- filters: the fast filters (dashboard.config.json "filters") that apply to this card; others are ignored
- return "data" (anything JSON-able, shaped for the chart) and "metrics" (named values for commentary
  {metric|format}; numbers as fractions/amounts, text as strings, null when not computable)
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ANALYSIS = Path(__file__).resolve().parent.parent
CARDS: dict[str, "Card"] = {}


@dataclass
class Card:
    id: str
    fn: Callable
    tables: list[str]
    filters: list[str] = field(default_factory=list)
    module: str = ""


def card(card_id: str, *, tables: list[str], filters: list[str] | tuple = ()):
    def deco(fn):
        if card_id in CARDS and CARDS[card_id].fn.__qualname__ != fn.__qualname__:
            raise ValueError(f"card {card_id} registered twice ({CARDS[card_id].module} and {fn.__module__})")
        CARDS[card_id] = Card(card_id, fn, list(tables), list(filters), fn.__module__)
        return fn
    return deco


def discover(reload: bool = False) -> dict[str, Card]:
    """Import every Analysis/*.py topic module (not server.py / check.py / precompute.py / _*.py)."""
    if str(ANALYSIS) not in sys.path:
        sys.path.insert(0, str(ANALYSIS))
    skip = {"server", "check", "precompute"}
    if reload:
        CARDS.clear()
    for f in sorted(ANALYSIS.glob("*.py")):
        name = f.stem
        if name in skip or name.startswith("_"):
            continue
        if reload and name in sys.modules:
            importlib.reload(sys.modules[name])
        else:
            importlib.import_module(name)
    return CARDS
