"""Component target: one shared, presentational component, changed for every place that uses it.

Reading guide
- EDITABLE lists the components the agent may change (display only). Everything else that is
  shared (ChartECharts, SectionFrame, lib/, filter controls, App) is locked: Inspect says so and
  points to a Claude Code session instead.
- usage_map() reads the project's imports: which sections use a component, directly or through
  another component; SectionFrame means "every section", App means "the page".
- ComponentSession: tools view_component, edit_component, edit_styles (Src/custom.css, only rules
  for the component's own classes). Visual-only requests go to CSS first.
- Preview: the code is written to <project>/.dashboard-agent/component-preview.json; the dev server
  (vite-plugin.js) serves it in place of the real file and hot-swaps it, so every card using the
  component updates. The tab reports render errors; a broken version is replaced by the last good
  one while the agent fixes it.
- Checks on every code edit: parses; same exports; every prop accepted before is still accepted
  and new props have defaults; imports only from the allowlist; no network, storage, window,
  document, eval or raw HTML (checks/component-check.mjs).
- Keep writes the real file (and custom.css), records it in kept-writes.json (no page reload) and
  in component-changes.json (the original's hash: the file is now "modified" from the template).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict

from section_agent import (_VERSIONS, CRLF, LF, MAX_FAILED_EDITS, ROOT, SECTIONS, STATE_DIR, ChatSession,
                           RenderWaits, _err, _text, run_check, syntax_error)
from global_agent import write_kept

# name -> (file, CSS classes it owns). Display-only components; the rest stays locked.
EDITABLE = {
    "KpiTile": ("Src/Components/KpiTile.jsx", [".kpi"]),
    "Commentary": ("Src/Components/Commentary.jsx", [".commentary"]),
    "ReportHeader": ("Src/Components/ReportHeader.jsx", [".report-header", ".stale-banner"]),
    "ReportFooter": ("Src/Components/ReportFooter.jsx", [".report-footer"]),
    "Segmented": ("Src/Controls/Segmented.jsx", [".segmented"]),
}
SHARED_DIRS = ("Src/Components/", "Src/Controls/")
ALLOWED_IMPORTS = ["react", "Src/Lib/theme.js", "Src/Lib/commentary.js", "Src/Components/ChartECharts.jsx"]
PREVIEW_JSON = STATE_DIR / "component-preview.json"
CHANGES_JSON = STATE_DIR / "component-changes.json"
IMPORT_RE = re.compile(r"""^\s*import\s+(?:[\w*{}\s,]+?\s+from\s+)?['"](\.{1,2}/[^'"]+)['"]""", re.M)


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _rel(path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def clear_preview():
    PREVIEW_JSON.unlink(missing_ok=True)


# ---------------------------------------------------------------- usage

def _sections() -> dict[str, dict]:
    out = {}
    for f in sorted(SECTIONS.glob("*.jsx")):
        if ".agent-preview." in f.name:
            continue
        src = f.read_text(encoding="utf-8")
        title = re.search(r"""\btitle:\s*(['"`])(.*?)\1""", src)
        tab = re.search(r"""\btab:\s*['"]([\w-]+)['"]""", src)
        out[_rel(f)] = {"id": f.stem, "title": title.group(2) if title else f.stem, "tab": tab.group(1) if tab else None}
    return out


def usage_map() -> dict[str, dict]:
    """Every shared file under Src/Components and Src/Controls -> who uses it."""
    src_dir = ROOT / "Src"
    importers: dict[str, set[str]] = defaultdict(set)
    for f in src_dir.rglob("*"):
        if f.suffix not in (".js", ".jsx") or ".agent-preview." in f.name:
            continue
        for m in IMPORT_RE.finditer(f.read_text(encoding="utf-8")):
            target = (f.parent / m.group(1)).resolve()
            if target.is_relative_to(ROOT):
                importers[_rel(target)].add(_rel(f))
    sections = _sections()
    frame, app = "Src/Components/SectionFrame.jsx", "Src/App.jsx"
    changes = _load_changes()
    out = {}
    for f in sorted(src_dir.rglob("*.jsx")):
        rel = _rel(f)
        if not rel.startswith(SHARED_DIRS) or ".agent-preview." in f.name:
            continue
        used, all_sections, page, seen, todo = [], rel == frame, False, {rel}, [] if rel == frame else [rel]
        while todo:
            for imp in sorted(importers.get(todo.pop(), ())):
                if imp in seen:
                    continue
                seen.add(imp)
                if imp in sections:
                    used.append(sections[imp])
                elif imp == frame:
                    all_sections = True
                elif imp == app:
                    page = True
                elif imp.startswith(SHARED_DIRS):
                    todo.append(imp)
        name = f.stem
        editable = EDITABLE.get(name, (None,))[0] == rel
        change = changes.get(rel)
        out[rel] = {
            "name": name, "file": rel, "editable": editable,
            "used_by": {"sections": [] if all_sections else used, "all_sections": all_sections,
                        "section_count": len(sections), "page": page},
            "modified": bool(change and _sha(f.read_text(encoding="utf-8")) != change["original_sha"]),
        }
    return out


def usage_words(info: dict) -> str:
    u = info["used_by"]
    parts = []
    if u["all_sections"]:
        parts.append(f"every section ({u['section_count']})")
    elif u["sections"]:
        n = len(u["sections"])
        parts.append(f"{n} section{'s' if n != 1 else ''}: " + ", ".join(f"{s['id']} ({s['title']})" for s in u["sections"]))
    if u["page"]:
        parts.append("the page itself (every tab)")
    return " and ".join(parts) or "nothing on the dashboard yet"


def _load_changes() -> dict:
    try:
        return json.loads(CHANGES_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_change(rel: str, original: str, kept: str):
    """Remember the pre-agent original's hash: the file now differs from what the template made."""
    changes = _load_changes()
    entry = changes.get(rel) or {"original_sha": _sha(original)}
    entry.update(kept_sha=_sha(kept), kept_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    changes[rel] = entry
    CHANGES_JSON.parent.mkdir(parents=True, exist_ok=True)
    CHANGES_JSON.write_text(json.dumps(changes, indent=1), encoding="utf-8")


def call_sites(name: str) -> list[str]:
    tag = re.compile(r"<%s\b" % re.escape(name))
    sites = []
    for f in sorted((ROOT / "Src").rglob("*.jsx")):
        if ".agent-preview." in f.name:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if tag.search(line):
                sites.append(f"  {_rel(f)}:{i}  {line.strip()[:170]}")
    return sites


# ---------------------------------------------------------------- session

class ComponentSession(RenderWaits, ChatSession):
    render_wait_s = 5.0

    @staticmethod
    def check_target(target_id: str) -> str:
        name = target_id.split(":", 1)[-1]
        if name not in EDITABLE:
            raise ValueError(f"{name} is locked: ask in a Claude Code session")
        return name

    def __init__(self, target_id: str, settings: dict, browser_alive):
        name = self.check_target(target_id)
        super().__init__(settings, browser_alive)
        self.id, self.name = target_id, name
        self.rel, self.prefixes = EDITABLE[name]
        self.file = ROOT / self.rel
        self.original = self.file.read_text(encoding="utf-8", newline="")
        self.code: str | None = None       # working code (may be broken while the agent fixes it)
        self.last_good: str | None = None
        self.reports = {}
        self.version = next(_VERSIONS)
        self.info = usage_map().get(self.rel) or {"used_by": {"sections": [], "all_sections": False, "section_count": 0, "page": False}}
        clear_preview()

    # ----- state
    @property
    def working(self) -> str:
        return self.code if self.code is not None else self.original

    @property
    def dirty(self) -> bool:
        return self.code is not None and self.code != self.original

    def _show(self, code: str | None):
        """What the dev server serves for the component: code, or None = the real file."""
        if code is None or code == self.original:
            clear_preview()
        else:
            PREVIEW_JSON.parent.mkdir(parents=True, exist_ok=True)
            PREVIEW_JSON.write_text(json.dumps({"file": self.rel, "code": code}), encoding="utf-8")
        self.version = next(_VERSIONS)

    # ----- user actions
    def keep(self):
        if not self.dirty:
            return
        write_kept(self.file, self.code)                 # same text the tab already runs: no reload
        record_change(self.rel, self.original, self.code)
        self.original = self.code
        self.code = self.last_good = None
        self._show(None)

    def discard(self):
        if self.code is not None:
            self.code = self.last_good = None
            self._show(None)

    async def close(self):
        clear_preview()
        await self.close_client()

    def _fail(self, message: str) -> dict:
        self.failed_edits += 1
        left = MAX_FAILED_EDITS - self.failed_edits
        return _err(message + (f"\n({left} attempt(s) left.)" if left > 0 else "\nNo attempts left: tell the user you couldn't apply it."))

    # ----- tools
    async def tool_view(self) -> dict:
        sites = "\n".join(call_sites(self.name) or ["  (no call sites found)"])
        return _text(f"{self.rel} (preview):\n```jsx\n{self.working}\n```\n\nWhere it is used:\n{sites}")

    async def tool_edit(self, old: str, new: str) -> dict:
        if self.failed_edits >= MAX_FAILED_EDITS:
            return _err("Edit limit reached for this request. Stop editing and tell the user you couldn't apply it.")
        current = self.working
        if CRLF in current:
            old, new = (t.replace(CRLF, LF).replace(LF, CRLF) for t in (old, new))
        count = current.count(old) if old else 0
        if count != 1:
            return self._fail(f"old_text must appear exactly once; found {count} matches. Use view (component) and copy the exact text.")
        candidate = current.replace(old, new, 1)
        problem = await syntax_error(candidate)
        if problem:
            return self._fail("Rejected, the file would not parse:\n" + problem)
        problem = await run_check("component-check", json.dumps({"file": self.rel, "original": self.original, "candidate": candidate, "allow": ALLOWED_IMPORTS}))
        if problem:
            return self._fail("Rejected:\n" + problem)

        self.code = candidate
        self._show(candidate)
        verdict = await self._wait_render(self.version)
        if verdict.startswith("render error"):
            self._show(self.last_good)                   # the page goes back to the last good version
            result = self._fail(verdict + "\nThe page is showing the last good version. Fix the code.")
            if self.failed_edits >= MAX_FAILED_EDITS:
                self.code = self.last_good
            return result
        self.last_good = candidate
        self.failed_edits = 0
        return _text(verdict + " The preview is live on every card that uses it.")
