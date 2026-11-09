# Turning existing work into a dashboard

This could be notebooks, scripts that write HTML or Excel, a Dash or Streamlit app, or an older integrated
dashboard. The aim is the same numbers in a clearer layout, without working the logic out again.

It follows the steps in `SKILL.md`: the survey helper reads only the parts of the existing work that make or show
numbers (queries, calculations, visuals; `peek.py` picks them out and skips servers, auth, config, build and
tests), you show the user a
plain map of where each piece will go and agree what to start with, then data helpers port the prep and card
helpers port the outputs (briefs: `survey.md` here, `helper-data.md` and `helper-cards.md` in dashboard-work). A few things specific to existing work:

- **Ask what people actually use** from it (the HTML files, the app, the spreadsheet). Some outputs may not be
  worth carrying over.
- **Keep the logic as it is** when moving it, and compare each card with the old output for two or three filter
  choices before moving on. Show the user what matches and what doesn't.
- **To get going quickly,** the existing output files can go straight into `Data/Current/` while the prep is
  ported properly later.
- **Leave the original where it is.** Pipeline scripts read from it; nothing in it gets edited or moved.

## What things usually turn into
| In the old work | In the dashboard |
|---|---|
| Loading and cleaning data | A Pipeline script |
| A function or cell that builds a table or chart | One card (its numbers in Analysis, its look in Sections) |
| A loop that writes one file per region or segment | A filter, plus one report with that filter as a choice (fast if all segments can be loaded together, slow if each needs its own query) |
| A date or setting edited at the top before each run | A slow filter (`parameters`) when it changes what's queried, or just left in the script if it never changes |
| A fixed number used in the math (12 months, a 10% threshold) | Stays in the Python; return it as a metric if the text mentions it |
| Dropdowns or inputs | Filters, or a switch inside one card |
| Styled tables (`to_html`, DataTable) | A table card. Colored cells get a flag from the Python |
| Line and bar charts | ECharts cards (Plotly if it has to look identical) |
| Image charts (matplotlib, seaborn) | Redrawn from the data |
| Captions and footnotes with numbers | The card's note (above) or text drawn in the card (below), with the numbers as metrics |
| Several output files or tabs | Pages, and a report per audience |

## Worth watching for
- **Things with no match:** CSV or Excel downloads, emailed files, summaries printed to the screen. Mention them
  to the user. A printed summary often makes a good headline card.
- **Notebooks:** point to cells ("cell 3, `trend_table`") rather than line numbers.
- **The same setting in two places** (one date typed into two notebooks): it becomes one setting.
- **Rules that look like styling but are really logic,** like "drop the last two months" or "red above 10%". Keep
  them in the Python.

## Older integrated dashboards
- **v2 projects:** same layout. Copy the cards (`Src/Sections`), the Analysis page files (not `Analysis/Shared`),
  the Pipeline scripts, `Reports`, `Themes`, `Src/custom.css` and `dashboard.config.json` into a fresh starter.
- **v1 projects:** cards worked out their numbers in JavaScript. Keep each card's look, and move its numbers into
  an Analysis function. The pipeline scripts, filters and themes carry over.
