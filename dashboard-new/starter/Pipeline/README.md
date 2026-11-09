# Pipeline/ (optional)

Scripts that pull source data into `Data/Current/`. Use them when data has to be queried or prepared,
refreshed on a schedule, or re-pulled when a reader changes a slow filter. If you already have the files, drop the
`.parquet` / `.csv` straight into `Data/Current/` instead.

- One script per table is the usual shape: `sales_monthly.py` ends with `write_dataset("sales_monthly", df, ...)`
  (from `_dataset_io.py`), which also records a description and as-of date for "About this data".
- `params()` gives the run's slow filter values (`parameters` in the config), if the project has any. Use them in
  the query: any value can be a slow filter (a region, a snapshot date, a scenario).
- `python Pipeline/run_all.py [--param region=East]` runs every script (not files starting with `_`) into a
  staging folder and swaps it in only if all succeed. It keeps slow filter values picked earlier (recorded in
  `Data/Current/manifest.json` as `params_chosen`); `--defaults` resets them all.
- `python Pipeline/run_all.py --try sales_monthly.py` runs ONE script into `Data/.try/` and shows what it wrote,
  without touching `Data/Current` (safe while other scripts are being worked on).
- `example_sales_monthly.py` makes sample data for the example cards (only there with `setup.py --keep-examples`).
