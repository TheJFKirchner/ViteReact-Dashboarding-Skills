"""Analysis server: the dashboard's only data source.

    python Analysis/server.py [--port 8765]        API only (npm run dev starts it and Vite forwards /api to it)
    python Analysis/server.py --serve [--port N]   API + the built dashboard (Dist/) on one port: the hosted shape

Routes
    GET  /api/meta                       filters + their options, slow parameters, cards, manifest, pipeline status
    GET  /api/card/<id>?<filter>=<value> one card's {"data", "metrics"} (or {"error"}) for those fast filters
    POST /api/pipeline/run {"params"}    re-pull with new slow parameters (background; one at a time)
    GET  /api/pipeline/status            idle | running | failed, elapsed seconds, log tail

Edits to Analysis/*.py are picked up on the next request (no restart).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fastapi import Body, FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from Shared import engine, pipeline, tables  # noqa: E402
from Shared.registry import CARDS, discover  # noqa: E402

app = FastAPI(title="Dashboard analysis")
_mtimes: dict = {}


def _sources() -> dict:
    return {p: p.stat().st_mtime for p in [*HERE.glob("*.py"), *(HERE / "Shared").glob("*.py")]}


_manifest_mtime = None


def maybe_reload():
    """Re-import Analysis modules when a file changed (dev edits), and drop cached results. Also drop them when
    Data/Current changed outside the app (npm run pipeline, a scheduled run)."""
    global _mtimes, _manifest_mtime
    stamp = tables.data_stamp()
    if _manifest_mtime is not None and stamp != _manifest_mtime:
        engine.clear_cache()
    _manifest_mtime = stamp
    now = _sources()
    if now != _mtimes:
        first = not _mtimes
        _mtimes = now
        if not first:
            import importlib
            for name in [m for m in list(sys.modules) if m.startswith("Shared.") and m not in ("Shared.engine", "Shared.pipeline", "Shared.tables", "Shared.registry")]:
                importlib.reload(sys.modules[name])
        discover(reload=not first)
        engine.clear_cache()


def last_month_end(today: dt.date | None = None) -> dt.date:
    return (today or dt.date.today()).replace(day=1) - dt.timedelta(days=1)


def parameter_options(name: str, spec: dict) -> list[dict]:
    opts = spec.get("options")
    if spec.get("type") == "month_end":
        count = (opts or {}).get("month_ends", 12) if isinstance(opts, dict) else 12
        d, out = last_month_end(), []
        for _ in range(count):
            out.append({"value": d.isoformat(), "label": d.strftime("%b %Y")})
            d = d.replace(day=1) - dt.timedelta(days=1)
        return out
    return [{"value": str(o), "label": str(o)} for o in (opts or [])]


def default_value(spec: dict) -> str:
    """Same as Pipeline/_dataset_io.py default_params(): month ends default to "latest", a list to its first option."""
    if spec.get("type") == "month_end":
        d = spec.get("default", "latest")
        return last_month_end().isoformat() if d == "latest" else str(d)
    opts = spec.get("options") if isinstance(spec.get("options"), list) else []
    return str(spec.get("default", opts[0] if opts else ""))


def parameters(m: dict) -> dict:
    out = {}
    for name, spec in tables.specs("parameters").items():
        options = parameter_options(name, spec)
        value = str((m.get("params") or {}).get(name) or default_value(spec))
        if value not in [o["value"] for o in options]:
            label = dt.date.fromisoformat(value).strftime("%b %Y") if spec.get("type") == "month_end" else value
            options.append({"value": value, "label": label})
        out[name] = {"label": spec.get("label", name), "type": spec.get("type", "choice"), "options": options, "value": value,
                     "default": default_value(spec)}
    return out


@app.get("/api/project")
def project():
    """Which project this server belongs to (npm run dev checks it before reusing a busy port)."""
    return {"root": str(HERE.parent.resolve())}


@app.get("/api/meta")
def meta():
    maybe_reload()
    m = tables.manifest()
    if not m["tables"]:
        return JSONResponse({"error": "No data yet. Run python Pipeline/run_all.py, or put .parquet/.csv files in Data/Current", "pipeline": pipeline.public()}, status_code=503)
    options = tables.filter_options(m)
    filters = {n: {"label": s.get("label", n), "column": s.get("column", n), "options": options.get(n, [tables.ALL])}
               for n, s in tables.specs("filters").items()}
    return {
        "filters": filters,
        "parameters": parameters(m),
        "cards": {c.id: {"filters": c.filters, "tables": c.tables, "module": c.module} for c in CARDS.values()},
        "manifest": m,
        "version": engine.state["version"],
        "pipeline": pipeline.public(),
    }


@app.get("/api/card/{card_id}")
def card(card_id: str, request: Request):
    maybe_reload()
    result = engine.run(card_id, dict(request.query_params))
    return JSONResponse(result, status_code=200 if "error" not in result else 422)


@app.post("/api/pipeline/run")
def run_pipeline(body: dict = Body(...)):
    values = {str(k): str(v) for k, v in (body.get("params") or {}).items()}
    known = parameters(tables.manifest())
    for k, v in values.items():
        if k not in known:
            return JSONResponse({"error": f'unknown parameter "{k}"'}, status_code=400)
        if v not in [o["value"] for o in known[k]["options"]]:
            return JSONResponse({"error": f'"{v}" is not an allowed value for {known[k]["label"]}'}, status_code=400)
    # only the changed value: run_all.py keeps the values picked earlier (manifest "params_chosen") and uses the
    # defaults for the rest, so a default like "latest" isn't frozen just because another slow filter changed
    result = pipeline.start(values)
    return JSONResponse(result, status_code=409 if "error" in result else 200)


@app.get("/api/pipeline/status")
def pipeline_status():
    return {**pipeline.public(), "version": engine.state["version"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int((tables.config().get("server") or {}).get("port", 8765)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--serve", action="store_true", help="also serve the built dashboard from Dist/ (run npm run build first)")
    a = ap.parse_args()
    if a.serve:
        from fastapi.staticfiles import StaticFiles
        dist = tables.ROOT / "Dist"
        if not (dist / "index.html").exists():
            sys.exit("Dist/index.html not found: run npm run build first")
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    import uvicorn
    maybe_reload()
    print(f"[analysis] {len(CARDS)} card function(s); http://{a.host}:{a.port}/api/meta", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
