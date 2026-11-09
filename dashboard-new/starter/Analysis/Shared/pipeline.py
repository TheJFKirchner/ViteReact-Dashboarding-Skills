"""Background pipeline runs started from the app (a slow parameter changed): Pipeline/run_all.py into a staging
folder, then swap it in as Data/Current under the table lock and clear the cache. One run at a time."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from . import engine, tables

STAGING = tables.ROOT / "Data" / ".staging"
status = {"state": "idle", "params": None, "started": None, "finished": None, "log": [], "error": None, "last_seconds": None}
_lock = threading.Lock()


def _set(**kw):
    status.update(kw)


def start(values: dict) -> dict:
    with _lock:
        if status["state"] == "running":
            return {"error": "a pipeline run is already in progress"}
        _set(state="running", params=values, started=time.time(), finished=None, log=[], error=None)
    threading.Thread(target=_run, args=(values,), daemon=True).start()
    return {"ok": True}


def _run(values: dict):
    cmd = [sys.executable, str(tables.ROOT / "Pipeline" / "run_all.py"), "--out", str(STAGING), "--no-swap"]
    for k, v in values.items():
        cmd += ["--param", f"{k}={v}"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("DASH_PIPELINE")}
    try:
        proc = subprocess.Popen(cmd, cwd=tables.ROOT / "Pipeline", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        for line in proc.stdout:
            status["log"] = (status["log"] + [line.rstrip()])[-40:]
        code = proc.wait()
        if code != 0:
            _set(state="failed", error=next((l for l in reversed(status["log"]) if l.startswith(("FAILED", "ERROR", "Traceback"))), f"exit code {code}"))
            return
        sys.path.insert(0, str(tables.ROOT / "Pipeline"))
        from run_all import swap_in  # noqa: E402 - Pipeline/ is not a package
        with tables.LOCK.write():
            swap_in(STAGING)
            engine.clear_cache()
        _set(state="idle", last_seconds=round(time.time() - status["started"]))
    except Exception as e:  # noqa: BLE001
        _set(state="failed", error=f"{type(e).__name__}: {e}")
    finally:
        status["finished"] = time.time()


def public() -> dict:
    s = dict(status)
    s["log"] = s["log"][-8:]
    s["elapsed"] = round(time.time() - s["started"]) if s["state"] == "running" and s["started"] else None
    return json.loads(json.dumps(s))
