"""Reports part of the dashboard agent (v2): the panel's Reports tab. Its own session and agent loop,
separate from the edit agent.

Reading guide
- A report template is Reports/<name>.json (v2 format: see the project's _PORTING.md / references/export.md).
  `node Tools/export.mjs <name>` precomputes every allowed filter combination (Python) and turns it into one
  static HTML file in Exports/. Nothing here changes the dashboard itself.
- v2 report format: "filters" {name: {value, locked} (fixed) | {value, options} (viewer picks among options)};
  filters a report doesn't list are fixed at All. "combinations" {only: [rules], except: [rules]} narrows the
  choosable combinations (a rule maps filters to a value or a list of values). "parameters" pins slow
  parameters (e.g. {"as_of": "2026-07-31"}). The export refuses above 500 combinations ("maxCombinations"
  up to 2000).
- list_reports / generate / duplicate / delete: buttons in the Reports tab, no model call.
  Delete moves the file to .dashboard-agent/deleted-reports/ (recoverable).
- ReportSession, mode "chat": the report builder (New report / Edit). Tools: set_report (change the
  draft, checked right away), ask_user (a question with buttons; the turn ends there), save_report.
- ReportSession, mode "instructions": one headless call. The user's instructions ("red theme, no
  footer, an Info tab saying ...") become report settings on a copy of the report; the panel shows
  the changes and the user applies them or not. Only set_report is available.
- Checks: fast ones here (catalog from checks/report-catalog.mjs: cards with their Analysis filters and
  metrics, tabs, filters and their values, parameters, theme values; the combination count mirrors
  Tools/project.mjs reportPlan); the real validation (checks/report-check.mjs = the export's own
  validateReport) runs before anything is written.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shutil
import time
from pathlib import Path

from section_agent import AGENT_DIR, MAX_TURNS, ROOT, STATE_DIR, ChatSession, _err, _text
from dashboard_agent import commentary_formats, commentary_problems

REPORTS = ROOT / "Reports"
EXPORTS = ROOT / "Exports"
DELETED = STATE_DIR / "deleted-reports"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FONT = re.compile(r"^[\w\s,'\"().-]{1,160}$")
TOOL_NAMES = ["set_report", "ask_user", "save_report"]
FIELDS = ("title", "audience", "sections", "tabs", "reportTabs", "parameters", "filters", "combinations", "maxCombinations", "commentary",
          "theme", "themeOverrides", "hide", "notice", "inspect")


def _plain_env() -> dict:
    """Node scripts that load the project must not plug the agent in again (it would print, and try to start)."""
    env = dict(os.environ)
    env.pop("DASHBOARD_AGENT", None)
    return env


async def run_node(name: str, text: str = "", timeout: float = 60) -> tuple[int, str]:
    script = (AGENT_DIR / "checks" / f"{name}.mjs").read_text(encoding="utf-8")
    proc = await asyncio.create_subprocess_exec("node", "--input-type=module", "-e", script, cwd=ROOT, env=_plain_env(),
                                                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    out, _ = await asyncio.wait_for(proc.communicate(text.encode("utf-8")), timeout)
    return proc.returncode, out.decode("utf-8", "replace").strip()


_catalog: dict | None = None


async def catalog(refresh: bool = False) -> dict:
    global _catalog
    if _catalog is None or refresh:
        code, out = await run_node("report-catalog")
        if code != 0:
            raise RuntimeError("couldn't load the project (run npm run check): " + out[-400:])
        _catalog = json.loads(out)
    return _catalog


def _read(name: str) -> dict:
    return json.loads((REPORTS / f"{name}.json").read_text(encoding="utf-8"))


def _write(name: str, report: dict):
    ordered = {k: report[k] for k in FIELDS if k in report}
    ordered.update({k: v for k, v in report.items() if k not in ordered})
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{name}.json").write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def card_ids(report: dict, cat: dict) -> list[str]:
    if isinstance(report.get("reportTabs"), list):
        return [c for t in report["reportTabs"] for c in (t.get("sections") or [])]
    if isinstance(report.get("tabs"), list):
        return [s["id"] for s in cat["sections"] if s["tab"] in report["tabs"]]
    return list(report.get("sections") or [])


def _as_list(v) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def used_filters(report: dict, cat: dict) -> list[str]:
    """Filters the report's cards use (from their Analysis functions), in catalog order."""
    ids = set(card_ids(report, cat))
    used = {f for s in cat["sections"] if s["id"] in ids for f in s["filters"]}
    return [f for f in cat["filters"] if f in used]


def plan(report: dict, cat: dict) -> dict:
    """Same rules as Tools/project.mjs reportPlan (the export's check is authoritative):
    {"filters": {name: {value, locked, options}}, "choosable": [names], "count": n, "max": n, "problems": [...]}"""
    all_ = cat["all"]
    rf = report.get("filters") or {}
    filters, problems = {}, []
    for f in used_filters(report, cat):
        spec = rf.get(f) if isinstance(rf.get(f), dict) else {}
        if spec.get("options") is not None:
            options = [str(o) for o in spec["options"]]
            filters[f] = {"value": str(spec.get("value", options[0] if options else all_)), "locked": False, "options": options}
        else:
            value = str(spec.get("value", all_))
            filters[f] = {"value": value, "locked": True, "options": [value]}
    names = list(filters)
    combos = [{}]
    for n in names:
        combos = [{**c, n: o} for c in combos for o in filters[n]["options"]]
    rules = report.get("combinations") or {}
    match = lambda c, rule: all(c.get(k) in _as_list(v) for k, v in rule.items())  # noqa: E731
    for kind in ("only", "except"):
        for rule in rules.get(kind) or []:
            for k in rule:
                if k not in filters:
                    problems.append(f"combinations.{kind}: {k} is not a filter this report's cards use")
                elif any(x not in filters[k]["options"] for x in _as_list(rule[k])):
                    problems.append(f"combinations.{kind}: {k} values in this report are {', '.join(filters[k]['options'])}")
    if not problems:
        if rules.get("only"):
            combos = [c for c in combos if any(match(c, r) for r in rules["only"])]
        if rules.get("except"):
            combos = [c for c in combos if not any(match(c, r) for r in rules["except"])]
    limit = report.get("maxCombinations") or cat.get("max_combinations", 500)
    if not combos:
        problems.append("no filter combinations are left after the only / except rules")
    elif len(combos) > limit:
        problems.append(f"{len(combos)} filter combinations is over the limit of {limit}: narrow the options or add only / except rules")
    start = {n: filters[n]["value"] for n in names}
    if combos and not problems and not any(all(c[n] == start[n] for n in names) for c in combos):
        problems.append(f"the starting values {start} are excluded by the combination rules")
    return {"filters": filters, "choosable": [n for n in names if not filters[n]["locked"]], "count": len(combos), "max": limit,
            "problems": problems}


def _rule_text(rule: dict, cat: dict) -> str:
    return " and ".join(f"{cat['filters'].get(k, {}).get('label', k)} {' or '.join(_as_list(v))}" for k, v in rule.items())


def summary(report: dict, cat: dict) -> dict:
    """What the panel shows for a report: plain-language lines."""
    titles = {s["id"]: s["title"] for s in cat["sections"]}
    tab_labels = {t["id"]: t["label"] for t in cat["tabs"]}
    ids = card_ids(report, cat)
    pl = plan(report, cat)
    filters = []
    for f, spec in pl["filters"].items():
        label = cat["filters"].get(f, {}).get("label", f)
        value = spec["value"]
        if spec["locked"]:
            filters.append(f"{label}: fixed at {value}")
        elif set(spec["options"]) >= set(cat["filters"].get(f, {}).get("options", [])):
            filters.append(f"{label}: viewer can change (all values)" + (f" (starts at {value})" if value != cat["all"] else ""))
        else:
            filters.append(f"{label}: viewer picks from {', '.join(spec['options'])}" + (f" (starts at {value})" if value != spec["options"][0] else ""))
    rules = report.get("combinations") or {}
    combos = None
    if pl["choosable"]:
        combos = f"{pl['count']} filter combination{'s' if pl['count'] != 1 else ''}"
        if rules.get("only"):
            combos += "; only " + "; ".join(_rule_text(r, cat) for r in rules["only"])
        if rules.get("except"):
            combos += "; except " + "; ".join(_rule_text(r, cat) for r in rules["except"])
        if pl["problems"]:
            combos += " (" + pl["problems"][0] + ")"
    if isinstance(report.get("reportTabs"), list):
        tabs = [f"{t.get('label')}: " + ("text" if t.get("text") else ", ".join(titles.get(c, c) for c in t.get("sections") or []))
                for t in report["reportTabs"]]
    elif isinstance(report.get("tabs"), list):
        tabs = [f"{tab_labels.get(t, t)} (dashboard tab)" for t in report["tabs"]]
    else:
        tabs = []
    settings = []
    for k, v in (report.get("parameters") or {}).items():
        info = (cat.get("parameters") or {}).get(k, {})
        label = next((o["label"] for o in info.get("options", []) if o["value"] == str(v)), v)
        settings.append(f"{info.get('label', k)}: {label} (pinned)")
    theme = report.get("theme") or cat["theme"]
    over = report.get("themeOverrides") or {}
    settings.append(f"theme {theme}" + (f" with {len(over)} change(s): " + ", ".join(f"{k} {v}" for k, v in list(over.items())[:4]) if over else ""))
    if report.get("hide"):
        settings.append("hidden: " + ", ".join(report["hide"]))
    if report.get("notice"):
        settings.append(f"notice: {report['notice']}")
    own = [titles.get(k, k) for k, v in (report.get("commentary") or {}).items() if isinstance(v, str)]
    off = [titles.get(k, k) for k, v in (report.get("commentary") or {}).items() if v is False]
    if own:
        settings.append("own description: " + ", ".join(own))
    if off:
        settings.append("no description: " + ", ".join(off))
    return {"title": report.get("title") or "(no title yet)", "audience": report.get("audience"),
            "cards": [{"id": c, "title": titles.get(c, f"{c} (not on the dashboard)")} for c in ids],
            "tabs": tabs, "filters": filters, "combinations": combos, "settings": settings}


def last_export(name: str, cat: dict) -> dict | None:
    pattern = re.compile(rf"^{re.escape(cat['project'])}_{re.escape(name)}_\d{{4}}-\d{{2}}-\d{{2}}(_\d+)?\.html$")
    files = [f for f in EXPORTS.glob("*.html") if pattern.match(f.name)] if EXPORTS.exists() else []
    if not files:
        return None
    f = max(files, key=lambda x: x.stat().st_mtime)
    return {"file": f.name, "url": f"/agent/exports/{f.name}", "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))}


async def list_reports() -> dict:
    cat = await catalog(refresh=True)
    out = []
    for f in sorted(REPORTS.glob("*.json")) if REPORTS.exists() else []:
        if f.name.startswith("_"):                     # ad hoc exports
            continue
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            out.append({"name": f.stem, "error": f"not valid JSON: {e}"})
            continue
        out.append({"name": f.stem, "report": report, "summary": summary(report, cat), "last": last_export(f.stem, cat)})
    return {"reports": out, "project": cat["project"]}


async def generate(name: str) -> dict:
    if not NAME_RE.fullmatch(name or "") or not (REPORTS / f"{name}.json").exists():
        return {"error": f"no report {name!r}"}
    proc = await asyncio.create_subprocess_exec("node", str(Path("Tools") / "export.mjs"), name, cwd=ROOT, env=_plain_env(),
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), 300)
    log = out.decode("utf-8", "replace")
    m = re.search(r"Exported Exports[\\/](\S+\.html) \(([^;)]*)", log)
    combos = re.search(r"^Combinations: (\d+)", log, re.M)
    if proc.returncode != 0 or not m:
        problems = [l for l in log.splitlines() if l.startswith(("ERROR", "WARN"))] or log.strip().splitlines()[-5:]
        return {"error": "Generate failed", "log": problems[:12]}
    warnings = [l[6:] for l in log.splitlines() if l.startswith("WARN")]
    return {"ok": True, "file": m.group(1), "size": m.group(2), "url": f"/agent/exports/{m.group(1)}", "warnings": warnings,
            "combinations": int(combos.group(1)) if combos else None}


def export_file(file: str) -> bytes | None:
    if not re.fullmatch(r"[\w.-]+\.html", file or ""):
        return None
    path = EXPORTS / file
    return path.read_bytes() if path.is_file() else None


def delete(name: str) -> dict:
    src = REPORTS / f"{name}.json"
    if not NAME_RE.fullmatch(name or "") or not src.exists():
        return {"error": f"no report {name!r}"}
    DELETED.mkdir(parents=True, exist_ok=True)
    dest = DELETED / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    shutil.move(str(src), dest)
    return {"ok": True, "moved_to": str(dest.relative_to(ROOT))}


def duplicate(name: str) -> dict:
    if not NAME_RE.fullmatch(name or "") or not (REPORTS / f"{name}.json").exists():
        return {"error": f"no report {name!r}"}
    n, new = 2, f"{name}-copy"
    while (REPORTS / f"{new}.json").exists():
        new, n = f"{name}-copy-{n}", n + 1
    report = _read(name)
    report["title"] = f"{report.get('title', name)} (copy)"
    _write(new, report)
    return {"ok": True, "name": new}


async def validate(name: str, report: dict) -> list[str]:
    """The export's own validateReport (Tools/project.mjs). [] = valid."""
    code, out = await run_node("report-check", json.dumps({"name": name, "report": report}))
    if code == 0:
        return []
    return [l[6:] for l in out.splitlines() if l.startswith("ERROR")] or [out[-400:] or "the report check failed to run"]


async def apply(name: str, report: dict) -> dict:
    """Write a report the user approved (e.g. the result of instructions), after the real validation."""
    if not NAME_RE.fullmatch(name or ""):
        return {"error": "name: lowercase letters, numbers and dashes"}
    errors = await validate(name, report)
    if errors:
        return {"error": "Not saved: " + "; ".join(errors[:5])}
    _write(name, report)
    return {"ok": True}


# ---------------------------------------------------------------- the report agent

PROMPT = """You build report templates for a React dashboard, inside its dev tools. A report is one
static HTML file made from some of the dashboard's cards, with its own filter settings and look.
It is saved as Reports/<name>.json and generated on demand: every filter combination the viewer may
choose is computed ahead (in Python) and stored in the file, so the number of combinations matters.
You never change the dashboard, its data or its calculations.

{mode_block}

Tools
- set_report(changes): change the draft. Fields (send only what changes; null removes a field):
  title, audience (who it's for, shown as "Prepared for ..."),
  cards (card ids in order) OR tabs (dashboard tab ids: all their cards) OR report_tabs (the
  report's own tabs: [{{"label", "cards": [ids]}} or {{"label", "text": "plain text"}}]; a text tab
  holds a note, e.g. an "Info" tab),
  filters ({{"<filter>": {{"mode": "viewer" | "fixed" | "limited", "value", "options"}}}}):
    viewer = the viewer can pick any value (value = where it starts, default All);
    fixed = always one value, filter hidden (value required);
    limited = the viewer picks among options only (they may include All; value = where it starts);
    a filter the report doesn't set is fixed at All,
  combinations ({{"only": [rules], "except": [rules]}} or {{}} = every combination allowed): narrows the
    filter combinations the viewer can choose; a rule maps filters to a value or a list of values,
    e.g. {{"only": [{{"line_of_business": "Commercial", "region": ["East", "West"]}}]}} keeps only those,
    {{"except": [{{"region": "West", "line_of_business": "Medicaid"}}]}} drops that one,
  parameters ({{"<parameter>": "<value>"}}): pin a slow parameter (e.g. the data month) for this
    report; null = the current data,
  theme (a theme name), theme_overrides ({{"colors.accent": "#C62828", ...}}: existing theme paths
  only; colors as #RRGGBB, font.size 10-20, effects true/false, fonts as plain lists),
  hide (any of: {parts}), notice (one line shown at the top, plain text),
  descriptions ({{"<card id>": "text" | false | true}}: own text for this report, none, or the card's
  own). Description text: plain sentences; numbers only as live references {{metric|format}} from
  that card's metrics; typed numbers are rejected.
  Every set_report result shows the draft, including the number of filter combinations.
- ask_user(question, options, multi): show the user ONE question with buttons (max 8 options;
  multi = they may pick several). Then stop and wait: their answer is the next message.
- save_report(name, overwrite): write Reports/<name>.json (lowercase letters, numbers, dashes).

{flow}

Rules
- Use only the cards, tabs, filters, values, parameters and themes listed below. A chart or number
  that is not on the dashboard is a Claude Code job (it has to be added to the dashboard first): say so.
- At most {max_combos} filter combinations per report; when a choice goes over, say so and suggest
  fewer options or an only / except rule.
- Keep replies to one or two short sentences; the panel shows the draft summary.
- Unsupported requests (new charts, data changes, layout inside a card, other files): say it's
  not something reports can do, and why, in one sentence.

Dashboard: {title}
Cards (id: title [tab] filters):
{cards}
Dashboard tabs: {tabs}
Filters and their values:
{filters}
Slow parameters (pinnable):
{parameters}
Themes: {themes} (dashboard default: {theme})
Theme values you may override ({theme_for} theme):
{tokens}"""

NEW_FLOW = """How to build a new report (skip any step the user already answered):
1. If the user hasn't said which cards, ask with ask_user, offering the dashboard tabs as options
   (multi) plus "Pick individual cards".
2. set_report with the cards (or tabs).
3. For EACH filter the chosen cards use, one ask_user: "How should <filter label> work?" with
   options "Viewer can change (all values)", "Fixed: <value>" for each value, and "Viewer picks
   from some values". For the last one, a second ask_user (multi) with the values. Record each
   answer with set_report.
4. Filter combinations: once the filters are set and the viewer can choose at least one, ask which
   combinations are allowed, naming the count set_report showed: ask_user "Allow all <N> filter
   combinations?" with options "Allow all <N>", "Only some combinations", "Leave some out". For the
   last two, ask which (buttons with the likely combinations), record them with set_report
   combinations (only / except) and tell the user the new count. "Allow all" = combinations {{}}.
5. Ask for a title and who it's for if not given (suggest one as an option).
6. Look, hidden parts, notice, text tabs, own descriptions, a pinned data month: only when the user asks.
7. Ask to save, suggesting a name as an option (e.g. "Save as finance-monthly"); then save_report."""

EDIT_FLOW = """You are editing the existing report "{name}" (its current settings are the draft). Make
the changes the user asks for with set_report. If the filters change and the viewer can choose any,
ask which filter combinations are allowed (all <N>, only some, or leave some out), as for a new
report, and say the new count. Then ask whether to save (save_report with the same name and
overwrite true)."""

INSTRUCTIONS_BLOCK = """Headless mode: turn the user's instructions into changes to the report "{name}" with
ONE set_report call (the current settings are the draft), then reply with one sentence listing
what you changed (with the filter combination count if filters changed) and anything you could not
do. Do not ask questions; ask_user and save_report are not available."""


class ReportSession(ChatSession):
    def __init__(self, name: str | None, settings: dict, browser_alive, cat: dict, mode: str = "chat"):
        super().__init__(settings, browser_alive)
        self.mode, self.name, self.cat = mode, name, cat
        self.original = _read(name) if name else None
        self.draft: dict = copy.deepcopy(self.original) if self.original else {}
        self.question: dict | None = None       # ask_user: shown as buttons with the reply
        self.saved: str | None = None           # name saved during the last request
        self.failed_edits = 0
        # the user has answered which filter combinations are allowed (set_report sent "combinations")
        self.combos_confirmed = bool(self.original) and self.original.get("filters") is not None

    # ----- state for the panel
    def state(self) -> dict:
        return {"name": self.name, "draft": self.draft, "summary": summary(self.draft, self.cat) if self.draft else None,
                "dirty": self.draft != (self.original or {}), "mode": self.mode}

    async def ask(self, message: str, clicked=None) -> dict:
        self.question, self.saved = None, None
        answer = await super().ask(message, clicked)
        return {**answer, **self.state(), "question": self.question, "saved": self.saved}

    async def close(self):
        await self.close_client()

    # ----- draft checks (fast; the real validation runs at save)
    def _check_and_apply(self, changes: dict) -> tuple[dict | None, list[str]]:
        cat = self.cat
        ids = {s["id"]: s for s in cat["sections"]}
        tab_ids = [t["id"] for t in cat["tabs"]]
        d = copy.deepcopy(self.draft)
        problems = []

        def put(key, value):
            if value is None:
                d.pop(key, None)
            else:
                d[key] = value

        for key in ("title", "audience", "notice"):
            if key in changes:
                v = changes[key]
                limit = {"title": 120, "audience": 120, "notice": 300}[key]
                if v is not None and (not isinstance(v, str) or not v.strip() or len(v) > limit or re.search(r"<[a-zA-Z/!]", v)):
                    problems.append(f"{key}: plain text, 1-{limit} characters")
                else:
                    put(key, v.strip() if isinstance(v, str) else None)
        picked = [k for k in ("cards", "tabs", "report_tabs") if changes.get(k) is not None]
        if len(picked) > 1:
            problems.append("use one of cards, tabs or report_tabs")
        elif picked:
            for k in ("sections", "tabs", "reportTabs"):
                d.pop(k, None)
            key = picked[0]
            if key == "cards":
                bad = [c for c in changes["cards"] if c not in ids]
                if bad or not changes["cards"]:
                    problems.append(f"unknown card(s) {', '.join(bad) or '(none given)'}")
                d["sections"] = list(dict.fromkeys(changes["cards"]))
            elif key == "tabs":
                bad = [t for t in changes["tabs"] if t not in tab_ids]
                if bad or not changes["tabs"]:
                    problems.append(f"unknown tab(s) {', '.join(bad) or '(none given)'}; tabs: {', '.join(tab_ids)}")
                d["tabs"] = changes["tabs"]
            else:
                rt, seen = [], set()
                for t in changes["report_tabs"]:
                    label = (t.get("label") or "").strip()
                    cards, text = t.get("cards"), (t.get("text") or "").strip()
                    if not label or len(label) > 40:
                        problems.append("each report tab needs a label (1-40 characters)")
                    if bool(cards) == bool(text):
                        problems.append(f"report tab {label!r}: either cards or text")
                    for c in cards or []:
                        if c not in ids:
                            problems.append(f"report tab {label!r}: unknown card {c}")
                        if c in seen:
                            problems.append(f"{c} is in two report tabs")
                        seen.add(c)
                    if text and (len(text) > 2000 or re.search(r"<[a-zA-Z/!]", text)):
                        problems.append(f"report tab {label!r}: text is plain, up to 2000 characters")
                    rt.append({"label": label, **({"sections": cards} if cards else {"text": text})})
                d["reportTabs"] = rt
        if "theme" in changes:
            if changes["theme"] is not None and changes["theme"] not in cat["themes"]:
                problems.append(f"theme must be one of {', '.join(cat['themes'])}")
            else:
                put("theme", changes["theme"])
        theme = d.get("theme") or cat["theme"]
        if "theme_overrides" in changes:
            over = changes["theme_overrides"]
            if over is None:
                d.pop("themeOverrides", None)
            else:
                tokens, merged = cat["tokens"][theme], dict(d.get("themeOverrides") or {})
                for path, v in over.items():
                    cur = tokens.get(path)
                    if cur is None:
                        problems.append(f"theme value {path!r} doesn't exist (e.g. colors.accent, colors.series.0, font.family)")
                    elif v is None:
                        merged.pop(path, None)
                    elif isinstance(cur, bool):
                        merged[path] = v if isinstance(v, bool) else problems.append(f"{path}: true or false")
                    elif isinstance(cur, (int, float)):
                        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and (path != "font.size" or 10 <= v <= 20)
                        merged[path] = v if ok else problems.append(f"{path}: a number" + (" 10-20" if path == "font.size" else ""))
                    elif HEX.match(str(cur)):
                        merged[path] = v.upper() if isinstance(v, str) and HEX.match(v) else problems.append(f'{path}: a color like "#C62828"')
                    else:
                        merged[path] = v if isinstance(v, str) and FONT.match(v) else problems.append(f"{path}: a plain font list")
                merged = {k: v for k, v in merged.items() if v is not None}
                put("themeOverrides", merged or None)
        if "hide" in changes:
            hide = changes["hide"]
            if hide is not None and any(h not in cat["parts"] for h in hide):
                problems.append(f"hide may list only {', '.join(cat['parts'])}")
            else:
                put("hide", list(dict.fromkeys(hide)) if hide else None)
        chosen = card_ids(d, cat)
        if "filters" in changes:
            filters = dict(d.get("filters") or {})
            for f, spec in (changes["filters"] or {}).items():
                info = cat["filters"].get(f)
                if info is None:
                    problems.append(f"unknown filter {f!r}; filters: {', '.join(cat['filters'])}")
                    continue
                if spec is None:
                    filters.pop(f, None)
                    continue
                mode, value, options = spec.get("mode", "viewer"), spec.get("value"), spec.get("options")
                values = info["options"]                      # data values, without All
                if mode == "fixed":
                    if value not in values and value != cat["all"]:
                        problems.append(f"{info['label']}: fixed needs one of {', '.join(values)}")
                        continue
                    filters[f] = {"value": value, "locked": True}
                elif mode == "limited":
                    options = list(dict.fromkeys(options or []))
                    bad = [o for o in options if o not in values and o != cat["all"]]
                    if not options or bad:
                        problems.append(f"{info['label']}: options must come from {cat['all']}, {', '.join(values)}")
                        continue
                    filters[f] = {"value": value if value in options else options[0], "options": options}
                elif mode == "viewer":                          # every value, All first
                    options = [cat["all"], *values]
                    filters[f] = {"value": value if value in options else cat["all"], "options": options}
                else:
                    problems.append(f"{info['label']}: mode is viewer, fixed or limited")
            put("filters", filters or None)
        if "combinations" in changes:
            rules = changes["combinations"]
            if rules is None or rules == {}:
                d.pop("combinations", None)
            elif not isinstance(rules, dict) or set(rules) - {"only", "except"}:
                problems.append('combinations: {"only": [rules], "except": [rules]} or {} for every combination')
            else:
                clean = {}
                for kind in ("only", "except"):
                    lst = rules.get(kind)
                    if not lst:
                        continue
                    for rule in lst:
                        if not isinstance(rule, dict) or not rule:
                            problems.append(f'combinations.{kind}: each rule maps filters to values, e.g. {{"region": ["East", "West"]}}')
                            continue
                        for k, v in rule.items():
                            if k not in cat["filters"]:
                                problems.append(f"combinations.{kind}: unknown filter {k!r}")
                            elif any(x not in cat["filters"][k]["options"] and x != cat["all"] for x in _as_list(v)):
                                problems.append(f"combinations.{kind}: {k} values must come from {', '.join(cat['filters'][k]['options'])}")
                    clean[kind] = lst
                put("combinations", clean or None)
        if "parameters" in changes:
            params = dict(d.get("parameters") or {})
            for k, v in (changes["parameters"] or {}).items():
                info = (cat.get("parameters") or {}).get(k)
                if info is None:
                    problems.append(f"unknown parameter {k!r}; parameters: {', '.join(cat.get('parameters') or {}) or 'none'}")
                elif v is None:
                    params.pop(k, None)
                elif str(v) not in [o["value"] for o in info["options"]]:
                    problems.append(f"{info['label']}: one of " + ", ".join(f"{o['value']} ({o['label']})" for o in info["options"][:12]))
                else:
                    params[k] = str(v)
            put("parameters", params or None)
        if "descriptions" in changes:
            own = dict(d.get("commentary") or {})
            for c, v in (changes["descriptions"] or {}).items():
                if c not in ids:
                    problems.append(f"descriptions: unknown card {c}")
                elif v is True or v is None:
                    own.pop(c, None)
                elif v is False:
                    own[c] = False
                elif isinstance(v, str):
                    issues = commentary_problems(v.strip(), ids[c]["metrics"], commentary_formats())
                    if issues:
                        problems.append(f"description for {c}: " + "; ".join(issues))
                    else:
                        own[c] = v.strip()
            put("commentary", own or None)
        if chosen and not problems:
            unused = [f for f in (d.get("filters") or {}) if not any(f in ids[c]["filters"] for c in chosen if c in ids)]
            for f in unused:
                d["filters"].pop(f)
            if d.get("filters") == {}:
                d.pop("filters")
            pl = plan(d, cat)
            if ("filters" in changes or "combinations" in changes or picked) and pl["problems"]:
                problems += pl["problems"]
        return (None, problems) if problems else (d, [])

    def _open_filters(self, d: dict) -> list[str]:
        return [self.cat["filters"][f]["label"] + f" ({f})" for f in used_filters(d, self.cat) if f not in (d.get("filters") or {})]

    def _combos_line(self, d: dict) -> str | None:
        pl = plan(d, self.cat)
        if not pl["choosable"]:
            return None
        sizes = " x ".join(f"{len(pl['filters'][n]['options'])} {self.cat['filters'][n]['label']}" for n in pl["choosable"])
        rules = d.get("combinations") or {}
        how = "after the only / except rules" if rules else f"= {sizes}"
        return f"Filter combinations: {pl['count']} {how} (limit {pl['max']})"

    def _fail(self, message: str) -> dict:
        self.failed_edits += 1
        left = 3 - self.failed_edits
        return _err(message + (f"\n({left} attempt(s) left.)" if left > 0 else "\nNo attempts left: tell the user what went wrong."))

    # ----- tools
    async def tool_set_report(self, changes: dict) -> dict:
        if not isinstance(changes, dict) or not changes:
            return self._fail("changes must be an object with at least one field.")
        draft, problems = self._check_and_apply(changes)
        if problems:
            return self._fail("Not applied:\n- " + "\n- ".join(problems[:8]))
        self.draft, self.failed_edits = draft, 0
        s = summary(draft, self.cat)
        lines = [f"Draft: {s['title']}", "Cards: " + (", ".join(f"{c['id']}" for c in s["cards"]) or "none yet")]
        lines += s["tabs"][:6] + s["filters"] + s["settings"]
        combos = self._combos_line(draft)
        if combos:
            lines.append(combos)
        if "combinations" in changes:
            self.combos_confirmed = True
        elif "filters" in changes:
            self.combos_confirmed = False
        todo = self._open_filters(draft)
        if todo and self.mode == "chat":
            lines.append("Filters not decided yet (ask about each): " + ", ".join(todo))
        elif combos and not self.combos_confirmed and self.mode == "chat":
            lines.append("Combinations not confirmed yet: ask which filter combinations are allowed (all, only some, or leave some out).")
        return _text("\n".join(lines))

    async def tool_ask(self, question: str, options: list, multi: bool = False) -> dict:
        if self.mode != "chat":
            return _err("No questions in headless mode: apply what you can and say what you couldn't.")
        opts = [str(o).strip() for o in options or [] if str(o).strip()][:8]
        if not question or len(opts) < 2:
            return _err("ask_user needs a question and 2-8 options.")
        self.question = {"text": question.strip(), "options": opts, "multi": bool(multi)}
        return _text("Question shown with buttons. Stop now; the answer comes as the next message.")

    async def tool_save(self, name: str, overwrite: bool = False) -> dict:
        if self.mode != "chat":
            return _err("Saving is not available in headless mode.")
        name = (name or "").strip().lower()
        if not NAME_RE.fullmatch(name):
            return _err("name: lowercase letters, numbers and dashes (e.g. finance-monthly).")
        if (REPORTS / f"{name}.json").exists() and name != self.name and not overwrite:
            return _err(f"A report named {name} already exists. Ask the user: overwrite it, or another name?")
        if not self.draft.get("title"):
            return _err("The report needs a title first.")
        if plan(self.draft, self.cat)["choosable"] and not self.combos_confirmed:
            return _err(f"Ask the user which filter combinations are allowed first ({self._combos_line(self.draft)}): all of them, only some, "
                        "or leave some out; record the answer with set_report combinations ({} = all).")
        errors = await validate(name, self.draft)
        if errors:
            return self._fail("Not saved:\n- " + "\n- ".join(errors[:8]))
        _write(name, self.draft)
        self.name, self.original, self.saved = name, copy.deepcopy(self.draft), name
        return _text(f"Saved as Reports/{name}.json. It's in the report list; the user can Generate it there.")

    # ----- one request
    def _user_text(self, message: str, clicked) -> str:
        return f"Request: {message}\nCurrent draft (report JSON): {json.dumps(self.draft, ensure_ascii=False)}"

    def system_prompt(self) -> str:
        cat = self.cat
        theme = self.draft.get("theme") or cat["theme"]
        if self.mode == "instructions":
            mode_block, flow = INSTRUCTIONS_BLOCK.format(name=self.name), ""
        elif self.name:
            mode_block, flow = f"Editing report {self.name}.", EDIT_FLOW.format(name=self.name)
        else:
            mode_block, flow = "Building a new report.", NEW_FLOW
        cards = "\n".join(f"  {s['id']}: {s['title']} [{s['tab'] or '-'}] {', '.join(s['filters']) or 'no filters'}"
                          + (f" metrics: {', '.join(s['metrics'])}" if s.get("metrics") else "") for s in cat["sections"])
        filters = "\n".join(f"  {f} ({i['label']}): {cat['all']}, {', '.join(i['options'])}" for f, i in cat["filters"].items())
        params = "\n".join(f"  {k} ({i['label']}): now {i['value']}; " + ", ".join(f"{o['value']} ({o['label']})" for o in i["options"][:12])
                           for k, i in (cat.get("parameters") or {}).items())
        tokens = ", ".join(f"{k}={v}" for k, v in cat["tokens"][theme].items())
        return PROMPT.format(mode_block=mode_block, flow=flow, parts=", ".join(cat["parts"]), title=cat["title"], cards=cards,
                             tabs=", ".join(f"{t['id']} ({t['label']})" for t in cat["tabs"]) or "none", filters=filters or "  none",
                             parameters=params or "  none", max_combos=cat.get("max_combinations", 500),
                             themes=", ".join(cat["themes"]), theme=cat["theme"], theme_for=theme, tokens=tokens)

    def options(self):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool
        s = self
        cards = [c["id"] for c in self.cat["sections"]]

        @tool("set_report", "Change the report draft (send only fields that change; null removes one).",
              {"type": "object", "additionalProperties": False, "required": ["changes"],
               "properties": {"changes": {"type": "object", "additionalProperties": False, "properties": {
                   "title": {"type": ["string", "null"]}, "audience": {"type": ["string", "null"]}, "notice": {"type": ["string", "null"]},
                   "cards": {"type": "array", "items": {"type": "string", "enum": cards}},
                   "tabs": {"type": "array", "items": {"type": "string"}},
                   "report_tabs": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["label"],
                                                               "properties": {"label": {"type": "string"}, "text": {"type": "string"},
                                                                              "cards": {"type": "array", "items": {"type": "string", "enum": cards}}}}},
                   "filters": {"type": "object", "additionalProperties": {"type": ["object", "null"], "additionalProperties": False, "properties": {
                       "mode": {"type": "string", "enum": ["viewer", "fixed", "limited"]}, "value": {"type": "string"},
                       "options": {"type": "array", "items": {"type": "string"}}}}},
                   "combinations": {"type": ["object", "null"], "additionalProperties": False, "properties": {
                       "only": {"type": "array", "items": {"type": "object", "additionalProperties": {"type": ["string", "array"], "items": {"type": "string"}}}},
                       "except": {"type": "array", "items": {"type": "object", "additionalProperties": {"type": ["string", "array"], "items": {"type": "string"}}}}}},
                   "parameters": {"type": ["object", "null"], "additionalProperties": {"type": ["string", "null"]}},
                   "theme": {"type": ["string", "null"]},
                   "theme_overrides": {"type": ["object", "null"], "additionalProperties": {"type": ["string", "number", "boolean", "null"]}},
                   "hide": {"type": ["array", "null"], "items": {"type": "string", "enum": self.cat["parts"]}},
                   "descriptions": {"type": "object", "additionalProperties": {"type": ["string", "boolean"]}}}}}})
        async def set_report(a):
            return await s.tool_set_report(a["changes"])

        tools = [set_report]
        if self.mode == "chat":
            @tool("ask_user", "Show the user one question with 2-8 buttons, then stop and wait for the answer.",
                  {"type": "object", "additionalProperties": False, "required": ["question", "options"],
                   "properties": {"question": {"type": "string"}, "options": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"type": "string"}},
                                  "multi": {"type": "boolean"}}})
            async def ask_user(a):
                return await s.tool_ask(a["question"], a["options"], a.get("multi", False))

            @tool("save_report", "Save the draft as Reports/<name>.json.",
                  {"type": "object", "additionalProperties": False, "required": ["name"],
                   "properties": {"name": {"type": "string"}, "overwrite": {"type": "boolean"}}})
            async def save_report(a):
                return await s.tool_save(a["name"], a.get("overwrite", False))

            tools += [ask_user, save_report]
        server = create_sdk_mcp_server(name="reports", version="1.0.0", tools=tools)
        workspace = STATE_DIR / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        names = ["set_report"] + (["ask_user", "save_report"] if self.mode == "chat" else [])
        return ClaudeAgentOptions(
            model=self.settings["model"], effort=self.settings["effort"], system_prompt=self.system_prompt(),
            tools=[], mcp_servers={"reports": server}, allowed_tools=[f"mcp__reports__{n}" for n in names],
            permission_mode="dontAsk", strict_mcp_config=True, setting_sources=[], skills=[],
            max_turns=MAX_TURNS if self.mode == "chat" else 3, cwd=str(workspace),
            env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "ENABLE_TOOL_SEARCH": "false"},
        )


def changes_between(old: dict, new: dict, cat: dict) -> list[str]:
    """Plain-language list of what instructions changed."""
    a, b = summary(old, cat), summary(new, cat)
    out = []
    for key in ("title", "audience", "combinations"):
        if a[key] != b[key]:
            out.append(f"{key}: {b[key] or '(none)'}")
    for key, label in (("tabs", "tabs"), ("filters", "filters"), ("settings", "settings")):
        added = [x for x in b[key] if x not in a[key]]
        removed = [x for x in a[key] if x not in b[key]]
        out += [f"{label} + {x}" for x in added] + [f"{label} - {x}" for x in removed]
    if [c["id"] for c in a["cards"]] != [c["id"] for c in b["cards"]]:
        out.append("cards: " + ", ".join(c["title"] for c in b["cards"]))
    return out


async def run_instructions(name: str, text: str, settings: dict) -> dict:
    """The headless call: instructions -> proposed settings for report `name` (not saved)."""
    cat = await catalog(refresh=True)
    session = ReportSession(name, settings, lambda: False, cat, mode="instructions")
    try:
        answer = await ChatSession.ask(session, text, None)
    finally:
        await session.close()
    return {"reply": answer["reply"], "cost": answer["cost"], "proposed": session.draft,
            "changes": changes_between(session.original, session.draft, cat), "changed": session.draft != session.original}
