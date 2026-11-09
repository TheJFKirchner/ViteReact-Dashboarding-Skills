# Dashboard agent (design assistant, dev only)

An in-app chat (Haiku) for presentation changes while the dashboard runs locally. Changing the agent itself: `agent/README.md`.

## What it does
- **Section looks:** click a section (or name it), then ask for chart colors, styles or commentary wording.
- **Page:** titles and labels, theme colors and fonts, styles for every section, the shared components (KPI tiles, header, footer).
- **Layout:** move, swap, resize, hide or show sections; move sections between tabs; reorder tabs.
- **Reports tab:** list, generate, duplicate, delete and build report files (it asks which filter combinations are allowed).
- **Every change is a preview** that you Keep or Discard. Hover anything to see which file it comes from.
- **Color questions** with no part named ("can we change the colors?") get color pickers, one per category or chart part.

## What it never does
- Change data, metrics, `Analysis/` or `Pipeline/`.
- Add or remove sections or tabs.
- Type numbers into commentary (only `{metric|format}` refs).

It replies "a Claude Code job" with the reason, and that work is done in Claude Code instead.

## Run it
- `Start dashboard.cmd`, or `npm run dev:agent`. Click ✦ to open it.
- `npm run dev` / `Start dashboard (viewer).cmd` runs without the agent (viewer).
- The agent is never part of `npm run build`, an export, or a hosted app.

## Setup (once per machine)
- `pip install -r <work>/agent/requirements.txt`, where `<work>` is the dashboard-work folder (Python 3.10+).
- **Never copy the agent into a project, and never weaken its lockdown without the user.**
- **The agent lives in dashboard-work, not in projects.** A project finds it through `"agent": { "home": "<dashboard-work folder>" }` in `dashboard.config.json` first (dashboard-new's setup writes this unless dashboard-work is installed in the standard place), then `DASHBOARD_AGENT_HOME`, then `~/.claude/skills/dashboard-work`. The first line in the dev window, `[agent] using ...`, says which one it found. To point an older project at this agent, set its `agent.home` to the dashboard-work folder.
- `agent/README.md` is kept unchanged from v2, so it still names v2 paths (`references/agent.md`, `integrated-dashboards-v2`, `DASHBOARD_AGENT_HOME` first). This page is the current word on where things are.
- **Two dashboards in dev mode at once:** the agent uses port 8787; give the second one `DASH_AGENT_PORT` (e.g. 8788).
- **Sign-in** uses the Claude Code login. If others will use it, flag that API keys are expected.
- **Turn it off for a project:** `"agent": { "enabled": false }` in `dashboard.config.json`.
- Model and cost display: the `agent` block in `dashboard.config.json` (default `claude-haiku-5-5`, effort `low`). The cost per reply is an estimate.

## Troubleshooting
| Problem | Cause |
|---|---|
| No ✦ button | Started with `npm run dev`, or the `[agent]` line in the window says the skill wasn't found or the agent is off |
| Commentary edits refused: "Analysis server not answering" | The Python server in the same window stopped. Read its error and restart `npm run dev:agent` |
| Leftover `*.agent-preview.jsx` or `.dashboard-agent/` | Safe to delete |
