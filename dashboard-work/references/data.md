# Getting data in

Sections read their data from `Data/Current/`. Each `.parquet` or `.csv` file there is one table, named after the
file (`Claims Monthly.csv` becomes `claims_monthly`). How the files get there is up to you.

## Ways to fill it
- **Drop the files in.** If the data already exists as files, copy them into `Data/Current/`. Changes are picked
  up on the next refresh of the page.
- **Pipeline scripts.** When data has to be fetched or prepared (a query, joins, cleaning), write a script per
  table in `Pipeline/`. `npm run pipeline` runs them all and only replaces the old data if every script worked.
- **Both.** A prepared table from a script next to a small lookup file you dropped in is fine.

## A pipeline script
Do the work however you like, then save the result with `write_dataset`:

```python
from _dataset_io import write_dataset

df = ...  # your query or prep code
write_dataset("claims_monthly", df,
              grain="month x region",
              source="Claims warehouse, paid through Oct 2026",
              description="Paid claims by month and region")
```
The grain, source and description show up in the report's "About this data" panel, so use wording the reader
will understand. If you're moving existing prep code, keep it as it was and compare the result with the old output.

To try one script on its own: `python Pipeline/run_all.py --try claims_monthly.py`. It runs just that script into
a scratch folder (`Data/.try/`) and shows the columns and first rows, without touching `Data/Current`. Several
people (or helpers) can try their scripts at the same time this way; run `npm run pipeline` once they're done.

Raw input files the scripts read (exports, snapshots, lookup lists) can live wherever suits the user, for example
a `Source/` folder in the project. Scripts run from inside `Pipeline/`, so build paths from the script's own
location (`Path(__file__).parent.parent / "Source"`) rather than relying on the current folder.

## Filters: fast or slow
Any choice a reader makes (region, product, line of business, a snapshot date) can be a **fast** or a **slow**
filter. The difference isn't what the filter is about. It's one question: **does changing it mean querying the
source again?**

- **Fast** (`filters` in `dashboard.config.json`): every value is already in the loaded tables, in a column.
  Changing it narrows rows that are already in `Data/Current`, so sections update at once. Options are read from the
  data. Each reader has their own choice, and it's kept in the page's link.
- **Slow** (`parameters` in `dashboard.config.json`): the data for one value has to be pulled on its own. Changing
  it re-runs the Pipeline scripts with the new value, which takes as long as the pull does. Options are listed in
  the config. There's one current value for everyone using that copy of the dashboard, and it always sits with
  the dashboard-wide filters (it changes the data under every tab).

| Make it slow when | Otherwise fast |
|---|---|
| All values together are too big to keep loaded, even summarized (e.g. pull one region of a huge claims table at a time) | Summarized, all values fit (millions of rows are fine) |
| Each value is a separate source: a month-end snapshot, a different database, a scenario run | One table holds every value in a column |
| The query itself needs the value (a stored procedure argument, an API call per value) | The value is just a `WHERE` on rows you already have |
| The number for a value can't be worked out from loaded rows (a re-run model, a recalculated allocation) | Sections can add up or filter the loaded rows |

Prefer fast when it's possible: it's instant and doesn't affect other readers. The two can work together, e.g. a slow
`year` decides which year is pulled and a fast `region` narrows it.

### A fast filter
One entry per column, at one level:
```json
"filters": {
  "region":     { "label": "Region", "column": "region" },
  "product":    { "label": "Product", "column": "product", "tab": "costs" },
  "claim_type": { "label": "Claim type", "column": "claim_type", "section": "s4_paid_by_type" }
}
```
| Level | Shown | Applies to |
|---|---|---|
| No `tab` or `section`: the whole dashboard | above the tabs | every section |
| `"tab": "<tab id>"` | under the tab names, on that tab | that tab's sections |
| `"section": "<section id>"` | in that section's header | that section |

A filter narrows only the sections in its reach whose tables have its column. Put each filter where the reader
expects it: something every page cares about goes on the dashboard, and a breakdown only one chart needs goes on
that section. A new project starts with none; add them once the data is in. `npm run status` shows each filter's
level and which tables have its column. In a section, `t.filters["region"]` is the reader's choice ("All" when
unfiltered).

### A slow filter
Under `parameters`, either a fixed list of choices (any kind of value; the default is the first one unless given):
```json
"parameters": { "region": { "label": "Region", "default": "East", "options": ["East", "North", "South", "West"] } }
```
or the last few month ends, counted back from today:
```json
"as_of": { "label": "Data as of", "type": "month_end", "default": "latest", "options": { "month_ends": 12 } }
```
In a Pipeline script, `params()["region"]` gives the chosen value (a date for `month_end`, text otherwise); the script
uses it in its query. In a section, `t.params["region"]` gives it too, handy for captions. A fixed list needs updating by
hand when a new value appears (the app can't list values without querying the source).

When a reader changes one, the app asks first, re-runs the pipeline and reloads. The sections keep showing the old data
until the new pull has worked; if it fails, nothing changes.

**Where the value is recorded:** `Data/Current/manifest.json`. `"params"` holds every value the loaded data was
pulled with (what the dashboard shows as selected), and `"params_chosen"` the ones picked on purpose (different from
their default). `npm run pipeline` and scheduled refreshes keep the picked ones, so a refresh doesn't undo a
reader's choice. Picking the default again (e.g. the latest month) stops keeping it, so "latest" rolls forward
again. `python Pipeline/run_all.py --defaults` puts every slow filter back to its default.

Call the date the data runs to `as_of`: the dashboard header and reports show it as "Data as of". Any other name
works too; it just won't appear in the header.

## An index of the data (optional)
If the folder the data comes from has a file describing it (`DATA_INDEX.md`, a readme, a data dictionary), the
survey helper reads that first. Anything works; a table like this is easy to keep up to date by hand:

| File | What it is | One row is | Notes |
|---|---|---|---|
| data/raw_orders.csv | POS export, pulled Mondays | one order line | returns are negative units; dates day/month/year |

plus a line on how things connect (raw file → script → output). If there isn't one, the survey can draft it.

## Tips on shaping tables
- Summarize to the level the sections need (e.g. monthly totals by region instead of every claim line). Pages stay quick.
- Keep different levels in different tables. A count that belongs to a whole claim, repeated on every line of
  that claim, gets added up too many times.
- A fast filter works on every table that has a column with its name. Use the same column name and values
  everywhere. A table without that column just isn't filtered (handy for lookup tables).
- Fast filter choices are listed alphabetically. To set the order, add it to the filter in `dashboard.config.json`:
  `"region": { "label": "Region", "column": "region", "order": ["North", "South", "East", "West"] }`.
