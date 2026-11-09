// npm run check (also runs first in npm run build). No server needed.
// Fails on: bad card meta (or v1 leftovers in it), cards without an Analysis function, Analysis functions that
// fail with every filter at "All", commentary refs that render as [missing: ...], sections that load data.
// Warns on: Analysis functions without a card, metrics that are null on unfiltered data.
// Report files (Reports/*.json) are checked too, as warnings (export treats them as errors).
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, loadProject, printResults, readJson, validateProject, validateReport } from './project.mjs';

let p;
try {
  p = await loadProject();
} catch (e) {
  console.log(`ERROR could not load the cards (Src/Sections/index.js): ${e.message}`);
  console.log('check FAILED');
  process.exit(1);
}
const result = validateProject(p);

const reportsDir = path.join(ROOT, 'Reports');
const reports = fs.existsSync(reportsDir) ? fs.readdirSync(reportsDir).filter((f) => f.endsWith('.json')) : [];
for (const f of reports) {
  const name = f.replace(/\.json$/, '');
  let report;
  try {
    report = readJson(`Reports/${f}`);
  } catch (e) {
    result.warnings.push(`report ${name}: not valid JSON (${e.message})`);
    continue;
  }
  const r = validateReport(name, report, p);
  result.warnings.push(...r.errors, ...r.warnings);
}

printResults(result);
const cards = Object.values(p.cards).filter((c) => c.module).length;
if (result.errors.length) {
  console.log(`check FAILED: ${result.errors.length} error(s), ${result.warnings.length} warning(s)`);
  process.exit(1);
}
console.log(
  `check OK: ${p.registry.length} section(s), ${cards} Analysis function(s), ${Object.keys(p.manifest?.tables ?? {}).length} table(s), ` +
    `${reports.length} report(s), ${result.warnings.length} warning(s)`,
);
