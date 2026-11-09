"""Local HTTP server for the dashboard agent.

Lives in the integrated-dashboards skill. Started by the project's dev server with
`npm run dev:agent` / Start dashboard.cmd (see vite-plugin.js), which passes the project folder
in DASH_PROJECT_ROOT; Vite proxies /agent/* here. Sign-in: the Claude Code login (no API keys).
Standard library only; the Claude Agent SDK is imported lazily so /agent/health can explain
what's missing. All session work runs on one asyncio loop thread.

Endpoints (JSON):
  GET  /agent/health   setup status (SDK installed, sign-in found, model)
  GET  /agent/state    current section, preview version, dirty flag   (polled by the open tab)
  GET  /agent/components  shared components: who uses each, editable or locked, modified
  POST /agent/select   {section_id}                 start a fresh session: a card (section id) or "page"
  POST /agent/close                                 end the session, discard any preview
  POST /agent/chat     {section_id, message, clicked}
  POST /agent/keep                                  write the preview to the real file
  POST /agent/discard                               drop the preview
  POST /agent/control  {card_id, control_id, value, final}   user tweak from a control card (no model call)
  POST /agent/render   {section_id, part, version, ok?, error?, image?}   reports from the tab (part: section | component)
Reports tab (report_agent.py; its own session, separate from the edit agent):
  GET  /agent/reports                  saved reports with a plain-language summary and the last generated file
  POST /agent/reports/generate {name}  node Tools/export.mjs <name>; returns the file
  GET  /agent/exports/<file>.html      a generated file (opened in a new browser tab)
  POST /agent/reports/duplicate|delete {name}    delete moves it to .dashboard-agent/deleted-reports/
  POST /agent/reports/instructions {name, text}  headless call: instructions -> proposed settings (not saved)
  POST /agent/reports/apply {name, report}       write approved settings (after the export's own validation)
  POST /agent/report/start {name|null} · /agent/report/chat {message} · /agent/report/close   report builder
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from section_agent import ROOT  # noqa: E402
from component_agent import clear_preview, usage_map  # noqa: E402
from dashboard_agent import DashboardSession  # noqa: E402
import report_agent as reports  # noqa: E402

# Variables a Claude desktop / Claude Code session injects into child processes. If the dev
# server was started from inside one, drop them so the agent signs in like a normal terminal.
SESSION_VAR_KEEP = {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_GIT_BASH_PATH", "CLAUDE_CONFIG_DIR"}


def clean_environment():
    if "CLAUDE_CODE_ENTRYPOINT" not in os.environ and "CLAUDECODE" not in os.environ:
        return
    for k in list(os.environ):
        if k in SESSION_VAR_KEEP:
            continue
        if k in ("CLAUDECODE", "CLAUDE_PID", "ANTHROPIC_BASE_URL") or k.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")):
            del os.environ[k]


def load_settings() -> dict:
    config = json.loads((ROOT / "dashboard.config.json").read_text(encoding="utf-8"))
    agent = config.get("agent", {})
    agent = agent if isinstance(agent, dict) else {"enabled": bool(agent)}
    return {
        "model": os.environ.get("DASH_AGENT_MODEL", agent.get("model", "claude-haiku-5-5")),
        "effort": os.environ.get("DASH_AGENT_EFFORT", agent.get("effort", "low")),
        "fake": os.environ.get("DASH_AGENT_FAKE") == "1",
        "pricing": agent.get("pricing", {}),
    }


def auth_source() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "API key (ANTHROPIC_API_KEY)"
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "gateway token (ANTHROPIC_AUTH_TOKEN)"
    if any(os.environ.get(v) for v in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")):
        return "cloud provider (Bedrock / Vertex / Foundry)"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "Claude token (CLAUDE_CODE_OAUTH_TOKEN)"
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    if (config_dir / ".credentials.json").exists():
        return "your Claude Code login"
    return None


class Agent:
    """Owns the single active session (the page, or one card): one preview at a time.
    Every method runs on the loop thread."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.session = None
        self.busy = False
        self.last_poll = 0.0
        self.report = None          # report builder session (Reports tab)
        self.report_busy = False

    def browser_alive(self) -> bool:
        return time.monotonic() - self.last_poll < 2.5

    def state(self) -> dict:
        base = self.session.state() if self.session else {"section_id": None}
        return {**base, "busy": self.busy}

    async def select(self, section_id: str):
        if self.session and self.session.id == section_id:
            return self.state()
        if section_id != "page" and not (ROOT / "Src" / "Sections" / f"{section_id}.jsx").exists():
            raise ValueError(f"unknown section {section_id!r}")   # leaves the current session alone
        await self.close()
        self.session = DashboardSession(section_id, self.settings, self.browser_alive)
        return self.state()

    async def close(self):
        if self.session:
            await self.session.close()
        self.session = None
        return self.state()

    async def chat(self, section_id: str, message: str, clicked):
        if not self.session or self.session.id != section_id:
            await self.select(section_id)
        if self.busy:
            return {"error": "The agent is still working on the last request."}
        self.busy = True
        try:
            answer = await self.session.ask(message.strip(), clicked)
        except Exception as e:  # surface setup/auth problems in the chat instead of a 500
            answer = {"reply": f"The agent couldn't run: {type(e).__name__}: {e}", "cost": None, "chat_cents": self.session.chat_cents}
        finally:
            self.busy = False
        return {**answer, **self.state()}

    async def keep(self):
        if self.session:
            try:
                self.session.keep()
            except (OSError, ValueError) as e:
                return {**self.state(), "error": f"Couldn't save: {e}"}
        return self.state()

    async def discard(self):
        if self.session:
            self.session.discard()
        return self.state()

    async def control(self, body: dict):
        if not self.session:
            return {"error": "No section selected."}
        if self.busy:
            return {"error": "The agent is still working; try again in a moment."}
        result = await self.session.apply_control(int(body["card_id"]), body["control_id"], body.get("value"), bool(body.get("final")))
        return {**result, **self.state()}

    # ----- Reports tab
    async def report_start(self, name):
        await self.report_close()
        self.report = reports.ReportSession(name or None, self.settings, self.browser_alive, await reports.catalog(refresh=True))
        return self.report.state()

    async def report_close(self):
        if self.report:
            await self.report.close()
        self.report = None
        return {"ok": True}

    async def report_chat(self, message: str):
        if not self.report:
            return {"error": "No report open."}
        if self.report_busy:
            return {"error": "The report agent is still working."}
        self.report_busy = True
        try:
            return await self.report.ask(message.strip())
        except Exception as e:
            return {"reply": f"The report agent couldn't run: {type(e).__name__}: {e}", "cost": None, **self.report.state()}
        finally:
            self.report_busy = False

    async def report_instructions(self, name: str, text: str):
        if self.report_busy:
            return {"error": "The report agent is still working."}
        self.report_busy = True
        try:
            return await reports.run_instructions(name, text.strip(), self.settings)
        except Exception as e:
            return {"error": f"The report agent couldn't run: {type(e).__name__}: {e}"}
        finally:
            self.report_busy = False

    async def render(self, body: dict):
        if self.session and body.get("section_id") == self.session.id:
            self.session.receive_report(body)
        return {"ok": True}


def make_handler(agent: Agent, loop: asyncio.AbstractEventLoop):
    def run(coro, timeout=120):
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)

    async def health():
        has_sdk = importlib.util.find_spec("claude_agent_sdk") is not None
        auth = auth_source()
        problems = []
        if not has_sdk and not agent.settings["fake"]:
            problems.append("Python package claude-agent-sdk is not installed: pip install -r agent/requirements.txt")
        if not auth and not agent.settings["fake"]:
            problems.append("No Claude sign-in found: run `claude` in a terminal and /login, then restart the dashboard")
        return {"ok": not problems, "problems": problems, "auth": auth, "model": agent.settings["model"],
                "effort": agent.settings["effort"], "test_mode": agent.settings["fake"]}

    async def poll_state():
        agent.last_poll = time.monotonic()
        return agent.state()

    async def components():
        return {"components": usage_map()}

    routes = {
        ("GET", "/agent/health"): lambda b: health(),
        ("GET", "/agent/state"): lambda b: poll_state(),
        ("GET", "/agent/components"): lambda b: components(),
        ("POST", "/agent/select"): lambda b: agent.select(b["section_id"]),
        ("POST", "/agent/close"): lambda b: agent.close(),
        ("POST", "/agent/chat"): lambda b: agent.chat(b["section_id"], b.get("message", ""), b.get("clicked")),
        ("POST", "/agent/keep"): lambda b: agent.keep(),
        ("POST", "/agent/discard"): lambda b: agent.discard(),
        ("POST", "/agent/render"): lambda b: agent.render(b),
        ("POST", "/agent/control"): lambda b: agent.control(b),
        ("GET", "/agent/reports"): lambda b: reports.list_reports(),
        ("POST", "/agent/reports/generate"): lambda b: reports.generate(b["name"]),
        ("POST", "/agent/reports/duplicate"): lambda b: asyncio.sleep(0, reports.duplicate(b["name"])),
        ("POST", "/agent/reports/delete"): lambda b: asyncio.sleep(0, reports.delete(b["name"])),
        ("POST", "/agent/reports/instructions"): lambda b: agent.report_instructions(b["name"], b.get("text", "")),
        ("POST", "/agent/reports/apply"): lambda b: reports.apply(b["name"], b["report"]),
        ("POST", "/agent/report/start"): lambda b: agent.report_start(b.get("name")),
        ("POST", "/agent/report/chat"): lambda b: agent.report_chat(b.get("message", "")),
        ("POST", "/agent/report/close"): lambda b: agent.report_close(),
    }

    class Handler(BaseHTTPRequestHandler):
        def _respond(self, method: str):
            path = self.path.split("?")[0]
            if method == "GET" and path.startswith("/agent/exports/"):
                return self._send_file(reports.export_file(path.rsplit("/", 1)[-1]))
            route = routes.get((method, path))
            if not route:
                return self._send(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                self._send(200, run(route(body)))
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def _send(self, status: int, payload: dict):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_file(self, data: bytes | None):
            if data is None:
                return self._send(404, {"error": "no such export"})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._respond("GET")

        def do_POST(self):
            self._respond("POST")

        def log_message(self, *args):  # keep the dev console quiet
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("DASH_AGENT_PORT", 8787)))
    args = parser.parse_args()

    clean_environment()
    clear_preview()   # a component preview left by a crash must not stay served
    agent = Agent(load_settings())
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(agent, loop))
    mode = "TEST MODE (scripted model)" if agent.settings["fake"] else f"{agent.settings['model']}, effort {agent.settings['effort']}"
    print(f"dashboard agent ready on 127.0.0.1:{args.port} ({mode}; sign-in: {auth_source() or 'none found'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run_coroutine_threadsafe(agent.close(), loop).result(10)
        asyncio.run_coroutine_threadsafe(agent.report_close(), loop).result(10)


if __name__ == "__main__":
    main()
