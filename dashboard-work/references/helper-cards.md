# Card helper

One per page. Mid-size model (e.g. Sonnet), can edit. Finish line: its cards pass `npm run check` and match the
old output. Start it only after every card shell exists (`helpers.md`, the order rule). Fill in the `<...>`
parts; `<work>` is the dashboard-work folder, and `<pattern card path>` is the full path to `s2_revenue_trend.jsx`
or `s1_summary.jsx` ("Charts" in `cards.md` says where it is). Send the quoted text only.

## Card helper

> Build the cards on the `<page>` page of the dashboard project at `<project>`. Each one already exists as an empty
> shell (made by `npm run new-card`): a function in `Analysis/<page>.py` and a file `Src/Sections/<id>.jsx`. Read
> `<work>/references/cards.md` first (the card format and a cheat sheet). `npm run status` shows the tables and their
> columns.
>
> Read only: `cards.md`, `Analysis/<page>.py`, your cards' `Src/Sections/<id>.jsx` files, the old code you're
> porting, and one pattern card (`<pattern card path>`). Don't open anything else in `<work>`, nor the project's
> `Src/Components`, `Src/Lib`, `Src/App.jsx`, `Analysis/Shared`, `Tools` or `Data`: `cards.md` covers what they
> offer.
>
> The cards:
> - `<id>`: `<title>`. Shows `<what>`, as a `<chart type>`. Reads `<tables>`; filters `<filters>`. The note should
>   say `<the takeaway, e.g. latest month vs a year ago>`. Old output to match: `<file / cell / function>`.
> - ...
>
> For each card:
> 1. **Numbers:** fill in its function in `Analysis/<page>.py`. Do the grouping, totals and sorting there and return
>    `data` shaped for the chart plus `metrics` for the note. For rates and averages, start from totals so they stay
>    right when someone filters. When porting existing code, keep its logic unchanged. Correct `tables=` and
>    `filters=` in the `@card(...)` line if needed.
> 2. **Look:** fill in `Src/Sections/<id>.jsx`: the title, the note (numbers only by name, like
>    `{total_paid|money}`), and the chart or table. Colors from the theme (`fx()`), never typed in. Replace the
>    "Not built yet" line.
> 3. **Test:** `python Analysis/check.py --show <id>` prints its full result (add `--filter region=East` to try a
>    filter); then `npm run check` for everything.
> 4. **Compare** with the old output where there is one, for all data and for two or three filter choices.
>
> Don't touch: `Src/Sections/index.js`, other pages' files, `dashboard.config.json`, `Pipeline/`, `Data/`,
> `Src/Components`, `Src/Lib`. If a card needs a little styling, add it to `Src/custom.css` scoped to its id
> (`#<id> ...`).
>
> If a card can't be built as described (a column is missing, a rule is unclear), build what you can, leave the
> rest showing "Not built yet", and say why. Don't invent numbers.
>
> Report, per card: done or not, its metrics with no filters, how it compares with the old output, and anything you
> assumed.

Afterwards: run `npm run check` yourself, open the dashboard in dev mode and look at each page before showing the
user. Charts that pass the check can still look wrong (empty axes, the wrong number format).
