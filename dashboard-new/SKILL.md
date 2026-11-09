---
name: dashboard-new
description: "Make a first integrated dashboard (Python for the numbers, React for the page) from a folder of data, scripts, notebooks, spreadsheets or an older dashboard: survey what's there, plan pages and cards with the user, set up the project, bring the data and outputs across. Once the dashboard exists, further changes use dashboard-work."
---

# Dashboard new

For the first build of a dashboard, including moving existing work into one. The building steps use the
**dashboard-work** skill's reference files, written `work:` below (the dashboard-work folder, installed next to this
one). Once the first cards are built and shown, later changes belong to dashboard-work.

## Read, run, copy: this folder is mostly a template
About 97% of this folder is used without being read. Open only what the **Read** row says, when the step says.

| | Files | What to do with them |
|---|---|---|
| **Read** | This page. `references/survey.md` at step 1 (hand it to the survey helper). `references/existing-work.md` only when moving existing work. The `work:references/...` file each step names | Read when the step comes up, not before |
| **Run, don't read** | `tools/peek.py`, `tools/setup.py` | Run them. `--help` lists the options; their output says what happened |
| **Never open** | `starter/` (the whole app: 62 files) and `themes/` | `setup.py` copies both into the new project. Don't read, copy or edit them here |

Pass the same rule on: a helper gets its brief and the paths it needs, never this folder to explore.

## Who does what
- **Scripts** do what needs no judgment and can't damage anything: `tools/peek.py` only reads, `tools/setup.py`
  only writes into a new or empty folder.
- **Helpers** (subagents) do self-contained jobs: a small read-only model surveys, mid-size models build one
  table or one page each.
- **You and the user** decide what it shows and check the results. Nothing runs end to end on its own: ask,
  build a little, show it running, ask again. It can span several conversations.

When something looks odd (a file that won't open, a script that fails, data that doesn't match the plan), say
what you found and carry on with the rest. Never edit or move the user's original files.

## The steps
| Step | What happens | Read | Run |
|---|---|---|---|
| 1. Find out what's there | Ask which folder holds the data or the current report, and whether it has an index or readme. Send a survey helper; big folder: one per subfolder, then combine. It reads only the data, queries, calculations and visuals; the rest of an app (backend, auth, config, tests) isn't read | `references/survey.md` | `python tools/peek.py <folder>` (the helper runs it; it sorts the code into "read" and "not needed") |
| 2. Plan together | Suggest pages, cards and filters in a short table, marking any filter that needs the source re-queried as slow; the user picks where to start. Their layout wins if they have one. Offer to save the briefing as `DATA_INDEX.md` if there was no index | `work:references/organizing.md`; existing work: `references/existing-work.md` | |
| 3. Set up the project | Copies the starter and themes into a new folder; records where the design agent is | "Setup" below | `python tools/setup.py <new folder> --title "..."` |
| 4. Get the data in | Ready files go into `Data/Current/`; anything needing prep gets a Pipeline script, one data helper per table when there are several | `work:references/data.md`, `work:references/helpers.md` | `--try` per script, then `npm run pipeline` once; add fast and slow filters to the config |
| 5. Make the cards | `new-card` for every planned card first (it edits the shared card list), then build them yourself or with one card helper per page | `work:references/cards.md`, `work:references/helpers.md` | `npm run new-card -- <name> --page <p> --chart ...` |
| 6. Check and show | Check, start it, look at it yourself before the user does. Moved work: compare the numbers with the old output | | `npm run check`, `npm run dev:agent` |
| 7. What's next | Round again from step 4 or 5, or hand over to dashboard-work | | |

## Setup
`python <this skill>/tools/setup.py <new folder> --title "Claims dashboard"`
- Copies `starter/` and `themes/` (as `Themes/`) into a new or empty folder. Then it removes the example cards,
  sets the title, picks a free port, records the dashboard-work folder as the design agent's home, runs
  `npm install` and runs the check. Nothing to copy or configure by hand.
- `--keep-examples` keeps two example cards with sample data, for a first look. `--no-install` skips npm.
- Needs Node and Python 3.10+ with `pip install fastapi uvicorn duckdb pyarrow pandas` (setup says what's missing).
- Avoid OneDrive folders for projects if possible: the installed packages sync badly.

## After setup: what to configure in the project
Everything from here on happens in the new project folder. Only these files are yours to write:

| File (in the project) | Step | What goes in it |
|---|---|---|
| `dashboard.config.json` | 4 | `filters` (fast) and `parameters` (slow), `dataSource`, `theme`, `staleDays`. Leave `project`, `title`, `server` and `agent` as setup wrote them unless the user asks |
| `Data/Current/` | 4 | Ready `.parquet` / `.csv` files, dropped in |
| `Pipeline/<table>.py` | 4 | One new script per table that needs prep (`work:references/data.md`) |
| `Analysis/<page>.py`, `Src/Sections/<id>.jsx` | 5 | Made as empty shells by `npm run new-card`, then filled in (`work:references/cards.md`) |
| `Src/Sections/index.js` | 5 | Written by `new-card`. Edit only to reorder cards or rename pages |
| `Src/custom.css` | any | Styling for one card, scoped to its id |
| `Reports/<name>.json` | later | Offline reports (`work:references/reports.md`) |

**Never open in the project** (it's the app; the `work:` references describe everything it offers): `Src/App.jsx`,
`Src/main.jsx`, `Src/styles.css`, `Src/Components/`, `Src/Controls/`, `Src/Filters/`, `Src/Lib/`, `Analysis/Shared/`,
`Analysis/server.py`, `check.py`, `precompute.py`, `Pipeline/run_all.py`, `Pipeline/_dataset_io.py`, `Tools/`,
`index.html`, `package.json`, `package-lock.json`, `vite*.config.js`, `node_modules/`.

Two exceptions:
- **First chart card:** read one example as the pattern. That's `Src/Sections/s2_revenue_trend.jsx` (chart) or
  `s1_summary.jsx` (KPI tiles), in the project with `--keep-examples`, otherwise in this skill's
  `starter/Src/Sections/`. 43 and 24 lines.
- **A chart type ECharts doesn't load yet** (sankey, gauge, radar): add it to the lists at the top of
  `Src/Components/ChartECharts.jsx`, reading only that top part.

## Existing work in short
Keep the logic as it is, leave the original where it is (Pipeline scripts read from it), and compare each card
with the old output. A v2 project has the same layout: copy its cards, Analysis page files, Pipeline scripts,
Reports, Themes, `Src/custom.css` and config into a fresh project. v1 cards worked out numbers in JavaScript;
those move into Analysis functions. Details: `references/existing-work.md`.
