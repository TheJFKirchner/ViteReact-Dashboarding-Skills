"""Layout part of the dashboard agent (v2): where cards sit. Order on the page, which tab, half or
full width, hidden or shown, and the order of the tabs. Nothing else.

Reading guide
- The layout lives in a few plain values, all read here:
    Src/Sections/index.js     the registry array (display order) and the tabs list (tab order)
    <id>.jsx  meta.tab        which tab a card is on
    <id>.jsx  meta.size       'half' (sits beside another half card) or absent = full width
  Hidden = a section file that is not in the registry array (its import line stays).
- LayoutSession is a "global" part: the preview is a plain dict the open tab applies in memory
  (Src/Lib/agent-context.js useAgentLayout, called by App.jsx). Keep rewrites only those values,
  in place, and records the writes so the dev server doesn't reload.
- tool_arrange takes the final card list of each tab it changes, so a swap or a move is written
  out in full and checked: every card exactly once, nothing silently dropped, known tabs only,
  sizes half/full, a card used by a saved report can't be hidden.
"""
from __future__ import annotations

import copy
import json
import re

from section_agent import CARD_ID_RE, ROOT, SECTIONS, _meta_block, _text
from global_agent import TABS_FILE, GlobalSession, _js_unescape

REPORTS = ROOT / "Reports"
NO_TAB = "page"           # the one group of a dashboard without tabs
IMPORT_RE = re.compile(r"""^import\s+\*\s+as\s+(\w+)\s+from\s+['"]\./([\w-]+)\.jsx['"];?[ \t]*(?=\r?$)""", re.M)   # CRLF or LF files
TAB_ENTRY_RE = re.compile(r"""\{\s*id:\s*(['"])([\w-]+)\1\s*,\s*label:\s*(['"])((?:\\.|(?!\3).)*)\3""")
CHART_KINDS = ("line", "bar", "pie", "scatter", "heatmap", "sankey", "radar", "treemap", "boxplot", "box", "funnel",
               "gauge", "sunburst", "candlestick", "graph", "violin", "histogram", "parallel", "map")


def _block(src: str, start_marker: str) -> tuple[int, int] | None:
    """(start, end) of `start_marker ... ];` (end points at the ']' of the closing '];')."""
    start = src.find(start_marker)
    if start < 0:
        return None
    end = src.find("];", start)
    return (start, end) if end > 0 else None


def chart_kind(src: str) -> str:
    if "KpiTile" in src:
        return "KPI tiles"
    if "<table" in src:
        return "table"
    kinds = [k for k in dict.fromkeys(re.findall(r"""\btype:\s*['"](\w+)['"]""", src)) if k in CHART_KINDS]
    return " + ".join(kinds) or "chart"


def reports_using(card_id: str) -> list[str]:
    """Saved reports that list this card by id (their 'sections' list, or a 'reportTabs' tab's sections)."""
    out = []
    for f in sorted(REPORTS.glob("*.json")) if REPORTS.exists() else []:
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
            listed = list(report.get("sections") or [])
            listed += [c for t in report.get("reportTabs") or [] if isinstance(t, dict) for c in t.get("sections") or []]
            if card_id in listed:
                out.append(f.stem)
        except (OSError, ValueError):
            pass
    return out


def paired(ids: list[str], cards: dict) -> dict[str, bool]:
    """Same rule as App.jsx: 'half' is honored only for two adjacent half cards."""
    out, i = {c: False for c in ids}, 0
    while i < len(ids) - 1:
        if cards[ids[i]]["size"] == "half" and cards[ids[i + 1]]["size"] == "half":
            out[ids[i]] = out[ids[i + 1]] = True
            i += 2
        else:
            i += 1
    return out


class LayoutSession(GlobalSession):
    id = "layout"
    files_label = "Src/Sections/index.js · meta.tab / meta.size"

    def __init__(self, settings: dict, browser_alive):
        self.focus: str | None = None          # card the tab scrolls to after a layout change
        self.changed_files: list = []          # section files the last Keep patched
        super().__init__(settings, browser_alive)

    # ----- read
    def load(self) -> dict:
        src = TABS_FILE.read_text(encoding="utf-8")
        self.import_names = {stem: name for name, stem in IMPORT_RE.findall(src)}
        by_name = {name: stem for stem, name in self.import_names.items()}
        tabs_at = _block(src, "export const tabs = [")
        self.tab_labels = {m.group(2): _js_unescape(m.group(4)) for m in TAB_ENTRY_RE.finditer(src[tabs_at[0]:tabs_at[1]])} if tabs_at else {}
        array_at = _block(src, "export default [")
        if not array_at:
            raise ValueError("Src/Sections/index.js: no `export default [ ... ];` registry array")
        order = [by_name[n] for n in re.findall(r"\b(\w+)\b", src[array_at[0] + len("export default ["):array_at[1]]) if n in by_name]
        self.titles, self.kinds, cards = {}, {}, {}
        for f in sorted(SECTIONS.glob("*.jsx")):
            if ".agent-preview." in f.name or not re.fullmatch(CARD_ID_RE, f.stem):
                continue
            code = f.read_text(encoding="utf-8")
            meta = _meta_block(code)
            if not meta:
                continue
            title = re.search(r"""\btitle:\s*(['"`])(.*?)\1""", meta)
            tab = re.search(r"""\n\s*tab:\s*['"]([\w-]+)['"]""", meta)
            size = re.search(r"""\n\s*size:\s*['"](\w+)['"]""", meta)
            self.titles[f.stem] = title.group(2) if title else f.stem
            self.kinds[f.stem] = chart_kind(code)
            cards[f.stem] = {"tab": tab.group(1) if tab else None, "size": "half" if size and size.group(1) == "half" else "full"}
        order = [c for c in order if c in cards]
        return {"order": order, "cards": cards, "tabs": list(self.tab_labels), "hidden": [c for c in cards if c not in order]}

    @property
    def has_tabs(self) -> bool:
        return bool(self.tab_labels)

    def groups(self, layout: dict) -> dict[str, list[str]]:
        """Tab id -> its visible cards in display order (tab order; NO_TAB without tabs)."""
        if not self.has_tabs:
            return {NO_TAB: list(layout["order"])}
        return {t: [c for c in layout["order"] if layout["cards"][c]["tab"] == t] for t in layout["tabs"]}

    def label(self, tab: str) -> str:
        return self.tab_labels.get(tab, tab) if self.has_tabs else "Page"

    # ----- what the agent and the user read
    def describe(self, layout: dict | None = None, only: set[str] | None = None) -> str:
        layout = layout or self.working
        lines = []
        for tab, ids in self.groups(layout).items():
            if only is not None and tab not in only:
                continue
            pair = paired(ids, layout["cards"])
            head = f"{self.label(tab)} tab ({tab})" if self.has_tabs else "Page"
            if not ids:
                lines.append(f"{head}: (empty: hidden from the tab bar)")
                continue
            lines.append(f"{head}:")
            for i, c in enumerate(ids, 1):
                size = layout["cards"][c]["size"]
                width = "half" if pair[c] else ("full (half, but no half-width neighbor)" if size == "half" else "full")
                lines.append(f"  {i}. {c} \"{self.titles[c]}\" - {self.kinds[c]}, {width}")
        hidden = [c for c in layout["cards"] if c not in layout["order"]]
        if hidden and only is None:
            lines.append("Hidden (not on the page): " + ", ".join(f'{c} "{self.titles[c]}"' for c in hidden))
        return "\n".join(lines)

    def public(self) -> dict | None:
        p = self.preview
        return None if p is None else {"order": p["order"], "cards": {c: p["cards"][c] for c in p["order"]}, "tabs": p["tabs"],
                                       "version": self.version, "focus": self.focus}

    # ----- tool
    async def tool_view(self) -> dict:
        return _text("Current layout (cards by tab, top to bottom; two adjacent half cards share a row):\n" + self.describe())

    async def tool_arrange(self, tabs: list | None, tab_order: list | None, hide: list | None) -> dict:
        w = copy.deepcopy(self.working)
        cards, groups = w["cards"], self.groups(w)
        tabs, hide = tabs or [], list(dict.fromkeys(hide or []))
        if not tabs and not tab_order and not hide:
            return self._fail("Nothing to change: give tabs (final card lists), tab_order or hide.")
        valid_tabs = list(groups)
        new_lists, seen, moved = {}, set(), []
        for g in tabs:
            tab = (g.get("tab") or NO_TAB) if isinstance(g, dict) else None
            if tab not in valid_tabs:
                return self._fail(f"Unknown tab {tab!r}. Tabs: {', '.join(valid_tabs)}. New tabs are a Claude Code job.")
            if tab in new_lists:
                return self._fail(f"Tab {tab} is listed twice.")
            lst = []
            for c in g.get("cards") or []:
                cid, size = (c, None) if isinstance(c, str) else (c.get("id"), c.get("size"))
                if cid not in cards:
                    return self._fail(f"Unknown card {cid!r}. Use view(\"layout\") for the card ids.")
                if cid in seen:
                    return self._fail(f"{cid} is listed more than once; each card goes in exactly one place.")
                if size not in (None, "half", "full"):
                    return self._fail(f"{cid}: size must be \"half\" or \"full\".")
                seen.add(cid)
                if self.has_tabs and cards[cid]["tab"] != tab:
                    moved.append((cid, cards[cid]["tab"], tab))
                    cards[cid]["tab"] = tab
                if size:
                    cards[cid]["size"] = size
                lst.append(cid)
            new_lists[tab] = lst
        for h in hide:
            if h not in cards:
                return self._fail(f"Unknown card {h!r}.")
            if h in seen:
                return self._fail(f"{h} is both placed and hidden.")
            using = reports_using(h)
            if using:
                return self._fail(f"{h} can't be hidden: saved report(s) {', '.join(using)} list it. Changing reports is a Claude Code job.")
        # cards that were on a listed tab must still be somewhere (or hidden on purpose)
        for tab in new_lists:
            lost = [c for c in groups[tab] if c not in seen and c not in hide]
            if lost:
                return self._fail(f"{', '.join(lost)} would disappear from {self.label(tab)}: list every card that stays, "
                                  "put moved cards in their new tab, or pass them in hide.")
        order_tabs = w["tabs"]
        if tab_order:
            if not self.has_tabs or sorted(tab_order) != sorted(w["tabs"]):
                return self._fail(f"tab_order must list every tab exactly once: {', '.join(w['tabs']) or '(this dashboard has no tabs)'}.")
            order_tabs = list(tab_order)
        final = {}
        for tab in (order_tabs if self.has_tabs else [NO_TAB]):
            final[tab] = new_lists.get(tab, [c for c in groups.get(tab, []) if c not in seen and c not in hide])
        order = [c for tab in final for c in final[tab]]
        if not order:
            return self._fail("At least one card must stay on the page.")
        w["order"], w["tabs"], w["hidden"] = order, order_tabs, [c for c in cards if c not in order]
        if w == self.working:
            return _text("That is already the layout; nothing changed.")
        before = self.working
        old_groups = self.groups(before)
        shifted = [c for t, ids in final.items() for i, c in enumerate(ids) if c in old_groups.get(t, []) and old_groups[t].index(c) != i]
        shown = [c for c in order if c not in before["order"]]
        self.focus = (moved[0][0] if moved else None) or (shown[0] if shown else None) or (shifted[0] if shifted else None)
        self._set_preview(w)
        self.failed_edits = 0
        changed = {t for t in final if final[t] != self.groups(before).get(t)} | {t for _, a, b in moved for t in (a, b)}
        notes = [f"{c} moved from {self.label(a)} to {self.label(b)}" for c, a, b in moved]
        notes += [f"{self.label(t)} is now empty, so its tab is hidden" for t in final if not final[t] and groups.get(t)]
        notes += [f"{h} hidden" for h in hide if h in before["order"]]
        notes += [f"{c} shown again" for c in order if c not in before["order"]]
        if order_tabs != before["tabs"]:
            notes.append("tab order: " + ", ".join(self.label(t) for t in order_tabs))
        lone = [c for t in final for c, p in paired(final[t], cards).items() if cards[c]["size"] == "half" and not p and t in changed]
        if lone:
            one = len(lone) == 1
            notes.append(f"{', '.join(lone)} {'is' if one else 'are'} set to half width but {'has' if one else 'have'} no half-width "
                         f"neighbor, so {'it shows' if one else 'they show'} full width (tell the user and offer a fix)")
        return _text("Previewing the new layout.\n" + self.describe(w, changed or None) + ("\nNotes: " + "; ".join(notes) if notes else ""))

    # ----- Keep: rewrite only the values that changed
    def prepare(self, old: dict, new: dict, base: dict) -> dict:
        out = {}
        read = lambda p: base[p] if p in base else p.read_text(encoding="utf-8", newline="")  # noqa: E731
        src = read(TABS_FILE)
        nl = "\r\n" if "\r\n" in src else "\n"
        if new["order"] != old["order"] or new["tabs"] != old["tabs"]:
            missing = [c for c in new["order"] if c not in self.import_names]
            if missing:                                          # shown again but never imported
                last = list(IMPORT_RE.finditer(src))[-1]
                add = "".join(f"{nl}import * as {c} from './{c}.jsx';" for c in missing)
                src = src[:last.end()] + add + src[last.end():]
                self.import_names.update({c: c for c in missing})
            if new["tabs"] != old["tabs"]:
                start, end = _block(src, "export const tabs = [")
                body = src[start:end]
                entries = list(re.finditer(r"""^[ \t]*\{\s*id:\s*(['"])([\w-]+)\1[^\r\n]*\}[ \t]*,?[ \t]*(?=\r?$)""", body, re.M))
                found = {m.group(2): m.group(0).rstrip().rstrip(",") + "," for m in entries}
                if sorted(found) != sorted(new["tabs"]):
                    raise ValueError("Src/Sections/index.js: tabs list isn't one tab per line; reorder tabs in Claude Code")
                head = body[:entries[0].start()]
                tail = body[entries[-1].end():]
                body = head + nl.join(found[t] for t in new["tabs"]) + tail
                src = src[:start] + body + src[end:]
            start, end = _block(src, "export default [")
            rows = []
            for ids in self.groups(new).values():
                names = [self.import_names[c] for c in ids]
                for i in range(0, len(names), 4):
                    rows.append("  " + ", ".join(names[i:i + 4]) + ",")
            src = src[:start] + "export default [" + nl + nl.join(rows) + nl + src[end:]
            out[TABS_FILE] = src
        for c, now in new["cards"].items():
            was = old["cards"][c]
            if now == was:
                continue
            path = SECTIONS / f"{c}.jsx"
            out[path] = patch_meta(read(path), now["tab"] if now["tab"] != was["tab"] else None,
                                   now["size"] if now["size"] != was["size"] else None)
        self.changed_files = [p for p in out if p != TABS_FILE]
        return out


def patch_meta(src: str, tab: str | None, size: str | None) -> str:
    """Set meta.tab and/or meta.size in place (size 'full' removes the line)."""
    start = src.find("export const meta")
    end = src.find("\n};", start)
    if start < 0 or end < 0:
        raise ValueError("meta block not found")
    meta = src[start:end]
    nl = "\r\n" if "\r\n" in src else "\n"
    if tab is not None:
        meta, n = re.subn(r"""(\n[ \t]*tab:[ \t]*)(['"])[\w-]+\2""", lambda m: f"{m.group(1)}{m.group(2)}{tab}{m.group(2)}", meta, count=1)
        if n != 1:
            raise ValueError("meta.tab not found")
    if size is not None:
        line = re.search(r"""\r?\n[ \t]*size:[ \t]*(['"])\w+\1[^\r\n]*""", meta)
        if size == "full" and line:
            meta = meta[:line.start()] + meta[line.end():]
        elif size == "half" and line:
            meta = meta[:line.start()] + re.sub(r"""(['"])\w+\1""", "'half'", line.group(0), count=1) + meta[line.end():]
        elif size == "half":
            anchor = re.search(r"\n([ \t]*)tab:[^\r\n]*", meta) or re.search(r"\n([ \t]*)title:[^\r\n]*", meta)
            if not anchor:
                raise ValueError("meta.title not found")
            meta = meta[:anchor.end()] + f"{nl}{anchor.group(1)}size: 'half'," + meta[anchor.end():]
    return src[:start] + meta + src[end:]
