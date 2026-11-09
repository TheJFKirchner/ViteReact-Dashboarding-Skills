"""The dashboard agent (v2): ONE locked-down Claude session that can make any presentation change.

Reading guide
- What the user clicked is context only: which card is current and what "this" is. Clicking is
  optional: the agent knows every card by title (the layout list is in its prompt). It routes
  each request itself: the current card's chart code or commentary, page labels, custom.css (one
  card or all), theme tokens, a shared component (every place it's used), or the layout.
- A session is the page, or one card. Card changes stay on one card per chat: a request about
  another card's chart or commentary -> open_card, and the panel starts a fresh chat for that
  card (unkept changes are kept or discarded first) and passes the request on. Page-wide changes
  (layout, styles, theme, page text) work from any chat.
- The work is done by "parts" that hold each file's original + preview and run its checks:
    SectionSession   (section_agent.py)    current card's <id>.jsx: guards, render check, controls
    PageSession      (global_agent.py)     page text labels + Src/custom.css
    ThemeSession     (global_agent.py)     Themes/<theme>/tokens.json, theme controls
    ComponentSession (component_agent.py)  one allowlisted shared component at a time
    LayoutSession    (layout_agent.py)     card order, tab, half/full width, hidden; tab order
  plus the current card's commentary (`export const commentary` in <id>.jsx), handled here.
- v2 projects: every number comes from Python (Analysis/<topic>.py, run by the Analysis server). The
  card file holds no data or metric code; metric names and live values for commentary are read from
  the Analysis server (analysis_api.py). The agent never touches Analysis/ or Pipeline/.
- One combined preview across those files; Keep writes all of it, Discard drops all of it.
- Tools (12): view, edit_section, look_at_chart, set_commentary, set_text, edit_styles, set_theme,
  edit_component, arrange, open_card, offer_chart_controls, offer_theme_controls.
"""
from __future__ import annotations

import difflib
import re

from section_agent import (_VERSIONS, MAX_TURNS, ROOT, STATE_DIR, ChatSession, SectionSession, _err, _meta_block,
                           _text, read_commentary, reference_card, write_commentary)
from global_agent import NAMED_PREFIX, STYLES, PageSession, ThemeSession, _get as token_at, format_tokens, named_key, write_kept
from component_agent import EDITABLE, ComponentSession, call_sites, usage_map, usage_words
from layout_agent import LayoutSession

COMMENTARY_JS = ROOT / "Src" / "Lib" / "commentary.js"
MAX_COMMENTARY = 1500
REF = re.compile(r"\{([^{}]*)\}")
# typed numbers go stale when data or filters change: money, percents, decimals, thousands, years.
# Small plain counts ("12-month", "3 categories") are fine.
NUMBER = re.compile(r"\$?\s?\d[\d,]*(?:\.\d+)?\s?%?")
# color expressions a control can bind to (see controls.is_color_value)
COLOR_EXPR = re.compile(r"f\.color\(\d\)|f\.(?:good|bad)\b|f\.colors\.(?:accent|textMuted|text)\b|'#[0-9a-fA-F]{6}'|" + r'"#[0-9a-fA-F]{6}"')
FINE_TUNE = "Use the controls below to fine-tune."
# open-ended color requests get a color picker: "can I change a color?", "what color options are there?",
# "change the line color". A request that names a color ("make it red", "#C62828", "series 3") does not.
COLOR_WORD = re.compile(r"\bcolou?r(s|ed|ing)?\b|\bpalette\b|\bhues?\b", re.I)
NAMED_COLOR = re.compile(
    r"#[0-9a-f]{3,6}\b|\b(?:series|theme colou?r|chart colou?r|colou?r)\s*\d\b|\b(?:red|orange|amber|yellow|gold|lime|green|teal|"
    r"turquoise|cyan|aqua|blue|navy|indigo|purple|violet|lavender|magenta|pink|rose|maroon|brown|tan|beige|gr[ae]y|black|white|silver|"
    r"cream)\b", re.I)


def open_color_request(message: str) -> bool:
    return bool(COLOR_WORD.search(message or "")) and not NAMED_COLOR.search(message or "")


# the part of the chart a color request is about ("the line", "the bars", "the rolling average", "the second
# series"). An open-ended request naming none of these ("can we change the colors?") changes nothing: the panel
# offers a picker for every color in the chart instead, each labeled with the part it colors.
COLOR_TARGET = re.compile(
    r"\b(?:lines?|bars?|columns?|areas?|fills?|borders?|outlines?|backgrounds?|labels?|axis|axes|grid(?:lines?)?|titles?|"
    r"legend|points?|markers?|dots?|bubbles?|slices?|wedges?|nodes?|links?|flows?|bands?|box(?:es)?|whiskers?|tooltips?|text|"
    r"fonts?|headings?|accent|highlight\w*|shad(?:e|ed|ing)|trend\w*|gauge|needle|first|second|third|fourth|last|1st|2nd|3rd|"
    r"comparison|prior|previous|current|target|actual|baseline|benchmark|average|forecast|fitted|favorable|unfavorable|scale)\b",
    re.I)
SERIES_NAME = re.compile(r"""\bname:\s*['"]([^'"]{1,40})['"]""")
PICK_ANY = "Pick a color for any part below."
PICK_CATEGORY = "Pick a color for any category below (a category keeps its color in every chart)."
# a reply that tells the user to use a picker: the picker must be there (the panel adds one if the model didn't)
PROMISE = re.compile(r"\bpick(?:ers?)?\b|\bcolou?r (?:controls?|wheel|selector)\b|\bcontrols? below\b", re.I)


GENERIC_WORDS = {"pmpm", "paid", "total", "value", "values", "rate", "share", "the", "and", "per", "chart", "color", "colors",
                 "month", "months", "12-month", "data"}


def color_target_named(message: str, part_names=()) -> bool:
    """True when the request names a part: a chart element word, or a distinctive word of a series name
    ("rolling" for "Rolling 12-month PMPM")."""
    text = (message or "").lower()
    if COLOR_TARGET.search(text):
        return True
    words = set(re.findall(r"[a-z0-9-]+", text))
    return any(w in words for n in part_names for w in re.findall(r"[a-z0-9-]+", n.lower()) if len(w) > 3 and w not in GENERIC_WORDS)
TOOL_NAMES = ["view", "edit_section", "look_at_chart", "set_commentary", "set_text", "edit_styles", "set_theme",
              "edit_component", "arrange", "open_card", "offer_chart_controls", "offer_theme_controls"]


def _object_keys(src: str, start_marker: str) -> list[str]:
    """Keys at the top level of the object literal that follows start_marker (e.g. 'metrics: {')."""
    start = src.find(start_marker)
    if start < 0:
        return []
    i, n, depth, keys, expect_key = start + len(start_marker), len(src), 1, [], True
    while i < n and depth:
        ch = src[i]
        if ch in "'\"`":                                   # skip string literals
            i += 1
            while i < n and src[i] != ch:
                i += 2 if src[i] == "\\" else 1
            i, expect_key = i + 1, False
            continue
        if src.startswith("//", i):                         # skip line comments
            end = src.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch in "{([":
            depth, expect_key = depth + 1, False
        elif ch in "})]":
            depth -= 1
        elif depth == 1 and ch == ",":
            expect_key = True
        elif depth == 1 and expect_key and not ch.isspace():
            m = re.match(r"(\w+)\s*:", src[i:])
            expect_key = False
            if m:
                keys.append(m.group(1))
                i += m.end()
                continue
        i += 1
    return keys


def commentary_formats() -> list[str]:
    if not COMMENTARY_JS.exists():
        return []
    return _object_keys(COMMENTARY_JS.read_text(encoding="utf-8"), "export const FORMATS = {")


def commentary_problems(text: str, metrics: list[str], formats: list[str]) -> list[str]:
    problems = []
    if len(text) > MAX_COMMENTARY:
        problems.append(f"commentary is limited to {MAX_COMMENTARY} characters")
    if re.search(r"<[a-zA-Z/!]", text):
        problems.append("no HTML: plain sentences, blank lines between paragraphs, '- ' for bullets")
    for m in REF.finditer(text):
        name, _, fmt = m.group(1).partition("|")
        name, fmt = name.strip(), fmt.split(":")[0].strip()
        if name not in metrics:
            problems.append(f"{m.group(0)}: unknown metric {name!r}; available: {', '.join(metrics) or 'none'}")
        elif not fmt:
            problems.append(f"{m.group(0)}: needs a format, like {{{name}|pct:1}}")
        elif fmt not in formats:
            problems.append(f"{m.group(0)}: unknown format {fmt!r}; formats: {', '.join(formats)}")
    typed = [t.strip().rstrip(",") for t in NUMBER.findall(REF.sub(" ", text))
             if any(c in t for c in "$%.,") or len(re.sub(r"\D", "", t)) >= 4]
    if typed:
        problems.append(f"typed numbers {', '.join(dict.fromkeys(typed))}: use live numbers {{metric|format}} instead (typed numbers go stale)")
    return problems[:6]


PROMPT = """You are the editing assistant built into a React dashboard (dev mode). Every change you
make shows live as a preview; the user then chooses Keep or Discard. You never touch real files.

What the user clicked is context only: which card is current and what "this" means. They may
also name any card by its title ("the PMPM chart"); match it against the card list under
Reference. Do whatever they ask, wherever it belongs (the current card, the layout, the whole
page, the theme or a shared component). Never ask them to click, select or switch anything.

{card_block}

Tools
- view(what, name): "card" = current card code, "commentary" = its text and the live numbers it
  may use, "page" = text labels + Src/custom.css, "theme" = theme tokens, "layout" = every card by
  tab with its position and width, "component" = a shared component (name required).
- edit_section(old_text, new_text): the current card's chart code; replace one exact snippet
  (must occur once). Checked: parses, protected parts unchanged, no data loading or arithmetic
  added, renders; fix errors yourself. The chart builds from its `data` prop exactly as given.
- look_at_chart: a picture of the current card's chart.
- set_commentary(text): replace the current card's commentary (the text above its chart).
- set_text(slot, value): one page label (plain text, max 80 characters).
- edit_styles(old_text, new_text): Src/custom.css; old_text must occur once, "" appends a rule.
  Checked: parses; no @import or url(); never style the agent's panel (.agent-*).
- set_theme(changes): existing theme values, each {{"path": "colors.accent", "value": "#FF8800"}}.
- edit_component(name, old_text, new_text): a shared component's code; changes EVERY place it is
  used. Checked: same exports, every prop still accepted (new ones need defaults), allowed
  imports only, no network/storage/window/document/eval/raw HTML, renders.
- arrange(tabs, tab_order, hide): the layout. tabs = the FINAL card list of each tab you change,
  top to bottom, each card {{"id", "size"}} with size "half" or "full" (omit to keep it). A card
  listed under another tab moves there. A swap or move lists both tabs in full. Two adjacent half
  cards share a row; a lone half card shows full width. tab_order = every tab id in the new
  order. hide = card ids to take off the page (listing a hidden card in a tab shows it again).
- open_card(card, request): for a change to a DIFFERENT card's chart, commentary or card-only
  look: opens a fresh chat on that card and passes `request` (what to do there, in the user's
  words) on. Call it, then stop with one short sentence.
- offer_chart_controls(controls): live controls bound to the card code: anchor = a snippet that
  occurs once, value = the exact current value inside it (e.g. f.color(4), '#FFB020', 4, true).
- offer_theme_controls(controls): live controls bound to a theme path (color / slider / switch).

Where a request goes (decide yourself; prefer the narrowest change that does what was asked)
- move, swap, reorder, resize (half / full width), move to another tab, hide or show cards; reorder
  tabs -> arrange (from any chat, about any cards)
- the chart, commentary or card-only look of a card that is NOT the current one -> open_card
  (one card per chat). If a name fits more than one card, ask which, naming the candidates;
  a clear title match needs no question.
- the current card's chart (colors, lines, bars, markers, labels, axes, legend, tooltip, chart
  type, card title) -> edit_section
- the commentary's words -> set_commentary; its look (italic, size, color) -> edit_styles with
  #{sel} .commentary {{ ... }} (this card only) or .commentary (all cards)
- "this card" border, background, spacing, title style -> edit_styles with #{sel} selectors;
  all cards, header, tabs, filters, page -> edit_styles with general selectors
- colors and fonts everywhere, light/dark, glow/grid effects -> set_theme
- dashboard title, source line, tab or filter names -> set_text
- "every KPI tile" / "all commentary" structure or behavior -> edit_component; their look ->
  edit_styles with the component's classes. Only touch a shared component when the user means
  every place it is used.

Commentary rules
- Plain sentences; blank line between paragraphs; "- " starts a bullet. No HTML or markdown styling.
- Numbers only as live references {{metric|format}} or {{metric|format:arg}} from the card's
  metrics (view "commentary" lists them with their current values; the values change with the
  filters). Typed numbers ($683, 6.3%, 2026) are rejected: they go stale. A number no metric
  provides needs a new metric in the card's Analysis function: say it's a job for Claude Code.

Every number on the dashboard is computed in Python (Analysis/, fed by Pipeline/) and reaches a card
as its `data` and `metrics` props. Cards only display: never load data, fetch, or compute (no math
over data, no reduce / filter / sort of values); the checks reject it.
Never (say in one sentence that it's a Claude Code job and why): data, metric calculations, the
Analysis or Pipeline code, new cards or tabs, deleting cards (hiding is fine), the card's meta
other than its title (tab and width go through arrange), locked shared parts ({locked}).

Style rules
- Theme colors, not hex: in chart code through `const f = fx()` (see Reference), in CSS through
  var(--accent) var(--text) var(--text-muted) var(--good) var(--bad) var(--border)
  var(--series-0..5) var(--surface) var(--background). Exact hex only when the user gives one.
- Keep edits as small as the request. Don't reformat or tidy unrelated code or rules.
- Never hide or remove content unless asked for exactly that. Never move a card the user didn't
  mention, except a half-width partner they agree to.
- Changes accumulate; Discard returns everything to the original.
- Colors without a named part ("can we change the colors?", "the chart / data colors", "what color
  options are there?"): they mean the data colors; change nothing; say in one sentence they can pick
  a color for each one below (the panel attaches a picker per data color, e.g. per category). Don't
  guess a part.
- Charts colored by category use f.colorOf(name, i): a category's color is the theme value
  colors.named.<name> (e.g. colors.named.Inpatient), shared by every chart. "Make Inpatient green" ->
  set_theme colors.named.Inpatient (it may be new). Never hardcode a category color in the card.
- A named part but no color ("change the line color", "make the bars warmer"): set a sensible theme
  color for that part, then attach a color control bound to it. A named color: just apply it.

Reference
Cards (by tab, top to bottom):
{layout}
{card_reference}
Page text slots:
{slots}
Page parts and selectors:
  dashboard title .report-header h1 (with the "glow" effect it has a gradient text fill; to
  recolor: background: none; -webkit-text-fill-color: currentColor; color: ...) · source line
  .report-header .meta-line · tabs .tab-bar button, active .tab-bar button.on · filters
  .filter-bar · cards .card · card titles .card-head h2 · id badge .section-id · commentary
  .commentary · KPI tiles .kpi .kpi-label .kpi-value .kpi-change · tables table.data th / td ·
  whole page body .page. Effect rules use :root[data-effects~="glow"] prefixes.
Theme ({theme}) tokens: colors.text/textMuted, background (cards) / surface (page), border,
accent, good/bad, warning, series (chart colors, 0 = main, 2 = prior period), sequential,
diverging; font.family/heading/mono, font.size (10-20); effects.glow/gradients/grid/animation.
Current tokens:
{tokens}
Shared components you may change for every place they are used:
{components}

Built-in styles: Src/styles.css (in @layer base, so custom.css always wins). It is not shown here: before
writing CSS that overrides or matches a built-in rule (beyond the selectors above), call view("styles") to read it.

Reply with one plain sentence describing what changed (name the theme color used). After a layout
change also mention any side effect the tool noted (a card that moved tab, a lone half card), in
plain words. If you attached controls, end with: Use the controls below to fine-tune."""


class DashboardSession(ChatSession):
    def __init__(self, target: str, settings: dict, browser_alive):
        super().__init__(settings, browser_alive)
        self.id = target
        self.card = None if target in ("page", "theme") else target
        self.section = SectionSession(self.card, settings, browser_alive) if self.card else None
        self.page = PageSession(settings, browser_alive)
        self.theme = ThemeSession(settings, browser_alive)
        self.component: ComponentSession | None = None
        self.layout = LayoutSession(settings, browser_alive)
        self.switch_to: dict | None = None         # open_card: {card, request} for the panel
        self.color_changes: dict = {"chart": [], "theme": []}   # this request's color edits (auto controls)
        self.card_owner: dict[int, tuple] = {}     # our control-card id -> (part, part's card id)
        self.md_original = read_commentary(self.section.original) if self.section else ""
        self.md_preview: str | None = None
        self.md_version = next(_VERSIONS)
        meta = _meta_block(self.section.original) if self.section else ""
        self.title = (re.search(r"""title:\s*(['"`])(.*?)\1""", meta) or [None, None, self.card])[2] if self.card else None
        self.library = (re.search(r"library:\s*['\"](\w+)['\"]", meta) or [None, "echarts"])[1]
        # v2: metric names + live values come from the Analysis server (loaded at the first request)
        self.metric_values: dict | None = None
        self.metrics_error: str | None = None
        self.card_ref: str | None = None            # reference card text (theme + the card's data shape)

    @property
    def metrics(self) -> list[str]:
        return list(self.metric_values or {})

    async def load_card_info(self, refresh: bool = False):
        """Metric values and the data-shape reference for the current card, from the Analysis server."""
        if not self.card or (self.metric_values is not None and self.card_ref is not None and not refresh):
            return
        import asyncio
        import analysis_api as api
        try:
            result = await asyncio.to_thread(api.card, self.card)
            self.metric_values = result.get("metrics") or {}
            keys = (result.get("data") or {}).get("color_keys") if isinstance(result.get("data"), dict) else None
            # categories the card colors by name (f.colorOf): one picker each, theme colors.named.<key>
            self.color_keys = [str(k) for k in keys if isinstance(k, str) and named_key(NAMED_PREFIX + k)] if isinstance(keys, list) else []
            self.metrics_error = None
        except api.AnalysisUnavailable as e:
            self.metric_values, self.metrics_error, self.color_keys = None, str(e), []
        self.card_ref = await asyncio.to_thread(reference_card, self.section.original, self.card)

    def metrics_text(self) -> str:
        import analysis_api as api
        if self.metric_values is None:
            return f"unavailable ({self.metrics_error or 'not loaded'})"
        return ", ".join(f"{k} (now {api.show_value(v)})" for k, v in self.metric_values.items()) or "none"

    # ----- combined state
    @property
    def parts(self):
        return [p for p in (self.section, self.page, self.theme, self.component, self.layout) if p is not None]

    @property
    def version(self) -> int:
        return max([self.md_version] + [p.version for p in self.parts])

    @property
    def md_dirty(self) -> bool:
        return self.md_preview is not None and self.md_preview != self.md_original

    @property
    def dirty(self) -> bool:
        return self.md_dirty or any(p.dirty for p in self.parts)

    def pending(self) -> list[str]:
        out = []
        if self.section and self.section.dirty:
            out.append(f"{self.title} chart")
        if self.md_dirty:
            out.append(f"{self.title} commentary")
        if self.page.dirty:
            if self.page.preview["text"] != self.page.original["text"]:
                out.append("page text")
            if self.page.preview["css"] != self.page.original["css"]:
                out.append("styles")
        if self.theme.dirty:
            out.append("theme")
        if self.component and self.component.dirty:
            out.append(f"{self.component.name} (every place it's used)")
        if self.layout.dirty:
            out.append("layout")
        return out

    def state(self) -> dict:
        preview = {**(self.page.preview or {}), **(self.theme.preview or {})}
        comp = self.component
        return {
            "section_id": self.id, "kind": "card" if self.card else "page", "card_id": self.card,
            "file": f"{self.card}.jsx" if self.card else "page", "version": self.version,
            "has_preview": self.md_preview is not None or any(getattr(p, "preview", None) is not None for p in (self.section, self.page, self.theme, self.layout) if p)
                           or bool(comp and comp.code is not None),
            "dirty": self.dirty, "pending": self.pending(), "live_card_id": self.live_card,
            "preview": preview or None,
            "section": {"version": self.section.version, "has_preview": self.section.preview is not None} if self.section else None,
            "commentary": self.md_preview,
            "layout": self.layout.public(),
            "component": ({"name": comp.name, "file": comp.rel, "used_by": comp.info["used_by"], "version": comp.version,
                           "has_preview": comp.code is not None, "dirty": comp.dirty} if comp else None),
        }

    # ----- browser reports and control tweaks
    def receive_report(self, body: dict):
        part = self.component if body.get("part") == "component" else self.section
        if part is not None:
            part.receive_render(int(body.get("version", -1)), body.get("ok"), body.get("error"), body.get("image"))

    async def apply_control(self, card_id: int, control_id: str, raw, final: bool) -> dict:
        owner = self.card_owner.get(card_id)
        if card_id != self.live_card or owner is None:
            return {"error": "These controls are out of date; ask the agent again for new ones."}
        part, sub_id = owner
        result = await part.apply_control(sub_id, control_id, raw, final)
        for label, value in part.control_notes.items():
            self.control_notes[label] = value
        part.control_notes.clear()
        return result

    def _sync_live(self):
        """A newer edit in the part that owns the live control card makes that card stale."""
        owner = self.card_owner.get(self.live_card) if self.live_card else None
        if owner and owner[0].live_card != owner[1]:
            self.live_card = None

    # ----- user actions
    def keep(self):
        if self.component and self.component.dirty:
            self.component.keep()
        # every file's final text first (card code + commentary + layout meta; tab labels + tab order), then one write each
        writes = {}
        card = self._card_text()
        if card is not None:
            writes[self.section.file] = card
        for part in (self.page, self.theme, self.layout):
            if part.dirty:
                writes.update(part.prepare(part.original, part.preview, writes))
        for path, text in writes.items():
            write_kept(path, text)
        if self.section and self.section.file in writes:
            self._commit_card(writes[self.section.file])
        if self.md_dirty:
            self.md_original = self.md_preview
        for part in (self.page, self.theme, self.layout):
            if part.preview is not None:
                part.commit()
        self.notes.append("The user kept your changes; they are now the original.")

    def _card_text(self) -> str | None:
        """Final text of the current card's file if Keep changes it (chart code and/or commentary)."""
        if not self.section:
            return None
        text = self.section.preview if self.section.dirty else None
        if self.md_dirty:
            base = text if text is not None else self.section.file.read_text(encoding="utf-8", newline="")
            text = write_commentary(base, self.md_preview)
        return text

    def _commit_card(self, text: str):
        """Keep wrote this card's file: that text is the new original (the preview copy follows it)."""
        self.section.original = text
        if self.section.preview is not None:
            if self.section.preview != text:
                self.section._set_preview(text)
            self.section.last_good = text

    def discard(self):
        for p in self.parts:
            p.discard()
        if self.md_preview is not None:
            self.md_preview = None
            self.md_version = next(_VERSIONS)
        self.live_card = None
        self.notes.append("The user discarded your changes; everything is back to the original.")

    async def close(self):
        for p in self.parts:
            await p.close()
        await self.close_client()

    async def ask(self, message: str, clicked: dict | None) -> dict:
        for p in self.parts:
            p.failed_edits = 0
        self.switch_to = None
        self.color_changes = {"chart": [], "theme": []}
        self.note_request(message, clicked)
        await self.load_card_info(refresh=self.metric_values is None)   # retry if the Analysis server was down
        answer = await super().ask(message, clicked)
        return {**answer, "switch_to": self.switch_to}

    # ----- tools
    def _no_card(self) -> dict:
        if self.switch_to:
            return _err(f"A fresh chat is opening on {self.switch_to['card']}; stop here.")
        return _err("No card is current, so card tools are unavailable here. For a specific card's chart or commentary use open_card; "
                    "page-wide changes (layout, styles, theme, page text, shared components) work here.")

    def _wrap(self, result: dict) -> dict:
        self._sync_live()
        return result

    async def tool_view(self, what: str, name: str | None = None) -> dict:
        if what == "card":
            return self._no_card() if not self.section else await self.section.tool_view()
        if what == "commentary":
            if not self.section:
                return self._no_card()
            return _text(f"Commentary (export const commentary in {self.card}.jsx):\n{self.md_preview if self.md_preview is not None else self.md_original or '(none yet)'}\n\n"
                         f"Live numbers (metrics from the card's Analysis function, values at no filter): {self.metrics_text()}\n"
                         f"Formats: {', '.join(commentary_formats())}")
        if what == "page":
            return await self.page.tool_view()
        if what == "styles":
            css = STYLES.read_text(encoding="utf-8") if STYLES.exists() else "(no styles.css)"
            return _text("Src/styles.css (built-in, read-only; override in custom.css, don't repeat rules):\n```css\n" + css + "\n```")
        if what == "theme":
            return await self.theme.tool_view()
        if what == "layout":
            return await self.layout.tool_view()
        if what == "component":
            if name not in EDITABLE:
                return _err(f"{name!r} is not an editable component. Editable: {', '.join(EDITABLE)}.")
            if self.component and self.component.name == name:
                return await self.component.tool_view()
            code = (ROOT / EDITABLE[name][0]).read_text(encoding="utf-8")
            return _text(f"{EDITABLE[name][0]}:\n```jsx\n{code}\n```\n\nWhere it is used:\n" + "\n".join(call_sites(name) or ["  (none)"]))
        return _err('what must be "card", "commentary", "page", "styles", "theme", "layout" or "component".')

    def _unspecified_color_refusal(self) -> dict:
        return _err("The user didn't say which part of the chart to recolor, so change no color. Reply in one short "
                    "sentence that they can pick a color for each part of the chart below (the panel attaches a picker "
                    "for every color in this chart), or ask which part they mean. Don't attach controls yourself.")

    async def tool_edit(self, old: str, new: str) -> dict:
        if not self.section or self.switch_to:
            return self._no_card()
        if getattr(self, "color_unspecified", False) and COLOR_EXPR.findall(old) != COLOR_EXPR.findall(new):
            return self._unspecified_color_refusal()
        before = self.section.working
        result = self._wrap(await self.section.tool_edit(old, new))
        if not result.get("is_error"):
            self._note_chart_colors(before, self.section.working)
        return result

    # ----- automatic color picker for open-ended color requests (the model may forget to attach one)
    def note_request(self, text: str, clicked: dict | None = None):
        # scripted test messages (FAKE: [...]) hold code, not a request: the test sets it with a "request" step
        self.open_color = False if text.startswith("FAKE:") else open_color_request(text)
        parts = [*SERIES_NAME.findall(self.section.working), *(lab for *_, lab in self._chart_color_slots(12))] if self.section else []
        # no part named and no chart series clicked: offer every color instead of guessing one
        self.clicked_series = (clicked or {}).get("series") or None
        self.color_unspecified = self.open_color and not self.clicked_series and not color_target_named(text, parts)

    # option keys -> the words a person would use for what they color
    PART_WORDS = {"axisLabel": "Axis labels", "splitLine": "Grid lines", "axisLine": "Axis line", "axisTick": "Axis ticks",
                  "title": "Title text", "detail": "Value text", "label": "Labels", "lineStyle": "Line", "areaStyle": "Area",
                  "itemStyle": "Fill", "markLine": "Reference line", "markArea": "Highlight area", "markPoint": "Marker",
                  "visualMap": "Color scale", "emphasis": "Hover", "tooltip": "Tooltip", "legend": "Legend", "style": "Note text"}

    @classmethod
    def _color_part(cls, code: str, pos: int) -> tuple[str | None, int]:
        """(words for what the color expression at `pos` colors, priority): 0 = a data series (the user's
        "series 1, series 2"), 1 = favorable/unfavorable, highlights and scales, 2 = text, axes and grid."""
        line_start = code.rfind("\n", 0, pos) + 1
        upto = code[line_start:pos]
        names = list(SERIES_NAME.finditer(code))
        # innermost open option key on the line ("axisLabel: { color: ..." -> axisLabel)
        key = None
        for k in re.finditer(r"(\w+)\s*:\s*\{|style=\{\{", upto):
            rest = upto[k.end():]
            if rest.count("{") >= rest.count("}"):
                key = k.group(1) or "style"
        before = code[max(0, pos - 400):pos]
        for mark in ("markArea", "markLine", "markPoint", "visualMap"):
            k = before.rfind(mark)
            if k >= 0 and before.count("{", k) > before.count("}", k):
                sub = "label" if key == "label" else None
                return (f"{cls.PART_WORDS[mark]} {sub} color" if sub else f"{cls.PART_WORDS[mark]} color"), 1
        if key in ("axisLabel", "splitLine", "axisLine", "axisTick", "title", "detail", "tooltip", "legend", "style"):
            return f"{cls.PART_WORDS[key]} color", 2
        value = COLOR_EXPR.match(code, pos)
        expr = value.group(0) if value else ""
        # assigned to a variable (const [c0, c1] = [f.color(0), ...] / const c0 = ...): the series that uses it
        var = None
        line = code[line_start:code.find("\n", pos) if code.find("\n", pos) >= 0 else len(code)]
        m = re.search(r"const\s*\[([^\]]+)\]\s*=\s*\[([^\]]+)\]", line)
        if m:
            idents = [v.strip() for v in m.group(1).split(",")]
            exprs = list(COLOR_EXPR.finditer(m.group(2)))
            idx = next((i for i, e in enumerate(exprs) if line_start + m.start(2) + e.start() == pos), None)
            var = idents[idx] if idx is not None and idx < len(idents) else None
        else:
            m = re.search(r"const\s+(\w+)\s*=\s*$", upto)
            var = m.group(1) if m else None
        if var:
            for i, n in enumerate(names):
                seg = code[n.start():names[i + 1].start() if i + 1 < len(names) else min(len(code), n.start() + 600)]
                if re.search(rf"\b{re.escape(var)}\b", seg):
                    return f"{n.group(1)} color", 0
        # a series label written on the same line: ['Prior 12 months', values, f.color(5)] / bar('Prior 12 months', ..., f.color(2))
        lit = [s for s in re.findall(r"""['"]([^'"]{2,40})['"]""", upto) if re.search(r"[A-Z]|\s", s) and not s.startswith("#")]
        if lit and key is None:
            return f"{lit[-1]} color", 0
        # inside a named series object
        owner = next((n for n in reversed(names) if n.start() < pos), None)
        if owner and code[owner.start():pos].count("{") >= code[owner.start():pos].count("}") and key not in ("label",):
            sub = cls.PART_WORDS.get(key, "").lower() if key in ("lineStyle", "areaStyle", "itemStyle") else ""
            return " ".join(x for x in (owner.group(1), sub, "color") if x), 0
        if expr in ("f.good", "f.bad"):
            return ("Favorable color" if expr == "f.good" else "Unfavorable color"), 0
        if key in cls.PART_WORDS:
            return f"{cls.PART_WORDS[key]} color", 2 if key == "label" else 1
        return None, 2 if expr.startswith("f.colors.") else 1

    @classmethod
    def _color_label(cls, code: str, pos: int) -> str | None:
        """Which part of the chart the color expression at `pos` colors, in words ("Monthly PMPM color")."""
        return cls._color_part(code, pos)[0]

    def _chart_color_slots(self, limit: int = 6) -> list[tuple]:
        """The colors the chart sets, as (anchor, value, label) bindings labeled by the part they color: data series
        first, then highlights and scales, then text/axes/grid; empty when the chart sets no series color itself
        (its series then use the theme's chart colors, offered as theme controls instead)."""
        code = self.section.working
        slots, spans = [], []
        matches = list(COLOR_EXPR.finditer(code))
        for i, m in enumerate(matches):
            value = m.group(0)
            line_start = code.rfind("\n", 0, m.start()) + 1
            line_end = code.find("\n", m.end())
            line_stop = line_end if line_end >= 0 else len(code)
            # never reach into the neighboring color values (their own snippets need that text)
            line_start = max(line_start, matches[i - 1].end() if i else 0)
            line_stop = min(line_stop, matches[i + 1].start() if i + 1 < len(matches) else len(code))
            # the smallest unique snippet around the value that doesn't overlap another binding's snippet
            found = None
            for size in (0, 4, 8, 12, 24, 48, 96):
                for left, right in ((0, size), (size, 0), (size, size)):
                    start, stop = max(line_start, m.start() - left), min(line_stop, m.end() + right)
                    anchor = code[start:stop]
                    if (anchor.strip() == anchor and code.count(anchor) == 1 and anchor.count(value) == 1
                            and all(stop <= a or start >= b for a, b in spans)):
                        found = (anchor, start, stop)
                        break
                if found:
                    break
            if found:
                label, rank = self._color_part(code, m.start())
                slots.append((found[0], value, label or "", rank))
                spans.append(found[1:])
        if not any(rank <= 1 for *_, rank in slots):           # only text/axis colors: the series use theme colors
            return []
        slots.sort(key=lambda s: s[3])                          # stable: series in code order first
        out = [(a, v, lab or f"Color {i + 1}") for i, (a, v, lab, _) in enumerate(slots[:limit])]
        labels = [lab for _, _, lab in out]
        return [(a, v, lab if labels.count(lab) == 1 else f"{lab} {labels[:i + 1].count(lab)}") for i, (a, v, lab) in enumerate(out)]
    def _note_chart_colors(self, before: str, after: str):
        """Color expressions on lines this edit added or changed, as (anchor, value) a control can bind to."""
        old_lines = before.splitlines()
        new_lines = after.splitlines()
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            for k, line in enumerate(new_lines[j1:j2]):
                # a replaced line: only the colors that actually changed (same position, different value)
                was = [m.group(0) for m in COLOR_EXPR.finditer(old_lines[i1 + k])] if tag == "replace" and i1 + k < i2 else []
                for n, m in enumerate(COLOR_EXPR.finditer(line)):
                    value = m.group(0)
                    if n < len(was) and was[n] == value:
                        continue
                    for left in (12, 24, 48, 96, len(line)):
                        anchor = line[max(0, m.start() - left):m.end() + 1].strip() or value
                        if after.count(anchor) == 1 and anchor.count(value) == 1:
                            label = self._color_label(after, after.index(anchor) + anchor.index(value)) or "Color"
                            label = label[0].upper() + label[1:]
                            if all(a != anchor for a, _, _ in self.color_changes["chart"]):
                                self.color_changes["chart"].append((anchor, value, label))
                            break

    def _current_chart_colors(self) -> list[tuple]:
        """No color was changed (e.g. "what color options do I have?"): bind to the colors the chart uses now."""
        return self._chart_color_slots()

    async def _valid_controls(self, part, controls: list) -> list:
        """The controls whose bindings the checks accept (each tried alone), in order."""
        keep = []
        for c in controls:
            ok = not (await part.tool_offer([c])).get("is_error")
            part.pending_card = None
            if ok:
                keep.append(c)
        return keep

    async def _after_turn(self, reply: str) -> str:
        # a picker goes with every open-ended color request, and with any reply that promises one
        promised = bool(PROMISE.search(reply or "")) and bool(COLOR_WORD.search(reply or ""))
        if not (getattr(self, "open_color", False) or promised) or self.pending_card is not None or self.switch_to:
            return reply                                         # named color, agent's own controls, or handed off
        offered = False
        unspecified = getattr(self, "color_unspecified", False) or (promised and not self.color_changes["chart"] and not self.color_changes["theme"])
        chart = [c for c in self.color_changes["chart"] if self.section and c[0] in self.section.working][:3]
        nothing_changed = not chart and not self.color_changes["theme"]
        keys = getattr(self, "color_keys", None) or []
        if self.section and keys and "f.colorOf(" in self.section.working and (unspecified or nothing_changed):
            # a chart colored by category ("the data colors"): one picker per category, Inpatient, Outpatient, ...
            tokens = self.theme.working["tokens"]
            series = tokens["colors"]["series"]
            clicked = getattr(self, "clicked_series", None)
            order = sorted(range(len(keys)), key=lambda i: keys[i] != clicked) if clicked in keys else range(len(keys))
            controls = []
            for i in list(order)[:12]:
                try:
                    current = token_at(tokens, NAMED_PREFIX + keys[i])
                except KeyError:
                    current = series[i % len(series)]
                controls.append({"kind": "color", "label": keys[i], "path": NAMED_PREFIX + keys[i], "value": current})
            offered = not (await self._offer(self.theme, controls)).get("is_error")
            if offered:
                hint = PICK_CATEGORY
                return reply if hint in reply else (reply.rstrip() + " " + hint).strip()
        if self.section and (unspecified or nothing_changed):
            chart = self._chart_color_slots()                    # no part named: every color, nothing changed
            clicked = getattr(self, "clicked_series", None)
            if clicked:                                          # the clicked series first
                chart.sort(key=lambda c: not c[2].lower().startswith(clicked.lower()))
        if chart:
            labels = [c[2] for c in chart]
            controls = [{"kind": "color", "label": (lab if labels.count(lab) == 1 or len(chart) == 1 else f"{lab} {i + 1}"), "anchor": a, "value": v}
                        for i, (a, v, lab) in enumerate(chart)]
            offered = not (await self._offer(self.section, controls)).get("is_error")
            if not offered:                                      # drop only the bindings the checks refuse
                controls = await self._valid_controls(self.section, controls)
                offered = bool(controls) and not (await self._offer(self.section, controls)).get("is_error")
        # theme pickers whenever no chart picker could be shown: a theme color change, the page, or a card whose
        # series take the theme's chart colors
        if not offered:
            every = ["colors.accent", *[f"colors.series.{i}" for i in range(6)]]
            every = every[1:] if self.section else every[:6]     # a control card holds up to 6
            paths = list(dict.fromkeys(self.color_changes["theme"]))[:6] if self.color_changes["theme"] and not unspecified else every
            shared = " (theme: all charts)" if self.section else ""
            controls = [{"kind": "color", "label": self._theme_label(p) + shared, "path": p} for p in paths]
            offered = not (await self._offer(self.theme, controls)).get("is_error")
        hint = PICK_ANY if unspecified else FINE_TUNE
        if offered and hint not in reply:
            reply = (reply.rstrip() + " " + hint).strip()
        return reply

    @staticmethod
    def _theme_label(path: str) -> str:
        if named_key(path):
            return named_key(path)                               # a category color: its name ("Inpatient")
        parts = path.split(".")[1:]
        if parts[:1] == ["series"] and len(parts) == 2:
            return f"Chart color {int(parts[1]) + 1}"
        return re.sub(r"([a-z])([A-Z])", r"\1 \2", " ".join(parts)).capitalize()

    async def tool_look(self) -> dict:
        return self._no_card() if not self.section else await self.section.tool_look()

    async def tool_commentary(self, text: str) -> dict:
        if not self.section or self.switch_to:
            return self._no_card()
        text = (text or "").strip()
        if not text:
            return _err("Commentary can't be empty.")
        if self.metric_values is None:
            await self.load_card_info(refresh=True)
        if self.metric_values is None:
            return _err(f"Can't check the live numbers right now: {self.metrics_error}. Tell the user the Analysis server must be running "
                        "(npm run dev:agent starts it); nothing was changed.")
        problems = commentary_problems(text, self.metrics, commentary_formats())
        if problems:
            return _err("Rejected:\n" + "\n".join(problems))
        self.md_preview = text + "\n"
        self.md_version = next(_VERSIONS)
        return _text("Previewing the new commentary in the card.")

    async def tool_set_text(self, slot: str, value: str) -> dict:
        return await self.page.tool_set_text(slot, value)

    async def tool_edit_styles(self, old: str, new: str) -> dict:
        return await self.page.tool_edit_styles(old, new)

    async def tool_set_theme(self, changes: list) -> dict:
        if getattr(self, "color_unspecified", False) and any(str(c.get("path", "")).startswith("colors.") for c in changes if isinstance(c, dict)):
            return self._unspecified_color_refusal()
        result = self._wrap(await self.theme.tool_set_theme(changes))
        if not result.get("is_error"):
            self.color_changes["theme"] += [c["path"] for c in changes if isinstance(c, dict) and str(c.get("path", "")).startswith("colors.")
                                            and isinstance(c.get("value"), str) and c["value"].startswith("#")]
        return result

    async def tool_edit_component(self, name: str, old: str, new: str) -> dict:
        if name not in EDITABLE:
            return _err(f"{name!r} can't be changed here. Editable shared components: {', '.join(EDITABLE)}; everything else is locked (a Claude Code job).")
        if self.component is None or self.component.name != name:
            if self.component is not None and self.component.dirty:
                return _err(f"There is an unkept {self.component.name} change; one shared component per preview. Tell the user to Keep or Discard first.")
            if self.component is not None:
                await self.component.close()
            self.component = ComponentSession(f"component:{name}", self.settings, self.browser_alive)
        return await self.component.tool_edit(old, new)

    async def tool_arrange(self, tabs: list | None = None, tab_order: list | None = None, hide: list | None = None) -> dict:
        return await self.layout.tool_arrange(tabs, tab_order, hide)

    async def tool_open_card(self, card: str, request: str) -> dict:
        titles = self.layout.titles
        if card not in titles:
            return _err(f"Unknown card {card!r}. Cards: " + ", ".join(f'{c} "{t}"' for c, t in titles.items()))
        if card == self.card:
            return _err(f"{card} is already the current card: use the card tools directly.")
        if card not in self.layout.working["order"]:
            return _err(f"{card} is hidden. Show it first with arrange (it needs a place on a tab).")
        request = (request or "").strip()
        if not request:
            return _err("request must say what to do on that card.")
        self.switch_to = {"card": card, "request": request}
        return _text(f"The panel will open a fresh chat on {titles[card]} and pass the request on. Stop now; reply with one short sentence.")

    async def _offer(self, part, controls: list) -> dict:
        result = await part.tool_offer(controls)
        if not result.get("is_error") and part.pending_card:
            self.card_seq += 1
            self.card_owner[self.card_seq] = (part, part.pending_card["id"])
            self.pending_card = {**part.pending_card, "id": self.card_seq}
            self.live_card = self.card_seq
            part.pending_card = None
        return result

    async def tool_offer_chart(self, controls: list) -> dict:
        return self._no_card() if not self.section or self.switch_to else await self._offer(self.section, controls)

    async def tool_offer_theme(self, controls: list) -> dict:
        return await self._offer(self.theme, controls)

    async def tool_offer(self, controls: list) -> dict:     # scripted test model: route by binding
        theme = bool(controls) and all("path" in c for c in controls)
        return await (self.tool_offer_theme(controls) if theme else self.tool_offer_chart(controls))

    # ----- one user request
    def _user_text(self, message: str, clicked: dict | None) -> str:
        click = self._click_text(clicked, "nothing specific")
        text = f"Request: {message}\n{click}{self._take_notes()}"
        if self.section:
            text += (f"\n\nCurrent card code ({self.card}.jsx):\n```jsx\n{self.section.working}\n```\n"
                     f"Current commentary ({self.card}.jsx, export const commentary):\n{self.md_preview if self.md_preview is not None else self.md_original or '(none yet)'}")
        return text

    def _first_image(self) -> str | None:
        return self.section._first_image() if self.section else None

    def system_prompt(self) -> str:
        info = usage_map()
        components = "\n".join(f"  {name} ({', '.join(classes)}): used by {usage_words(info[file]) if file in info else 'nothing yet'}"
                               for name, (file, classes) in EDITABLE.items())
        locked = ", ".join(v["name"] for v in info.values() if not v["editable"]) + ", Src/Lib/, App.jsx, Analysis/, Pipeline/"
        if self.card:
            card_block = (f"Current card: {self.title} ({self.card}) - file {self.card}.jsx, chart library {self.library}. "
                          f"Its code and commentary come with each message. Card metrics for commentary: {self.metrics_text()}.")
            card_reference = self.card_ref or reference_card(self.section.original, self.card)
        else:
            card_block = ("No card is current (the user is on the page). Page-wide changes and the layout work here; for a "
                          "specific card's chart, commentary or card-only look, call open_card.")
            card_reference = "(no card selected)"
        slots = "\n".join(f"  {k}: {v}" for k, v in self.page.original["text"].items())
        return PROMPT.format(card_block=card_block, sel=self.card or "<card-id>", locked=locked, layout=self.layout.describe(),
                             card_reference=card_reference, slots=slots,
                             theme=self.theme.theme, tokens=format_tokens(self.theme.original["tokens"]), components=components,
                             )

    def options(self):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool
        import controls as ctl
        s = self
        edit = {"type": "object", "additionalProperties": False, "required": ["old_text", "new_text"],
                "properties": {"old_text": {"type": "string"}, "new_text": {"type": "string"}}}

        @tool("view", "Show current code or values: card, commentary, page (text + custom.css), styles (built-in styles.css, "
              "read-only), theme, layout, or a shared component (with name).",
              {"type": "object", "additionalProperties": False, "required": ["what"],
               "properties": {"what": {"type": "string", "enum": ["card", "commentary", "page", "styles", "theme", "layout", "component"]},
                              "name": {"type": "string", "enum": list(EDITABLE)}}})
        async def view(a):
            return await s.tool_view(a["what"], a.get("name"))

        @tool("edit_section", "Replace one exact snippet in the current card's chart code (must occur once).", edit)
        async def edit_section(a):
            return await s.tool_edit(a["old_text"], a["new_text"])

        @tool("look_at_chart", "A picture of the current card's chart as rendered.", {})
        async def look_at_chart(_a):
            return await s.tool_look()

        @tool("set_commentary", "Replace the current card's commentary text (plain sentences, live numbers as {metric|format}).",
              {"type": "object", "additionalProperties": False, "required": ["text"], "properties": {"text": {"type": "string"}}})
        async def set_commentary(a):
            return await s.tool_commentary(a["text"])

        @tool("set_text", "Change one page label: dashboard title, source line, a tab or a filter label.",
              {"type": "object", "additionalProperties": False, "required": ["slot", "value"],
               "properties": {"slot": {"type": "string", "enum": list(self.page.original["text"])}, "value": {"type": "string"}}})
        async def set_text(a):
            return await s.tool_set_text(a["slot"], a["value"])

        @tool("edit_styles", 'Edit Src/custom.css: replace old_text (must occur once) with new_text; old_text "" appends.', edit)
        async def edit_styles(a):
            return await s.tool_edit_styles(a["old_text"], a["new_text"])

        @tool("set_theme", "Change existing theme values by path, e.g. colors.accent or colors.series.2.",
              {"type": "object", "additionalProperties": False, "required": ["changes"],
               "properties": {"changes": {"type": "array", "minItems": 1, "items": {
                   "type": "object", "additionalProperties": False, "required": ["path", "value"],
                   "properties": {"path": {"type": "string"}, "value": {"type": ["string", "number", "boolean"]}}}}}})
        async def set_theme(a):
            return await s.tool_set_theme(a["changes"])

        @tool("edit_component", "Replace one exact snippet in a shared component's code; changes every place it is used.",
              {"type": "object", "additionalProperties": False, "required": ["name", "old_text", "new_text"],
               "properties": {"name": {"type": "string", "enum": list(EDITABLE)}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}})
        async def edit_component(a):
            return await s.tool_edit_component(a["name"], a["old_text"], a["new_text"])

        cards = list(self.layout.titles)
        tab_ids = list(self.layout.groups(self.layout.original))

        @tool("arrange", "Change the layout: the final card list of each tab you change (top to bottom), tab order, cards to hide.",
              {"type": "object", "additionalProperties": False,
               "properties": {
                   "tabs": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["tab", "cards"],
                       "properties": {"tab": {"type": "string", "enum": tab_ids},
                                      "cards": {"type": "array", "items": {
                                          "type": "object", "additionalProperties": False, "required": ["id"],
                                          "properties": {"id": {"type": "string", "enum": cards},
                                                         "size": {"type": "string", "enum": ["half", "full"]}}}}}}},
                   "tab_order": {"type": "array", "items": {"type": "string", "enum": tab_ids}},
                   "hide": {"type": "array", "items": {"type": "string", "enum": cards}}}})
        async def arrange(a):
            return await s.tool_arrange(a.get("tabs"), a.get("tab_order"), a.get("hide"))

        @tool("open_card", "Open a fresh chat on another card and pass it the request (that card's chart, commentary or look).",
              {"type": "object", "additionalProperties": False, "required": ["card", "request"],
               "properties": {"card": {"type": "string", "enum": cards}, "request": {"type": "string"}}})
        async def open_card(a):
            return await s.tool_open_card(a["card"], a["request"])

        @tool("offer_chart_controls", "Attach live controls bound to exact values in the current card's code.",
              {"type": "object", "additionalProperties": False, "required": ["controls"],
               "properties": {"controls": {"type": "array", "minItems": 1, "maxItems": ctl.MAX_CONTROLS, "items": {
                   "type": "object", "additionalProperties": False, "required": ["kind", "label", "anchor", "value"],
                   "properties": {"kind": {"type": "string", "enum": list(ctl.KINDS)}, "label": {"type": "string"},
                                  "anchor": {"type": "string"}, "value": {"type": "string"},
                                  "min": {"type": "number"}, "max": {"type": "number"}, "step": {"type": "number"}}}}}})
        async def offer_chart_controls(a):
            return await s.tool_offer_chart(a["controls"])

        @tool("offer_theme_controls", "Attach live controls bound to theme token paths.",
              {"type": "object", "additionalProperties": False, "required": ["controls"],
               "properties": {"controls": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
                   "type": "object", "additionalProperties": False, "required": ["kind", "label", "path"],
                   "properties": {"kind": {"type": "string", "enum": ["color", "slider", "switch"]}, "label": {"type": "string"},
                                  "path": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"},
                                  "step": {"type": "number"}}}}}})
        async def offer_theme_controls(a):
            return await s.tool_offer_theme(a["controls"])

        tools = [view, edit_section, look_at_chart, set_commentary, set_text, edit_styles, set_theme, edit_component,
                 arrange, open_card, offer_chart_controls, offer_theme_controls]
        server = create_sdk_mcp_server(name="dashboard", version="1.0.0", tools=tools)
        workspace = STATE_DIR / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return ClaudeAgentOptions(
            model=self.settings["model"],
            effort=self.settings["effort"],
            system_prompt=self.system_prompt(),
            tools=[],                                       # no built-in tools at all
            mcp_servers={"dashboard": server},
            allowed_tools=[f"mcp__dashboard__{n}" for n in TOOL_NAMES],
            permission_mode="dontAsk",                     # anything not pre-approved is denied
            strict_mcp_config=True,                         # ignore other MCP configs / connectors
            setting_sources=[],                             # no CLAUDE.md, settings, hooks, skills
            skills=[],
            max_turns=MAX_TURNS,
            cwd=str(workspace),
            env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "ENABLE_TOOL_SEARCH": "false"},
        )
