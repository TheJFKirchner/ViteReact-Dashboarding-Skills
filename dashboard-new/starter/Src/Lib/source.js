// The ONLY place the dashboard gets data from.
//   Live (npm run dev / hosted): the Analysis server (Analysis/server.py) at /api.
//   Export (standalone HTML):    results precomputed by Tools/export.mjs for the report's filter combinations.
// Cards never fetch: SectionFrame asks here and passes { data, metrics } as props.
import precomputed from '@precomputed';

export const ALL = 'All';
export const isStatic = Boolean(precomputed);

/** "channel=Online|region=All": a card's filter values in a stable order. */
export function comboKey(names, values) {
  return [...names].sort().map((n) => `${n}=${values[n] ?? ALL}`).join('|');
}

async function json(url, init) {
  const res = await fetch(url, init);
  let body;
  try {
    body = await res.json();
  } catch {
    throw new Error(`${url}: the Analysis server did not answer (is it running? npm run dev starts it)`);
  }
  if (!res.ok && !body?.error) throw new Error(`${url}: HTTP ${res.status}`);
  return body;
}

/** { filters, parameters, cards, manifest, version, pipeline } */
export async function getMeta() {
  if (precomputed) return precomputed.meta;
  const meta = await json('/api/meta');
  if (meta.error && !meta.filters) throw new Error(meta.error);
  return meta;
}

/** { data, metrics } or { error } for one card and its filter values. */
export async function getCard(id, filterNames, values) {
  if (precomputed) {
    const hit = precomputed.cards[id]?.[comboKey(filterNames, values)];
    return hit ?? { error: 'This filter combination is not included in this report.', notIncluded: true };
  }
  const qs = new URLSearchParams(filterNames.map((n) => [n, values[n] ?? ALL]));
  return json(`/api/card/${encodeURIComponent(id)}?${qs}`);
}

export const getStatus = () => json('/api/pipeline/status');

export const runPipeline = (params) =>
  json('/api/pipeline/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params }) });
