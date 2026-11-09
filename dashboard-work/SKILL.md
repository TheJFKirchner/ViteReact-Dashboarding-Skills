---
name: dashboard-work
description: "Change an existing integrated dashboard (a folder with dashboard.config.json, Analysis/ and Src/Sections/). Almost every request is adding a section or editing one; also filters, data, looks, offline HTML reports and hosting. For a new dashboard, or moving existing work into one, use dashboard-new."
---

# Dashboard work

## How a dashboard is built
- A dashboard has **tabs**, and each tab has **sections**. A section is one block on the page: a chart, a table,
  KPI tiles, or a few of these together.
- A section is two files that share an id such as `s3_paid_by_region`:
  - `Analysis/<tab>.py`: a Python function that works out its numbers.
  - `Src/Sections/s3_paid_by_region.jsx`: how it looks.

  Its place on the page is one line in `Src/Sections/index.js`.
- **Data** lives in `Data/Current/`, one file per table. `Pipeline/` scripts fill it, or files are dropped in.
- **Filters** live in `dashboard.config.json`. Each filter sits at one level and applies to the sections under it:

| Level | In the config | Shown | Applies to |
|---|---|---|---|
| Dashboard | no `tab` or `section` | above the tabs | every section |
| Tab | `"tab": "<tab id>"` | under the tab names, on that tab | that tab's sections |
| Section | `"section": "<section id>"` | in that section's header | that section |

  A filter only narrows sections whose tables have its column. Sections never build their own filter dropdowns.
  - **Fast filters** (`filters`, the usual kind) narrow data that's already loaded.
  - **Slow filters** (`parameters`) re-query the source and always apply to the whole dashboard. Use one only
    when changing the value means pulling data again.

## First: is this adding a section or editing one?
Run `npm run status`. It lists every tab, section, table and filter. Then sort the request:
- "Show X", "add a chart of Y", "a new tab with ...": **Add a section**.
- "Change", "fix", "move", "rename", "the numbers on X look wrong": **Edit a section**. Find it in the status
  list by its title.
- Anything else (a filter, data, looks only, a report, hosting): see the matching heading below.

## Add a section
1. Settle what it is with the user before building:
   - **What it shows:** its charts or tables, and its tab.
   - **Which filters it needs.** Filters already in its reach (dashboard-wide, its tab's) apply on their own.
     For a new one, decide what it applies to: this section only (section level), its whole tab, or everything.
     Then decide fast or slow (see **Add or move a filter**).
2. Pick the tables it reads. `npm run status` lists each table's columns. If no table has the data yet, do
   **Add or change data** first.
3. Run `npm run new-section -- <name> --page <tab> --tables <table> --chart echarts|table|kpi|text`. This makes
   both files as empty shells and puts the section on the page.
4. Numbers: fill in its function in `Analysis/<tab>.py` (`references/sections.md`).
5. Look: fill in `Src/Sections/<id>.jsx`. Several charts or tables in one section is fine.
6. Add any new filter from step 1 to the config at its level (see **Add or move a filter**).
7. Run `npm run check` and fix anything it names. Then show the user.

## Edit a section
1. Find its id in `npm run status`.
2. Open only its two files.
3. Change the right part:

| The user wants | Change |
|---|---|
| Different numbers | Its function in `Analysis/<tab>.py` |
| A different chart or table, title or note | Its `.jsx` file (`references/sections.md`) |
| Colors, fonts, spacing, size, order | The design agent (`references/agent.md`), or `Src/custom.css` scoped to `#<id>` |
| A different tab | `tab:` in its `meta` |
| Different filters | The filter's level in the config, not the section |

4. Run `npm run check`. Then show the user.

## Add or move a filter
1. Fast or slow? Ask one question: does changing it mean querying the source again? If not, it's fast
   (`filters`). If so, it's slow (`parameters`); see `references/data.md`.
2. Pick its level from what it applies to: every section (dashboard), one tab's sections (`"tab"`) or one section (`"section"`).
3. Add it to the config, e.g. `"product": { "label": "Product", "column": "product", "tab": "costs" }`.
4. Run `npm run check`. It warns if the filter reaches no section that has that column.

## Add or change data
1. If the file is ready, drop it into `Data/Current/`. If it needs prep, write `Pipeline/<table>.py`, ending with
   `write_dataset(...)` (`references/data.md`).
2. Run `python Pipeline/run_all.py --try <table>.py`, then `npm run pipeline`.

## Everything else
| Task | Read |
|---|---|
| Looks only (colors, fonts, wording, moving sections) | `references/agent.md` |
| An offline HTML report | `references/reports.md` |
| Hosting it | `references/hosting.md` |
| Several sections or tables at once | `references/helpers.md` |
| Remove a section | Nothing to read. Ask the user first, then delete its two files, its line in `index.js` and any report that lists it |
| Changing the design agent itself | `agent/README.md` |

## What to open
| | Files |
|---|---|
| **Edit** (read the one you're changing) | `dashboard.config.json`, `Pipeline/<table>.py`, `Analysis/<tab>.py`, `Src/Sections/*.jsx`, `Src/Sections/index.js`, `Src/custom.css`, `Reports/*.json`, `Themes/` |
| **Run, don't read** | The commands below. Their output is the answer |
| **Never open** | The app itself: `Src/App.jsx`, `Src/main.jsx`, `Src/styles.css`, `Src/Components/`, `Src/Controls/`, `Src/Filters/`, `Src/Lib/`, `Analysis/Shared/`, `Analysis/server.py`, `check.py`, `precompute.py`, `Pipeline/run_all.py`, `Pipeline/_dataset_io.py`, `Tools/`, `index.html`, `package*.json`, `vite*.config.js`, `node_modules/`, `Data/` |

In this skill folder, open only this page and the reference file a step names. `agent/` is never opened or
copied. Helpers get their brief, which lists the files they may open, never a folder to explore.

## Commands (run in the project)
| Command | Does |
|---|---|
| `npm run status` | Map of the dashboard: tabs, sections, tables, filters and their levels, reports |
| `npm run new-section -- <name> --page <tab> --tables <t> --chart <kind>` | Empty section shell; never overwrites |
| `npm run check` | Every section has its numbers, its text refers to real ones, filters reach a section |
| `npm run dev` / `npm run dev:agent` | Open it / open it with the design agent |
| `python Analysis/check.py --show <id> [--filter col=value]` | Print one section's numbers |
| `python Pipeline/run_all.py --try <script>` | Try one Pipeline script without touching Data/Current |
| `npm run pipeline` | Refresh all data |
| `npm run export -- <report>` | Offline HTML report |
