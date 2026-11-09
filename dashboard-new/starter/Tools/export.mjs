// npm run export -- <report>                export Reports/<report>.json
// npm run export -- 1,3,5                  ad hoc: card numbers (1 or s1) or ids -> writes Reports/_adhoc_<date>.json, then exports it
// npm run export -- tabs:overview          ad hoc: every card on those tabs
//
// Output: Exports/<project>_<report>_<YYYY-MM-DD>.html: one self-contained file (never overwrites; _2, _3 ...).
// The page needs no server: every allowed filter combination is precomputed (Analysis/precompute.py).
//   1. validate the project (errors on cards in the report stop the export) and the report (v2 format)
//   2. pinned "parameters" that differ from Data/Current: pull them into a separate folder (Data/.export-pull) and
//      precompute from there; Data/Current and the running dashboard are never touched; the folder is removed after
//   3. precompute: show the combination count + estimated size, refuse above the limits, then compute
//   4. .export/{precomputed.json, report.json, entry.jsx, index.html} -> vite build (vite.export.config.js)
//   5. offline check (no external references), write Exports/...html
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { build } from 'vite';
import {
  ALL, PYTHON, ROOT, daysBetween, loadProject, printResults, python, readJson, reportPlan, reportSectionIds, sectionCommentary, todayIso,
  validateProject, validateReport,
} from './project.mjs';

const WARN_MB = 5;
const STOP_MB = 25;
const EXPORT_DIR = path.join(ROOT, '.export');
const REPORTS = path.join(ROOT, 'Reports');

class ExportError extends Error {}
const fail = (msg) => {
  throw new ExportError(msg);
};

/** path, or path_2, path_3 ... (first that doesn't exist) */
function uniquePath(dir, stem, ext) {
  for (let n = 1; ; n++) {
    const p = path.join(dir, `${stem}${n === 1 ? '' : `_${n}`}${ext}`);
    if (!fs.existsSync(p)) return p;
  }
}

const mb = (bytes) => `${(bytes / 1e6).toFixed(2)} MB`;

const PINNED_DIR = path.join(ROOT, 'Data', '.export-pull');

/** python Pipeline/run_all.py --param k=v ... --out Data/.export-pull --no-swap (Data/Current untouched). */
function pullPinned(params, why) {
  const args = [...Object.entries(params).flatMap(([k, v]) => ['--param', `${k}=${v}`]), '--out', PINNED_DIR, '--no-swap'];
  console.log(`${why}: python Pipeline/run_all.py ${args.join(' ')}`);
  const r = spawnSync(PYTHON, [path.join(ROOT, 'Pipeline', 'run_all.py'), ...args], { cwd: path.join(ROOT, 'Pipeline'), stdio: 'inherit' });
  return r.status === 0;
}

const loadedParams = () => {
  const f = path.join(ROOT, 'Data', 'Current', 'manifest.json');
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')).params ?? {} : {};
};

const cleanupPinned = () => fs.rmSync(PINNED_DIR, { recursive: true, force: true });
process.once('SIGINT', () => {
  cleanupPinned();
  process.exit(130);
});

// join with "," so `a,c`, `a c` and shells that split commas (PowerShell) all work
const arg = process.argv.slice(2).join(',').replace(/,+/g, ',').replace(/\s/g, '').replace(/^,|,$/g, '');

async function main() {
  const p = await loadProject();

  if (!arg) {
    const reports = fs.readdirSync(REPORTS).filter((f) => f.endsWith('.json') && !f.startsWith('_')).map((f) => f.slice(0, -5));
    console.log('Usage: npm run export -- <report>   |   npm run export -- 1,3   |   npm run export -- tabs:overview');
    console.log(`Reports: ${reports.join(', ') || '(none)'}`);
    console.log(`Sections: ${p.registry.map((m) => m.meta.id).join(', ')}`);
    if (p.tabs.length) console.log(`Tabs: ${p.tabs.map((t) => t.id).join(', ')}`);
    process.exitCode = 1;
    return;
  }

  // 1. Resolve the report (named file, or ad hoc card / tab list -> new _adhoc_ file)
  let name;
  let report;
  const today = todayIso();
  const viewerChooses = (ids) => {
    // ad hoc: every filter the cards use is choosable among all its values, starting at "All"
    const used = Object.keys(p.FILTERS).filter((f) => ids.some((id) => p.cards[id]?.filters?.includes(f)));
    return Object.fromEntries(used.map((f) => [f, { value: ALL, options: p.filterOptions(f) }]));
  };
  if (fs.existsSync(path.join(REPORTS, `${arg}.json`))) {
    name = arg;
    try {
      report = readJson(`Reports/${arg}.json`);
    } catch (e) {
      fail(`Reports/${arg}.json is not valid JSON: ${e.message}`);
    }
  } else if (/^tabs:[a-z0-9_-]+(,[a-z0-9_-]+)*$/.test(arg)) {
    const tabs = arg.slice(5).split(',');
    for (const t of tabs) if (!p.tabs.some((x) => x.id === t)) fail(`ad hoc: no tab "${t}" (tabs: ${p.tabs.map((x) => x.id).join(', ')})`);
    const labels = tabs.map((t) => p.tabs.find((x) => x.id === t).label);
    report = { title: `${p.config.title}: ${labels.join(' + ')}`, audience: null, tabs, filters: {}, commentary: {}, theme: p.config.theme };
    report.filters = viewerChooses(reportSectionIds(report, p));
  } else if (/^[a-z0-9_]+(,[a-z0-9_]+)*$/.test(arg)) {
    const ids = arg.split(',').map((tok) => {
      const num = /^s?(\d+)$/.exec(tok)?.[1];
      const m = p.registry.find((s) => s.meta.id === tok || (num && s.meta.id.startsWith(`s${num}_`)));
      if (!m) fail(`ad hoc: no section with number or id "${tok}" (sections: ${p.registry.map((s) => s.meta.id).join(', ')})`);
      return m.meta.id;
    });
    report = { title: `${p.config.title} (selected sections)`, audience: null, sections: ids, filters: viewerChooses(ids), commentary: {}, theme: p.config.theme };
  } else {
    fail(`no report Reports/${arg}.json, and "${arg}" is not a section list (1,3,5) or tab list (tabs:overview)`);
  }

  // 2. Validate: project errors on the report's cards (or global ones) stop the export; others are only listed
  const sectionIds = reportSectionIds(report, p);
  const project = validateProject(p);
  const elsewhere = Object.entries(project.cardErrors).filter(([id]) => !sectionIds.includes(id)).flatMap(([, msgs]) => msgs);
  const blocking = project.errors.filter((e) => !elsewhere.includes(e));
  printResults({ warnings: [...project.warnings, ...elsewhere.map((e) => `(not in this report) ${e}`)], errors: blocking });
  if (blocking.length) fail('fix the errors above (npm run check) before exporting');

  if (!name) {
    const file = uniquePath(REPORTS, `_adhoc_${today}`, '.json');
    fs.writeFileSync(file, JSON.stringify(report, null, 2) + '\n');
    name = path.basename(file, '.json');
    console.log(`Wrote ad hoc report: Reports/${name}.json`);
  }
  const reportFile = path.join(REPORTS, `${name}.json`);
  const checked = validateReport(name, report, p);
  printResults(checked);
  if (checked.errors.length) fail(`report ${name} is invalid`);
  const plan = reportPlan(report, p);

  // 3. Pin slow parameters
  const current = loadedParams();
  const pinned = Object.fromEntries(Object.entries(report.parameters ?? {}).map(([k, v]) => [k, String(v)]));
  const differs = Object.entries(pinned).filter(([k, v]) => String(current[k] ?? '') !== v);
  const generated = p.manifest?.generated_at;
  if (!differs.length && generated && daysBetween(generated, today) > (p.config.staleDays ?? 7)) {
    console.log(`WARN  Data/Current was pulled ${daysBetween(generated, today)} days ago (${generated.slice(0, 10)}); the export uses it as-is. Refresh: python Pipeline/run_all.py`);
  }

  let dataEnv = {}; // precompute reads Data/Current, or the pinned pull
  try {
    if (differs.length) {
      dataEnv = { DASH_DATA_DIR: PINNED_DIR };
      if (!pullPinned({ ...current, ...pinned }, `Pinning ${differs.map(([k, v]) => `${k}=${v}`).join(', ')} (loaded: ${differs.map(([k]) => `${k}=${current[k] ?? 'default'}`).join(', ')})`)) {
        fail('the pipeline run with the report\'s parameters failed');
      }
    }

    // 4. Precompute: estimate first (count + size), then compute
    fs.rmSync(EXPORT_DIR, { recursive: true, force: true });
    fs.mkdirSync(EXPORT_DIR, { recursive: true });
    const pre = (extra) => {
      const r = python([path.join('Analysis', 'precompute.py'), '--report', reportFile, '--cards', sectionIds.join(','), ...extra], { env: { ...process.env, ...dataEnv } });
      for (const line of r.stderr.trim().split('\n').filter(Boolean)) console.log(/^(ERROR|WARN)/.test(line) ? line : `  ${line}`);
      let summary = null;
      try {
        summary = JSON.parse(r.stdout.trim().split('\n').at(-1));
      } catch { /* no summary: the error is in stderr */ }
      return { ok: r.code === 0, summary };
    };
    const est = pre(['--estimate']);
    if (est.summary) {
      const s = est.summary;
      const choose = Object.entries(s.filters).map(([k, v]) => `${k} (${v.length})`).join(', ') || 'none';
      console.log(`Combinations: ${s.combinations} (limit ${s.max_combinations}); choosable: ${choose}; fixed: ${JSON.stringify(s.fixed)}; parameters: ${JSON.stringify(s.parameters)}`);
      console.log(`Precompute: ${s.card_runs} card run(s) for ${s.cards} card(s), estimated ${mb(s.estimated_bytes)} (~${s.estimated_seconds}s)`);
    }
    if (!est.ok) fail('precompute refused the report (see above)');
    if (est.summary.combinations > est.summary.max_combinations) fail(`${est.summary.combinations} combinations is over the limit of ${est.summary.max_combinations}`);
    if (est.summary.estimated_bytes > STOP_MB * 1e6) fail(`estimated ${mb(est.summary.estimated_bytes)} is over the ${STOP_MB} MB limit`);
    if (est.summary.combinations !== plan.combos.length) console.log(`WARN  precompute counted ${est.summary.combinations} combinations, the report check ${plan.combos.length}; using precompute's`);

    const precomputedFile = path.join(EXPORT_DIR, 'precomputed.json');
    const full = pre(['--out', precomputedFile]);
    if (!full.ok || !fs.existsSync(precomputedFile)) fail('precompute failed (see above)');
    const bytes = fs.statSync(precomputedFile).size;
    if (bytes > STOP_MB * 1e6) fail(`precomputed results are ${mb(bytes)}, over the ${STOP_MB} MB limit`);
    if (bytes > WARN_MB * 1e6) console.log(`WARN  precomputed results are ${mb(bytes)} (over ${WARN_MB} MB); the export will be slow to open`);
    console.log(`Precomputed ${full.summary.card_runs} card result(s): ${mb(bytes)} in ${full.summary.seconds}s`);
    const precomputed = JSON.parse(fs.readFileSync(precomputedFile, 'utf8'));
    cleanupPinned(); // the pinned pull is no longer needed

    // 5. Temp entry: renders only the chosen sections; App gets the report's filters and parameters
    const byId = new Map(p.registry.map((m) => [m.meta.id, m]));
    const included = sectionIds.map((id) => byId.get(id));
    // report tabs: the report's own grouping (reportTabs, incl. text tabs) or the dashboard tabs it uses
    const reportTabs = Array.isArray(report.reportTabs)
      ? report.reportTabs.map((t, i) => ({ id: `r${i + 1}`, label: t.label, ...(t.text ? { text: t.text } : {}), sections: t.sections ?? [] }))
      : null;
    const tabOf = reportTabs ? Object.fromEntries(reportTabs.flatMap((t) => t.sections.map((id) => [id, t.id]))) : null;
    const includedTabs = reportTabs ? reportTabs.map(({ sections, ...t }) => t) : p.tabs.filter((t) => included.some((m) => m.meta.tab === t.id)); // eslint-disable-line no-unused-vars
    const runtimeReport = {
      name,
      title: report.title,
      audience: report.audience || null,
      theme: report.theme || p.config.theme,
      sections: sectionIds,
      filters: plan.filters, // {name: {value, locked, options}}; the FilterBar shows the unlocked ones
      parameters: Object.fromEntries(Object.entries(precomputed.meta.parameters).map(([k, v]) => [k, v.value])),
      combinations: precomputed.combos.length,
      exportDate: today,
      inspect: report.inspect === true, // "About this data" buttons (opt-in per report)
      hide: report.hide ?? [],
      notice: report.notice || null,
      themeOverrides: report.themeOverrides ?? null,
    };
    fs.writeFileSync(path.join(EXPORT_DIR, 'report.json'), JSON.stringify(runtimeReport, null, 2));

    const imports = [];
    const commentary = [];
    included.forEach((m, i) => {
      const id = m.meta.id;
      imports.push(`import * as m${i} from '../Src/Sections/${id}.jsx';`);
      imports.push(tabOf ? `const s${i} = { ...m${i}, meta: { ...m${i}.meta, tab: ${JSON.stringify(tabOf[id])} } };` : `const s${i} = m${i};`);
      const own = report.commentary?.[id];
      const text = typeof own === 'string' ? own : own === false ? null : sectionCommentary(m);
      if (text) commentary.push(`${JSON.stringify(id)}: ${JSON.stringify(text)}`);
    });
    fs.writeFileSync(
      path.join(EXPORT_DIR, 'entry.jsx'),
      [
        '// GENERATED by Tools/export.mjs; do not edit.',
        "import { mount } from '../Src/App.jsx';",
        "import report from './report.json';",
        ...imports,
        `const tabs = ${JSON.stringify(includedTabs)};`,
        `mount({ sections: [${included.map((_, i) => `s${i}`).join(', ')}], tabs, commentary: { ${commentary.join(', ')} }, report });`,
        '',
      ].join('\n'),
    );
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
    fs.writeFileSync(
      path.join(EXPORT_DIR, 'index.html'),
      `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="UTF-8" />\n<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n<title>${esc(report.title)}</title>\n</head>\n<body>\n<div id="root"></div>\n<script type="module" src="./entry.jsx"></script>\n</body>\n</html>\n`,
    );

    // 6. Single-file build (Plotly is bundled only if an included section imports ChartPlotly)
    console.log(`Building ${name}: ${sectionIds.join(', ')}${includedTabs.length ? ` (tabs: ${includedTabs.map((t) => t.id).join(', ')})` : ''}`);
    // loadProject() started a Vite dev server, which sets NODE_ENV=development; without this reset the
    // export would be a development build (larger React, and dev-only code such as the section agent).
    process.env.NODE_ENV = 'production';
    await build({ configFile: path.join(ROOT, 'vite.export.config.js'), mode: 'production', logLevel: 'warn' });

    const built = fs.readFileSync(path.join(EXPORT_DIR, 'dist', 'index.html'), 'utf8');
    const tagsOnly = built.replace(/(<(script|style)\b[^>]*>)[\s\S]*?<\/\2>/gi, '$1');
    if (/<script[^>]+\bsrc=|<link[^>]+\bhref=/i.test(tagsOnly)) fail('build output still references external files; it would not open offline');
    if (!/\bcombos\\?"?:/.test(built)) fail('build output does not contain the precomputed results (check the @precomputed alias in vite.export.config.js)');

    // 7. Write Exports/<project>_<report>_<date>.html without overwriting, print path + size
    const outDir = path.join(ROOT, 'Exports');
    fs.mkdirSync(outDir, { recursive: true });
    const reportPart = name.startsWith('_adhoc_') ? 'adhoc' : name;
    const out = uniquePath(outDir, `${p.config.project}_${reportPart}_${today}`, '.html');
    fs.writeFileSync(out, built);
    fs.rmSync(EXPORT_DIR, { recursive: true, force: true });
    console.log(`Exported ${path.relative(ROOT, out)} (${mb(Buffer.byteLength(built))}; ${precomputed.combos.length} combination(s), results ${mb(bytes)})`);
  } finally {
    cleanupPinned();
  }
}

try {
  await main();
} catch (e) {
  console.log(`ERROR ${e instanceof ExportError ? e.message : e.stack ?? e}`);
  process.exitCode = 1;
}
