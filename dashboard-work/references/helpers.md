# Helpers (subagents)

Helpers do the copying work: one table or one tab each. Porting is copying, not new analysis, so a small model
(Haiku) does it. Each helper gets a brief with exactly the files it may open, and stops after one check.

| Helper | Model | One per | Done when | Brief |
|---|---|---|---|---|
| Inventory | Haiku, read-only | folder of existing work | `PLAN.md` written | dashboard-new: `references/plan.md` |
| Pipeline | Haiku, can edit | table | its script passes `--try` | `helper-pipeline.md` |
| Sections | Haiku, can edit | tab | `npm run check` passes | `helper-sections.md` |

## Rules
- **Order:** pipeline helpers first. Then you run `npm run pipeline`, add the filters, and make every section's
  shell with `npm run new-section`. Then the section helpers, one per tab, so no two helpers edit the same file.
- **Give them the plan rows, not the conversation.** A helper only knows what its brief says: its rows of
  `PLAN.md`, the old code to copy, and the rules to keep.
- **Files, not folders.** Never hand a helper a skill folder or a whole project to look around in.
- **One check each.** No extra testing, no comparing every filter choice. If the user wants the old and new
  numbers compared, that's a separate step at the end.
- **Use Sonnet only** for new analysis (nothing to copy), or when Haiku fails the same job twice.
- **For one table or one section,** doing it yourself is quicker than writing a brief.
