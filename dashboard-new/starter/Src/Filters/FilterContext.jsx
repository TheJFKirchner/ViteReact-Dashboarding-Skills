// Shared fast filter state. Any filter can be fast or slow, set in dashboard.config.json:
//   "filters"    fast: every value is in the loaded tables; the Analysis server narrows rows on every request
//                (options come from the data). State here, per reader, mirrored in the URL hash (App.jsx HashSync).
//   "parameters" slow: the data for a value has to be pulled on its own; changing one re-runs the pipeline. Its
//                value is server state (Data/Current/manifest.json "params"), shared by everyone.
// Cards opt in to fast filters in their Analysis function: @card(..., filters=[...]).
import { createContext, useContext, useMemo, useState } from 'react';

export { ALL } from '../Lib/source.js';

const Ctx = createContext(null);

export function FilterProvider({ initial, children }) {
  const [values, setValues] = useState(initial);
  const value = useMemo(() => ({ values, setFilter: (name, v) => setValues((s) => ({ ...s, [name]: v })) }), [values]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFilters() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useFilters must be used inside <FilterProvider>');
  return ctx;
}
