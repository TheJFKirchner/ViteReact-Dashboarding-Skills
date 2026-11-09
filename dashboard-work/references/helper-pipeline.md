# Pipeline helper

One per table. Haiku, can edit. It copies existing prep code into one Pipeline script, runs it once, and stops.
Fill in the `<...>` parts and send only the quoted text. `<work>` is the dashboard-work folder.

> Build one data table, `<table>`, for the dashboard project at `<project>`. You're copying existing logic into a
> new file, not redesigning it.
>
> Read only:
> - the old code named below;
> - the "A pipeline script" section of `<work>/references/data.md`.
>
> Open nothing else in `<work>` or in the project.
>
> The table (from the plan): `<one row is ...; columns ...>`.
> Copy from: `<old file and function / cell / query, with full paths>`.
> Rules to keep: `<e.g. drops cancelled orders; drops the current month>`.
>
> 1. Write `Pipeline/<table>.py`. Copy the old prep code as it is. Change only two things:
>    - file paths, made absolute or built from `Path(__file__)`;
>    - the end: save with `write_dataset("<table>", df, grain=..., source=..., description=...)` from
>      `_dataset_io`.
> 2. Run `python Pipeline/run_all.py --try <table>.py`. Fix errors until it runs. That's the only check.
> 3. Stop.
>
> Don't touch: the user's original files, other Pipeline scripts, `Data/`, `Analysis/`, `Src/`,
> `dashboard.config.json`. Don't run `npm run pipeline`.
>
> Report in a few lines: the script's path, its columns and row count, and anything odd (rows dropped, encodings,
> date formats).
