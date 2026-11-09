# Data helper

One per table. Mid-size model (e.g. Sonnet), can edit. Finish line: its Pipeline script passes `--try` and
matches the old output. Read `helpers.md` first for the order rule. Fill in the `<...>` parts; `<work>` is
the dashboard-work folder.

> Build one data table, `<table>`, for the dashboard project at `<project>`. The reference files are in `<work>/references`.
>
> What it should hold: `<one row is ...; columns ...>`.
> Where it comes from: `<files / existing script, with paths>`.
> Rules to keep: `<e.g. drop returns (units < 0), drop the current month>`.
> Old output to match (if any): `<file>`.
>
> 1. Write `Pipeline/<table>.py`. It ends with `write_dataset("<table>", df, grain=..., source=..., description=...)`
>    from `_dataset_io` (see "A pipeline script" in `<work>/references/data.md`). Use wording a reader understands for grain,
>    source and description.
> 2. If an existing script already prepares this data, keep its logic exactly as it is: copy the prep code in
>    (changing only file paths and the final save), or call it if it can be imported without side effects. Read
>    the source files where they are, using absolute paths or paths built from `Path(__file__)`. Don't copy the
>    user's raw data into the project unless the brief says so.
> 3. Try it: `python Pipeline/run_all.py --try <table>.py`. This runs only your script into a scratch folder and
>    shows the columns and first rows; it never touches `Data/Current`, so it's safe while others work. Fix it
>    until it passes.
> 4. If there's an old output, compare: row count, the total of each measure, and a few individual values. Report
>    any difference with your best explanation; don't adjust numbers to make them match.
>
> Don't touch: the user's original files, `Data/Current`, other Pipeline scripts, `Src/`, `Analysis/`,
> `dashboard.config.json`. Don't run `npm run pipeline` (the main session does that once everyone is done).
>
> Report: the script's path, the table's columns and row count, how it compares with the old output, and anything
> you assumed or found odd (bad rows, encodings, dates).
