# Writing a section

A section is one block on a tab: a chart, a table, KPI tiles, or a few of these together. It's two files that
share an id, e.g. `s3_paid_by_region`. Start one with:

```
npm run new-section -- paid_by_region --page costs --tables claims_monthly --chart echarts
```
This picks the next number and writes both files as empty shells (the section shows "Not built yet"). It adds the
section to `Src/Sections/index.js`, and adds the tab if it's new. It never overwrites anything.

Options:
- `--title "Paid by region"`
- `--size half`: sits next to another half-width section.
- `--chart echarts | plotly | table | kpi | text`: what the shell starts with.

Filters aren't chosen here: each filter's level in `dashboard.config.json` decides where it applies.

## 1. The numbers: `Analysis/<tab>.py`
One Python function per section. It gets the tables it asks for, already filtered, and returns two things:
`data` for the charts and tables, and `metrics`, single named values for the section's text.

```python
from Shared.registry import section

@section("s3_paid_by_region", tables=["claims_monthly"])
def paid_by_region(t):
    df = t.claims_monthly
    by = df.groupby("region", as_index=False)["paid"].sum().sort_values("paid", ascending=False)
    return {
        "data": {"regions": by["region"].tolist(), "paid": by["paid"].tolist()},
        "metrics": {"top_region": by["region"].iloc[0], "total_paid": by["paid"].sum()},
    }
```
- `tables` lists what it reads.
- **Filters are already applied.** The section gets every filter in its reach (dashboard-wide, its tab's, its
  own) whose column its tables have. It never filters again.
- `t.filters["region"]` is the reader's choice ("All" when unfiltered). `t.params` holds the slow filter values,
  handy for captions.
- Do the grouping, totals and sorting here, so the `.jsx` file only draws.
- Use `None` for a value that can't be worked out; it shows as "n/a".
- **Porting existing code:** copy the calculation as it is.
- Older projects may have `filters=[...]` on the line. It still works, but leaving it out lets the config decide.

## 2. The look: `Src/Sections/s3_paid_by_region.jsx`
```jsx
export const meta = { id: 's3_paid_by_region', title: 'Paid by region', tab: 'costs', library: 'echarts', size: 'half' };

export const commentary = `
{top_region|name} had the most paid claims, out of {total_paid|compact} in total.
`;

export default function Section({ data, metrics }) {
  // draw data.regions / data.paid; a chart and a table together is fine
}
```
- `library` says what draws it: `echarts`, `plotly`, or `none` for tables, tiles and text.
- `tab` is the tab's id. On a one-page dashboard, leave it out.
- `commentary` is the note above the section. It refers to metrics by name and never types numbers in.
- **No filter dropdowns in here.** A filter that only this section uses goes in the config with
  `"section": "<this id>"`, and it appears in this section's header. A switch that only changes the view
  (count vs amount, chart vs table) is fine inside the section.

## Text formats
| Write | Shows |
|---|---|
| `{x\|pct:1}` | 5.2% |
| `{x\|direction}` | rose / fell / was flat |
| `{x\|money}` / `{x\|compact}` | $1,234 / $913.2M (both add the $) |
| `{x\|int}` / `{x\|short}` / `{x\|num:2}` | 12,345 / 913.2M (no $) / 4.64 |
| `{x\|pts:1}` | 2.4 points (a difference between two rates) |
| `{x\|name}` | the text as it is |

`pct` shows the size without a sign; pair it with `direction` ("rose 5.2%").

## Charts and tables
- **Pattern to copy:** for the first chart, read `s2_revenue_trend.jsx`; for KPI tiles, read `s1_summary.jsx`.
  They're in the project's `Src/Sections/` if it kept the examples, otherwise in dashboard-new's
  `starter/Src/Sections/`. Read nothing else from the starter.
- **ECharts:** `<ChartECharts option={option} height={300} />`, with `option` built in
  `useMemo(() => ..., [data])`. Ready to use: line, bar, pie, scatter, heatmap. Other types (sankey, gauge,
  radar) get added to the lists at the top of `Src/Components/ChartECharts.jsx`.
- **Plotly:** `<ChartPlotly>`, for box plots and histograms, or to match an old Plotly chart exactly.
- **Tables:** a plain `<table className="data">`. Cells can use the `good` and `bad` classes.
- **KPI tiles:** `<div className="kpis">` with `<KpiTile label value format change goodWhen="up" spark={[...]} />`.
- **Colors** come from the theme: `const f = fx()` from `../Lib/theme.js`. Use `f.color(i)`,
  `f.colorOf(name, i)`, `f.good`, `f.bad`, `f.colors.text`, `f.colors.textMuted`, `f.colors.accent`,
  `f.area(color)` and `f.bar(color, horizontal)`. Never type colors in.
- **Number formats in the drawing:** `FORMATS` from `../Lib/commentary.js` (`money`, `pct`, `int`, `compact`).
- One-off styling goes in `Src/custom.css`, scoped to `#<id>`.

## Python helpers (optional)
`from Shared.periods import ...`:
- `total(df, col)`
- `sum_by(df, key, col)`
- `last_periods(df, 12, offset=0)`
- `change(cur, prior)`
- `ratio(a, b)`
- `month_label("2026-10-01")`, which gives "Oct 2026"

They return `None` rather than failing.

## Checking
`npm run check` once when you're done. To see one section's numbers:
`python Analysis/check.py --show <id> [--filter region=East]`.
