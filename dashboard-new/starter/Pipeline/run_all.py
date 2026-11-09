"""Pull every table into a staging folder, then swap it in as Data/Current (only if every script succeeded).

Runs each Pipeline/*.py except this file and files starting with "_".

Usage:
    python Pipeline/run_all.py                         slow filters as they are now: values a reader picked in the
                                                       dashboard are kept, the rest use their defaults
    python Pipeline/run_all.py --param as_of=2026-07-31   pick a value (kept by later runs until changed)
    python Pipeline/run_all.py --defaults              forget picked values: every slow filter back to its default
    python Pipeline/run_all.py --out <folder> --no-swap   (used by the Analysis server, which swaps under its own lock)
    python Pipeline/run_all.py --try sales_monthly.py      run ONE script into Data/.try/<name>/ and show what it
                                                           wrote; Data/Current is not touched (safe while others work)

A failed run leaves Data/Current untouched.

Slow filters ("parameters" in dashboard.config.json) are recorded in Data/Current/manifest.json:
    "params"         every value this data was pulled with (what the dashboard shows as selected)
    "params_chosen"  the ones picked on purpose, i.e. different from their default when picked. A plain run keeps
                     these, so a scheduled refresh doesn't undo a reader's choice. A value picked equal to its
                     default isn't kept, so "latest" keeps rolling forward.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from _dataset_io import CURRENT, DATA, default_params, param_specs, read_manifest, write_manifest

HERE = Path(__file__).resolve().parent


def check_params(values: dict) -> list[str]:
    spec = param_specs()
    problems = [f"unknown parameter {k!r} (defined: {', '.join(spec) or 'none'})" for k in values if k not in spec]
    for k, v in values.items():
        if spec.get(k, {}).get("type") == "month_end":
            import datetime as dt
            try:
                d = dt.date.fromisoformat(v)
                if (d + dt.timedelta(days=1)).day != 1:
                    problems.append(f"{k}: {v} is not a month end")
            except ValueError:
                problems.append(f"{k}: {v!r} is not a date (YYYY-MM-DD)")
        elif isinstance(spec.get(k, {}).get("options"), list) and v not in [str(o) for o in spec[k]["options"]]:
            problems.append(f"{k}: {v!r} is not one of its options ({', '.join(map(str, spec[k]['options']))})")
    return problems


def with_kept_choices(values: dict) -> dict:
    """The values picked earlier (manifest "params_chosen"), overridden by this run's --param values. A kept value
    that is no longer allowed (an option removed from the config) is dropped with a warning."""
    kept = read_manifest(CURRENT).get("params_chosen") or {}
    out = {}
    for k, v in kept.items():
        problems = check_params({k: str(v)})
        if problems:
            print(f"WARN  not keeping {k}={v}: {'; '.join(problems)}", flush=True)
        else:
            out[k] = str(v)
    if out and any(k not in values for k in out):
        print(f"Keeping values picked earlier: {json.dumps({k: v for k, v in out.items() if k not in values})} "
              "(--defaults resets them)", flush=True)
    return {**out, **values}


def chosen_only(values: dict) -> dict:
    """The values that differ from their default: the ones a later plain run should keep."""
    defaults = default_params()
    return {k: v for k, v in values.items() if str(v) != defaults.get(k)}


def carry_dropped_files(out: Path) -> None:
    """Keep .parquet/.csv files that were put in Data/Current by hand (not written by a pipeline script)."""
    if not CURRENT.exists():
        return
    written = {e.get("path") for e in read_manifest(CURRENT).get("tables", {}).values()}
    for f in CURRENT.iterdir():
        if f.suffix.lower() in (".parquet", ".csv") and f.name not in written and not (out / f.name).exists():
            shutil.copy2(f, out / f.name)
            print(f"  kept {f.name} (added by hand)", flush=True)


def swap_in(staging: Path) -> None:
    """Replace Data/Current with the staging folder (old copy removed after the swap)."""
    old = DATA / f".old-{int(time.time())}"
    if CURRENT.exists():
        CURRENT.rename(old)
    staging.rename(CURRENT)
    shutil.rmtree(old, ignore_errors=True)


def run(values: dict, out: Path) -> int:
    scripts = sorted(p for p in HERE.glob("*.py") if p.name != "run_all.py" and not p.name.startswith("_"))
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    env = {**os.environ, "DASH_PIPELINE_OUT": str(out), "DASH_PARAMS": json.dumps(values)}
    print(f"Parameters: {json.dumps({**default_params(), **values})}", flush=True)
    for script in scripts:
        print(f"> {script.name}", flush=True)
        if subprocess.run([sys.executable, str(script)], cwd=HERE, env=env).returncode != 0:
            print(f"FAILED: {script.name}; nothing was replaced", flush=True)
            shutil.rmtree(out, ignore_errors=True)
            return 1
    carry_dropped_files(out)
    manifest = read_manifest(out)
    manifest["params"] = {**default_params(), **values}
    manifest["params_chosen"] = chosen_only(values)
    write_manifest(manifest, out)
    print(f"OK: {len(scripts)} script(s), {len(manifest['tables'])} table(s)", flush=True)
    return 0


def try_one(name: str, values: dict) -> int:
    """Run one script into Data/.try/<stem>/ and describe each table it wrote. Never touches Data/Current."""
    script = HERE / (name if name.endswith(".py") else f"{name}.py")
    if not script.exists():
        print(f"ERROR no script {script.name} in Pipeline/")
        return 2
    out = DATA / ".try" / script.stem
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    env = {**os.environ, "DASH_PIPELINE_OUT": str(out), "DASH_PARAMS": json.dumps(values)}
    print(f"> {script.name} (trial run into {out.relative_to(DATA.parent)})", flush=True)
    if subprocess.run([sys.executable, str(script)], cwd=HERE, env=env).returncode != 0:
        print(f"FAILED: {script.name}")
        return 1
    tables = read_manifest(out).get("tables", {})
    if not tables:
        print("WARNING the script finished but wrote no table (call write_dataset(...) at the end)")
        return 1
    try:
        import pandas as pd
    except ImportError:
        pd = None
    for tname, entry in tables.items():
        print()
        print(f"table {tname}: {entry.get('rows', '?')} rows, grain: {entry.get('grain') or '(not given)'}")
        if pd is not None:
            try:
                df = pd.read_parquet(out / entry["path"]) if entry["path"].endswith(".parquet") else pd.read_csv(out / entry["path"])
                for col in df.columns:
                    s = df[col]
                    ranged = pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s)
                    info = f"{s.min()} .. {s.max()}" if ranged and s.notna().any() else f"{s.nunique()} distinct"
                    print(f"  {col:<28} {str(s.dtype):<10} {info}")
                print(df.head(5).to_string(index=False))
            except Exception as e:  # the table was written; only the preview failed
                print(f"  (couldn't preview it: {type(e).__name__}: {e})")
    print()
    print("OK (trial only: run npm run pipeline to put it in Data/Current)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", action="append", default=[], help="name=value (repeatable)")
    ap.add_argument("--out", help="staging folder (default Data/.staging)")
    ap.add_argument("--no-swap", action="store_true", help="leave the result in --out")
    ap.add_argument("--defaults", action="store_true", help="forget values picked earlier; use every default")
    ap.add_argument("--try", dest="trial", metavar="SCRIPT", help="run one script into Data/.try/ and describe it")
    a = ap.parse_args()
    values = dict(p.split("=", 1) for p in a.param)
    problems = check_params(values)
    if problems:
        print("ERROR " + "; ".join(problems))
        return 2
    if not a.defaults:
        values = with_kept_choices(values)
    if a.trial:
        return try_one(a.trial, values)
    out = Path(a.out) if a.out else DATA / ".staging"
    code = run(values, out)
    if code == 0 and not a.no_swap:
        swap_in(out)
        print("Swapped in as Data/Current", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
