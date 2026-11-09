---
name: dashboard-new
description: "Make a new integrated dashboard (Python for the numbers, React for the page), or port existing work into one: notebooks, scripts, SQL, spreadsheets, a Dash or Streamlit app, an older dashboard. Four steps: copy the template, take stock, rebuild the data, make the sections. Later changes use dashboard-work."
---

# Dashboard new

## What you're making
A dashboard has **tabs**, and each tab has **sections**. A section is one block: a chart, a table, KPI tiles, or a
few together. Filters sit at one of three levels: the whole dashboard, one tab, or one section. The
**dashboard-work** skill (installed next to this one, written `work:` below) explains the parts. Read its
`SKILL.md` "How a dashboard is built" once.

## Four steps, one check each
New dashboards and ports go through the same steps. Each step has one check. Don't add more testing than that,
and don't build anything the plan doesn't list.

| Step | Done when |
|---|---|
| 1. Copy the template | setup prints `check OK` |
| 2. Take stock and plan | the user has agreed `PLAN.md` |
| 3. Rebuild the data | `npm run pipeline` finishes |
| 4. Make the sections | `npm run check` passes and the user has seen it |

### 1. Copy the template
1. Ask where the project should go. Avoid OneDrive folders: the installed packages sync badly.
2. Run `python <this skill>/tools/setup.py <folder> --title "<title>"`.
3. It copies the template, installs it and runs the check. `check OK` means the template runs. Move on; don't
   open or test the template.

If it says something is missing (Node, or Python 3.10+ with `pip install fastapi uvicorn duckdb pyarrow pandas`),
tell the user and stop.

### 2. Take stock and plan
**Porting:**
1. Ask which folder holds the existing work.
2. Send one inventory helper (Haiku) with the brief in `references/plan.md`. It reads only the queries,
   calculations, visuals and filters, and writes `PLAN.md` into the project.
3. Read `PLAN.md` with the user and settle what to keep.
4. Settle every filter. This is the part to get right, because it decides where everything sits. For each
   filter that exists today:
   - **What does it apply to?** That sets its level: every section is dashboard-wide, one tab's sections is
     tab, one section is section.
   - **Fast or slow?** Does changing it mean re-querying the source? Look for values passed into a query, a run
     argument, a date typed in before each run, or a loop writing one file per value.

   `references/plan.md`, "Filters: the part to get right", has the guide.

**New:**
1. Ask what the dashboard should answer and where the data is.
2. Ask which filters readers need, what each applies to (which sets its level), and whether any needs the data
   re-queried (slow).
3. Write `PLAN.md` yourself in the shape in `references/plan.md`: tables, sections per tab, and filters with
   level and fast or slow. Agree it with the user.

### 3. Rebuild the data
1. For each table in the plan:
   - **ready file:** copy it into `Data/Current/`;
   - **needs prep:** write a Pipeline script that copies the existing prep code. Use one pipeline helper (Haiku)
     per table, with the brief in `work:references/helper-pipeline.md`.
2. Run `npm run pipeline` once.
3. Add the plan's filters to `dashboard.config.json`, each at its level (`work:references/data.md`).

Don't compare numbers with the old output unless the user asks.

### 4. Make the sections
1. Run `npm run new-section -- <name> --page <tab> --tables <table> --chart <kind>` for every section in the
   plan. Make all of them before any helper starts.
2. Fill them: one sections helper (Haiku) per tab with the brief in `work:references/helper-sections.md`, or do
   it yourself for a few. They copy the old logic and visuals; filters come from the config.
3. Run `npm run check` once, open it with `npm run dev`, look once, and show the user.

After this, changes go through **dashboard-work**: add a section, or edit one.

## Who does what
- **You:** talk to the user, settle the plan (filter levels, fast or slow), and run setup, the pipeline,
  `new-section` and the final check.
- **Haiku helpers:** take stock, then copy the code (one helper per table, then one per tab). They copy, they
  don't redesign. Use Sonnet only for new analysis with nothing to copy, or after Haiku fails the same job
  twice.
- If something looks odd, tell the user and carry on. Never edit or move the user's original files.

## What to open
| | Files |
|---|---|
| **Read** | This page; `references/plan.md` at step 2; the `work:` file a step names |
| **Run, don't read** | `tools/setup.py`, `tools/peek.py` (`--help` lists options) |
| **Never open** | `starter/` and `themes/`. Setup copies them. In the project, open only the files `work:` `SKILL.md` lists under **Edit** |

Pass the same rule on: a helper gets its brief and the paths it needs, never a folder to explore.
