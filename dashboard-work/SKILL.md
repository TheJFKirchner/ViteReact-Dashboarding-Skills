---
name: dashboard-work
description: "Add to or change an existing integrated dashboard (a folder with dashboard.config.json, Analysis/ and Src/Sections/): new or changed cards, pages, filters, data, looks, offline HTML reports, hosting. Holds the design agent for dev mode and the reference docs for building cards and data. For a first dashboard or moving existing work into one, use dashboard-new."
---

# Dashboard work

For a dashboard that already exists. Read this page, then open only the reference files the task needs (the
table at the bottom). To make a new dashboard, or to move notebooks, scripts or an old dashboard into one,
use the **dashboard-new** skill instead; it uses this skill's references for the building steps.

## The project in one look
```
dashboard.config.json   name, theme, fast filters, slow filters (parameters), where the design agent is
Data/Current/           the data: one .parquet or .csv per table
Pipeline/               optional scripts that prepare data into Data/Current
Analysis/<page>.py      the numbers: one @card function per card
Src/Sections/<id>.jsx   the look: one file per card;  Src/Sections/index.js = card order and pages
Src/custom.css, Themes/ styling
Reports/ -> Exports/    saved report settings -> offline HTML files
```
`Src/Components`, `Src/Lib`, `Tools`, `Analysis/Shared` are the app itself and rarely need opening.
A card is three pieces with one name (e.g. `s3_paid_by_region`): its function, its `.jsx` file, its line in
`index.js`. Numbers live in Python, the look in React, so a style change can't break a number.

## How to work
1. `npm run status` first: pages, cards, tables, filters, reports and the check result.
2. Sort the request with the table below and read only those files.
3. Build a little, `npm run check`, look at it running (`npm run dev:agent`), show the user, ask what's next.

When something looks odd (a script fails, a column is missing), say what you found and carry on with the rest.
Removing a card or a page: confirm with the user first.

## Route: task -> files
| The user wants | Read | Run |
|---|---|---|
| Colors, fonts, labels, wording, move / resize / hide cards | `references/agent.md` | `npm run dev:agent`, the ✦ button |
| A new card, or different numbers on one | `references/cards.md` | `npm run new-card -- <name> --page <page> --chart ...` |
| A new page, or reorganizing pages | `references/organizing.md`, then `references/cards.md` | `npm run new-card` per card |
| New or refreshed data, a new table | `references/data.md` | `python Pipeline/run_all.py --try <script>`, then `npm run pipeline` |
| A new filter (fast, or slow if changing it means re-querying the source) | `references/data.md` (Filters: fast or slow) | edit `dashboard.config.json` |
| Several tables or pages at once | `references/helpers.md` + the brief it names | one helper per table or page |
| An offline HTML report | `references/reports.md` | `npm run export -- <report>` |
| Hosting it | `references/hosting.md` | `npm run build` |
| Remove a card | none | delete its three pieces, take it out of any report |
| Change the design agent itself | `agent/README.md` (maintainer notes) | |

## Commands (run in the project)
| Command | Does |
|---|---|
| `npm run status` | Map of the dashboard (read-only) |
| `npm run dev` / `npm run dev:agent` | Open it / open it with the design agent and card labels |
| `npm run new-card -- <name> --page <p> --chart echarts\|table\|kpi\|plotly\|text` | Empty card shell; never overwrites |
| `python Analysis/check.py --show <id> [--filter col=value]` | Print one card's numbers |
| `python Pipeline/run_all.py --try <script>` | Try one Pipeline script without touching Data/Current |
| `npm run pipeline` | Refresh all data (swaps in only if every script works) |
| `npm run check` | Every card has its numbers and its text refers to real ones |
| `npm run export -- <report>` | Offline HTML report |

## Files in this skill
| File | What it is |
|---|---|
| `references/cards.md` | Writing a card: the Python function, the `.jsx` file, text formats, cheat sheet |
| `references/data.md` | Getting data in, Pipeline scripts, fast and slow filters, shaping tables |
| `references/organizing.md` | Laying out pages, cards and filters; naming; a plan table |
| `references/helpers.md` | When to use helpers, the order rule, checking what they return |
| `references/helper-data.md` | Brief for a data helper (one per table, mid-size model) |
| `references/helper-cards.md` | Brief for a card helper (one per page, mid-size model) |
| `references/reports.md` | Offline HTML reports |
| `references/hosting.md` | Building and serving it, scheduled refresh |
| `references/agent.md` | The design agent: what it does, setup, troubleshooting |
| `agent/` | The design agent's code. One copy, used by every project; never copied into one |
