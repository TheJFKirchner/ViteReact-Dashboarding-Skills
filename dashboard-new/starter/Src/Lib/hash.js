// The view in the URL hash: #tab=costs&region=East&channel=Online
// The tab and the reader's fast filter choices live here, so a reload or a shared link opens the same view
// (in exports too). Filters at "All" and locked report filters are left out. "tab" is never a filter name.
import { ALL } from './source.js';

/** { tab, <filter>: value, ... } from the current hash. */
export function readHash() {
  return Object.fromEntries(new URLSearchParams(window.location.hash.slice(1)));
}

/** Rewrite the hash (no new history entry, no hashchange event) when it differs. */
export function writeHash(tab, filters) {
  const q = new URLSearchParams();
  if (tab) q.set('tab', tab);
  for (const [name, value] of Object.entries(filters)) {
    if (name !== 'tab' && value && value !== ALL) q.set(name, value);
  }
  const want = q.toString() ? `#${q}` : '';
  if (want !== window.location.hash) {
    window.history.replaceState(null, '', want || window.location.pathname + window.location.search);
  }
}
