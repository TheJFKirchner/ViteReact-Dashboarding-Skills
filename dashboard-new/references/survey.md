# Survey helper

One per folder (or per subfolder of a big one). Small model (e.g. Haiku), read-only tools (e.g. the Explore
agent type). Fill in the `<...>` parts; `<skill>` is the dashboard-new folder. Its finish line is one briefing
in the shape below. Send the quoted text only, not this page or the skill folder.

The survey reads the least it can: the data, the queries and calculations that make the numbers, and the visuals
that show them. That's all a migration needs. Servers, routing, auth, config, build files, tests, styles and plain
UI parts are carried over by the new dashboard's own app, so nobody needs to read them. `peek.py` sorts the code
into "read" and "not needed" for the helper.

> Survey the folder `<folder>` so we can plan a dashboard from it. Read only: don't change, move, copy, install or
> run anything, except the inventory script below. Don't open anything in `<skill>`: run its script, nothing more.
> Your job is the user's folder, and only the parts of it that make or show numbers.
>
> 1. Run `python "<skill>/tools/peek.py" "<folder>"`. It lists data files (columns, rows, date ranges, likely
>    filter and measure columns), sorts the code into **Code to read** (queries, calculations, visuals) and **Code
>    not needed** (servers, routing, auth, config, build, tests, plain UI parts), and lists outputs and readme files.
>    For a large folder add `--max-files 1000` or run it on subfolders.
> 2. If there's an index or readme that describes the data, read it first. Treat it as the owner's description,
>    and check it against what's actually on disk.
> 3. Open only the files under **Code to read**, and in each one only the parts around the lines (or notebook
>    cells) it lists: the queries, the calculations and rules, the chart and table definitions. Don't read whole
>    files top to bottom.
> 4. Don't open anything under **Code not needed** or **Other files**. One exception: a file you're reading gets a
>    number from a function elsewhere (e.g. a page fetches `/api/revenue`, which calls `monthly_revenue()`). Find
>    that function by searching for its name, and read just that function. List these in your report.
> 5. Open outputs only if they're small text (csv, html); otherwise go by name and the code that makes them.
>
> Report in plain words, short, in this shape:
>
> **Data:** for each table (or sheet): file, what it holds in one line, what one row is (e.g. "one order",
> "month x region"), rows, date range, columns that look like filters, columns that are measures. Mention
> quirks: not UTF-8, day/month date order, several sheets, blank columns. For data that comes from a database,
> the tables the queries read.
>
> **Queries and calculations:** each one: where it is (file and function, or cell), what it reads, what it does in
> order (joins, filters, grouping, calculations), the rules and fixed values it uses (e.g. "drops cancelled
> orders", "drops the current month", "red below 95% of target"), and which visual it feeds.
>
> **Visuals:** every chart, table, KPI tile and page that exists today: what it shows, its type (line, bar, table
> ...), where it's defined, which query or calculation feeds it, and the filters or inputs a reader can change.
>
> **How it fits together:** the chain from source to visual, e.g. orders table → `monthly_revenue()` →
> `/api/revenue` → Overview page, "Revenue by month" line chart.
>
> **Odd or unclear:** files that couldn't be read, files mentioned but missing, the index disagreeing with what's
> on disk, steps that must run in a certain order, dates or settings typed into the code.
>
> **Not opened:** how many files peek listed as not needed, and any you opened anyway (step 4) with why.
>
> **Index:** whether there was one and whether it matched.
>
> Describe what's there. Don't suggest a dashboard design.

Afterwards: check the rules and numbers you'll rely on against the source (a reader can miss a filter or a
threshold). If the user had no index, offer to save a tidied briefing as `DATA_INDEX.md` in their folder: a table
of file / what it is / one row is / notes, plus the chain. It's theirs to keep up to date, and the next survey
starts from it.

If a visual or a number the user cares about is missing from the briefing, peek's sorting may have missed it
(it works by patterns). Ask the user where it lives, or send a helper to read just that file.
