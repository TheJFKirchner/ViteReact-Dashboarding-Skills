"""Page and theme parts of the dashboard agent: global edits that change every tab and every
future export (dashboard_agent.DashboardSession calls these tools).

Reading guide
- PageSession: page text values (dashboard title, source line, tab labels, filter labels) and
  the override stylesheet Src/custom.css. Tools: tool_view, tool_set_text, tool_edit_styles.
- ThemeSession: Themes/<theme>/tokens.json (colors, fonts, effects). Tools: tool_view,
  tool_set_theme, tool_offer (live controls bound to a token path), apply_control.
- Neither writes a file until Keep. The preview is a plain dict the open tab applies in memory
  (text overrides, an injected stylesheet, theme tokens). Keep writes only the exact values that
  changed and lists the written files in .dashboard-agent/kept-writes.json so the dev server
  skips the page reload (the tab already shows the kept result).
- No JavaScript edits, no new keys or slots, nothing outside these files.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re

from section_agent import (_VERSIONS, ROOT, STATE_DIR, ChatSession, _color_name, _err, _text, run_check)

CONFIG = ROOT / "dashboard.config.json"           # title, dataSource, filter + parameter labels (v2)
TABS_FILE = ROOT / "Src" / "Sections" / "index.js"
CUSTOM_CSS = ROOT / "Src" / "custom.css"
STYLES = ROOT / "Src" / "styles.css"
KEPT_WRITES = STATE_DIR / "kept-writes.json"

MAX_TEXT = 80
MAX_CSS = 20_000
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FONT_OK = re.compile(r"^[\w\s,'\"().-]{1,160}$")
# category colors: colors.named.<category> (e.g. colors.named.Inpatient), used by cards through f.colorOf(name, i);
# the one place the theme may gain new keys (hex values only)
NAMED_PREFIX = "colors.named."
NAMED_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/+'()_-]{0,39}$")


def named_key(path: str) -> str | None:
    """The category of a colors.named.<category> path, or None."""
    if isinstance(path, str) and path.startswith(NAMED_PREFIX) and NAMED_KEY.match(path[len(NAMED_PREFIX):]):
        return path[len(NAMED_PREFIX):]
    return None
TAB_RE = r"""(\{{\s*id:\s*(['"]){id}\2\s*,\s*label:\s*)(['"])((?:\\.|(?!\3).)*)\3"""
# "filters": { ..., "<name>": { ... "label": "..." } }: the label inside one flat filter / parameter spec
CONFIG_LABEL_RE = r"""("{group}"\s*:\s*\{{.*?"{name}"\s*:\s*\{{[^{{}}]*?"label"\s*:\s*)"(?:[^"\\]|\\.)*\""""
LABEL_GROUPS = {"filter": "filters", "param": "parameters"}   # slot prefix -> dashboard.config.json section


# ---------------------------------------------------------------- shared helpers

def record_kept_write(path, text: str):
    """Tell agent/vite-plugin.js not to reload the page for this exact file content."""
    KEPT_WRITES.parent.mkdir(parents=True, exist_ok=True)
    try:
        kept = json.loads(KEPT_WRITES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    kept[os.path.normcase(os.path.normpath(str(path))).lower()] = hashlib.sha1(text.encode("utf-8")).hexdigest()
    KEPT_WRITES.write_text(json.dumps(kept, indent=1), encoding="utf-8")


def same_newlines(path, text: str) -> str:
    """text with the line endings the file on disk already uses (files are read with universal newlines,
    so a CRLF file would otherwise come back as LF on every line)."""
    try:
        with open(path, "rb") as f:
            crlf = b"\r\n" in f.read()
    except OSError:
        return text
    lf = text.replace(CRLF_, LF_)
    return lf.replace(LF_, CRLF_) if crlf else lf


CRLF_, LF_ = "\r\n", "\n"


def write_kept(path, text: str):
    text = same_newlines(path, text)
    record_kept_write(path, text)            # record first: the watcher may fire right after the write
    path.write_text(text, encoding="utf-8", newline="")


def _js_unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def _js_string(value: str, quote: str) -> str:
    return quote + value.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote


async def css_problem(css: str) -> str | None:
    return await run_check("css-check", css)


class GlobalSession(ChatSession):
    """Preview = dict applied by the tab. Subclasses: load(), write(), tools, options()."""
    id = ""
    files_label = ""

    def __init__(self, settings: dict, browser_alive):
        super().__init__(settings, browser_alive)
        self.original: dict = self.load()
        self.preview: dict | None = None
        self.version = next(_VERSIONS)

    @property
    def working(self) -> dict:
        return self.preview if self.preview is not None else self.original

    @property
    def dirty(self) -> bool:
        return self.preview is not None and self.preview != self.original

    def state(self) -> dict:
        return {"section_id": self.id, "kind": self.id, "file": self.files_label, "version": self.version,
                "has_preview": self.preview is not None, "dirty": self.dirty, "live_card_id": self.live_card,
                "preview": self.preview}

    def _set_preview(self, value: dict | None):
        self.preview = value
        self.version = next(_VERSIONS)

    def receive_render(self, version, ok, error, image):   # the tab applies global previews itself
        pass

    def prepare(self, old: dict, new: dict, base: dict) -> dict:
        """Files to write for Keep: {path: text}. base = texts already planned for this Keep (read those, not the disk)."""
        raise NotImplementedError

    def commit(self):
        """After Keep wrote prepare()'s files: the preview is the new original."""
        self.original = copy.deepcopy(self.preview)
        self.notes.append("The user kept your changes; they are now the original.")

    def keep(self):
        if self.preview is None:
            return
        for path, text in self.prepare(self.original, self.preview, {}).items():
            write_kept(path, text)
        self.commit()

    def discard(self):
        if self.preview is not None:
            self._set_preview(None)
            self.live_card = None
            self.notes.append("The user discarded your changes; everything is back to the original.")

    async def close(self):
        self.preview = None
        await self.close_client()

    def _fail(self, message: str) -> dict:
        self.failed_edits += 1
        left = 3 - self.failed_edits
        return _err(message + (f"\n({left} attempt(s) left.)" if left > 0 else "\nNo attempts left: tell the user you couldn't apply it."))

# ---------------------------------------------------------------- Page

class PageSession(GlobalSession):
    id = "page"
    files_label = "dashboard.config.json (title, source, filter labels) · tab labels · custom.css"

    # ----- read the current values
    def load(self) -> dict:
        text = {}
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        for key in ("title", "dataSource"):
            if isinstance(config.get(key), str):
                text[key] = config[key]
        if TABS_FILE.exists():
            for m in re.finditer(r"""\{\s*id:\s*(['"])([\w-]+)\1\s*,\s*label:\s*(['"])((?:\\.|(?!\3).)*)\3""", TABS_FILE.read_text(encoding="utf-8")):
                text[f"tab:{m.group(2)}"] = _js_unescape(m.group(4))
        # v2: fast filters and slow parameters are defined (with their labels) in dashboard.config.json
        for prefix, group in LABEL_GROUPS.items():
            for name, spec in (config.get(group) or {}).items():
                if isinstance(spec, dict) and isinstance(spec.get("label"), str) and not name.startswith("_"):
                    text[f"{prefix}:{name}"] = spec["label"]
        css = CUSTOM_CSS.read_text(encoding="utf-8") if CUSTOM_CSS.exists() else ""
        return {"text": text, "css": css}

    # ----- Keep: only what changed, in place
    def prepare(self, old: dict, new: dict, base: dict) -> dict:
        out = {}
        read = lambda p: base[p] if p in base else p.read_text(encoding="utf-8")  # noqa: E731
        changed = {k: v for k, v in new["text"].items() if old["text"].get(k) != v}
        labels = {k: v for k, v in changed.items() if k.split(":")[0] in LABEL_GROUPS}
        if "title" in changed or "dataSource" in changed or labels:
            src = read(CONFIG)
            for key in ("title", "dataSource"):
                if key in changed:
                    pattern = re.compile(r'("%s"\s*:\s*)"(?:[^"\\]|\\.)*"' % key)
                    if len(pattern.findall(src)) != 1:
                        raise ValueError(f'could not find "{key}" in dashboard.config.json')
                    src = pattern.sub(lambda m: m.group(1) + json.dumps(changed[key], ensure_ascii=False), src, count=1)
            for slot, label in labels.items():
                prefix, name = slot.split(":", 1)
                pattern = re.compile(CONFIG_LABEL_RE.format(group=LABEL_GROUPS[prefix], name=re.escape(name)), re.S)
                src, n = pattern.subn(lambda m: m.group(1) + json.dumps(label, ensure_ascii=False), src, count=1)
                if n != 1:
                    raise ValueError(f'could not find the label of {LABEL_GROUPS[prefix]} "{name}" in dashboard.config.json')
            parsed = json.loads(src)  # still valid JSON, and the labels landed where they belong
            for slot, label in labels.items():
                prefix, name = slot.split(":", 1)
                if (parsed.get(LABEL_GROUPS[prefix]) or {}).get(name, {}).get("label") != label:
                    raise ValueError(f"could not set the {slot} label in dashboard.config.json")
            out[CONFIG] = src
        tabs = {k[4:]: v for k, v in changed.items() if k.startswith("tab:")}
        if tabs:
            src = read(TABS_FILE)
            for tab_id, label in tabs.items():
                pattern = re.compile(TAB_RE.format(id=re.escape(tab_id)))
                if len(pattern.findall(src)) != 1:
                    raise ValueError(f"could not find tab {tab_id} in Src/Sections/index.js")
                src = pattern.sub(lambda m: m.group(1) + _js_string(label, m.group(3)), src, count=1)
            out[TABS_FILE] = src
        if new["css"] != old["css"]:
            out[CUSTOM_CSS] = new["css"]
        return out

    # ----- tools
    async def tool_view(self) -> dict:
        w = self.working
        slots = "\n".join(f"  {k}: {v}" for k, v in w["text"].items())
        return _text(f"Text values:\n{slots}\n\nSrc/custom.css:\n```css\n{w['css']}\n```")

    async def tool_set_text(self, slot: str, value: str) -> dict:
        if slot not in self.original["text"]:
            return self._fail(f"Unknown slot {slot!r}. Slots: {', '.join(self.original['text'])}.")
        value = (value or "").strip()
        if not value or len(value) > MAX_TEXT or any(ord(c) < 32 for c in value):
            return self._fail(f"Text must be one line of 1-{MAX_TEXT} characters.")
        new = copy.deepcopy(self.working)
        new["text"][slot] = value
        self._set_preview(new)
        return _text(f"Previewing {slot} = {value!r}.")

    async def tool_edit_styles(self, old: str, new: str) -> dict:
        css = self.working["css"]
        if old:
            count = css.count(old)
            if count != 1:
                return self._fail(f"old_text must appear exactly once in custom.css; found {count}. Use view_page and copy it exactly.")
            candidate = css.replace(old, new, 1)
        else:
            candidate = css.rstrip() + "\n\n" + new.strip() + "\n"
        if len(candidate) > MAX_CSS:
            return self._fail(f"custom.css would exceed {MAX_CSS} characters.")
        problem = await css_problem(candidate)
        if problem:
            return self._fail("Rejected:\n" + problem)
        value = copy.deepcopy(self.working)
        value["css"] = candidate
        self._set_preview(value)
        self.failed_edits = 0
        return _text("Applied to the page preview.")

# ---------------------------------------------------------------- Theme

def _get(tokens, path: str):
    node = tokens
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise KeyError(path)
    return node


def _set(tokens, path: str, value):
    *parents, last = path.split(".")
    node = tokens
    for part in parents:
        if isinstance(node, dict) and part not in node and path.startswith(NAMED_PREFIX):
            node[part] = {}                                    # colors.named is created on first use
        node = node[int(part)] if isinstance(node, list) else node[part]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def format_tokens(value, indent: int = 0) -> str:
    """tokens.json layout: scalar arrays and short scalar objects on one line, the rest indented."""
    pad, inner = "  " * indent, "  " * (indent + 1)
    if isinstance(value, dict):
        if indent > 0 and all(not isinstance(v, (dict, list)) for v in value.values()):
            one = "{ " + ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in value.items()) + " }"
            if len(one) + len(inner) <= 90:
                return one
        items = [f"{inner}{json.dumps(k)}: {format_tokens(v, indent + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
        return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


class ThemeSession(GlobalSession):
    id = "theme"

    def __init__(self, settings: dict, browser_alive):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.theme = config.get("theme", "house")
        self.tokens_file = ROOT / "Themes" / self.theme / "tokens.json"
        self.files_label = f"Themes/{self.theme}/tokens.json"
        super().__init__(settings, browser_alive)

    def load(self) -> dict:
        return {"tokens": json.loads(self.tokens_file.read_text(encoding="utf-8"))}

    def prepare(self, old: dict, new: dict, base: dict) -> dict:
        return {self.tokens_file: format_tokens(new["tokens"]) + "\n"} if new["tokens"] != old["tokens"] else {}

    # ----- validation: existing leaf paths only, typed like the original value
    def coerce(self, path: str, raw):
        """Return the value to store at path, or raise ValueError with a reason."""
        if named_key(path):                                     # a category color (may be new)
            if not HEX.match(str(raw)):
                raise ValueError(f'{path} must be a color like "#FF8800"')
            return str(raw).upper()
        if not re.fullmatch(r"[A-Za-z]+(\.[A-Za-z0-9]+)+", path or "") or path.split(".")[0] == "name":
            raise ValueError(f"{path!r} is not an editable theme path")
        try:
            current = _get(self.original["tokens"], path)
        except KeyError:
            raise ValueError(f"{path!r} does not exist in the theme (no new keys)") from None
        if isinstance(current, (dict, list)):
            raise ValueError(f"{path!r} is a group; set its individual values (e.g. {path}.0)")
        if isinstance(current, bool):
            if raw in (True, "true"):
                return True
            if raw in (False, "false"):
                return False
            raise ValueError(f"{path} must be true or false")
        if isinstance(current, (int, float)):
            v = float(raw)
            lo, hi = (10, 20) if path == "font.size" else (0, 100)
            if not lo <= v <= hi:
                raise ValueError(f"{path} must be between {lo} and {hi}")
            return int(v) if v.is_integer() else round(v, 2)
        if HEX.match(str(current)):
            if not HEX.match(str(raw)):
                raise ValueError(f'{path} must be a color like "#FF8800"')
            return str(raw).upper()
        if not FONT_OK.match(str(raw)):
            raise ValueError(f"{path} must be a plain CSS font list (letters, spaces, commas, quotes)")
        return str(raw)

    @staticmethod
    def kind_of(value) -> str:
        if isinstance(value, bool):
            return "switch"
        if isinstance(value, (int, float)):
            return "slider"
        return "color" if HEX.match(str(value)) else "text"

    @staticmethod
    def show(value) -> str:
        return ("true" if value else "false") if isinstance(value, bool) else str(value)

    # ----- tools
    async def tool_view(self) -> dict:
        return _text(format_tokens(self.working["tokens"]))

    async def tool_set_theme(self, changes: list) -> dict:
        if not isinstance(changes, list) or not changes:
            return self._fail("changes must be a non-empty list of {path, value}.")
        tokens = copy.deepcopy(self.working["tokens"])
        done = []
        for c in changes:
            try:
                value = self.coerce(c.get("path"), c.get("value"))
            except (ValueError, TypeError) as e:
                return self._fail(f"Rejected: {e}. Nothing was changed.")
            _set(tokens, c["path"], value)
            done.append(f"{c['path']} = {self.show(value)}")
        self._set_preview({"tokens": tokens})
        self.live_card = None
        self.failed_edits = 0
        return _text("Previewing " + "; ".join(done) + ".")

    def _swatches(self) -> list[dict]:
        colors = self.working["tokens"]["colors"]
        picks = [(f"series {i}", h) for i, h in enumerate(colors.get("series", []))]
        picks += [(k, colors[k]) for k in ("accent", "good", "bad", "warning", "text", "textMuted") if isinstance(colors.get(k), str)]
        seen, out = set(), []
        for label, h in picks:
            if HEX.match(h) and h.upper() not in seen:
                seen.add(h.upper())
                out.append({"label": f"{label} ({_color_name(h)})", "hex": h.upper(), "expr": h.upper()})
        return out

    async def tool_offer(self, controls: list) -> dict:
        all_named = isinstance(controls, list) and controls and all(named_key(c.get("path")) for c in controls if isinstance(c, dict))
        limit = 12 if all_named else 6                        # one picker per category (a chart can have more than 6)
        if not isinstance(controls, list) or not 1 <= len(controls) <= limit:
            return _err(f"Offer between 1 and {limit} controls.")
        specs = []
        for i, c in enumerate(controls):
            path, kind, label = c.get("path"), c.get("kind"), (c.get("label") or "").strip()
            name = f'control {i + 1} ("{label or path}")'
            try:
                value = _get(self.working["tokens"], path or "")
            except KeyError:
                if not (named_key(path) and HEX.match(str(c.get("value", "")))):
                    return _err(f"{name}: path {path!r} does not exist" + (" (a new category color needs its current color as value)" if named_key(path) else "") + ".")
                value = str(c["value"]).upper()                # category color not set yet: its current (default) color
            if path.split(".")[0] == "name" or self.kind_of(value) != kind:
                return _err(f"{name}: a {kind} control can't bind to {path} (it holds {self.show(value)!r}).")
            if not label:
                return _err(f"{name}: needs a short label.")
            spec = {"id": f"c{i}", "kind": kind, "label": label, "path": path, "value": self.show(value)}
            if kind == "slider":
                lo, hi = (10, 20) if path == "font.size" else (float(c.get("min", 0)), float(c.get("max", 100)))
                spec.update(min=float(c.get("min", lo)), max=float(c.get("max", hi)), step=float(c.get("step") or 1))
                if not spec["min"] < spec["max"]:
                    return _err(f"{name}: min must be below max.")
            specs.append(spec)
        self.card_seq += 1
        self.cards[self.card_seq] = specs
        self.live_card = self.card_seq
        keys = ("id", "kind", "label", "value", "min", "max", "step")
        self.pending_card = {"id": self.card_seq, "swatches": self._swatches(), "custom_note": "any color",
                             "controls": [{k: s[k] for k in keys if k in s} for s in specs]}
        return _text("Controls shown to the user: " + ", ".join(f'{s["label"]} ({s["kind"]})' for s in specs) + ".")

    async def apply_control(self, card_id: int, control_id: str, raw, final: bool) -> dict:
        specs = self.cards.get(card_id)
        if card_id != self.live_card or not specs:
            return {"error": "These controls are out of date; ask the agent again for new ones."}
        spec = next((s for s in specs if s["id"] == control_id), None)
        if spec is None:
            return {"error": "Unknown control."}
        try:
            value = self.coerce(spec["path"], raw)
            if spec["kind"] == "slider" and not spec["min"] <= float(value) <= spec["max"]:
                raise ValueError(f"value must be between {spec['min']:g} and {spec['max']:g}")
        except (ValueError, TypeError) as e:
            return {"error": str(e)}
        tokens = copy.deepcopy(self.working["tokens"])
        _set(tokens, spec["path"], value)
        if tokens != self.working["tokens"]:
            self._set_preview({"tokens": tokens})
        spec["value"] = self.show(value)
        self.control_notes[spec["label"]] = spec["value"]
        return {"ok": True, "value": spec["value"], "verdict": "Applied." if final else None}
