# Dashboard agent: maintainer notes

For changing the agent itself: routing, lockdown, color picker, files, tests. To use it in a project, see `references/agent.md`.

One Claude agent (Haiku) for the live dashboard. Open the ✦ panel and ask for any presentation change:
- a card's chart look or commentary, by clicking it or naming it;
- styles for one card or all;
- page labels, the theme, a shared component;
- layout: move, swap, resize, hide or show cards, move them between tabs, reorder tabs.

Every change is a preview you Keep or Discard. Hovering anything shows where it comes from (Inspect). The Reports tab builds and generates standalone reports.

**It changes looks only.** It never edits `Analysis/` or `Pipeline/`, never adds data, metrics, cards or tabs. A number no metric provides is a Claude Code job. It's never part of `npm run build`, a hosted app, or an export.

## Where it lives (one copy, in the skill)
- **Not copied into projects.** It lives in `<skill>/agent/`, so updating the skill updates every project.
- **Run with the agent:** `Start dashboard.cmd` or `npm run dev:agent` (Analysis server + Vite + agent). `npm run dev` is the viewer, with no agent and no card id badges.
- **Finding the skill:** a project looks at `DASHBOARD_AGENT_HOME` (the skill folder or its `agent/`; on Windows also the saved user setting), then `~/.claude/skills/integrated-dashboards-v2`. Not found: the dashboard starts without the agent and says why.
- **Per-project kill switch:** `"agent": { "enabled": false }` in dashboard.config.json.

## What it knows about a card
- **The card file:** chart JSX, commentary, meta.
- **A reference card:**
  - theme color names, `fx()`, `FORMATS`;
  - the card's Analysis module (`meta.cards[id].module`);
  - the shape of its `data` prop;
  - its metric names and current values;
  - its fast filters.

  Metrics come read-only from the Analysis server over HTTP (`analysis_api.py`: `/api/meta`, `/api/card/<id>`), so the agent never loads Analysis code.
- A picture of the chart (on the first message and on `look_at_chart`).

## How it works (agreed design; don't change without the user)
- **One agent with every tool.** The click is context only: which card is current and what "this" is. Cards can also be named; the prompt carries the card list (id, title, tab, position, width, chart kind).
- **Routing** (narrowest change wins):

  | Request | Tool |
  |---|---|
  | this card's chart | `edit_section` |
  | commentary words | `set_commentary` |
  | "this card" looks | `edit_styles` with `#<id>` selectors |
  | all cards / header / tabs / page | `edit_styles` |
  | colors, fonts, effects everywhere | `set_theme` |
  | title, source line, tab, filter and parameter names | `set_text` |
  | "every KPI tile" structure | `edit_component` |
  | move / swap / resize / hide / reorder | `arrange` |
  | another card's chart or commentary | `open_card` (Keep/Discard asked if needed, then a fresh chat on that card with the request passed on) |
- **One card per chat.** Layout, styles, theme and page text work from any chat.
- **One combined preview** across every file touched:
  - the page banner lists what's pending;
  - Original / Agent flips all of it;
  - Keep writes each file once (the final text is computed first);
  - Discard drops everything;
  - there's no other history.
- **Card chart:** a preview copy `Src/Sections/<id>.agent-preview.jsx`. The chart builds only from the `data`/`metrics` props.
- **Commentary:** `export const commentary` in the card file.
  - Numbers only as `{metric|format}` refs to the card's Analysis metrics, checked against the server's metric names; typed numbers are rejected.
  - If the Analysis server isn't answering, `set_commentary` refuses and says why.
- **Layout** (`arrange(tabs, tab_order, hide)`):
  - previews live;
  - Keep rewrites only the registry array and tabs list in `Src/Sections/index.js` and `meta.tab` / `meta.size`;
  - a card used by a saved report (`sections` or `reportTabs`) can't be hidden.
- **Page text, styles, theme:**
  - previews in memory;
  - filter and parameter labels live in `dashboard.config.json` (`filters.<name>.label`, `parameters.<name>.label`);
  - kept edits apply to every tab and to future exports.
- **Shared components:** `KpiTile`, `Commentary`, `ReportHeader`, `ReportFooter` and `Controls/Segmented` are editable. Locked: `ChartECharts`, `ChartPlotly`, `SectionFrame`, `DataOrigin`, `FilterBar`, `TabBar`, `Select`, `Lib/`, `App.jsx`. Previews hot-swap in place, and Keep records the original hash ("modified").
- **Color picker:**
  - **No part named** ("can we change the colors?", "what color options?") and no chart series clicked:
    - nothing changes, and a guessed color edit or theme color change is refused;
    - a chart colored by category (`f.colorOf` + `data.color_keys`) gets one picker per category ("Inpatient", "Outpatient", … up to 12). Each is bound to the theme value `colors.named.<category>`, so that category's color changes in every chart; Keep writes it to the theme;
    - other charts get a picker for every color they set (up to 6), labeled by the part it colors: series first ("Monthly PMPM color", "Prior 12 months color"), then highlights and scales, then text/axes;
    - a card whose series take the theme's chart colors by position gets "Chart color 1-6 (theme: all charts)";
    - the page gets the accent plus chart colors.
  - **A part named but no color** ("change the line color", "the rolling average", "the comparison"): a sensible theme color is set for that part, and a picker is bound to it.
  - **A named color:** just applied.
  - **Any reply that mentions a picker** ("pick a color below") always comes with one: chart colors, else the theme's chart colors.
- **Refuses** (one sentence, "a Claude Code job" + why): data, metric calculations, `Analysis/`, `Pipeline/`, adding or removing cards or tabs, card meta other than title, locked parts.

## Reports tab
- **Lists** `Reports/*.json` (not `_adhoc_*`) in plain words: cards, tabs, filters, combinations, pinned parameters, look and parts, the last generated file.
- **Generate** runs `node Tools/export.mjs <name>` (no model call) and shows the file's combination count, with **Open** served from `Exports/`.
- **Duplicate.** **Delete** asks first and moves the file to `.dashboard-agent/deleted-reports/`.
- **Propose changes:** one headless Haiku call turns instructions ("red theme, no footer, an Info tab saying ...") into report settings, which you Apply or Discard.
- **New report / Edit** (the report builder, `report_agent.py`, with tools `set_report`, `ask_user`, `save_report`):
  - It asks, per filter of the chosen cards: reader can change (all values), fixed, or reader picks from some values.
  - Then it asks **which combinations are allowed** (`only`/`except` rules) and shows the combination count on every draft update. `save_report` refuses until that question is answered.
  - Then the title, audience and name.
  - It saves only after the export's own validation (`checks/report-check.mjs`) and never overwrites another report without asking.

## Files
In the skill (`<skill>/agent/`):
- `server.py`: local HTTP server; Vite proxies `/agent/*` to it.
- `dashboard_agent.py`: the one agent (tools, prompt, lockdown, combined preview, commentary checks, color picker).
- `section_agent.py`: chat/cost plumbing and the card-chart part (guards, preview copy).
- `global_agent.py`: page text + `Src/custom.css`, and the theme (`Themes/<theme>/tokens.json`).
- `layout_agent.py`: `arrange`.
- `component_agent.py`: shared components.
- `report_agent.py`: Reports tab and builder.
- `controls.py`: control cards.
- `analysis_api.py`: read-only Analysis server client.
- `checks/`:
  - `syntax-check`, `css-check`, `component-check`;
  - `card-check`: rejects new data loading or arithmetic in chart edits;
  - `report-catalog`, `report-check`: use `Tools/project.mjs`.
- `ui/`: `AgentProvider.jsx`, `AgentPanel.jsx`, `ReportsPanel.jsx`, `ControlCard.jsx`, `inspect.js`, `capture.js`, `api.js`, `agent.css`.
- `vite-plugin.js`: aliases `@dash` = project `Src/`; stamps `data-src` in dev.
- `fake_model.py` (tests only), `requirements.txt`.

In each project:
- `Tools/agent-loader.js`: also gives `vite.export.config.js` the "off" stub.
- `Src/Lib/agent-context.js`: `AgentContext`, `useShellText`, `useAgentLayout`; inert without the agent.
- `Src/custom.css`.
- `.dashboard-agent/` (git-ignored).

## Setup (once per machine)
- **Python 3.10+:** `pip install -r <skill>/agent/requirements.txt` (`claude-agent-sdk`). Don't put a virtual environment inside OneDrive (override with `DASH_AGENT_PYTHON`).
- **Skill not in the standard place:** `setx DASHBOARD_AGENT_HOME "<skill folder>"` (ask the user first).
- **Sign-in:** the Claude Code login, with no API keys. A claude.ai subscription login is for the user's own local use; if the agent will be shared with others, flag that API keys are expected.

## Config
- `dashboard.config.json`: `"agent": { "enabled": true, "model": "claude-haiku-5-5", "effort": "low", "pricing": {...} }`.
- **Env:** `DASH_AGENT_MODEL`, `DASH_AGENT_EFFORT`, `DASH_AGENT_PORT` (default 8787), `DASH_API_PORT` (Analysis server), `DASH_AGENT_FAKE=1`.
- **Cost line per reply:** an estimate from token usage × pricing, not a bill.

## Lockdown (enforced in code)
- **Prompt size:** about 3,300 tokens of system prompt + about 1,500 of tool definitions per call. The built-in `styles.css` (~3,500 tokens) is not in the prompt; the agent reads it with `view("styles")` only when writing CSS that overrides a built-in rule.
- **Tools:** `view` (card, commentary, page, styles, theme, layout, component), `edit_section`, `look_at_chart`, `set_commentary`, `set_text`, `edit_styles`, `set_theme`, `edit_component`, `offer_chart_controls`, `offer_theme_controls`, `arrange`, `open_card`.
- **SDK options:** `tools=[]` (no built-ins), `permission_mode="dontAsk"`, `setting_sources=[]`, `strict_mcp_config=True`, `skills=[]`, memory and connectors off.
- **Chart edits:**
  1. exact single match;
  2. protected parts unchanged (imports, exports, meta except `title`, commentary);
  3. JSX parses;
  4. `card-check` passes: no new fetch/XHR/storage/window/eval/dynamic import, no new arithmetic or array maths (`reduce`, `filter`, `sort`…), `Math.*` only for display rounding;
  5. the open tab confirms the render.
- **`set_text`:** known slots, one line, max 80 chars.
- **`edit_styles`:** custom.css only; must parse; no `@import`, `url()`, `.agent-*`.
- **`set_theme`:** existing leaf paths, typed values. The only new keys allowed are category colors `colors.named.<category>` (hex).
- **`set_commentary`:** max 1500 chars, no HTML, refs valid, no typed numbers.
- **`edit_component`:** allowlist only; same exports and props; no new imports beyond the allowed set.
- **Limits:** first try + 2 self-fixes per request, 8 turns, 60 s.

## Troubleshooting
- **No ✦ button:** started with `npm run dev`, or the `[agent]` line says the skill wasn't found or the agent is off.
- **Commentary edits refused, "Analysis server not answering":** the Python server in the same window stopped. Check its error and restart `npm run dev:agent`.
- **Leftover `*.agent-preview.jsx` or `.dashboard-agent/`:** safe to delete.
- **Export contains agent code:** `Tools/export.mjs` must set `NODE_ENV=production`, and `vite.export.config.js` must use `agentOff()`.

## Testing
- **Fake server:** `DASHBOARD_AGENT_HOME=<skill> DASH_AGENT_FAKE=1 DASH_AGENT_PORT=8792 DASH_API_PORT=8793 VITE_CACHE_DIR=node_modules/.vite-test node Tools/dev.mjs --agent --port 5182 --strictPort`. Then send `FAKE: [steps]`: real tools, guards and previews, with no tokens.
  - `{"edit": [old, new]}`, `{"commentary": text}`, `{"text": [slot, value]}`, `{"css": [old, new]}`, `{"theme": [{path, value}]}`, `{"component": [name, old, new]}`, `{"controls": [...]}`, `{"arrange": {...}}`, `{"open": {...}}`, `{"request": "..."}`, `{"say": "..."}`.
- **Suites** in `integrated-dashboards-dev/test-tools/`: `dash2-agent-e2e`, `dash2-agent-unified-e2e`, `dash2-agent-controls-e2e`, `dash2-agent-flash-e2e`, `dash2-agent-v2-colors-e2e`, `dash2-agent-v2-e2e` (layout), `dash2-agent-v2-reports-e2e` (`node <suite>.mjs <project> http://localhost:5182/`). Each restores every file it changes.
- **Never run the real model in tests.** For a live check, ask the user first.
