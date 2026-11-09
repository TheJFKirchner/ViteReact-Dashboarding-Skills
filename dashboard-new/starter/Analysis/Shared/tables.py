"""Table access: Data/Current/*.parquet and *.csv via DuckDB, with fast filters pushed into the query.

Tables come from Data/Current/manifest.json (written by Pipeline/ scripts through write_dataset), plus any
.parquet or .csv file dropped straight into Data/Current (table name = file name in snake_case).
The ONLY code that reads Data/. To move to another store later (e.g. Databricks SQL), change this file.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
import os  # noqa: E402

# Data/Current; an export with pinned slow parameters points DASH_DATA_DIR at its own pull instead
CURRENT = Path(os.environ["DASH_DATA_DIR"]) if os.environ.get("DASH_DATA_DIR") else ROOT / "Data" / "Current"
ALL = "All"
_con = duckdb.connect()    # one in-memory DuckDB; each query uses its own cursor (cheap, thread-safe)


class _ReadWriteLock:
    """Many readers at once; the pipeline swap (writer) waits for them and blocks new ones."""

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writing = False

    def read(self):
        return _Guard(self, False)

    def write(self):
        return _Guard(self, True)


class _Guard:
    def __init__(self, lock, write):
        self.lock, self.write = lock, write

    def __enter__(self):
        c = self.lock._cond
        with c:
            if self.write:
                c.wait_for(lambda: not self.lock._writing and self.lock._readers == 0)
                self.lock._writing = True
            else:
                c.wait_for(lambda: not self.lock._writing)
                self.lock._readers += 1

    def __exit__(self, *exc):
        c = self.lock._cond
        with c:
            if self.write:
                self.lock._writing = False
            else:
                self.lock._readers -= 1
            c.notify_all()


LOCK = _ReadWriteLock()    # LOCK.read() around queries; LOCK.write() while the pipeline swaps Data/Current


def config() -> dict:
    return json.loads((ROOT / "dashboard.config.json").read_text(encoding="utf-8"))


def specs(section: str) -> dict:
    """dashboard.config.json "filters" or "parameters", without "_note"-style keys."""
    return {k: v for k, v in (config().get(section) or {}).items() if not k.startswith("_")}


DATA_SUFFIXES = (".parquet", ".csv")
_described: dict = {}   # (file, mtime) -> {column: type}, so dropped-in files are described once


def _table_name(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")


def _source_sql(path: str) -> str:
    return f"read_csv_auto('{path}')" if path.lower().endswith(".csv") else f"read_parquet('{path}')"


def _kind(t: str) -> str:
    if re.match(r"(TINY|SMALL|BIG|HUGE|U)?INT|DOUBLE|FLOAT|DECIMAL|REAL", t):
        return "number"
    if t.startswith(("DATE", "TIMESTAMP")):
        return "date"
    return "boolean" if t == "BOOLEAN" else "string"


def _describe(f: Path) -> dict:
    key = (f.name, f.stat().st_mtime)
    if key not in _described:
        cur = _con.cursor()
        try:
            rows = cur.execute(f"DESCRIBE SELECT * FROM {_source_sql(f.as_posix())}").fetchall()
        finally:
            cur.close()
        _described[key] = {r[0]: _kind(str(r[1]).upper()) for r in rows}
    return _described[key]


def data_stamp() -> tuple:
    """Changes whenever Data/Current changes (manifest or any data file), so cached results are dropped."""
    if not CURRENT.exists():
        return ()
    return tuple(sorted((f.name, f.stat().st_mtime) for f in CURRENT.iterdir()
                        if f.name == "manifest.json" or f.suffix.lower() in DATA_SUFFIXES))


def manifest() -> dict:
    """manifest.json (pipeline tables) plus any .parquet/.csv in Data/Current that it doesn't list."""
    f = CURRENT / "manifest.json"
    m = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"generated_at": None, "params": {}, "tables": {}}
    m.setdefault("tables", {})
    listed = {e.get("path") for e in m["tables"].values()}
    if CURRENT.exists():
        for data in sorted(CURRENT.iterdir()):
            name = _table_name(data.stem)
            if data.suffix.lower() not in DATA_SUFFIXES or data.name in listed or not name or name in m["tables"]:
                continue
            m["tables"][name] = {"path": data.name, "grain": None, "columns": _describe(data), "rows": None,
                                 "as_of": "", "source": f"file {data.name}", "discovered": True}
    return m


def _path(name: str, m: dict) -> str:
    entry = m["tables"].get(name)
    if not entry:
        raise KeyError(f'table "{name}" is not in Data/Current (run python Pipeline/run_all.py, or add {name}.parquet / {name}.csv)')
    return (CURRENT / entry["path"]).as_posix()


def load(name: str, filters: dict | None = None, m: dict | None = None):
    """Rows of one table as a pandas DataFrame, with fast filters (not "All") applied when the table has the column."""
    m = m or manifest()
    cols = m["tables"].get(name, {}).get("columns", {})
    where, args = [], []
    fast = specs("filters")
    for fname, value in (filters or {}).items():
        col = fast.get(fname, {}).get("column", fname)
        if value in (None, "", ALL) or col not in cols:
            continue
        where.append(f'"{col}" = ?')
        args.append(value)
    sql = f"SELECT * FROM {_source_sql(_path(name, m))}" + (f" WHERE {' AND '.join(where)}" if where else "")
    with LOCK.read():
        cur = _con.cursor()
        try:
            return cur.execute(sql, args).df()
        finally:
            cur.close()


def filter_options(m: dict | None = None) -> dict:
    """{filter: [All, ...distinct values across every table that has its column]}."""
    m = m or manifest()
    out = {}
    with LOCK.read():
        con = _con.cursor()
        try:
            for fname, spec in specs("filters").items():
                col = spec.get("column", fname)
                values = set()
                for name, entry in m["tables"].items():
                    if col in entry.get("columns", {}):
                        rows = con.execute(f'SELECT DISTINCT "{col}" FROM {_source_sql(_path(name, m))}').fetchall()
                        values.update(str(r[0]) for r in rows if r[0] is not None)
                order = [str(v) for v in spec.get("order") or []]   # optional display order from the config
                out[fname] = [ALL, *[v for v in order if v in values], *sorted(values - set(order))]
        finally:
            con.close()
    return out


class Tables:
    """What a card function receives: t.<table> (filtered DataFrame), t.filters, t.params (slow parameters)."""

    def __init__(self, allowed: list[str], filters: dict, m: dict):
        self._allowed, self._m, self._cache = allowed, m, {}
        self.filters = dict(filters)
        self.params = dict(m.get("params") or {})

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._allowed:
            raise AttributeError(f'table "{name}" is not in this card\'s tables=[...] list')
        if name not in self._cache:
            self._cache[name] = load(name, self.filters, self._m)
        return self._cache[name]
