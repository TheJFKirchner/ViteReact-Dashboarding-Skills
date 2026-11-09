# Writing a card

A card is three small pieces that share a name, e.g. `s3_paid_by_region`. Start one with:

```
npm run new-card -- paid_by_region --page costs --chart echarts --tables claims_monthly
```
It picks the next number, writes the two files as empty shells (the card shows "Not built yet"), adds the card to
`Src/Sections/index.js` (and the page to `tabs` if it's new), and never overwrites anything. Options: `--title`,
`--size half`, `--filters region,product` (default: all the dashboard's filters; `none` for none), `--chart`
`echarts | plotly | table | kpi | text`. Then fill in the two files as below.

## 1. The numbers: `Analysis/<page>.py`
A Python function tagged with the card's name. It gets the tables it asks for (already filtered) and returns
two things: `data` for the chart or table, and `metrics`, single named values for the card's text.

```python
from Shared.registry import card

@card("s3_paid_by_region", tables=["claims_monthly"], filters=["region"])
def paid_by_region(t):
    df = t.claims_monthly
    by = df.groupby("region", as_index=False)["paid"].sum().sort_values("paid", ascending=False)
    return {
        "data": {"regions": by["region"].tolist(), "paid": by["paid"].tolist()},
        "metrics": {"top_region": by["region"].iloc[0], "total_paid": by["paid"].sum()},
    }
```
- `tables` lists what it reads. `filters` lists which of the dashboard's filters apply to it.
- `t.filters` holds the reader's fast filter choices (e.g. `t.filters["region"]`, "All" when unfiltered) and
  `t.params` the slow ones the data was pulled with, handy for captions like "East, snapshot Oct 31". The tables
  are already filtered by both; a card doesn't filter again.
- Do the grouping, totals and sorting here, so the card file only draws.
- Use `None` for a value that can't be worked out; the card shows "n/a".
- Try it without opening the page: `python Analysis/check.py --show s3_paid_by_region` prints everything it
  returns; add `--filter region=East` to try a filter.
- Moving existing code? Keep it as it was, so the numbers match the old output.
- `Analysis/Shared/periods.py` has helpers for last-12-months, change vs prior and similar. They're optional.

## 2. The look: `Src/Sections/s3_paid_by_region.jsx`
```jsx
export const meta = { id: 's3_paid_by_region', title: 'Paid by region', library: 'echarts', size: 'half' };

export const commentary = `
{top_region|name} had the most paid claims, out of {total_paid|compact} in total.
`;

export default function Section({ data, metrics }) {
  // draw data.regions / data.paid
}
```
- `library` says what draws it: `echarts`, `plotly`, or `none` for tables, tiles and text.
- `size: 'half'` sits next to another half card. With pages, add `tab: '<page id>'`; on a one-page dashboard
  leave it out (and keep `export const tabs = []` in `index.js`).
- The `commentary` is the note above the card. It refers to metrics by name instead of typing numbers.

## 3. Its place: `Src/Sections/index.js`
`npm run new-card` adds it. By hand: import the card and add it to the list. The list order is the order on the page.

## Text formats
| Write | Shows |
|---|---|
| `{x\|pct:1}` | 5.2% |
| `{x\|direction}` | rose / fell / was flat |
| `{x\|money}` / `{x\|compact}` | $1,234 / $913.2M (both are **money**: they add the $) |
| `{x\|int}` / `{x\|short}` / `{x\|num:2}` | 12,345 / 913.2M (no $, for counts) / 4.64 |
| `{x\|pts:1}` | 2.4 points (a difference between two rates) |
| `{x\|name}` | the text as it is |

`pct` shows the size without a sign ("rose 5.2%" reads better than "rose +5.2%"); pair it with `direction`. For a
signed column in a table ("+12.1%", "-1.2%"), add the sign in the card.

A fixed value the text mentions (like "12 months" or "above 10%") can be returned as a metric too, so the text
always matches the code. The note always sits above the card; a footnote under a table is written in the card
itself, with its numbers taken from `metrics` and formatted with `FORMATS`.

## Charts and tables
- **Charts:** the starter uses ECharts (`Src/Components/ChartECharts.jsx`). `s2_revenue_trend.jsx` shows the pattern.
  Less common chart types (sankey, gauge, radar) need adding to the list at the top of that file.
- **Colors:** take them from the theme (`fx()` in `Src/Lib/theme.js`), so a theme change reaches every chart.
- **Plotly:** good for box plots and histograms, or to match an existing Plotly chart exactly. It makes exports
  bigger (~1.5 MB).
- **Tables:** a plain `<table className="data">`. Cells can use the `good` / `bad` classes for color.
- **Headline numbers:** `KpiTile` (`Src/Components/KpiTile.jsx`), as in `s1_summary.jsx`.
- **Number formatting in the card:** `FORMATS` from `Src/Lib/commentary.js` (`money`, `pct`, `int`, `compact`).
- One-off styling for a card goes in `Src/custom.css`.

## Cheat sheet
**In Python** (`from Shared.periods import ...`, all optional): `total(df, col)`, `sum_by(df, key, col)` → dict,
`distinct(df, col)` → sorted list, `last_periods(df, 12, offset=0)` → rows in the last 12 months (`offset=12` for
the 12 before), `change(cur, prior)` → 0.052 for +5.2%, `ratio(a, b)`, `top_key(dict)`, `quantile(values, q)`,
`month_label("2026-10-01")` or `month_label("2026-10")` → "Oct 2026" (use it for months in notes). They return `None` rather than failing when a value can't be worked out.

**Formats** (in text `{x|name}`, in the card `FORMATS.name(x)` from `../Lib/commentary.js`): `pct`, `pts`, `money`,
`compact` (money), `short` (plain), `int`, `num`, `direction`, `name`. `FORMATS.pct(v, '0')` takes decimals as text.

**Colors** (`const f = fx()` from `../Lib/theme.js`, inside the chart's `useMemo`): `f.color(i)` (series colors in
order), `f.colorOf(name, i)` (a category's fixed color if the theme names one), `f.good`, `f.bad`,
`f.colors.text`, `f.colors.textMuted`, `f.colors.accent`, `f.colors.border`, `f.sequential`, `f.diverging`.
Fills: `f.area(color)` under a line, `f.bar(color, horizontal)` for bars; `...f.glow(color)` in a `lineStyle` or
`itemStyle`. These follow the theme's effects, so a theme change restyles every chart.

**ECharts types ready to use:** line, bar, pie, scatter, heatmap; tooltip, legend, grid, dataZoom, markLine,
visualMap. Anything else gets added to the lists at the top of `Src/Components/ChartECharts.jsx`.
`<ChartECharts option={option} height={300} />`; build `option` in `useMemo(() => ..., [data])`.

**Page pieces:** `<table className="data">` (numbers right-aligned, first column left; `td` classes `good` / `bad`),
`<div className="kpis">` with `<KpiTile label value format change goodWhen="up" spark={[...]} />`,
`<ChartPlotly>` for Plotly. Text: `var(--text-muted)` and the other theme colors are CSS variables.

**Card meta:** `{ id, title, library: 'echarts' | 'plotly' | 'none', size: 'half', tab: '<page id>' }`. `tab`
only when the dashboard has pages.

