"""Read-only inventory of a folder, for the inventory helper (or anyone) before planning a dashboard.

    python <skill>/tools/peek.py <folder> [--max-files 400] [--depth 6] [--json]

Lists, without changing, running or copying anything:
  - data files (.csv .tsv .txt-with-delimiters .parquet .xlsx .xls .json .feather): columns, types, rows,
    date ranges, and which columns look like filters (few distinct values) or measures (numbers)
  - code (.py .ipynb .sql .r, and app code: .js .jsx .ts .tsx .vue .svelte, .java .cs .go ...), sorted into
      READ: has queries or calculations (SQL, groupby/merge/pivot, dplyr, read_sql ...) or draws a visual (Plotly,
            matplotlib, Dash, Streamlit, ECharts, Chart.js, Recharts, D3, ggplot, HTML tables ...), or places a
            chart component on a page, or takes a filter or input (dropdowns, widgets, run arguments, query
            parameters, a loop per segment, a date typed in at the top). Each with the kind of hit and the lines.
      NOT NEEDED: everything else (servers, routing, auth, config, build, tests, styles, plain UI parts, vendored
            code), grouped by reason. These don't need opening to plan a dashboard or a migration.
  - outputs (.html .png .jpg .svg .pdf, Tableau/Power BI files), and possible index/readme files about the data
Anything it can't read is listed with the reason; it never stops on a bad file. Big files are sampled.
The sorting is by pattern, so it can be wrong: a skipped file can be opened when a READ file points to it.
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
             ".vite", ".idea", ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache", ".dashboard-agent",
             "coverage", ".next", ".nuxt", "out", "target", "bin", "obj", "bower_components"}
DATA_EXT = {".csv", ".tsv", ".parquet", ".pq", ".xlsx", ".xlsm", ".xls", ".json", ".feather", ".txt"}
CODE_EXT = {".py", ".ipynb", ".sql", ".r", ".rmd", ".qmd", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
            ".java", ".cs", ".go", ".rb", ".php", ".scala", ".kt", ".sas", ".dax"}
OUTPUT_EXT = {".html", ".htm", ".png", ".jpg", ".jpeg", ".svg", ".pdf", ".pptx", ".docx", ".twb", ".twbx", ".pbix", ".pbit"}

# What makes code worth reading for a dashboard: the numbers (queries, calculations) and the visuals.
LOGIC = [
    # SQL in code: SELECT ... FROM in capitals, or a string that starts with select ... from (not `import Select from`)
    ("SQL", re.compile(r"\bSELECT\s[\s\S]{1,800}?\bFROM\s|[\"'`]\s*(?i:select)\s[^\"'`]{1,600}?\s(?i:from)\s")),
    ("calculations", re.compile(r"\.(groupby|merge|pivot_table|pivot|melt|agg|aggregate|resample|rolling|cumsum|pct_change|crosstab)\s*\(")),
    ("dplyr", re.compile(r"\b(group_by|summari[sz]e|mutate|left_join|inner_join)\s*\(")),
    ("data access", re.compile(r"\b(read_sql\w*|spark\.sql|cursor\.execute|pd\.read_\w+|dbGetQuery|sqlContext)\b")),
    ("JS calculations", re.compile(r"\b(d3\.(rollup|rollups|group|sum|mean)|_\.(groupBy|sumBy|meanBy)|groupBy)\s*\(")),
]
VISUAL = [
    ("Plotly", re.compile(r"\bplotly\b|\bpx\.[a-z_]+\(|\bgo\.(Figure|Scatter|Bar|Pie|Heatmap|Indicator)\b|\bplot_ly\(")),
    ("matplotlib/seaborn", re.compile(r"\bplt\.[a-z_]+\(|\bsns\.[a-z_]+\(|\.plot\(\s*kind=")),
    ("Altair/Bokeh", re.compile(r"\balt\.Chart\(|\bfrom bokeh|\bbokeh\.plotting")),
    ("Dash", re.compile(r"\bdcc\.Graph\b|\bdash_table\b|\bDataTable\(")),
    ("Streamlit", re.compile(r"\bst\.(plotly_chart|line_chart|bar_chart|area_chart|altair_chart|pyplot|metric|dataframe|table|map)\(")),
    ("ECharts", re.compile(r"\becharts\b|ReactECharts")),
    ("Chart.js", re.compile(r"\bnew Chart\(|react-chartjs")),
    ("React charts", re.compile(r"<(LineChart|BarChart|AreaChart|PieChart|ComposedChart|ScatterChart|Victory\w+|Responsive(Line|Bar|Pie)|AgGridReact|DataGrid|Plot)\b|highcharts|\bvega\b|ag-grid")),
    ("D3", re.compile(r"\bd3\.(select|scale\w*|axis\w*|line|area|arc|pie)\b")),
    ("ggplot/Shiny", re.compile(r"\bggplot\(|\brenderPlot\w*\(|\bDT::")),
    ("HTML table", re.compile(r"\.to_html\(|\.style\.(apply|format|background_gradient|highlight)|<table\b")),
]
# Filters and inputs: what a reader (or whoever runs it) can change, and what the queries take as a value.
# Each becomes a dashboard filter; values passed into a query or typed in before a run are slow-filter candidates.
FILTERS = [
    ("Dash inputs", re.compile(r"\bdcc\.(Dropdown|RadioItems|Checklist|Slider|RangeSlider|DatePickerRange|DatePickerSingle|Input)\b")),
    ("Streamlit inputs", re.compile(r"\bst\.(sidebar\.)?(selectbox|multiselect|radio|slider|select_slider|date_input|checkbox|text_input|number_input|segmented_control|pills)\(")),
    ("notebook widgets", re.compile(r"\bwidgets\.(Dropdown|SelectMultiple|Select|RadioButtons|DatePicker|\w*Slider|Text|ToggleButtons)\(|@interact\b")),
    ("Shiny inputs", re.compile(r"\b(selectInput|selectizeInput|dateRangeInput|dateInput|sliderInput|radioButtons|checkboxGroupInput)\(")),
    ("UI filters", re.compile(r"<(select|Select|Dropdown|DatePicker|RangePicker|DateRangePicker|Slider|Autocomplete|MultiSelect)\b[^>]*\bonChange")),
    ("request parameters", re.compile(r"\brequest\.(args|GET|query_params)\b|\bsearchParams\.get\(|\buseSearchParams\(|\bQuery\(")),
    ("run settings", re.compile(r"\.add_argument\(\s*[\"']--|@click\.option\(|\bsys\.argv\b|\bcommandArgs\(|^\s*#\s*parameters\b", re.M)),
    ("query parameters", re.compile(r"(?i:\bwhere\b|\band\b)[^\n;]{0,120}?(=|>=|<=|<|>|\bin\b|\bbetween\b)\s*\(?\s*(\?|%s|%\(\w+\)s|:[a-z_]\w*|@[a-z_]\w*|\{[a-z_]\w*\})|\bparams\s*=\s*[\[\(\{]")),
    ("per-segment loop", re.compile(r"^\s*for\s+\w+\s+in\s+[A-Z][A-Z_]{2,}\b", re.M)),
    ("setting typed in", re.compile(r"^[A-Z][A-Z_]{2,}\s*=\s*[\"']\d{4}-\d{2}(-\d{2})?[\"']|^[A-Z][A-Z_]{2,}\s*=\s*\[\s*[\"']", re.M)),
]
# Never worth reading for planning, whatever they mention
HARD_SKIP = [
    ("tests", re.compile(r"(^|/)(tests?|__tests__|spec|e2e|cypress)/|(^|/)test_[^/]*$|_test\.\w+$|\.(test|spec)\.\w+$|(^|/)conftest\.py$")),
    ("vendored or minified", re.compile(r"\.min\.\w+$|(^|/)(vendor|vendors|third_party|external)/")),
    ("config and build", re.compile(r"(^|/)(setup|manage|wsgi|asgi|settings|config|conf)\.py$|(^|/)(webpack|vite|rollup|babel|jest|eslint|prettier|tailwind|postcss|next|nuxt|svelte|tsconfig|karma)[^/]*$|\.config\.\w+$|\.d\.ts$|(^|/)(migrations|alembic)/|(^|/)tools/[^/]*\.(m?js|cjs|ts)$", re.I)),
]
# Labels for code with nothing worth reading
SOFT_REASONS = [
    ("server, routing, auth", re.compile(r"(^|/)(auth|login|middleware|routes?|router|urls|api|server|app|main|index|deploy|docker)[^/]*\.\w+$|(^|/)(auth|middleware|deploy|infra)/", re.I)),
]
CONFIG_JSON = re.compile(r"^(package(-lock)?|tsconfig[\w.-]*|jsconfig|composer|bower|lerna|nx|turbo|vercel|netlify|"
                         r"app|appsettings[\w.-]*|launch|settings|extensions|\.?eslintrc|\.?babelrc|\.?prettierrc)\.json$"
                         r"|\.config\.json$", re.I)
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
            parts, cell_starts, line = [], [], 1   # cell_starts: (first line in the joined text, cell number)
            for n, c in enumerate(cells, 1):
                if c.get("cell_type") == "code":
                    src = "".join(c.get("source", []))
                    cell_starts.append((line, n))
                    parts.append(src)
                    line += src.count("\n") + 1
            text = "\n".join(parts)
            extra = {"cells": len(cells), "code_cells": sum(1 for c in cells if c.get("cell_type") == "code"),
                     "has_outputs": any(c.get("outputs") for c in cells), "_cell_starts": cell_starts}
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            extra = {"lines": text.count("\n") + 1}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    roles = classify(path, text, extra)
    refs = sorted(set(m.group(1) for m in DATA_REF.finditer(text)))[:25]
    writes = bool(WRITE_HINT.search(text))
    funcs = re.findall(r"^def\s+(\w+)", text, re.M)[:20] if path.suffix.lower() in (".py", ".ipynb") else []
    imports = sorted(set(re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w]*)", text, re.M)))[:20]
    return {**extra, **roles, "mentions_files": refs, "writes_files": writes, "functions": funcs, "imports": imports,
            "_text": text}


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def classify(path: Path, text: str, extra: dict) -> dict:
    """{"logic", "visual", "filters": [kinds], "hit_lines", "filter_lines": [first hit lines]} from patterns."""
    logic, visual, filters, lines, flines = [], [], [], set(), set()
    if path.suffix.lower() in (".sql", ".dax", ".sas"):
        logic.append(path.suffix.lower()[1:].upper() + " file")
    for kind, rx in LOGIC:
        hits = list(rx.finditer(text))[:6]
        if hits:
            logic.append(f"{kind} x{len(hits)}" if len(hits) > 1 else kind)
            lines.update(_line(text, m.start()) for m in hits)
    for kind, rx in VISUAL:
        hits = list(rx.finditer(text))[:6]
        if hits:
            visual.append(kind)
            lines.update(_line(text, m.start()) for m in hits)
    for kind, rx in FILTERS:
        hits = list(rx.finditer(text))[:6]
        if hits:
            filters.append(kind)
            flines.update(_line(text, m.start()) for m in hits)
    if extra.get("has_outputs"):
        visual.append("notebook outputs")
    return {"logic": logic, "visual": visual, "filters": filters, "hit_lines": sorted(lines)[:12], "filter_lines": sorted(flines)[:12]}


# An integrated dashboard (v2/v3 layout): only its own pieces carry over; the rest comes fresh from the starter
INTEGRATED_OWN = re.compile(r"^(Analysis/(?!server|check|precompute)[^/]+\.py|Src/Sections/(?!index\.)[^/]+\.jsx?|Pipeline/(?!run_all|_)[^/]+\.py)$")


def sort_code(code: list[dict], root: Path) -> bool:
    """Mark each code entry read (with why) or not needed (with a reason). Returns True for an integrated dashboard.

    A file that places a chart component on a page (a visual file's name used as a tag, e.g. <TrendChart) is read:
    that's where the visual's title and data are chosen. A chart component placed by two or more files is a building
    block (a generic wrapper), not a visual of its own, so it isn't."""
    integrated = (root / "dashboard.config.json").exists() and (root / "Analysis" / "Shared" / "registry.py").exists()
    ui = (".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte")
    texts = {e["file"]: e.pop("_text", "") for e in code}
    rel = {f: f.replace("\\", "/") for f in texts}
    hard = {f: next((r for r, rx in HARD_SKIP if rx.search(rel[f])), None) for f in texts}
    components = {Path(e["file"]).stem for e in code
                  if e.get("visual") and not hard[e["file"]] and Path(e["file"]).suffix.lower() in ui
                  and Path(e["file"]).stem[:1].isupper()}
    tag = re.compile(r"<(" + "|".join(map(re.escape, sorted(components))) + r")\b") if components else None
    places, users = {}, {}
    for f, text in texts.items():
        if tag and not hard[f]:
            used = sorted(set(tag.findall(text)) - {Path(f).stem})
            places[f] = used
            for c in used:
                users.setdefault(c, []).append(f)
    for e in code:
        f = e["file"]
        if integrated:
            own = bool(INTEGRATED_OWN.match(rel[f]))
            e["read"], e["why"] = own, None if own else "the app itself (a new project gets it fresh from the starter)"
            continue
        used = places.get(f, [])
        if e.get("error"):
            e["read"], e["why"] = False, "couldn't read"
        elif hard[f]:
            e["read"], e["why"] = False, hard[f]
        elif len(users.get(Path(f).stem, [])) >= 2 and not e.get("logic"):
            e["read"], e["why"] = False, "chart building blocks (the files that place them are listed to read)"
        elif e.get("logic") or e.get("visual") or e.get("filters") or used:
            e["read"], e["why"] = True, None
            if used:
                e["visual"] = e.get("visual", []) + [f"places {', '.join(used[:5])}"]
                e["hit_lines"] = sorted(set(e.get("hit_lines", [])) |
                                        {_line(texts[f], m.start()) for m in tag.finditer(texts[f])})[:12]
        else:
            e["read"] = False
            e["why"] = next((r for r, rx in SOFT_REASONS if rx.search(rel[f])), "no queries, calculations or visuals found")
    return integrated


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
        if ext == ".json" and CONFIG_JSON.search(f.name):   # app settings, not data
            report["other"].append({"file": rel, "size": human(size)})
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

    report["integrated_dashboard"] = sort_code(report["code"], root)
    if a.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    p = print
    p(f"# Inventory of {root}")
    if report["integrated_dashboard"]:
        p("This is an integrated dashboard project (v2/v3 layout). Moving it: dashboard-new references/plan.md,"
          " \"An older integrated dashboard\". Only its own sections, Analysis pages and Pipeline scripts are listed to read.")
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
    to_read = [e for e in report["code"] if e.get("read")]
    p(f"\n## Code to read ({len(to_read)} of {len(report['code'])} code files): queries, calculations, visuals, filters")
    p("Open only these, and in them only the parts around the lines shown.")
    for e in to_read:
        size_bit = f"{e['cells']} cells" if "cells" in e else f"{e.get('lines', '?')} lines"
        p(f"- {e['file']} ({size_bit}){' - writes files' if e.get('writes_files') else ''}")
        if e.get("logic"):
            p(f"  numbers: {', '.join(e['logic'])}")
        if e.get("visual"):
            p(f"  visuals: {', '.join(e['visual'])}")
        where = lambda ls: (f"cells {', '.join(map(str, sorted({next(n for start, n in reversed(e['_cell_starts']) if start <= ln) for ln in ls})))}"
                            if e.get("_cell_starts") else f"lines {', '.join(map(str, ls))}")   # notebooks: cells, not joined lines
        if e.get("filters"):
            p(f"  filters and inputs: {', '.join(e['filters'])} ({where(e['filter_lines'])})")
        if e.get("hit_lines"):
            p(f"  look at {where(e['hit_lines'])}")
        if e.get("mentions_files"):
            p(f"  mentions: {', '.join(e['mentions_files'])}")
        if e.get("functions"):
            p(f"  functions: {', '.join(e['functions'])}")
    not_needed = [e for e in report["code"] if not e.get("read")]
    if not_needed:
        p(f"\n## Code not needed ({len(not_needed)}): don't open unless a file above calls into one")
        groups: dict = {}
        for e in not_needed:
            groups.setdefault(e["why"], []).append(e["file"])
        for why, names in groups.items():
            p(f"- {why} ({len(names)}): {', '.join(names[:12])}{' ...' if len(names) > 12 else ''}")
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
