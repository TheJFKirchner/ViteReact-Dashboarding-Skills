"""Shared base of the dashboard agent + the card-chart part.

Reading guide
- ChatSession: chat turns, cost estimate, control-card bookkeeping, SDK client (run_claude).
  dashboard_agent.DashboardSession is the one session the server runs; it builds on this.
- RenderWaits: render reports from the open tab (card charts, shared components).
- SectionSession: the "card chart" part: original and preview code of one <id>.jsx, its guards
  (exact-match replace, protected parts unchanged, JSX parses, the open tab confirms the preview
  renders; up to 2 self-fixes per request) and its control cards. The real file is only written
  by keep(); discard deletes the preview copy.
"""
from __future__ import annotations

import asyncio
import colorsys
import itertools
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import controls as ctl

# The agent code lives in the skill; the project it works on comes from the dev server
# (agent/vite-plugin.js sets DASH_PROJECT_ROOT). Per-project state goes in <project>/.dashboard-agent/.
AGENT_DIR = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("DASH_PROJECT_ROOT") or Path.cwd()).resolve()
STATE_DIR = ROOT / ".dashboard-agent"
SECTIONS = ROOT / "Src" / "Sections"     # v2 layout: capitalized folders
MAX_FAILED_EDITS = 3          # first try + 2 self-fixes
RENDER_WAIT_S = 3.0
REQUEST_TIMEOUT_S = 60
MAX_TURNS = 8
CRLF, LF = chr(13) + chr(10), chr(10)

# Cost estimate - ASSUMPTIONS, not a bill. Claude Haiku 5.5 list prices in USD per million tokens
# (prompts up to 100K tokens; ours are ~5-15K). Override in dashboard.config.json:
#   "agent": { "pricing": { "input_per_mtok": 0.10, "output_per_mtok": 0.50, ... } }
DEFAULT_PRICING = {
    "input_per_mtok": 0.10,      # uncached input
    "output_per_mtok": 0.50,     # output (includes thinking)
    "cache_write_x": 1.25,       # cache writes billed at 1.25x input
    "cache_read_x": 0.10,        # cache reads billed at 0.1x input
}


def estimate_cost(usage: dict | None, pricing: dict | None) -> dict | None:
    """Approximate cost of one request from the SDK's usage totals: {cents, input_tokens, output_tokens}."""
    if not usage:
        return None
    p = {**DEFAULT_PRICING, **(pricing or {})}
    fresh = usage.get("input_tokens", 0) or 0
    written = usage.get("cache_creation_input_tokens", 0) or 0
    read = usage.get("cache_read_input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    usd = (fresh + written * p["cache_write_x"] + read * p["cache_read_x"]) * p["input_per_mtok"] / 1e6 + out * p["output_per_mtok"] / 1e6
    return {"cents": round(usd * 100, 4), "input_tokens": fresh + written + read, "output_tokens": out}
# Preview versions never repeat while the server runs: the tab imports
# <id>.agent-preview.jsx?agentv=<version>, and a reused number would hit a cached module.
_VERSIONS = itertools.count(int(time.time() * 1000))


# ---------------------------------------------------------------- guards

def _meta_block(src: str) -> str:
    start = src.find("export const meta")
    end = src.find("\n};", start)
    return src[start:end] if start >= 0 and end > 0 else ""


# A card's commentary: `export const commentary = `...`;` in its file (text above the chart).
COMMENTARY_RE = re.compile(r"export const commentary = `((?:\\.|[^`\\])*)`;?")
CARD_ID_RE = r"(?:s\d+|[a-z])_[a-z0-9_]+"     # s2_pmpm_trend (older projects: b_pmpm_trend)


def read_commentary(src: str) -> str:
    m = COMMENTARY_RE.search(src)
    return re.sub(r"\\(.)", r"\1", m.group(1)).strip() if m else ""


def write_commentary(src: str, text: str) -> str:
    """src with its commentary set to text (added after the meta block if the card has none)."""
    nl = CRLF if CRLF in src else LF
    body = text.strip().replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${").replace(LF, nl)
    literal = f"export const commentary = `{nl}{body}{nl}`;"
    m = COMMENTARY_RE.search(src)
    if m:
        return src[:m.start()] + literal + src[m.end():]
    start = src.find("export const meta")
    end = src.find(nl + "};", start)
    if start < 0 or end < 0:
        raise ValueError("meta block not found")
    end += len(nl + "};")
    return src[:end] + nl + nl + "// Text above the chart. Numbers only as live references {metric|format}." + nl + literal + src[end:]


def protected_signature(src: str) -> dict:
    """Everything the agent may not change. Only meta.title is allowed to differ."""
    meta = re.sub(r"(\n\s*title:\s*)(['\"`]).*?\2", r"\1<title>", _meta_block(src))
    return {
        "commentary (use set_commentary)": read_commentary(src),
        "imports": [l.strip() for l in src.splitlines() if l.lstrip().startswith("import ")],
        "meta (id, tab, size, library)": meta,
        "exports": re.findall(r"^export\s+(?:default\s+)?\w+\s+\w+", src, re.M),
    }


def guard_problems(original: str, candidate: str) -> list[str]:
    a, b = protected_signature(original), protected_signature(candidate)
    return [f"changes {k}" for k in a if a[k] != b[k]]


async def data_problems(original: str, candidate: str) -> str | None:
    """v2: a card only displays. Its numbers arrive as the `data` / `metrics` props from the Analysis
    server, so a chart edit may not add data loading (fetch, network, storage, dynamic import) or
    arithmetic over data (math operators, reduce / filter / sort, Math.*). checks/card-check.mjs
    compares the candidate with the original: nothing of that kind may be added. None = OK."""
    return await run_check("card-check", json.dumps({"original": original, "candidate": candidate}))


async def run_check(name: str, text: str) -> str | None:
    """Run <skill>/agent/checks/<name>.mjs on text. It runs as `node -e` with cwd = the project,
    so its imports (vite, postcss) resolve to the project's node_modules. None = OK."""
    script = (AGENT_DIR / "checks" / f"{name}.mjs").read_text(encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(
        "node", "--input-type=module", "-e", script,
        cwd=ROOT, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate(text.encode("utf-8"))
    return None if proc.returncode == 0 else out.decode("utf-8", "replace").strip()


async def syntax_error(code: str) -> str | None:
    return await run_check("syntax-check", code)


# ---------------------------------------------------------------- reference card

def _color_name(hex_: str) -> str:
    r, g, b = (int(hex_.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.2:
        return "grey"
    names = [(15, "red"), (45, "orange"), (65, "amber"), (160, "green"), (195, "cyan"),
             (250, "blue"), (290, "violet"), (335, "pink"), (360, "red")]
    hue = h * 360
    name = next(n for limit, n in names if hue <= limit)
    return ("dark " if l < 0.3 else "light " if l > 0.75 else "") + name


def reference_card(section_src: str, card_id: str | None = None) -> str:
    config = json.loads((ROOT / "dashboard.config.json").read_text(encoding="utf-8"))
    theme = config.get("theme", "house")
    tokens = json.loads((ROOT / "Themes" / theme / "tokens.json").read_text(encoding="utf-8"))
    c = tokens["colors"]
    series = "\n".join(f"  f.color({i})  {_color_name(h)}" + ("  main / current-period series" if i == 0 else "  comparison / prior period" if i == 2 else "")
                       for i, h in enumerate(c["series"]))
    return f"""Theme: {theme}. Use colors by name through `const f = fx()`, never hex:
{series}
  f.good  {_color_name(c.get('good', c['series'][0]))} = favorable    f.bad  {_color_name(c.get('bad', c['series'][1]))} = unfavorable
  f.colors.accent · f.colors.text · f.colors.textMuted · f.colors.border · f.colors.background
  f.colorOf(name, i)  a category's color (theme colors.named.<name>, else series i); set with set_theme
Helpers (already imported where the file uses them):
  f.area(color, top=0.35)   gradient fill under a line
  f.bar(color, horizontal)  bar fill
  ...f.glow(color, blur)    glow; spread into itemStyle / lineStyle
  alpha(hex, a)             transparency (import exists only if the file already imports it)
Number formats (display only): FORMATS.money(v) · FORMATS.compact(v) · FORMATS.int(v) · FORMATS.num(v, 1) · FORMATS.pct(v, 1)
{card_data_reference(card_id) if card_id else ''}"""


def card_data_reference(card_id: str) -> str:
    """What the card's chart builds from: the `data` prop's shape and the metric names (from the Analysis server)."""
    import analysis_api as api
    try:
        info = (api.meta().get("cards") or {}).get(card_id) or {}
        result = api.card(card_id)
    except api.AnalysisUnavailable as e:
        return f"Card data: unknown right now ({e})."
    module = f"Analysis/{info['module']}.py" if info.get("module") else "Analysis/"
    return (f"Card data (computed in Python by {module}; the card only displays it, never recomputes it):\n"
            f"  data = {api.shape(result.get('data'))}\n"
            f"  metrics = {', '.join(result.get('metrics') or {}) or 'none'}\n"
            f"  fast filters: {', '.join(info.get('filters') or []) or 'none'}")


# ---------------------------------------------------------------- session

@dataclass
class RenderReport:
    ok: bool | None = None
    error: str | None = None
    image: str | None = None            # base64 PNG
    arrived: asyncio.Event = field(default_factory=asyncio.Event)
    image_arrived: asyncio.Event = field(default_factory=asyncio.Event)


class ChatSession:
    """Shared by every target (section, page, theme): chat turns, cost, control cards, SDK client."""

    def __init__(self, settings: dict, browser_alive):
        self.settings = settings
        self.browser_alive = browser_alive    # () -> bool, True if the dashboard tab polled recently
        self.client = None
        self.failed_edits = 0
        self.notes: list[str] = []           # facts the agent should hear with the next message
        self.first_message = True
        self.chat_cents = 0.0               # estimated cost of this chat so far
        self.cards: dict[int, list[dict]] = {}   # control cards: id -> bound control specs
        self.card_seq = 0
        self.live_card: int | None = None        # only the newest card stays live
        self.pending_card: dict | None = None    # card offered during the current request
        self.control_notes: dict[str, str] = {}  # label -> value the user picked, told to the agent next time

    async def close_client(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def _take_notes(self) -> str:
        if self.control_notes:
            picked = "; ".join(f"{k} = {v}" for k, v in self.control_notes.items())
            self.notes.append(f"The user adjusted your controls: {picked}.")
            self.control_notes.clear()
        notes = "".join(f"\nNote: {n}" for n in self.notes)
        self.notes.clear()
        return notes

    @staticmethod
    def _click_text(clicked: dict | None, default: str) -> str:
        if not clicked:
            return f"Clicked element: none ({default})."
        what = ", ".join(f"{k} {v!r}" for k, v in clicked.items() if v not in (None, ""))
        return f"Clicked element: {what}"

    def _user_text(self, message: str, clicked: dict | None) -> str:   # per target
        raise NotImplementedError

    def _first_image(self) -> str | None:
        return None

    async def _after_turn(self, reply: str) -> str:                     # per target: e.g. add a control card
        return reply

    def options(self):                                                  # per target
        raise NotImplementedError

    async def ask(self, message: str, clicked: dict | None) -> dict:
        self.failed_edits = 0
        self.pending_card = None
        text = self._user_text(message, clicked)
        image = self._first_image() if self.first_message else None
        self.first_message = False
        if self.settings.get("fake"):
            from fake_model import run_fake
            reply, usage = await run_fake(self, message)
        else:
            reply, usage = await run_claude(self, text, image)
        cost = estimate_cost(usage, self.settings.get("pricing"))
        if cost:
            self.chat_cents += cost["cents"]
        reply = await self._after_turn(reply)
        card = self.pending_card if self.pending_card and self.pending_card["id"] == self.live_card else None
        return {"reply": reply, "cost": cost, "chat_cents": round(self.chat_cents, 4), "card": card}


class RenderWaits:
    """Render reports from the open tab: "rendered OK / error" per preview version, plus a picture.
    Used by targets whose previews run as code (sections, shared components)."""
    render_wait_s = RENDER_WAIT_S

    def _report(self, version: int) -> RenderReport:
        return self.reports.setdefault(version, RenderReport())

    def receive_render(self, version: int, ok, error, image):   # called on the event loop
        r = self._report(version)
        if ok is not None:
            r.ok, r.error = ok, error
            r.arrived.set()
        if image:
            r.image = image.split(",", 1)[-1]
            r.image_arrived.set()

    async def _wait_render(self, version: int) -> str:
        if not self.browser_alive():
            return "Syntax OK. Render not verified (the dashboard tab is not open)."
        r = self._report(version)
        try:
            await asyncio.wait_for(r.arrived.wait(), self.render_wait_s)
        except asyncio.TimeoutError:
            return f"Syntax OK. Render not confirmed within {self.render_wait_s:g} s."
        return "Rendered OK." if r.ok else f"render error: {r.error}"


class SectionSession(RenderWaits, ChatSession):
    def __init__(self, section_id: str, settings: dict, browser_alive):
        if not re.fullmatch(CARD_ID_RE, section_id):
            raise ValueError(f"bad section id {section_id!r}")
        super().__init__(settings, browser_alive)
        self.id = section_id
        self.file = SECTIONS / f"{section_id}.jsx"
        self.preview_file = SECTIONS / f"{section_id}.agent-preview.jsx"
        self.original = self.file.read_text(encoding="utf-8", newline="")   # keep line endings as-is
        self.preview: str | None = None      # None = no preview (showing original)
        self.last_good: str | None = None
        self.version = next(_VERSIONS)
        self.reports: dict[int, RenderReport] = {}

    # ----- state helpers
    @property
    def working(self) -> str:
        return self.preview if self.preview is not None else self.original

    @property
    def dirty(self) -> bool:
        return self.preview is not None and self.preview != self.original

    def state(self) -> dict:
        return {"section_id": self.id, "kind": "section", "file": self.file.name, "version": self.version,
                "has_preview": self.preview is not None, "dirty": self.dirty, "live_card_id": self.live_card}

    def _set_preview(self, code: str | None):
        self.preview = code
        if code is None:
            self.preview_file.unlink(missing_ok=True)
        else:
            self.preview_file.write_text(code, encoding="utf-8", newline="")
        self.version = next(_VERSIONS)

    # ----- user actions
    def keep(self):
        if self.preview is None:
            return
        self.file.write_text(self.preview, encoding="utf-8", newline="")   # preview copy stays: Vite skips this reload
        self.original = self.preview
        self.notes.append("The user kept your changes; they are now the original.")

    def discard(self):
        if self.preview is not None:
            self._set_preview(None)
            self.live_card = None
            self.notes.append("The user discarded your changes; the code is back to the original.")

    async def close(self):
        if self.preview is not None:
            self._set_preview(None)
        await self.close_client()

    # ----- tools (shared by the real SDK agent and the scripted test model)
    async def tool_view(self) -> dict:
        return _text(self.working)

    async def tool_look(self) -> dict:
        r = self._report(self.version)
        if not r.image and self.browser_alive():
            try:
                await asyncio.wait_for(r.image_arrived.wait(), 2.5)
            except asyncio.TimeoutError:
                pass
        if not r.image:
            return _text("No picture available (dashboard tab closed, or this section has no chart).")
        return {"content": [{"type": "image", "data": r.image, "mimeType": "image/png"}]}

    async def tool_edit(self, old: str, new: str) -> dict:
        if self.failed_edits >= MAX_FAILED_EDITS:
            return _err("Edit limit reached for this request. Stop editing and tell the user you couldn't apply it.")
        current = self.working
        if CRLF in current:  # match the file's line endings (model snippets use plain LF)
            old, new = (t.replace(CRLF, LF).replace(LF, CRLF) for t in (old, new))
        count = current.count(old) if old else 0
        if count != 1:
            return self._fail(f"old_text must appear exactly once; found {count} matches. Use view_section and copy the exact text.")
        candidate = current.replace(old, new, 1)
        problems = guard_problems(self.original, candidate)
        if problems:
            return self._fail("Rejected: this edit " + ", ".join(problems) + ". Only presentation code may change.")
        syntax = await syntax_error(candidate)
        if syntax:
            return self._fail("Rejected, the file would not parse:\n" + syntax)
        data = await data_problems(self.original, candidate)
        if data:
            return self._fail("Rejected: " + data + "\nCards only display: their numbers come computed from Python (the data / metrics "
                              "props). A new number or calculation is a Claude Code job (Analysis/).")

        self._set_preview(candidate)
        self.live_card = None                 # a newer edit replaces any control card
        verdict = await self._wait_render(self.version)
        if verdict.startswith("render error"):
            result = self._fail(verdict + "\nThe card is showing the last good version. Fix the code.")
            if self.failed_edits >= MAX_FAILED_EDITS and self.last_good is not None:
                self._set_preview(None if self.last_good == self.original else self.last_good)
            return result
        self.last_good = candidate
        self.failed_edits = 0
        return _text(verdict)

    def _swatches(self) -> list[dict]:
        return ctl.theme_swatches(ROOT, "fx()" in self.working, _color_name)

    async def tool_offer(self, controls: list) -> dict:
        swatches = self._swatches()
        specs, error = ctl.check_offer(self.working, controls, swatches)
        if error:
            return _err(error)
        for spec in specs:
            trial = self.working.replace(spec["anchor"], spec["anchor"].replace(spec["value"], ctl.trial_value(spec), 1), 1)
            problems = guard_problems(self.original, trial)
            if problems:
                return _err(f'control "{spec["label"]}" is bound to protected code ({", ".join(problems)}). Bind presentation values only.')
        self.card_seq += 1
        self.cards[self.card_seq] = specs
        self.live_card = self.card_seq
        self.pending_card = ctl.public_card(self.card_seq, specs, swatches)
        return _text("Controls shown to the user: " + ", ".join(f'{s["label"]} ({s["kind"]})' for s in specs) + ".")

    async def apply_control(self, card_id: int, control_id: str, raw, final: bool) -> dict:
        """User tweak from a control card: swap the bound value. No model call."""
        specs = self.cards.get(card_id)
        if card_id != self.live_card or not specs:
            return {"error": "These controls are out of date; ask the agent again for new ones."}
        spec = next((s for s in specs if s["id"] == control_id), None)
        if spec is None:
            return {"error": "Unknown control."}
        try:
            new_value = ctl.code_value(spec, raw, self._swatches())
        except (ValueError, TypeError) as e:
            return {"error": str(e)}
        code = self.working
        if code.count(spec["anchor"]) != 1:
            self.live_card = None
            return {"error": "The code changed under these controls; ask the agent again."}
        new_anchor = spec["anchor"].replace(spec["value"], new_value, 1)
        candidate = code.replace(spec["anchor"], new_anchor, 1)
        problems = guard_problems(self.original, candidate)
        if problems:
            return {"error": "Rejected: " + ", ".join(problems)}
        if final:  # values are whitelisted so syntax can't break, but verify once on release
            if await syntax_error(candidate):
                return {"error": "That value would not parse."}
        if candidate != code:
            self._set_preview(candidate)
        spec["anchor"], spec["value"] = new_anchor, new_value
        self.control_notes[spec["label"]] = new_value
        verdict = await self._wait_render(self.version) if final else None
        if verdict and not verdict.startswith("render error"):
            self.last_good = candidate
        return {"ok": True, "value": new_value, "verdict": verdict}

    def _fail(self, message: str) -> dict:
        self.failed_edits += 1
        left = MAX_FAILED_EDITS - self.failed_edits
        return _err(message + (f"\n({left} attempt(s) left.)" if left > 0 else "\nNo attempts left: tell the user you couldn't apply it."))

    def _first_image(self) -> str | None:
        return self._report(self.version).image


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def _err(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}], "is_error": True}


# ---------------------------------------------------------------- Claude Agent SDK

async def run_claude(session: ChatSession, text: str, image_b64: str | None) -> tuple[str, dict | None]:
    from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock

    if session.client is None:
        session.client = ClaudeSDKClient(options=session.options())
        await session.client.connect()

    content = [{"type": "text", "text": text}]
    if image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}})
        content[0]["text"] += "\n\n(The attached picture shows the section as it looks now.)"

    async def one_message():
        yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}

    last_text, result = "", None
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT_S):
            await session.client.query(one_message())
            async for msg in session.client.receive_response():
                if isinstance(msg, AssistantMessage):
                    texts = [b.text for b in msg.content if isinstance(b, TextBlock) and b.text.strip()]
                    if texts:
                        last_text = " ".join(texts)
                elif isinstance(msg, ResultMessage):
                    result = msg
    except TimeoutError:
        await session.close_client()
        return f"Stopped: that took longer than {REQUEST_TIMEOUT_S} seconds. The preview keeps any change already applied.", None

    usage = result.usage if result is not None else None
    if result is not None and result.is_error:
        if result.subtype == "error_max_turns":
            return f"Stopped after {MAX_TURNS} steps without finishing. The preview keeps any change already applied.", usage
        detail = "; ".join(result.errors or []) or (result.result or result.subtype)
        return f"The agent hit an error: {detail}", usage
    return (result.result if result and result.result else last_text) or "Done.", usage

