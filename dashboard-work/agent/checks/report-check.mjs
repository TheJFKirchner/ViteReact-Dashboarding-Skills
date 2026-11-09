// The real report validation (the same one npm run export uses, Tools/project.mjs validateReport) for one
// report object. stdin: {"name": "...", "report": {...}}. Exit 0 = valid (warnings on stdout), 1 = errors.
// Also prints "PLAN <json>" (allowed filter combinations: count, choosable filters) when the report is valid.
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const project = await import(pathToFileURL(path.join(process.cwd(), 'Tools', 'project.mjs')).href);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { name, report } = JSON.parse(input);
const p = await project.loadProject();
const { errors, warnings } = project.validateReport(name, report, p);
const lines = [...errors.map((e) => `ERROR ${e}`), ...warnings.map((w) => `WARN  ${w}`)];
if (!errors.length && project.reportPlan) {
  const plan = project.reportPlan(report, p);
  const choosable = Object.fromEntries(Object.entries(plan.filters).filter(([, f]) => !f.locked).map(([k, f]) => [k, f.options]));
  lines.push(`PLAN ${JSON.stringify({ combinations: plan.combos.length, max: plan.max, choosable })}`);
}
process.stdout.write(lines.join('\n'));
process.exit(errors.length ? 1 : 0);
