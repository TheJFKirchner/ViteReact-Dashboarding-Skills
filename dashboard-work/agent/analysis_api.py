"""Read-only access to the project's Analysis server (v2 projects: Python owns every number).

The dashboard's numbers come from Analysis/<topic>.py functions, run by Analysis/server.py:
    GET /api/meta                 filters + options, slow parameters, cards {id: {filters, tables, module}}, manifest
    GET /api/card/<id>?<filters>  {"data", "metrics"} for one card (or {"error"})
The agent only READS these, to know a card's metric names (commentary checks), the live values (so the
model can write sensible words around them) and the shape of the `data` prop the chart builds from.
It never imports or edits Analysis/ or Pipeline/ code.

Port: DASH_API_PORT (Tools/dev.mjs passes it to Vite, Vite passes its environment to the agent), else
dashboard.config.json server.port, else 8765.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("DASH_PROJECT_ROOT") or Path.cwd()).resolve()   # same as section_agent.ROOT
TIMEOUT_S = 20


class AnalysisUnavailable(RuntimeError):
    """The Analysis server didn't answer (not running, or the card's function failed)."""


def port() -> int:
    if os.environ.get("DASH_API_PORT"):
        return int(os.environ["DASH_API_PORT"])
    try:
        config = json.loads((ROOT / "dashboard.config.json").read_text(encoding="utf-8"))
        return int((config.get("server") or {}).get("port") or 8765)
    except (OSError, ValueError, TypeError):
        return 8765


def _get(path: str) -> dict:
    url = f"http://127.0.0.1:{port()}{path}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:            # 422 = the card's Analysis function failed; body has the error
        try:
            return json.loads(e.read().decode("utf-8"))
        except ValueError:
            raise AnalysisUnavailable(f"{path}: HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AnalysisUnavailable(f"the Analysis server on port {port()} did not answer ({e})") from None


def meta() -> dict:
    m = _get("/api/meta")
    if m.get("error") and not m.get("cards"):
        raise AnalysisUnavailable(m["error"])
    return m


def card(card_id: str, filters: dict | None = None) -> dict:
    """{"data", "metrics"} for one card at the given filters (missing ones = All)."""
    qs = urllib.parse.urlencode({k: v for k, v in (filters or {}).items() if v is not None})
    result = _get(f"/api/card/{urllib.parse.quote(card_id)}" + (f"?{qs}" if qs else ""))
    if "error" in result:
        raise AnalysisUnavailable(f"Analysis for {card_id} failed: {result['error']}")
    return result


def metrics(card_id: str) -> dict:
    """The card's metric values at no filters (All): {name: value}."""
    return card(card_id).get("metrics") or {}


def show_value(v) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, str):
        return repr(v[:40])
    return "null" if v is None else str(v)


def shape(value, depth: int = 0) -> str:
    """Short description of a JSON value's shape: what the chart's `data` prop holds (no values dumped)."""
    if isinstance(value, dict):
        if depth >= 2:
            return f"object ({len(value)} keys)"
        inner = ", ".join(f"{k}: {shape(v, depth + 1)}" for k, v in list(value.items())[:14])
        return "{" + inner + (", ..." if len(value) > 14 else "") + "}"
    if isinstance(value, list):
        if not value:
            return "list[0]"
        first = next((v for v in value if v is not None), None)
        nulls = " (some null)" if any(v is None for v in value) else ""
        kind = shape(first, depth + 1) if isinstance(first, (dict, list)) else _kind(first)
        example = f" e.g. {show_value(first)}" if not isinstance(first, (dict, list)) and first is not None else ""
        return f"list[{len(value)}] of {kind}{example}{nulls}"
    return _kind(value)


def _kind(v) -> str:
    return {bool: "boolean", str: "text", float: "number", int: "number", type(None): "null"}.get(type(v), type(v).__name__)
