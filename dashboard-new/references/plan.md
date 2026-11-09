# The plan (PLAN.md)

Every build works from one short file in the new project, `PLAN.md`. It says what data there is, which sections
go on which tab, and where each filter lives. For a port, an inventory helper fills it in from the existing work.
For a new dashboard, you write it with the user. Steps 3 and 4 just follow it.

## Its shape
```markdown
# Plan: <dashboard title>

## Data
| Table | From (old file, query or script) | One row is | Columns |
|---|---|---|---|
| orders_monthly | backend/services/sales_service.py: monthly_revenue() | month x region | month, region, revenue |

## Tabs and sections
| Tab | Section | Shows | Reads | Copy from |
|---|---|---|---|---|
| Overview | Revenue by month | Line of revenue by month, table under it | orders_monthly | frontend/src/pages/Overview.jsx |

## Filters
| Filter | Column | In the old work | Applies to | Level | Fast / slow | Why |
|---|---|---|---|---|---|---|
| Region | region | Dropdown, Overview.jsx line 12 | every section | dashboard | fast | a WHERE on loaded rows |
| As of | month | `--as-of` argument, make_reports.py line 12 | every section | dashboard | slow | passed into the query |

## Rules to keep
- Drops cancelled orders (sales_service.py: monthly_revenue)
```

## Filters: the part to get right
Filters decide where things sit on the page, so find every one and settle each before building.

**1. Find them.** Anything a reader or whoever runs it can change is a filter. peek lists these as "filters and
inputs":
- dropdowns, radio buttons, date pickers, sliders, widgets;
- URL or request parameters;
- run arguments (`--as-of`);
- values passed into a query (`WHERE region = ?`, `params=`);
- a loop that writes one output per segment (`for region in REGIONS`);
- a date or list typed in at the top before each run.

**2. What each applies to.** List the sections (old charts and tables) whose numbers change with it. That
decides its level:

| Applies to | Level |
|---|---|
| Every section, on every page | `dashboard` (above the tabs) |
| Every section on one page or tab | `tab <tab>` |
| One section only | `section <section>` |

Never repeat one filter in several sections; if two sections need it, move it up a level. A switch that only
changes the view (paid vs per-member, chart vs table) isn't a filter; it stays inside its section.

**3. Fast or slow.** Slow (re-queries the source) when the value:
- is passed into the query, stored procedure or API call;
- picks which file, snapshot or database is read;
- is a run argument or a date typed in before each run;
- has data that's too big to load for every value at once.

Otherwise it's fast: it narrows rows already loaded. Prefer fast. Write the reason in **Why**.

The helper fills in what it finds, with Level and Fast / slow as guesses marked `?`. You settle both with the
user before step 3.

## Inventory helper (porting)
One per folder. Haiku, read-only tools. Fill in the `<...>` parts and send only the quoted text. `<skill>` is the
dashboard-new folder.

> Take stock of the existing work in `<folder>` and write the plan for moving it into a new dashboard. Read only:
> don't change, move, copy, install or run anything, except the inventory script below and writing one file.
> Don't open anything in `<skill>` except running its script.
>
> 1. Run `python "<skill>/tools/peek.py" "<folder>"`. It lists the data files and sorts the code into **Code to
>    read** (queries, calculations, visuals) and **Code not needed** (servers, auth, config, build, tests).
> 2. If there's a readme or index describing the data, read it first.
> 3. Open only the files under **Code to read**, and in each one only the parts around the lines or cells it
>    lists. Don't open anything under **Code not needed**, unless a file you're reading gets its numbers from a
>    function there. In that case, search for that function by name and read just that function.
> 4. Find every filter and input. peek lists them per file as "filters and inputs", with lines. Look for:
>    - dropdowns and widgets;
>    - request or URL parameters;
>    - run arguments;
>    - values passed into queries;
>    - loops that write one output per segment;
>    - dates or lists typed in at the top.
>
>    For each one, note:
>    - its column;
>    - where it is in the old work;
>    - which visuals change with it;
>    - whether its value goes into the query, or picks a file or snapshot. If it does, it's likely slow.
> 5. Write `<project>/PLAN.md` in exactly this shape: `<paste "Its shape" from this page>`.
>    - One row per table, per visual group (a section) and per filter.
>    - Tabs follow the old pages or files.
>    - "Copy from" names the file and function, or notebook cell.
>    - **Applies to** names the sections. Guess Level from it: every section is `dashboard`, one page is
>      `tab <tab>`, one section is `section <section>`.
>    - Guess Fast / slow, and give the reason in **Why**. Mark both guesses with `?`.
>    - A switch that only changes the view (e.g. paid vs per-member) is not a filter. Note it in that section's
>      Shows column.
>    - A loop that makes one output per value (one file per region) is one section plus a filter, not one section
>      per value.
>    - Under "Rules to keep", list every threshold or fixed value the old code applies.
> 6. Report in a few lines: what you found, the filters and what each applies to, anything you couldn't read,
>    and anything unclear.
>
> Describe what's there and where it goes. Don't design anything new.

Then read `PLAN.md` and settle the filters with the user, one by one: keep it or not, its level, fast or slow. If a visual they care about is missing, ask where
it lives. peek sorts files by patterns, so it can miss one.

## What old things become
| In the old work | In the dashboard |
|---|---|
| Loading and cleaning data | A Pipeline script (one per table) |
| A query, function or cell that makes the numbers for a chart or table | A section's Analysis function |
| A chart, table or KPI row (or a few shown together) | One section |
| A page, notebook or output file | A tab |
| Dropdowns or inputs | Filters at the level they applied (whole app, one page, one chart) |
| A loop writing one file per region | A filter, plus one offline report |
| A date or setting typed at the top before each run | A slow filter if it changes what's queried; otherwise left in the script |
| Image charts (matplotlib, seaborn) | Redrawn with ECharts from the same numbers |
| Styled tables, colored cells | A table; the color rule stays in Python as a flag |

## An older integrated dashboard
- **v2 or v3** (same layout): copy its `Src/Sections/*.jsx`, its `Analysis/<page>.py` files (not
  `Analysis/Shared`), `Pipeline/` scripts, `Reports/`, `Themes/`, `Src/custom.css` and `dashboard.config.json`
  into the new project. Then give each filter a level in the config. Old `@card(..., filters=[...])` lines keep
  working; removing `filters=[...]` lets the levels decide.
- **v1:** the sections worked out their numbers in JavaScript. Keep each look, and move its numbers into an
  Analysis function.
