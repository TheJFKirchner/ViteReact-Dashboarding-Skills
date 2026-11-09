"""Shared writer for pipeline scripts. The only code that writes Data/.

A pipeline run pulls source data ONCE (slow) into local parquet tables; the Analysis server reads them on
every request (fast). One set of tables exists at a time: Data/Current/.

Usage from a dataset script:
    from _dataset_io import params, write_dataset
    p = params()                     # {"as_of": date(2026, 10, 31), ...}: the run's slow parameters
    write_dataset("sales_monthly", rows_or_dataframe,
                  grain="month x region",
                  source="Sales ledger - through Oct 2026",
                  description="Revenue by month and region")  # optional

Slow filters (dashboard.config.json "parameters": a snapshot date, a region of a huge table, any value the query
needs) are passed by run_all.py to every script. A script decides what they mean for its source.
"""
from __future__ import annotations

import datetime as dt
import inspect
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "Data"
CURRENT = DATA / "Current"
OUT = Path(os.environ.get("DASH_PIPELINE_OUT") or CURRENT)   # run_all.py points this at a staging folder
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_config() -> dict:
    return json.loads((ROOT / "dashboard.config.json").read_text(encoding="utf-8"))


def param_specs() -> dict:
    """dashboard.config.json "parameters", without "_note"-style keys."""
    return {k: v for k, v in (load_config().get("parameters") or {}).items() if not k.startswith("_")}


def last_month_end(today: dt.date | None = None) -> dt.date:
    return (today or dt.date.today()).replace(day=1) - dt.timedelta(days=1)


def default_params() -> dict:
    """Each slow parameter's default value (as strings, like the API sends them)."""
    out = {}
    for name, spec in param_specs().items():
        if spec.get("type") == "month_end":
            d = spec.get("default", "latest")
            d = last_month_end().isoformat() if d == "latest" else d
        else:   # a fixed list: its "default", else the first option
            opts = spec.get("options") if isinstance(spec.get("options"), list) else []
            d = spec.get("default", opts[0] if opts else "")
        out[name] = str(d)
    return out


def params() -> dict:
    """This run's slow parameters: defaults, overridden by run_all.py (DASH_PARAMS). Dates become date objects."""
    values = default_params()
    values.update(json.loads(os.environ.get("DASH_PARAMS") or "{}"))
    spec = param_specs()
    return {k: (dt.date.fromisoformat(v) if spec.get(k, {}).get("type") == "month_end" else v) for k, v in values.items()}


def _clean(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and value != value:  # NaN -> null
        return None
    return value


def _frame(rows):
    import pandas as pd

    if hasattr(rows, "to_parquet"):
        df = rows.copy()
    else:
        df = pd.DataFrame([{k: _clean(v) for k, v in r.items()} for r in rows])
    for col in df.columns:
        if str(df[col].dtype).startswith("datetime"):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    return df


def _col_type(series) -> str:
    kind = str(series.dtype)
    if kind == "bool":
        return "boolean"
    if kind.startswith(("int", "float", "Int", "Float")):
        return "number"
    vals = series.dropna().astype(str)
    if len(vals) and vals.str.match(_DATE.pattern).all():
        return "date"
    return "string"


def read_manifest(folder: Path = OUT) -> dict:
    f = folder / "manifest.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"generated_at": None, "params": {}, "tables": {}}


def write_manifest(manifest: dict, folder: Path = OUT) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    manifest["generated_at"] = dt.datetime.now().replace(microsecond=0).isoformat()
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def write_dataset(name: str, rows, *, grain: str, source: str, description: str | None = None, as_of: str | None = None) -> Path:
    """Write one table as Data/.../<name>.parquet and record it in the manifest.

    as_of: the table's data completeness date; defaults to the run's "as_of" parameter."""
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise ValueError(f"dataset name must be snake_case: {name!r}")
    df = _frame(rows)
    if df.empty:
        raise ValueError(f"{name}: no rows")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.parquet"
    df.to_parquet(path, index=False)

    run = params()
    manifest = read_manifest()
    manifest["params"] = {k: _clean(v) for k, v in run.items()}
    manifest["tables"][name] = {
        "path": path.name,
        "grain": grain,
        "columns": {c: _col_type(df[c]) for c in df.columns},
        "rows": int(len(df)),
        "as_of": str(as_of or _clean(run.get("as_of")) or ""),
        "source": source,
        "script": Path(inspect.stack()[1].filename).name,   # which pipeline script wrote it (dev inspector only)
    }
    if description:
        manifest["tables"][name]["description"] = description
    write_manifest(manifest)
    print(f"  wrote {name}.parquet: {len(df):,} rows, {path.stat().st_size / 1e6:.2f} MB", flush=True)
    return path
