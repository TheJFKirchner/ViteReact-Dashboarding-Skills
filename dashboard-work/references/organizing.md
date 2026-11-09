# Organizing a dashboard

Tips, not rules. If the user already has a layout in mind, use theirs.

## Tabs
- Give each question or audience its own tab: "Overview", "Costs by service", "Regions". One tab is fine for a
  small dashboard.
- Order inside a tab: the headline (a few big numbers) first, then the trend, then the breakdown, then detail
  tables. Many readers stop after the first screen.

## Sections
- One section, one idea. A chart with the table behind it is one idea; two unrelated charts are two sections.
- The title says what it shows ("Paid per member by month"), not the chart type.
- The note gives the takeaway in a sentence. Skip it when the chart says it all.
- Half width (two side by side) or full width. Tables and long trends usually want full width.
- The number in a section's id is permanent; saved reports point to it. A section that moves keeps its number.

## Filters: put each one where it belongs
| The filter matters to | Level | Example |
|---|---|---|
| Every tab | Dashboard (above the tabs) | Region, line of business, a snapshot date |
| One tab | That tab (`"tab"`) | Product, on a Products tab |
| One section | That section (`"section"`) | Claim type, on a "Paid by claim type" section |

- Keep them few: each one is something readers have to think about.
- Never repeat the same filter in several sections. If more than one section needs it, move it up a level.
- Fast or slow is a separate question: does changing it mean querying the source again? (`data.md`)
- A switch that only changes how one section looks (count vs amount, chart vs table) stays inside that section.

## Writing the plan down
| Tab | Section | Shows | Data |
|---|---|---|---|
| Overview | Summary | Big numbers: paid, cost per member, change vs last year | claims_monthly |
| Overview | Paid trend | Line over 24 months, this year vs last | claims_monthly |

| Filter | Column | Fast / slow | Level |
|---|---|---|---|
| Region | region | fast | dashboard |
| Product | product | fast | tab costs |
