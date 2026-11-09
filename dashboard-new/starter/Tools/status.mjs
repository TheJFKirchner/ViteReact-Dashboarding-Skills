// npm run status [-- --json]
// A read-only map of this dashboard: pages, sections (and what each reads), tables, filters, reports, and the
// check result. Use it to get oriented before changing anything. Changes nothing.
// If the cards can't be loaded (a broken file), it still lists what it can from the folders.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, loadProject, readJson, reportSectionIds, validateProject } from './project.mjs';

const asJson = process.argv.includes('--json');
const out = { project: null, pages: [], cards: [], tables: [], filters: {}, parameters: {}, reports: [], check: null, problems: [] };

const safe = (fn, fallback) => {
  try {
    return fn();
  } catch (e) {
    out.problems.push(e.message);
    return fallback;
  }
};
const config = safe(() => readJson('dashboard.config.json'), {});
out.project = { title: config.title ?? null, theme: config.theme ?? null, port: config.server?.port ?? 8765, agent: config.agent?.enabled !== false };

let p = null;
try {
  p = await loadProject();
} catch (e) {
  out.problems.push(`could not load the cards (Src/Sections/index.js): ${e.message}`);
}

if (p) {
  const result = validateProject(p);
  out.pages = (p.tabs ?? []).map((t) => ({ id: t.id, label: t.label, cards: p.registry.filter((m) => m.meta?.tab === t.id).map((m) => m.meta.id) }));
  out.cards = (p.registry ?? []).map((m) => {
    const id = m.meta?.id;
    const a = p.cards[id] ?? {};
    return {
      id,
      title: m.meta?.title,
      page: m.meta?.tab ?? null,
      chart: m.meta?.library,
      size: m.meta?.size ?? 'full',
      analysis: a.module ? `Analysis/${a.module}.py` : null,
      tables: a.tables ?? [],
      filters: a.filters ?? [],
      metrics: Object.keys(a.metrics ?? {}),
      problems: result.cardErrors[id] ?? [],
      built: !(fs.existsSync(path.join(ROOT, 'Src', 'Sections', `${id}.jsx`)) && /Not built yet\./.test(fs.readFileSync(path.join(ROOT, 'Src', 'Sections', `${id}.jsx`), 'utf8'))),
    };
  });
  out.filters = Object.fromEntries(Object.entries(p.FILTERS).map(([k, f]) => [k, { label: f.label, column: f.column, level: f.section ? `section ${f.section}` : f.tab ? `tab ${f.tab}` : 'dashboard', values: f.options.filter((o) => o !== p.ALL) }]));
  out.parameters = p.parameters ?? {};
  out.check = { errors: result.errors, warnings: result.warnings };
}

// tables: from the manifest when there is one, else the files
const manifest = p?.manifest ?? safe(() => JSON.parse(fs.readFileSync(path.join(ROOT, 'Data', 'Current', 'manifest.json'), 'utf8')), null);
if (manifest?.tables) {
  const filterCols = Object.entries(config.filters ?? {}).filter(([k]) => !k.startsWith('_')).map(([k, s]) => s.column ?? k);
  out.tables = Object.entries(manifest.tables).map(([name, t]) => ({
    name,
    rows: t.rows ?? null,
    grain: t.grain ?? null,
    as_of: t.as_of ?? null,
    source: t.source ?? null,
    script: t.script ?? null,
    columns: Object.keys(t.columns ?? {}),
    filterColumns: filterCols.filter((c) => (t.columns ?? {})[c] !== undefined),
    usedBy: out.cards.filter((c) => c.tables.includes(name)).map((c) => c.id),
  }));
} else {
  const dir = path.join(ROOT, 'Data', 'Current');
  out.tables = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => /\.(parquet|csv)$/i.test(f)).map((f) => ({ name: f, rows: null, columns: [] })) : [];
}

// reports
const rdir = path.join(ROOT, 'Reports');
for (const f of fs.existsSync(rdir) ? fs.readdirSync(rdir).filter((x) => x.endsWith('.json')) : []) {
  const r = safe(() => readJson(`Reports/${f}`), null);
  if (!r) continue;
  const ids = p ? reportSectionIds(r, p) : Array.isArray(r.sections) ? r.sections : [];
  const known = new Set(out.cards.map((c) => c.id));
  out.reports.push({ name: f.replace(/\.json$/, ''), title: r.title ?? null, cards: ids, missing: p ? ids.filter((id) => !known.has(id)) : [] });
}

// pipeline scripts and Analysis files nothing points to (useful when tidying)
const pdir = path.join(ROOT, 'Pipeline');
out.pipeline = fs.existsSync(pdir) ? fs.readdirSync(pdir).filter((f) => f.endsWith('.py') && f !== 'run_all.py' && !f.startsWith('_')) : [];

if (asJson) {
  console.log(JSON.stringify(out, null, 2));
  process.exit(0);
}

const line = (s = '') => console.log(s);
line(`${out.project.title ?? '(untitled)'}   theme ${out.project.theme}, data server port ${out.project.port}, design agent ${out.project.agent ? 'on' : 'off'}`);
line();
if (out.pages.length) {
  line('Pages');
  for (const pg of out.pages) line(`  ${pg.id.padEnd(16)} ${pg.label} (${pg.cards.length} section${pg.cards.length === 1 ? '' : 's'})`);
  line();
}
line(`Sections (${out.cards.length}, in page order)`);
if (!out.cards.length) line('  none yet: npm run new-section -- <name>');
for (const c of out.cards) {
  const flags = [c.size === 'half' ? 'half' : null, c.built ? null : 'NOT BUILT', c.problems.length ? `${c.problems.length} problem(s)` : null].filter(Boolean).join(', ');
  line(`  ${c.id.padEnd(28)} ${String(c.title).slice(0, 40).padEnd(40)} ${(c.page ?? '').padEnd(12)} ${String(c.chart).padEnd(8)} ${flags}`);
  line(`  ${''.padEnd(28)} reads ${c.tables.join(', ') || '(no tables)'}; filters ${c.filters.join(', ') || 'none'}; numbers in ${c.analysis ?? '(no Analysis function)'}`);
}
line();
line(`Tables in Data/Current (${out.tables.length})`);
if (!out.tables.length) line('  none yet: npm run pipeline, or put .parquet/.csv files in Data/Current');
for (const t of out.tables) {
  line(`  ${t.name.padEnd(28)} ${t.rows ?? '?'} rows${t.grain ? `, ${t.grain}` : ''}${t.as_of ? `, as of ${t.as_of}` : ''}${t.script ? `, from Pipeline/${t.script}` : ''}`);
  if (t.columns.length) line(`  ${''.padEnd(28)} columns: ${t.columns.join(', ')}`);
  if (t.usedBy) line(`  ${''.padEnd(28)} used by: ${t.usedBy.join(', ') || 'no section'}${t.filterColumns?.length ? `; filterable by ${t.filterColumns.join(', ')}` : ''}`);
}
line();
const fnames = Object.keys(out.filters);
line(`Filters: ${fnames.length ? fnames.map((k) => `${k} (${out.filters[k].level}, ${out.filters[k].values.length} values)`).join(', ') : 'none'}`);
const pnames = Object.keys(out.parameters);
if (pnames.length) line(`Refresh settings: ${pnames.join(', ')}`);
line(`Pipeline scripts: ${out.pipeline.join(', ') || 'none'}`);
line(`Reports: ${out.reports.length ? out.reports.map((r) => `${r.name} (${r.cards.length} sections${r.missing.length ? `, MISSING ${r.missing.join(', ')}` : ''})`).join('; ') : 'none'}`);
line();
if (out.check) {
  line(`Check: ${out.check.errors.length} error(s), ${out.check.warnings.length} warning(s)`);
  for (const e of out.check.errors) line(`  ERROR ${e}`);
  for (const w of out.check.warnings.slice(0, 15)) line(`  warn  ${w}`);
  if (out.check.warnings.length > 15) line(`  ... ${out.check.warnings.length - 15} more warning(s): npm run check`);
}
for (const pr of out.problems) line(`PROBLEM ${pr}`);
