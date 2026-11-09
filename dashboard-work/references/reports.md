# Offline HTML reports

A report is a single HTML file with chosen cards in it. Every filter choice it offers is worked out when it's
made, so it opens anywhere with no server. Good for people who should get a file rather than run the dashboard.

## Quickest way
`npm run export -- 1,3` (card numbers) or `npm run export -- tabs:overview` (whole pages). Readers get every filter
those cards use. The settings are saved as `Reports/_adhoc_<date>.json`; rename it to keep it, or delete it.

## A saved report
One file per report in `Reports/`, e.g. `Reports/finance.json`:

```json
{
  "title": "Cost trend: Commercial",
  "audience": "Finance leadership",
  "sections": ["s1_summary", "s2_paid_trend"],
  "filters": {
    "line_of_business": { "value": "Commercial", "locked": true },
    "region": { "value": "All", "options": ["All", "East", "West"] }
  }
}
```
Then `npm run export -- finance`. The file lands in `Exports/` as `<project>_<report>_<date>.html`.

- **Title and audience:** shown at the top; the audience reads as "Prepared for Finance leadership".
- **Cards:** `sections` lists them by name. Or use `"tabs": ["overview"]` for whole pages.
- **Fast filters:** `locked` fixes a value and hides the filter. `options` lets the reader pick. A filter the report
  doesn't mention is set to "All". The reader's picks show in the file's link (`#region=East`), so a link to the
  file with that ending opens on the same choice.
- **Slow filters (pinned data):** `"parameters": { "as_of": "2026-07-31" }` makes the report use the data pulled
  for that value, without changing what the dashboard shows. A report has one value per slow filter (readers can't
  switch it, since that would need a new pull); for several values, make one report each. Without it, the report
  uses whatever data is loaded.
- **Only some combinations:** `"combinations": { "only": [...], "except": [...] }`, e.g. a product choice that only
  makes sense for one line of business.
- **Extras:** `theme`, `notice` (a line under the title), `hide` (`footer`, `source`, `commentary`, `filters`),
  `inspect: true` ("About this data" buttons), `reportTabs` (the report's own pages, including text-only ones).

A habit of "one file per region" can be one report with a region choice, or a locked report per region if
readers shouldn't see each other's numbers. Ask the user which.

## Size
Before building, the export says how many combinations it will work out and roughly how big the file gets. If
it's too much, lock filters the audience doesn't need or leave out heavy cards.

## Checking one
Open the file in a browser with no server running. The cards should show, changing a filter should update them,
and nothing should load from the internet. The design agent's Reports tab can list, make and edit reports too.
