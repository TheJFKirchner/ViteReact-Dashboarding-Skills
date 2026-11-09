---
name: dashboard-new
description: "Make a first integrated dashboard (Python for the numbers, React for the page) from a folder of data, scripts, notebooks, spreadsheets or an older dashboard: survey what's there, plan pages and cards with the user, set up the project, bring the data and outputs across. Once the dashboard exists, further changes use dashboard-work."
---

# Dashboard new

For the first build of a dashboard, including moving existing work into one. Read this page, then open only the
files the current step needs (the table below). The building steps use the **dashboard-work** skill's reference
files, written `work:` below (the dashboard-work folder, installed next to this one). Once the first cards are
built and shown, later changes belong to dashboard-work.

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
| 1. Find out what's there | Ask which folder holds the data or the current report, and whether it has an index or readme. Send a survey helper; big folder: one per subfolder, then combine | `references/survey.md` | `python tools/peek.py <folder>` (the helper runs it) |
| 2. Plan together | Suggest pages, cards and filters in a short table, marking any filter that needs the source re-queried as slow; the user picks where to start. Their layout wins if they have one. Offer to save the briefing as `DATA_INDEX.md` if there was no index | `work:references/organizing.md`; existing work: `references/existing-work.md` | |
| 3. Set up the project | New project from the starter; records where the design agent is | below | `python tools/setup.py <new folder> --title "..."` |
| 4. Get the data in | Ready files go into `Data/Current/`; anything needing prep gets a Pipeline script, one data helper per table when there are several | `work:references/data.md`, `work:references/helpers.md` | `--try` per script, then `npm run pipeline` once; add fast and slow filters to the config |
| 5. Make the cards | `new-card` for every planned card first (it edits the shared card list), then build them yourself or with one card helper per page | `work:references/cards.md`, `work:references/helpers.md` | `npm run new-card -- <name> --page <p> --chart ...` |
| 6. Check and show | Check, start it, look at it yourself before the user does. Moved work: compare the numbers with the old output | | `npm run check`, `npm run dev:agent` |
| 7. What's next | Round again from step 4 or 5, or hand over to dashboard-work | | |

## Setup
`python <this skill>/tools/setup.py <new folder> --title "Claims dashboard"`
- Writes only into a new or empty folder, removes the example cards, picks a free port, runs `npm install` and the
  check, and records the dashboard-work folder as the design agent's home.
- `--keep-examples` keeps two example cards with sample data, for a first look. `--no-install` skips npm.
- Needs Node and Python 3.10+ with `pip install fastapi uvicorn duckdb pyarrow pandas` (setup says what's missing).
- Avoid OneDrive folders for projects if possible: the installed packages sync badly.

## Existing work in short
Keep the logic as it is, leave the original where it is (Pipeline scripts read from it), and compare each card
with the old output. A v2 project has the same layout: copy its cards, Analysis page files, Pipeline scripts,
Reports, Themes, `Src/custom.css` and config into a fresh project. v1 cards worked out numbers in JavaScript;
those move into Analysis functions. Details: `references/existing-work.md`.

## Files in this skill
| File | What it is |
|---|---|
| `references/survey.md` | Brief for the survey helper (small read-only model), its report shape, the `DATA_INDEX.md` offer |
| `references/existing-work.md` | What notebooks, scripts, apps and old outputs turn into; moving v1/v2 dashboards |
| `tools/peek.py` | Read-only inventory of a folder: data files, columns, scripts, outputs, readmes |
| `tools/setup.py` | Makes a project from `starter/` and `themes/` |
| `starter/` | The project template (app code, commands, example cards) |
| `themes/` | Color and font sets, copied into projects as `Themes/` |
