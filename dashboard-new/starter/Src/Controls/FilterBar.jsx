import { useFilters } from '../Filters/FilterContext.jsx';
import { useShellText } from '../Lib/agent-context.js';
import Select from './Select.jsx';

/** Fast filters (instant: the Analysis server recomputes the cards from loaded data) and slow filters, the config's
 *  "parameters" (re-query the source: changing one asks first, then re-runs the pipeline). Locked report filters
 *  are excluded by the caller. Used twice: the dashboard-wide bar (above the tabs, with the slow filters) and the
 *  current tab's bar (className "tab-level"). Section filters sit in the section's header (SectionFrame). */
export default function FilterBar({ names, meta, params = [], onParam, busy, className = '' }) {
  const { values, setFilter } = useFilters();
  const text = useShellText();
  if (!names.length && !params.length) return null;
  return (
    <div className={`filter-bar ${className}`.trim()}>
      {names.map((n) => (
        <Select key={n} slot={`filter:${n}`} label={text(`filter:${n}`, meta.filters[n].label)} value={values[n]} options={meta.filters[n].options} onChange={(v) => setFilter(n, v)} />
      ))}
      {params.length > 0 && names.length > 0 && <span className="filter-sep" aria-hidden="true" />}
      {params.map((n) => {
        const p = meta.parameters[n];
        return (
          <Select
            key={n}
            slot={`param:${n}`}
            label={<>{text(`param:${n}`, p.label)} <span className="slow-mark" title="Changing this re-pulls the data (pipeline run)">⟳</span></>}
            value={p.value}
            options={p.options}
            disabled={busy}
            title="Changing this re-pulls the data (pipeline run)"
            onChange={(v) => onParam(n, v)}
          />
        );
      })}
    </div>
  );
}
