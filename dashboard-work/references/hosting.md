# Hosting

- `npm run build`, then `python Analysis/server.py --serve --host 0.0.0.0 --port <port>` serves the whole thing
  from one process.
- Refresh data by running `python Pipeline/run_all.py` on a schedule. It keeps slow filter values readers picked;
  add `--defaults` if the scheduled refresh should always go back to the defaults (e.g. always the latest month).
  All data reading is in `Analysis/Shared/tables.py`, the place to change if the data should come from a warehouse
  instead.
- Fast filters are per reader. A slow filter (`parameters` in `dashboard.config.json`, see `data.md`) changes the
  data for everyone at once, so with many users it needs one data folder per value before going live, or should be
  made fast if the data allows.
- Sign-in is the host's job. The design agent only runs locally and is never part of a build.
- For people who only need a file, an offline HTML report may be enough instead (`reports.md`).
