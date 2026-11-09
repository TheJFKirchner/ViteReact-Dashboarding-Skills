// ISO date helpers (dates are "YYYY-MM-DD" strings everywhere).

export function formatDate(iso) {
  if (!iso) return 'unknown';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

export const todayIso = () => new Date().toLocaleDateString('en-CA'); // local YYYY-MM-DD

export function daysBetween(fromIso, toIso) {
  return Math.round((Date.parse(toIso.slice(0, 10)) - Date.parse(fromIso.slice(0, 10))) / 86_400_000);
}

/** "Data as of": the run's as_of parameter, else the earliest as_of among the given tables (conservative). */
export function dataAsOf(manifest, names) {
  if (manifest?.params?.as_of) return manifest.params.as_of;
  const dates = names.map((n) => manifest?.tables?.[n]?.as_of).filter(Boolean).sort();
  return dates[0] ?? null;
}
