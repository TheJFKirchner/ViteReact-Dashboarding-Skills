"""Project check for the Analysis side (used by Tools/check.mjs; no server needed).

    python Analysis/check.py                 every card, each run with all its fast filters at "All"
    python Analysis/check.py --cards s1_summary,s2_revenue_trend
    python Analysis/check.py --show s3_paid_by_region [--filter region=East]   one card's full result, readable

Prints JSON on stdout:
    {
      "cards":      {id: {"filters", "tables", "module", "metrics", "error"}},
      "modules":    {module: null | "import error"},     # a topic module that fails to import registers no cards
      "filters":    {name: [All, ...values in the data]},
      "parameters": {name: {label, type, options, value, default}},   # same as /api/meta
      "manifest":   Data/Current/manifest.json
    }
Exit code 0 even when cards fail (the failures are in the JSON); 2 when there is no data at all.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from Shared import engine, tables  # noqa: E402
from Shared.registry import CARDS  # noqa: E402

SKIP = {"server", "check", "precompute"}


def import_modules() -> dict:
    """Import every topic module separately, so one broken module doesn't hide the others' cards."""
    out = {}
    for f in sorted(HERE.glob("*.py")):
        name = f.stem
        if name in SKIP or name.startswith("_"):
            continue
        try:
            importlib.import_module(name)
            out[name] = None
        except Exception as e:  # noqa: BLE001 - reported by Tools/check.mjs
            tb = traceback.extract_tb(e.__traceback__)
            where = next((f"{Path(fr.filename).name}:{fr.lineno}" for fr in reversed(tb) if Path(fr.filename).parent == HERE), "")
            if isinstance(e, SyntaxError) and e.lineno:
                where = f"{Path(e.filename or f).name}:{e.lineno}"
            out[name] = f"{type(e).__name__}: {e}" + (f" ({where})" if where else "")
    return out


def parameters(m: dict) -> dict:
    import server  # the same parameter logic as /api/meta
    return server.parameters(m)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cards", help="comma-separated card ids (default: every registered card)")
    ap.add_argument("--show", metavar="CARD", help="print one card's full result (data and metrics) as indented JSON")
    ap.add_argument("--filter", action="append", default=[], metavar="NAME=VALUE", help="with --show: a filter choice")
    a = ap.parse_args()

    modules = import_modules()
    m = tables.manifest()
    if not m["tables"]:
        print(json.dumps({"error": "No data yet. Run python Pipeline/run_all.py, or put .parquet/.csv files in Data/Current", "modules": modules}))
        return 2
    if a.show:
        broken = {k: v for k, v in modules.items() if v}
        if a.show not in CARDS:
            print(json.dumps({"error": f"no Analysis function for {a.show}", "broken_modules": broken}, indent=2))
            return 1
        chosen = dict(f.split("=", 1) for f in a.filter if "=" in f)
        print(json.dumps({"card": a.show, "filters": engine.card_filters(a.show, chosen), **engine.run(a.show, chosen)}, indent=2, default=str))
        return 0
    wanted = [c for c in a.cards.split(",") if c] if a.cards else list(CARDS)
    cards = {}
    for cid in wanted:
        c = CARDS.get(cid)
        if not c:
            cards[cid] = {"filters": [], "tables": [], "module": None, "metrics": {}, "error": "no Analysis function registered"}
            continue
        t0 = time.perf_counter()
        result = engine.run(cid, {})    # every filter at "All"
        cards[cid] = {
            "filters": c.filters,
            "tables": c.tables,
            "module": c.module,
            "metrics": result.get("metrics", {}),
            "error": result.get("error"),
            "bytes": len(json.dumps(result, separators=(",", ":"))) if "error" not in result else None,
            "seconds": round(time.perf_counter() - t0, 3),
        }
    print(json.dumps({
        "cards": cards,
        "modules": modules,
        "filters": tables.filter_options(m),
        "parameters": parameters(m),
        "manifest": m,
    }, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
