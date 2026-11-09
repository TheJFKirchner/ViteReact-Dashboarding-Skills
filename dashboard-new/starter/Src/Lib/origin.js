// "Where does this come from?" for one card, in business terms.
// Used by the export inspector (reports with "inspect": true) and the dev agent's Inspect panel.
// Reads the server's meta: which tables the card's Analysis function reads, the manifest, the filters.
import { ALL } from './source.js';

const humanize = (s) => String(s).replace(/_/g, ' ');
const grainText = (g) => humanize(g).replace(/\s+x\s+/g, ' × ');

/** { datasets: [{ name, label, described, grain, source, asOf, rows, script, columns }], filters: [{ label, value, locked }] } */
export function dataOrigin(cardId, meta, values = {}, reportFilters = {}) {
  const info = meta?.cards?.[cardId] ?? { tables: [], filters: [] };
  const datasets = (info.tables ?? []).map((name) => {
    const e = meta?.manifest?.tables?.[name] ?? {};
    return {
      name,
      label: e.description || humanize(name).replace(/^./, (c) => c.toUpperCase()),
      described: Boolean(e.description),
      grain: e.grain ? grainText(e.grain) : null,
      source: e.source ?? null,
      asOf: e.as_of ?? null,
      rows: e.rows ?? null,
      script: e.script ?? null,
      columns: e.columns ? Object.keys(e.columns) : [],
    };
  });
  const filters = (info.filters ?? [])
    .filter((n) => meta?.filters?.[n])
    .map((n) => ({ name: n, label: meta.filters[n].label, value: values[n] ?? reportFilters[n]?.value ?? ALL, locked: Boolean(reportFilters[n]?.locked) }));
  return { datasets, filters };
}
