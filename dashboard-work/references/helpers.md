# Helpers (subagents)

Self-contained jobs go to helpers. Each gets a short brief (its own file, `<...>` parts filled in) and reports
back; you check what matters and talk it through with the user.

| Helper | Model | Tools | One per | Finish line | Brief |
|---|---|---|---|---|---|
| Survey | small (e.g. Haiku) | read-only (e.g. Explore) | folder | a briefing | dashboard-new: `references/survey.md` |
| Data | mid-size (e.g. Sonnet) | can edit | table | its Pipeline script passes `--try` and matches the old output | `helper-data.md` |
| Card | mid-size (e.g. Sonnet) | can edit | page | its cards pass `npm run check` and match the old output | `helper-cards.md` |

**When to use them.** The survey helper is worth it whenever there's a folder to understand. Data and card helpers
earn their keep when there are several tables or pages, or existing work to port and compare. For one table or a
card or two, doing it yourself is quicker than writing the brief.

**Order matters.** Data helpers run first (cards need the data). Then you run `npm run pipeline`, add the filters,
and make every card's shell with `npm run new-card`, because that edits the shared card list. Only then start the
card helpers, one per page, so no two helpers ever edit the same file.

**Give them the plan, not the conversation.** Each brief should carry what the user decided (the row from the plan
table, the rules to keep, which old output to match). A helper only knows what the brief says.

**Check what comes back.** Reports can be confidently wrong. Spot-check the numbers and rules that matter, look at
the dashboard yourself, and tell the user plainly what matched and what didn't.
