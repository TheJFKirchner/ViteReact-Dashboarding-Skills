# Organizing a dashboard

Two goals: a reader finds the answer quickly, and whoever looks after it can find and change one thing without
reading everything. These are tips, not rules. If the user already has a structure in mind, use theirs.

## Pages
- Give each question or audience its own page: "Overview", "Costs by service", "Regions".
- One page is fine for a small dashboard. Add pages when scrolling starts to hide things.
- Put the headline first (a few big numbers or a one-line summary), then the trend, then the breakdown, then
  detail tables. Many readers stop after the first screen.
- A handful of cards per page reads best. A very large dashboard (dozens of cards) may be better as two.

## Cards
- One card, one idea. If the title needs an "and", it might be two cards.
- The title says what it shows ("Paid per member by month"), not what kind of chart it is.
- The note on a card gives the takeaway in a sentence or two. Skip it when the chart says it all.
- Cards can be half width (two side by side) or full width. Tables and long trends usually want full width.

## Filters
- **Filters** (region, product, a snapshot date, and so on) apply to every card that uses them. Keep them few: each
  one is something readers have to think about.
- Any filter can be **fast** (narrows the data already loaded, instant) or **slow** (re-pulls the data for the
  chosen value, as slow as the pull, one value for everyone). Ask whether changing it needs the source queried
  again; if not, make it fast. `data.md` has the guide.
- **Switches inside a card** (count vs amount, chart vs table) are better when only that card cares.

## Keeping files easy to edit
- Keep card files small: title, note, drawing. The working-out lives in `Analysis/`, so a style change can't
  break a number.
- One Analysis file per page (`Analysis/overview.py`, `Analysis/regions.py`) keeps a page's numbers together.
- Name things by what they hold: `s4_paid_by_region`, `regions.py`, `claims_monthly`.
- The number in a card's name is its permanent id; saved reports point to it. A card that moves up the page
  keeps its number.
- If the same piece shows up on several cards (a style of table, a row of tiles), make it once in
  `Src/Components/`.
- For look-only changes (colors, fonts, labels, spacing), use the design agent, `Src/custom.css` or the theme,
  rather than editing many card files.

## Writing the plan down
Any format works. A table like this usually covers it:

| Page | Card | Shows | Filters (mark slow ones) | Data |
|---|---|---|---|---|
| Overview | Summary | Big numbers: paid, cost per member, change vs last year | region | claims_monthly |
| Overview | Paid trend | Line over 24 months, this year vs last | region | claims_monthly |
