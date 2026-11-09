# Sections helper

One per tab. Haiku, can edit. Start it only after every section shell exists (`npm run new-section`). It copies
the old calculations and visuals into the sections, runs one check, and stops. Fill in the `<...>` parts and send
only the quoted text:
- `<work>` is the dashboard-work folder.
- `<pattern>` is the full path to `s2_revenue_trend.jsx` (charts) or `s1_summary.jsx` (KPI tiles). They're in the
  project's `Src/Sections/` if it kept the examples, otherwise in dashboard-new's `starter/Src/Sections/`.

> Fill in the sections on the `<tab>` tab of the dashboard project at `<project>`. Each section already exists as
> an empty shell: a function in `Analysis/<tab>.py` and a file `Src/Sections/<id>.jsx`. You're copying existing
> logic and visuals, not redesigning them.
>
> Read only these files, and open nothing else:
> - `<work>/references/sections.md`
> - `Analysis/<tab>.py`
> - your sections' `.jsx` files
> - the old code named below
> - `<pattern>`
>
> The sections (from the plan):
> - `<id>`: `<title>`. Shows `<the visuals, e.g. a line of revenue by month and the table under it>`. Reads
>   `<tables>`. Copy from `<old file and function / cell>`.
> - ...
>
> For each section:
> 1. **Numbers:** in its function in `Analysis/<tab>.py`, copy the old calculation. Return `data` for the visuals
>    and `metrics` for the note. The tables arrive already filtered.
> 2. **Look:** in `Src/Sections/<id>.jsx`, draw the same visuals as the old version. Several charts or tables in
>    one section is fine. Take colors from the theme (`fx()`). Replace the "Not built yet" line.
> 3. **Don't add filter dropdowns.** Filters come from `dashboard.config.json` and are drawn by the app.
>
> When all are done, run `npm run check` once and fix what it names. That's the only check.
>
> Don't touch: `Src/Sections/index.js`, other tabs' files, `dashboard.config.json`, `Pipeline/`, `Data/`,
> `Src/Components`, `Src/Lib`.
>
> If a section can't be built as described (a column is missing, the old logic is unclear), leave it showing
> "Not built yet" and say why. Don't invent numbers.
>
> Report in a few lines per section: done or not, and anything you assumed.
