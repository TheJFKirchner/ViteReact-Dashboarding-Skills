// npm run new-card -- <name> [options]
// Makes the three pieces of a new card as empty shells, so it shows "Not built yet" and npm run check passes:
//   Src/Sections/s<N>_<name>.jsx       the look (title, note, drawing)
//   Analysis/<page>.py                 the numbers (a function tagged @card, added to the page's file)
//   Src/Sections/index.js              its place (import + list entry; a new page is added to `tabs`)
// Never overwrites anything: stops if the card already exists.
//
// Options:
//   --title "Paid by region"    card title (default: from the name)
//   --page costs                the page (tab) it goes on, and the Analysis file its numbers go in
//   --chart echarts             echarts (default) | plotly | table | kpi | text
//   --size half                 half width (sits next to another half card)
//   --tables claims_monthly     tables it reads (comma-separated; must be in Data/Current)
//   --filters region,product    dashboard filters that apply (default: all of them; "none" for none)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SECTIONS = path.join(ROOT, 'Src', 'Sections');
const INDEX = path.join(SECTIONS, 'index.js');
const ANALYSIS = path.join(ROOT, 'Analysis');
const CHARTS = { echarts: 'echarts', plotly: 'plotly', table: 'none', kpi: 'none', text: 'none' };

function fail(msg) {
  console.log(`new-card: ${msg}`);
  process.exit(1);
}

// ---- arguments
const argv = process.argv.slice(2);
const opts = {};
const positional = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a.startsWith('--')) {
    const [k, inline] = a.slice(2).split('=', 2);
    opts[k] = inline ?? (argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : 'true');
  } else positional.push(a);
}
if (!positional.length || opts.help) {
  console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').filter((l) => l.startsWith('//')).map((l) => l.slice(3)).join('\n'));
  process.exit(positional.length ? 0 : 1);
}
const chart = (opts.chart ?? 'echarts').toLowerCase();
if (!CHARTS[chart]) fail(`--chart must be one of ${Object.keys(CHARTS).join(', ')} (got "${chart}")`);
const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
const list = (s) => (s && s !== 'true' ? String(s).split(',').map((x) => x.trim()).filter(Boolean) : []);

// ---- what exists already
/** Replace what's between the [ and ] of a matched `... = [ ... ];` block. */
const fillBlock = (block, body) => block.slice(0, block.indexOf('[') + 1) + body + block.slice(block.lastIndexOf(']'));
const read = (f) => (fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '');
const indexSrc = read(INDEX);
if (!indexSrc) fail('Src/Sections/index.js not found (run this inside a dashboard project)');
const sectionFiles = fs.readdirSync(SECTIONS).filter((f) => /^s\d+_.*\.jsx$/.test(f) && !f.includes('.agent-preview.'));
const analysisFiles = fs.readdirSync(ANALYSIS).filter((f) => f.endsWith('.py'));
const analysisIds = analysisFiles.flatMap((f) => [...read(path.join(ANALYSIS, f)).matchAll(/@card\(\s*["'](s\d+_[a-z0-9_]+)["']/g)].map((m) => m[1]));
const usedIds = new Set([...sectionFiles.map((f) => f.replace(/\.jsx$/, '')), ...analysisIds]);
const usedNumbers = new Set([...usedIds].map((id) => Number(/^s(\d+)_/.exec(id)[1])));

// ---- the card id
let id = positional[0];
if (!/^s\d+_[a-z0-9_]+$/.test(id)) {
  const name = slug(id);
  if (!name) fail(`"${id}" doesn't make a usable name (use letters and numbers, e.g. paid_by_region)`);
  const next = Math.max(0, ...usedNumbers) + 1;
  id = `s${next}_${name}`;
}
const number = Number(/^s(\d+)_/.exec(id)[1]);
if (usedIds.has(id)) fail(`${id} already exists (Src/Sections/${id}.jsx or an @card("${id}") in Analysis/)`);
if (usedNumbers.has(number)) fail(`the number s${number} is already used by another card; leave the number off and one is picked`);
const shortName = id.replace(/^s\d+_/, '');
const title = opts.title && opts.title !== 'true' ? opts.title : shortName.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

// ---- pages
const tabsBlock = /export\s+const\s+tabs\s*=\s*\[([\s\S]*?)\]\s*;/.exec(indexSrc);
const tabIds = tabsBlock ? [...tabsBlock[1].matchAll(/id\s*:\s*['"]([^'"]+)['"]/g)].map((m) => m[1]) : [];
const defaultBlock = /export\s+default\s+\[([\s\S]*?)\]\s*;/.exec(indexSrc);
const hasCards = defaultBlock ? /[A-Za-z_]/.test(defaultBlock[1].replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')) : sectionFiles.length > 0;
const page = opts.page && opts.page !== 'true' ? slug(opts.page) : null;
let tab = null; // meta.tab
let addTab = null; // a new { id, label } for `tabs`
const notes = [];
if (tabIds.length) {
  tab = page ?? tabIds[0];
  if (!tabIds.includes(tab)) addTab = tab;
} else if (page) {
  if (hasCards) notes.push(`this dashboard has one page (no tabs), so the card goes on it; "${page}" only names its Analysis file. To split into pages, see the dashboard-work skill, references/organizing.md.`);
  else (tab = page), (addTab = page);
}
const analysisName = page ?? tab ?? 'overview';
const analysisFile = path.join(ANALYSIS, `${analysisName}.py`);
if (['server', 'check', 'precompute'].includes(analysisName) || analysisName.startsWith('_')) fail(`"${analysisName}" can't be a page name (it's reserved)`);

// ---- tables and filters
let config = {};
try {
  config = JSON.parse(read(path.join(ROOT, 'dashboard.config.json')) || '{}');
} catch (e) {
  fail(`dashboard.config.json is not valid JSON: ${e.message}`);
}
const allFilters = Object.keys(config.filters ?? {}).filter((k) => !k.startsWith('_'));
const filters = opts.filters === 'none' ? [] : opts.filters ? list(opts.filters) : allFilters;
const unknown = filters.filter((f) => !allFilters.includes(f));
if (unknown.length) fail(`filter(s) ${unknown.join(', ')} not in dashboard.config.json "filters" (${allFilters.join(', ') || 'none defined'})`);
const tables = list(opts.tables).map(slug);
const manifest = (() => {
  try {
    return JSON.parse(read(path.join(ROOT, 'Data', 'Current', 'manifest.json')) || '{}').tables ?? {};
  } catch {
    return {};
  }
})();
const dataFiles = fs.existsSync(path.join(ROOT, 'Data', 'Current')) ? fs.readdirSync(path.join(ROOT, 'Data', 'Current')).map((f) => slug(f.replace(/\.(parquet|csv)$/i, ''))) : [];
for (const t of tables) if (!manifest[t] && !dataFiles.includes(t)) notes.push(`table "${t}" isn't in Data/Current yet; npm run check will say so until it is.`);

// ---- the card file
const pyList = (xs) => `[${xs.map((x) => JSON.stringify(x)).join(', ')}]`;
const metaLine = `export const meta = { id: '${id}', title: ${JSON.stringify(title)}${tab ? `, tab: '${tab}'` : ''}, library: '${CHARTS[chart]}'${opts.size === 'half' ? ", size: 'half'" : ''} };`;
const hints = {
  echarts: "Draw with ChartECharts (see dashboard-work: references/cards.md): build an ECharts option from data, colors from fx().",
  plotly: "Draw with ChartPlotly (../Components/ChartPlotly.jsx), e.g. for box plots or histograms.",
  table: 'A plain <table className="data">; cells can use className "good" / "bad".',
  kpi: 'A row of KpiTile (../Components/KpiTile.jsx) inside <div className="kpis">.',
  text: 'Text or a short list built from metrics, formatted with FORMATS.',
};
const jsx = `// Numbers: Analysis/${analysisName}.py (${shortName}). ${hints[chart]}
${metaLine}

// The note above the card. Refer to numbers by name, e.g. {total_paid|money}. Leave empty for no note.
export const commentary = \`\`;

export default function Section({ data, metrics }) {
  return <p style={{ color: 'var(--text-muted)' }}>Not built yet.</p>;
}
`;

// ---- the Analysis function
let analysisSrc = read(analysisFile);
const defNames = new Set([...analysisSrc.matchAll(/^def\s+([A-Za-z_]\w*)/gm)].map((m) => m[1]));
let fnName = /^[a-z_]/.test(shortName) ? shortName : `card_${shortName}`;
for (let i = 2; defNames.has(fnName); i++) fnName = `${shortName}_${i}`;
const header = analysisSrc
  ? ''
  : `"""${analysisName.replace(/_/g, ' ')}: the numbers for this page's cards (one function per card)."""\nfrom Shared.registry import card\n`;
if (analysisSrc && !/from\s+Shared\.registry\s+import[^\n]*\bcard\b/.test(analysisSrc)) analysisSrc = `from Shared.registry import card\n${analysisSrc}`;
const fn = `

@card("${id}", tables=${pyList(tables)}, filters=${pyList(filters)})
def ${fnName}(t):
    """${title}. Not built yet."""
    # read tables as t.<table name> (pandas, filters already applied); see dashboard-work: references/cards.md
    return {"data": {}, "metrics": {}}
`;

// ---- the registry (index.js)
let newIndex = null;
if (defaultBlock) {
  let src = indexSrc;
  const importLine = `import * as ${id} from './${id}.jsx';`;
  const imports = [...src.matchAll(/^import[^\n]*\n/gm)];
  // after the last import; with none yet, after the comment lines at the top of the file
  const lead = /^(?:\s*\/\/[^\n]*\n)*/.exec(src)[0].length;
  const at = imports.length ? imports.at(-1).index + imports.at(-1)[0].length : lead;
  src = src.slice(0, at) + importLine + '\n' + src.slice(at);
  if (addTab) {
    const tb = /export\s+const\s+tabs\s*=\s*\[([\s\S]*?)\]\s*;/.exec(src);
    if (tb) {
      const label = addTab.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
      const inner = tb[1].replace(/\s+$/, '');
      const sep = inner.trim() && !inner.trim().endsWith(',') ? ',' : '';
      const body = `${inner}${sep}\n  { id: '${addTab}', label: '${label}' },\n`;
      src = src.slice(0, tb.index) + fillBlock(tb[0], body) + src.slice(tb.index + tb[0].length);
    } else notes.push(`add the page to Src/Sections/index.js by hand: export const tabs = [{ id: '${addTab}', label: '...' }];`);
  }
  const db = /export\s+default\s+\[([\s\S]*?)\]\s*;/.exec(src);
  const inner = db[1].replace(/\s+$/, '');
  const sep = inner.replace(/\/\/.*$/gm, '').trim() && !inner.replace(/\/\/.*$/gm, '').trim().endsWith(',') ? ',' : '';
  src = src.slice(0, db.index) + fillBlock(db[0], `${inner}${sep}\n  ${id},\n`) + src.slice(db.index + db[0].length);
  newIndex = src;
}

// ---- write
fs.writeFileSync(path.join(SECTIONS, `${id}.jsx`), jsx);
fs.writeFileSync(analysisFile, (analysisSrc ? analysisSrc.replace(/\s*$/, '\n') : header) + fn);
if (newIndex) fs.writeFileSync(INDEX, newIndex);

console.log(`new-card: ${id} ("${title}")`);
console.log(`  Src/Sections/${id}.jsx      the look (shows "Not built yet")`);
console.log(`  Analysis/${analysisName}.py${' '.repeat(Math.max(1, 18 - analysisName.length))}the numbers: ${fnName}(t), tables ${pyList(tables)}, filters ${pyList(filters)}`);
if (newIndex) console.log(`  Src/Sections/index.js       added to the list${addTab ? `, new page "${addTab}"` : ''}${tab ? ` (page: ${tab})` : ''}`);
else {
  console.log('  Src/Sections/index.js       NOT changed (couldn\'t find `export default [ ... ];`). Add these two lines by hand:');
  console.log(`      import * as ${id} from './${id}.jsx';      and ${id} in the default-exported list`);
}
for (const n of notes) console.log(`  note: ${n}`);
