"""Precompute a report's card results for a standalone export (used by Tools/export.mjs).

    python Analysis/precompute.py --report Reports/example.json --out .export/precomputed.json
    python Analysis/precompute.py --report Reports/example.json --estimate        count + estimated size only
    ... [--cards s1_summary,s2_revenue_trend] the report's cards (export.mjs passes them; default: read from
                                              the report: "sections", "reportTabs", or "tabs" via meta.tab)

Combinations (v2 report format, see _PORTING.md): every fast filter used by an included card is either fixed
(locked, or not listed = "All") or choosable among its "options"; the allowed combinations are the cartesian
product of those, then "combinations.only" keeps combos matching any rule and "combinations.except" drops
matching ones. Each card runs once per distinct value of ITS OWN filters (Src/Lib/source.js comboKey).

Output file: {"meta": like /api/meta (report options only, fixed parameters, manifest without "script",
pipeline null), "cards": {id: {comboKey: {"data", "metrics"}}}, "combos": [{filter: value}, ...]}
Stdout: one JSON summary {combinations, card_runs, estimated_bytes | bytes, ...}. Problems go to stderr as
"ERROR ..." / "WARN  ..." lines; exit 1 on errors (including over the limits).
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from check import import_modules, parameters  # noqa: E402
from Shared import engine, tables  # noqa: E402
from Shared.registry import CARDS  # noqa: E402

ALL = tables.ALL
DEFAULT_MAX_COMBOS, HARD_MAX_COMBOS = 500, 2000
WARN_BYTES, STOP_BYTES = 5_000_000, 25_000_000
SECTIONS = tables.ROOT / "Src" / "Sections"


class Problem(Exception):
    pass


def warn(msg: str):
    print(f"WARN  {msg}", file=sys.stderr, flush=True)


def combo_key(names: list[str], values: dict) -> str:
    """Same as comboKey() in Src/Lib/source.js."""
    return "|".join(f"{n}={values.get(n, ALL)}" for n in sorted(names))


def report_cards(report: dict, given: str | None) -> list[str]:
    if given:
        return [c for c in given.split(",") if c]
    if isinstance(report.get("reportTabs"), list):
        return [cid for t in report["reportTabs"] for cid in (t.get("sections") or [])]
    if isinstance(report.get("tabs"), list):
        # registry order isn't known here (that's Src/Sections/index.js); file order by section number is close
        found = []
        for f in SECTIONS.glob("s*.jsx"):
            m = re.search(r"\btab:\s*['\"]([^'\"]+)['\"]", f.read_text(encoding="utf-8"))
            if m and m.group(1) in report["tabs"]:
                found.append(f.stem)
        return sorted(found, key=lambda s: int(re.match(r"s(\d+)", s).group(1)))
    return list(report.get("sections") or [])


def as_list(v) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def plan(report: dict, card_ids: list[str], data_options: dict) -> tuple[dict, list[dict], dict]:
    """-> (filters {name: {value, locked, options}}, allowed combos, limits). Raises Problem."""
    specs = tables.specs("filters")
    used = [n for n in specs if any(n in CARDS[c].filters for c in card_ids)]
    rf = report.get("filters") or {}
    for n in rf:
        if n not in specs:
            raise Problem(f'filter "{n}" is not defined in dashboard.config.json "filters" ({", ".join(specs)})')
        if n not in used:
            warn(f'filter "{n}" is not used by any included card; ignored')
    filters = {}
    for n in used:
        spec = rf.get(n) or {}
        known = data_options.get(n, [ALL])
        if spec.get("options") is not None:
            if spec.get("locked"):
                raise Problem(f'filter "{n}" is locked; "options" only applies to filters the viewer can change')
            options = as_list(spec["options"])
            if not options:
                raise Problem(f'filter "{n}": "options" must be a non-empty list')
            if len(set(options)) != len(options):
                raise Problem(f'filter "{n}": "options" has duplicates')
            value = str(spec.get("value", options[0]))
            if value not in options:
                raise Problem(f'filter "{n}" starts at "{value}", which is not in its options {options}')
            locked = False
        else:
            value = str(spec.get("value", ALL))
            options, locked = [value], True
        bad = [o for o in options if o not in known]
        if bad:
            raise Problem(f'filter "{n}": {", ".join(map(repr, bad))} not found in the data (values: {", ".join(known)})')
        filters[n] = {"value": value, "locked": locked, "options": options}

    names = list(filters)
    combos = [dict(zip(names, vals)) for vals in itertools.product(*(filters[n]["options"] for n in names))]
    rules = report.get("combinations") or {}
    if not isinstance(rules, dict) or set(rules) - {"only", "except"}:
        raise Problem('"combinations" must be {"only": [rules], "except": [rules]}')

    def rule_ok(rule, where):
        if not isinstance(rule, dict) or not rule:
            raise Problem(f'{where}: each rule is an object like {{"region": ["East", "West"]}}')
        for k, v in rule.items():
            if k not in filters:
                raise Problem(f'{where}: filter "{k}" is not used by this report\'s cards ({", ".join(names) or "none"})')
            for x in as_list(v):
                if x not in filters[k]["options"]:
                    raise Problem(f'{where}: "{x}" is not one of filter "{k}"\'s values in this report {filters[k]["options"]}')

    def matches(combo, rule):
        return all(combo[k] in as_list(v) for k, v in rule.items())

    for kind in ("only", "except"):
        lst = rules.get(kind)
        if lst is None:
            continue
        if not isinstance(lst, list) or not lst:
            raise Problem(f'combinations.{kind} must be a non-empty list of rules')
        for i, r in enumerate(lst):
            rule_ok(r, f"combinations.{kind}[{i}]")
    if rules.get("only"):
        combos = [c for c in combos if any(matches(c, r) for r in rules["only"])]
    if rules.get("except"):
        combos = [c for c in combos if not any(matches(c, r) for r in rules["except"])]
    if not combos:
        raise Problem("no filter combinations left after combinations.only / except")
    start = {n: f["value"] for n, f in filters.items()}
    if start not in combos:
        raise Problem(f"the starting values {start} are excluded by \"combinations\"; the report would open on an empty page")

    mx = report.get("maxCombinations", DEFAULT_MAX_COMBOS)
    if not isinstance(mx, int) or isinstance(mx, bool) or mx < 1 or mx > HARD_MAX_COMBOS:
        raise Problem(f'"maxCombinations" must be a whole number from 1 to {HARD_MAX_COMBOS}')
    return filters, combos, {"max_combinations": mx}


def check_parameters(report: dict, m: dict) -> dict:
    """Pinned parameters must be what Data/Current holds (export.mjs re-runs the pipeline first)."""
    known = parameters(m)
    pinned = {str(k): str(v) for k, v in (report.get("parameters") or {}).items()}
    for k, v in pinned.items():
        if k not in known:
            raise Problem(f'unknown parameter "{k}" (defined: {", ".join(known) or "none"})')
        if v not in [o["value"] for o in known[k]["options"]]:
            raise Problem(f'parameter "{k}": "{v}" is not an allowed value')
    loaded = {k: str(v) for k, v in (m.get("params") or {}).items()}
    diff = {k: v for k, v in pinned.items() if loaded.get(k) != v}
    if diff:
        raise Problem(f"the report pins {diff} but Data/Current was pulled with {loaded}; "
                      f"npm run export re-runs the pipeline for this (or: python Pipeline/run_all.py --param ...)")
    out = {}
    for k, p in known.items():
        value = pinned.get(k, p["value"])
        label = next((o["label"] for o in p["options"] if o["value"] == value), value)
        out[k] = {**p, "options": [{"value": value, "label": label}], "value": value, "fixed": True}
    return out


def build_meta(m: dict, filters: dict, card_ids: list[str], params: dict) -> dict:
    specs = tables.specs("filters")
    manifest = {**m, "tables": {n: {k: v for k, v in e.items() if k != "script"} for n, e in m["tables"].items()}}
    used_tables = {t for c in card_ids for t in CARDS[c].tables}
    manifest["tables"] = {n: e for n, e in manifest["tables"].items() if n in used_tables}
    return {
        "filters": {n: {"label": s.get("label", n), "column": s.get("column", n),
                        "options": filters[n]["options"] if n in filters else [ALL]} for n, s in specs.items()},
        "parameters": params,
        "cards": {c: {"filters": CARDS[c].filters, "tables": CARDS[c].tables, "module": CARDS[c].module} for c in card_ids},
        "manifest": manifest,
        "version": 0,
        "pipeline": None,
    }


def size(obj) -> int:
    return len(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def run_card(cid: str, values: dict) -> dict:
    r = engine.run(cid, values)
    if "error" in r:
        shown = ", ".join(f"{k}={v}" for k, v in values.items()) or "all filters at All"
        raise Problem(f"card {cid} failed for {shown}: {r['error']}")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True, help="report JSON file (v2 format)")
    ap.add_argument("--out", help="output JSON file (required unless --estimate)")
    ap.add_argument("--estimate", action="store_true", help="print combination count + estimated size, compute nothing else")
    ap.add_argument("--cards", help="comma-separated card ids (default: from the report)")
    a = ap.parse_args()
    if not a.estimate and not a.out:
        ap.error("--out is required unless --estimate")
    try:
        report = json.loads(Path(a.report).read_text(encoding="utf-8"))
        broken = {k: v for k, v in import_modules().items() if v}
        card_ids = report_cards(report, a.cards)
        if not card_ids:
            raise Problem("the report has no cards")
        missing = [c for c in card_ids if c not in CARDS]
        if missing:
            extra = f" (modules failing to import: {broken})" if broken else ""
            raise Problem(f"no Analysis function for {', '.join(missing)}{extra}")
        m = tables.manifest()
        if not m["tables"]:
            raise Problem("no data yet: run python Pipeline/run_all.py, or put .parquet/.csv files in Data/Current")
        params = check_parameters(report, m)
        filters, combos, limits = plan(report, card_ids, tables.filter_options(m))

        # per card: the distinct values of its own filters among the allowed combos
        per_card = {}
        for c in card_ids:
            names = CARDS[c].filters
            seen = {}
            for combo in combos:
                vals = {n: combo.get(n, ALL) for n in names}
                seen.setdefault(combo_key(names, vals), vals)
            per_card[c] = seen
        runs = sum(len(v) for v in per_card.values())
        start = {n: f["value"] for n, f in filters.items()}

        t0 = time.perf_counter()
        first = {c: run_card(c, {n: start.get(n, ALL) for n in CARDS[c].filters}) for c in card_ids}
        sample_s = time.perf_counter() - t0
        meta = build_meta(m, filters, card_ids, params)
        estimate = size(meta) + size(combos) + sum(size(first[c]) * len(per_card[c]) for c in card_ids)
        summary = {
            "cards": len(card_ids),
            "combinations": len(combos),
            "card_runs": runs,
            "estimated_bytes": estimate,
            "estimated_seconds": round(sample_s / len(card_ids) * runs, 1),
            "max_combinations": limits["max_combinations"],
            "filters": {n: f["options"] for n, f in filters.items() if not f["locked"]},
            "fixed": {n: f["value"] for n, f in filters.items() if f["locked"]},
            "parameters": {k: p["value"] for k, p in params.items()},
        }
        problems = []
        if len(combos) > limits["max_combinations"]:
            problems.append(f"{len(combos)} combinations is over the limit of {limits['max_combinations']} "
                            f"(narrow the options or use \"combinations\"; \"maxCombinations\" can raise it up to {HARD_MAX_COMBOS})")
        if estimate > STOP_BYTES:
            problems.append(f"estimated {estimate / 1e6:.1f} MB of results is over the {STOP_BYTES / 1e6:.0f} MB limit")
        if a.estimate or problems:
            print(json.dumps(summary))
            for p in problems:
                print(f"ERROR {p}", file=sys.stderr)
            return 1 if problems else 0

        cards = {c: {} for c in card_ids}
        for c in card_ids:
            for key, vals in per_card[c].items():
                cards[c][key] = first[c] if vals == {n: start.get(n, ALL) for n in CARDS[c].filters} else run_card(c, vals)
        out = {"meta": meta, "cards": cards, "combos": combos}
        text = json.dumps(out, separators=(",", ":"))
        nbytes = len(text.encode("utf-8"))
        if nbytes > STOP_BYTES:
            print(json.dumps({**summary, "bytes": nbytes}))
            print(f"ERROR results are {nbytes / 1e6:.1f} MB, over the {STOP_BYTES / 1e6:.0f} MB limit", file=sys.stderr)
            return 1
        if nbytes > WARN_BYTES:
            warn(f"results are {nbytes / 1e6:.1f} MB (over {WARN_BYTES / 1e6:.0f} MB); the export will be slow to open")
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(json.dumps({**summary, "bytes": nbytes, "seconds": round(time.perf_counter() - t0, 1), "out": str(a.out)}))
        return 0
    except Problem as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
