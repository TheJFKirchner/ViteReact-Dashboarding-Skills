// What a report can be built from, as JSON on stdout: cards (with the filters and metrics their Analysis
// functions declare), tabs, fast filters with their values, slow parameters, themes and their token values,
// hideable parts, combination limits. Runs as `node -e` with cwd = the project; loads it the way
// npm run check does (Tools/project.mjs: card meta via Vite SSR + python Analysis/check.py).
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const project = await import(pathToFileURL(path.join(process.cwd(), 'Tools', 'project.mjs')).href);
const p = await project.loadProject();
const flat = (node, prefix = '', out = {}) => {
  for (const [k, v] of Object.entries(node)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === 'object') flat(v, key, out);
    else if (key !== 'name') out[key] = v;
  }
  return out;
};
const tokens = Object.fromEntries(p.themes.map((t) => [t, flat(JSON.parse(fs.readFileSync(path.join(process.cwd(), 'Themes', t, 'tokens.json'), 'utf8')))]));
const card = (id) => p.cards[id] ?? {};
const usedFilters = [...new Set(p.registry.flatMap((m) => card(m.meta.id).filters ?? []))].filter((f) => p.FILTERS[f]);
process.stdout.write(JSON.stringify({
  project: p.config.project,
  title: p.config.title,
  theme: p.config.theme,
  themes: p.themes,
  tokens,
  parts: project.REPORT_PARTS ?? ['footer', 'source', 'commentary', 'filters'],
  max_combinations: project.MAX_COMBINATIONS ?? 500,
  hard_max_combinations: project.HARD_MAX_COMBINATIONS ?? 2000,
  tabs: p.tabs.map((t) => ({ id: t.id, label: t.label })),
  sections: p.registry.map((m) => ({
    id: m.meta.id,
    title: m.meta.title,
    tab: m.meta.tab ?? null,
    filters: card(m.meta.id).filters ?? [],
    metrics: Object.keys(card(m.meta.id).metrics ?? {}),
    error: card(m.meta.id).error ?? (card(m.meta.id).module ? null : 'no Analysis function'),
  })),
  filters: Object.fromEntries(usedFilters.map((f) => [f, { label: p.FILTERS[f].label, options: p.filterOptions(f).filter((o) => o !== p.ALL) }])),
  parameters: Object.fromEntries(Object.entries(p.parameters ?? {}).map(([k, s]) => [k, { label: s.label ?? k, value: s.value, options: (s.options ?? []).map((o) => ({ value: String(o.value), label: o.label ?? String(o.value) })) }])),
  all: p.ALL,
  analysis_error: p.analysis?.error ?? null,
}));
process.exit(0);
