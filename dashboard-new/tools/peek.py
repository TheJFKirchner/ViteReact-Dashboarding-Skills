"""Read-only inventory of a folder, for the survey helper (or anyone) before planning a dashboard.

    python <skill>/tools/peek.py <folder> [--max-files 400] [--depth 6] [--json]

Lists, without changing, running or copying anything:
  - data files (.csv .tsv .txt-with-delimiters .parquet .xlsx .xls .json .feather): columns, types, rows,
    date ranges, and which columns look like filters (few distinct values) or measures (numbers)
  - scripts and notebooks (.py .ipynb .sql .r .R): which data files they seem to read and write (hints only)
  - outputs (.html .png .jpg .svg .pdf), and possible index/readme files that describe the data
Anything it can't read is listed with the reason; it never stops on a bad file. Big files are sampled.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "env", "site-packages", ".ipynb_checkpoints",
             ".vite", ".idea", ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache", ".dashboard-agent"}
DATA_EXT = {".csv", ".tsv", ".parquet", ".pq", ".xlsx", ".xlsm", ".xls", ".json", ".feather", ".txt"}
CODE_EXT = {".py", ".ipynb", ".sql", ".r"}
OUTPUT_EXT = {".html", ".htm", ".png", ".jpg", ".jpeg", ".svg", ".pdf", ".pptx", ".docx"}
INDEX_NAMES = re.compile(r"^(readme|index|data[_ -]?index|data[_ -]?dictionary|catalog|about|notes)\b", re.I)
SAMPLE_ROWS = 50_000
BIG_BYTES = 150 * 1024 * 1024
DATA_REF = re.compile(r"""["']([^"'\n]{1,240}\.(?:csv|tsv|parquet|pq|xlsx|xlsm|xls|json|feather|html|png|pdf|sqlite|db))["']""", re.I)
WRITE_HINT = re.compile(r"\.(to_csv|to_parquet|to_excel|to_html|to_json|savefig|write_image|write_html|save)\s*\(|open\([^)]*['\"]w", re.I)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def walk(root: Path, max_files: int, depth: int):
    files, skipped, truncated = [], [], False
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel_depth = len(d.relative_to(root).parts)
        keep = []
        for n in sorted(dirnames):
            if n in SKIP_DIRS or n.startswith("."):
                skipped.append(str((d / n).relative_to(root)))
            elif rel_depth >= depth:
                skipped.append(str((d / n).relative_to(root)) + " (too deep)")
            else:
                keep.append(n)
        dirnames[:] = keep
        for n in sorted(filenames):
            if len(files) >= max_files:
                truncated = True
                break
            files.append(d / n)
        if truncated:
            break
    return files, skipped, truncated


def read_table(path: Path):
    """-> (DataFrame sample, total rows or None, note). Raises on failure."""
    import pandas as pd
    ext = path.suffix.lower()
    size = path.stat().st_size
    note = ""
    if ext in (".parquet", ".pq"):
        try:
            import pyarrow.parquet as pq
            meta = pq.ParquetFile(path).metadata
            total = meta.num_rows
            df = pq.ParquetFile(path).read_row_groups([0]).to_pandas() if meta.num_row_groups else pd.DataFrame()
            if len(df) > SAMPLE_ROWS:
                df = df.head(SAMPLE_ROWS)
            if total > len(df):
                note = f"sampled first {len(df):,} rows"
            return df, total, note
        except ImportError:
            df = pd.read_parquet(path)
            return df, len(df), note
    if ext == ".feather":
        df = pd.read_feather(path)
        return df, len(df), note
    if ext in (".xlsx", ".xlsm", ".xls"):
        sheets = pd.read_excel(path, sheet_name=None, nrows=SAMPLE_ROWS)
        return {name: (df, len(df) if len(df) < SAMPLE_ROWS else None) for name, df in list(sheets.items())[:10]}, None, (
            f"{len(sheets)} sheets" + (" (first 10 shown)" if len(sheets) > 10 else ""))
    if ext == ".json":
        if size > BIG_BYTES:
            raise ValueError("JSON too large to sample safely")
        try:
            df = pd.read_json(path)
        except ValueError:
            df = pd.read_json(path, lines=True)
        return df.head(SAMPLE_ROWS), len(df), note
    # delimited text
    sep = "\t" if ext == ".tsv" else None
    last_err = None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(path, sep=sep, engine="python", nrows=SAMPLE_ROWS, encoding=enc, on_bad_lines="skip")
            if enc == "latin-1":
                note = "not UTF-8 (read as latin-1)"
            break
        except UnicodeDecodeError as e:
            last_err = e
    else:
        raise last_err or ValueError("could not decode")
    if ext == ".txt" and df.shape[1] < 2:
        raise ValueError("plain text, not a table")
    total = None
    if size <= BIG_BYTES:
        with open(path, "rb") as f:
            total = max(0, sum(1 for _ in f) - 1)
    if total is None or total > len(df):
        note = (note + "; " if note else "") + f"sampled first {len(df):,} rows"
    return df, total, note


def profile(df) -> list[dict]:
    import pandas as pd
    cols = []
    n = len(df)
    for c in df.columns:
        s = df[c]
        info = {"name": str(c), "type": str(s.dtype), "nulls": int(s.isna().sum())}
        try:
            nun = int(s.nunique(dropna=True))
            info["distinct"] = nun
            if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
                if s.notna().any():
                    info["min"], info["max"] = float(s.min()), float(s.max())
                whole = pd.api.types.is_integer_dtype(s) or (s.dropna() % 1 == 0).all()
                if whole and n > 20 and nun >= 0.95 * s.notna().sum():
                    info["looks_like"] = "id (nearly every value different)"
                elif not whole or nun > 12:
                    info["looks_like"] = "measure"
                else:
                    info["looks_like"] = "code/category (numeric)"
            else:
                as_date = None
                if pd.api.types.is_datetime64_any_dtype(s):
                    as_date = s
                elif s.dtype == object or str(s.dtype).startswith("str"):
                    sample = s.dropna().astype(str).head(2000)
                    if len(sample) and sample.str.match(r"^\d{4}-\d{2}(-\d{2})?").mean() > 0.8:
                        as_date = pd.to_datetime(s, errors="coerce")
                    elif len(sample) and sample.str.match(r"^\d{1,2}/\d{1,2}/\d{2,4}").mean() > 0.8:
                        parts = sample.str.extract(r"^(\d{1,2})/(\d{1,2})/").astype(int)
                        day_first = (parts[0] > 12).any()
                        month_first = (parts[1] > 12).any()
                        order = "day/month/year" if day_first and not month_first else "month/day/year" if month_first and not day_first else None
                        if order is None:
                            info["note"] = "slash dates; day/month order unclear from the values"
                        else:
                            info["format"] = order
                        as_date = pd.to_datetime(s, errors="coerce", dayfirst=(order != "month/day/year"))
                if as_date is not None and as_date.notna().any():
                    info["looks_like"] = "date"
                    info["min"], info["max"] = str(as_date.min())[:10], str(as_date.max())[:10]
                elif nun <= 30 and n:
                    info["looks_like"] = "filter candidate"
                    info["values"] = [str(v) for v in s.dropna().unique()[:12]]
                else:
                    info["looks_like"] = "text/id"
                    info["examples"] = [str(v)[:40] for v in s.dropna().unique()[:3]]
        except Exception as e:  # odd column types (lists, dicts): report, don't stop
            info["note"] = f"couldn't profile: {type(e).__name__}"
        cols.append(info)
    return cols


def code_hints(path: Path) -> dict:
    try:
        if path.suffix.lower() == ".ipynb":
            nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            cells = nb.get("cells", [])
            text = "\n".join("".join(c.get("source", [])) for c in cells if c.get("cell_type") == "code")
            extra = {"cells": len(cells), "code_cells": sum(1 for c in cells if c.get("cell_type") == "code"),
                     "has_outputs": any(c.get("outputs") for c in cells)}
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            extra = {"lines": text.count("\n") + 1}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    refs = sorted(set(m.group(1) for m in DATA_REF.finditer(text)))[:25]
    writes = bool(WRITE_HINT.search(text))
    funcs = re.findall(r"^def\s+(\w+)", text, re.M)[:20] if path.suffix.lower() in (".py", ".ipynb") else []
    imports = sorted(set(re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w]*)", text, re.M)))[:20]
    return {**extra, "mentions_files": refs, "writes_files": writes, "functions": funcs, "imports": imports}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--max-files", type=int, default=400)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(a.folder).expanduser().resolve()
    if not root.exists():
        print(f"peek: {root} doesn't exist")
        return 0
    if root.is_file():
        files, skipped, truncated = [root], [], False
        root = root.parent
    else:
        files, skipped, truncated = walk(root, a.max_files, a.depth)

    try:
        import pandas  # noqa: F401
        have_pandas = True
    except ImportError:
        have_pandas = False

    started = time.time()
    report = {"folder": str(root), "data": [], "code": [], "outputs": [], "index_files": [], "other": [],
              "skipped_folders": skipped, "truncated": truncated, "pandas": have_pandas}
    for f in files:
        rel = str(f.relative_to(root))
        ext = f.suffix.lower()
        try:
            size = f.stat().st_size
        except OSError as e:
            report["other"].append({"file": rel, "error": str(e)})
            continue
        if INDEX_NAMES.match(f.stem) and ext in (".md", ".txt", ".rst", ".yaml", ".yml", ".csv", ".xlsx", ""):
            report["index_files"].append({"file": rel, "size": human(size)})
            if ext not in (".csv", ".xlsx"):
                continue
        if ext in DATA_EXT:
            entry = {"file": rel, "size": human(size)}
            if size == 0:
                entry["error"] = "empty file"
            elif not have_pandas:
                entry["error"] = "pandas not installed; listed only"
            elif time.time() - started > 240:
                entry["error"] = "skipped (time limit reached)"
            else:
                try:
                    df, total, note = read_table(f)
                    if isinstance(df, dict):  # a workbook: one entry per sheet
                        for sheet, (sdf, srows) in df.items():
                            report["data"].append({"file": f"{rel} [sheet: {sheet}]", "size": human(size), "note": note,
                                                   "rows": srows if srows is not None else f"{len(sdf):,}+ (sampled)",
                                                   "columns": profile(sdf)})
                        continue
                    entry.update({"rows": total if total is not None else f"{len(df):,}+ (sampled)", "columns": profile(df)})
                    if note:
                        entry["note"] = note
                except Exception as e:
                    if ext in (".txt", ".json") and "not a table" in str(e).lower() or ext == ".txt":
                        report["other"].append({"file": rel, "size": human(size)})
                        continue
                    entry["error"] = f"couldn't read: {type(e).__name__}: {str(e)[:160]}"
            report["data"].append(entry)
        elif ext in CODE_EXT:
            report["code"].append({"file": rel, "size": human(size), **code_hints(f)})
        elif ext in OUTPUT_EXT:
            report["outputs"].append({"file": rel, "size": human(size)})
        else:
            report["other"].append({"file": rel, "size": human(size)})

    if a.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    p = print
    p(f"# Inventory of {root}")
    if truncated:
        p(f"(stopped after {a.max_files} files; run on a subfolder or raise --max-files for the rest)")
    if not have_pandas:
        p("(pandas isn't installed, so data files are listed but not opened)")
    p(f"\n## Index / readme files ({len(report['index_files'])})")
    for e in report["index_files"]:
        p(f"- {e['file']} ({e['size']})")
    p(f"\n## Data files ({len(report['data'])})")
    for e in report["data"]:
        p(f"\n### {e['file']}  ({e['size']}, {e.get('rows', '?')} rows)")
        if e.get("note"):
            p(f"note: {e['note']}")
        if e.get("error"):
            p(f"PROBLEM: {e['error']}")
            continue
        for c in e["columns"]:
            bits = [c["type"], c.get("looks_like", "")]
            if "min" in c:
                bits.append(f"{c['min']} .. {c['max']}")
            if c.get("format"):
                bits.append(f"written {c['format']}")
            if "values" in c:
                bits.append("values: " + ", ".join(c["values"]) + (" ..." if c.get("distinct", 0) > len(c["values"]) else ""))
            if "examples" in c:
                bits.append(f"{c.get('distinct', '?')} distinct, e.g. " + ", ".join(c["examples"]))
            if c.get("nulls"):
                bits.append(f"{c['nulls']} blank")
            if c.get("note"):
                bits.append(c["note"])
            p(f"- {c['name']}: " + "; ".join(b for b in bits if b))
    p(f"\n## Scripts and notebooks ({len(report['code'])})")
    for e in report["code"]:
        if e.get("error"):
            p(f"- {e['file']}: PROBLEM {e['error']}")
            continue
        size_bit = f"{e['cells']} cells" if "cells" in e else f"{e.get('lines', '?')} lines"
        p(f"- {e['file']} ({size_bit}){' - writes files' if e.get('writes_files') else ''}")
        if e.get("mentions_files"):
            p(f"  mentions: {', '.join(e['mentions_files'])}")
        if e.get("functions"):
            p(f"  functions: {', '.join(e['functions'])}")
        if e.get("imports"):
            p(f"  imports: {', '.join(e['imports'])}")
    p(f"\n## Outputs ({len(report['outputs'])})")
    for e in report["outputs"]:
        p(f"- {e['file']} ({e['size']})")
    if report["other"]:
        p(f"\n## Other files ({len(report['other'])})")
        for e in report["other"][:60]:
            p(f"- {e['file']}" + (f" ({e['size']})" if e.get("size") else "") + (f" PROBLEM {e['error']}" if e.get("error") else ""))
        if len(report["other"]) > 60:
            p(f"- ... {len(report['other']) - 60} more")
    if skipped:
        p(f"\n(skipped folders: {', '.join(skipped[:20])}{' ...' if len(skipped) > 20 else ''})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"peek: stopped early: {type(e).__name__}: {e} (everything above is still valid)")
        sys.exit(0)
