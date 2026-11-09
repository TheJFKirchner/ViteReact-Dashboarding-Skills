# Survey helper

One per folder (or per subfolder of a big one). Small model (e.g. Haiku), read-only tools (e.g. the Explore
agent type). Fill in the `<...>` parts; `<skill>` is the dashboard-new folder. Its finish line is one briefing
in the shape below. Send the quoted text only, not this page or the skill folder.

> Survey the folder `<folder>` so we can plan a dashboard from it. Read only: don't change, move, copy, install or
> run anything, except the inventory script below. Don't open anything in `<skill>`: run its script, nothing more.
> Your job is the user's folder.
>
> 1. Run `python "<skill>/tools/peek.py" "<folder>"`. It lists data files (columns, types, rows, date ranges,
>    likely filter and measure columns), scripts and notebooks (files they mention), outputs, and readme or index
>    files. It never stops on a bad file; it lists the problem instead. For a large folder add `--max-files 1000`
>    or run it on subfolders.
> 2. If there's an index or readme that describes the data, read it first. Treat it as the owner's description,
>    and check it against what's actually on disk.
> 3. Open each script and notebook enough to say what it does. Skim; you don't need every line.
> 4. Open outputs only if they're small text (csv, html); otherwise go by name and the script that makes them.
>
> Report in plain words, short, in this shape:
>
> **Data:** for each table (or sheet): file, what it holds in one line, what one row is (e.g. "one order",
> "month x region"), rows, date range, columns that look like filters, columns that are measures. Mention
> quirks: not UTF-8, day/month date order, several sheets, blank columns.
>
> **Scripts and notebooks:** for each: what it reads, what it does in order (joins, filters, calculations), the
> rules and fixed values it uses (e.g. "drops returns: units < 0", "drops the current month", "red below 95% of
> target"), and what it writes or shows. Point to the function name or cell number.
>
> **Outputs:** each chart, table, file or page: what it shows and which script or cell makes it.
>
> **How it fits together:** the chain from raw files to outputs, e.g. raw_orders.csv → prep_orders.py →
> orders_monthly.csv → monthly_review.ipynb → trend chart, region-vs-target table.
>
> **Odd or unclear:** files that couldn't be read, files mentioned but missing, the index disagreeing with what's
> on disk, steps that must run in a certain order, dates or settings typed into the code.
>
> **Index:** whether there was one and whether it matched.
>
> Describe what's there. Don't suggest a dashboard design.

Afterwards: check the rules and numbers you'll rely on against the source (a reader can miss a filter or a
threshold). If the user had no index, offer to save a tidied briefing as `DATA_INDEX.md` in their folder: a table
of file / what it is / one row is / notes, plus the chain. It's theirs to keep up to date, and the next survey
starts from it.
