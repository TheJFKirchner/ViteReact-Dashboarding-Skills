"""Section registry. Each Analysis page module registers one function per dashboard section:

    from Shared.registry import section

    @section("s2_revenue_trend", tables=["sales_monthly"])
    def revenue_trend(t):
        sales = t.sales_monthly            # pandas DataFrame, fast filters already applied
        ...
        return {"data": {...chart-ready...}, "metrics": {"yoy_change": 0.052, ...}}

- tables: the Data tables the section reads (t.<name>); only these are loaded
- filters: worked out from where each filter lives (dashboard.config.json "filters"): a filter with no "tab" or
  "section" is dashboard-wide, "tab": "<tab id>" applies on that tab, "section": "<section id>" to that section.
  A section gets every filter in its reach whose column one of its tables has. An explicit filters=[...] list
  (older projects) overrides this.
- return "data" (anything JSON-able, shaped for the chart) and "metrics" (named values for commentary
  {metric|format}; numbers as fractions/amounts, text as strings, null when not computable)
"""
from __future__ import annotations

import importlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ANALYSIS = Path(__file__).resolve().parent.parent
SECTIONS = ANALYSIS.parent / "Src" / "Sections"
CARDS: dict[str, "Card"] = {}
_META = re.compile(r"export\s+const\s+meta\s*=\s*\{([^}]*)\}")
_TAB = re.compile(r"(?<![\w$])tab\s*:\s*['\"]([^'\"]+)['\"]")


def section_tab(section_id: str) -> str | None:
    """The tab a section sits on (meta.tab in Src/Sections/<id>.jsx), or None."""
    try:
        src = (SECTIONS / f"{section_id}.jsx").read_text(encoding="utf-8")
    except OSError:
        return None
    m = _META.search(src)
    t = _TAB.search(m.group(1)) if m else None
    return t.group(1) if t else None


def in_reach(spec: dict, section_id: str, tab: str | None) -> bool:
    """Does a filter (its config entry) reach this section? No tab/section = the whole dashboard."""
    if spec.get("section"):
        return spec["section"] == section_id
    if spec.get("tab"):
        return spec["tab"] == tab
    return True


def section_filters(section_id: str, table_names: list[str]) -> list[str]:
    """Fast filters that apply to a section: in reach, and one of its tables has the filter's column."""
    from . import tables
    m = tables.manifest()
    tab = section_tab(section_id)
    out = []
    for name, spec in tables.specs("filters").items():
        col = spec.get("column", name)
        if in_reach(spec, section_id, tab) and any(col in m["tables"].get(t, {}).get("columns", {}) for t in table_names):
            out.append(name)
    return out


@dataclass
class Card:
    id: str
    fn: Callable
    tables: list[str]
    declared: list[str] | None = None   # explicit filters=[...] (older projects); None = worked out from levels
    module: str = ""

    @property
    def filters(self) -> list[str]:
        return list(self.declared) if self.declared is not None else section_filters(self.id, self.tables)


def card(card_id: str, *, tables: list[str], filters: list[str] | tuple | None = None):
    def deco(fn):
        if card_id in CARDS and CARDS[card_id].fn.__qualname__ != fn.__qualname__:
            raise ValueError(f"section {card_id} registered twice ({CARDS[card_id].module} and {fn.__module__})")
        CARDS[card_id] = Card(card_id, fn, list(tables), None if filters is None else list(filters), fn.__module__)
        return fn
    return deco


section = card   # the name used in new projects: @section("s3_paid_by_region", tables=[...])


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
