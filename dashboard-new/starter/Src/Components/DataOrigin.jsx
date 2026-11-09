// Read-only "About this data" panel: which datasets feed a section, their source and as-of date,
// and the filters applied. No file names or code (that's for the dev Inspect panel only).
import { formatDate } from '../Lib/dates.js';
import { ALL } from '../Filters/FilterContext.jsx';

export default function DataOrigin({ origin, dev = false }) {
  const { datasets, filters } = origin;
  return (
    <div className="data-origin">
      {datasets.map((d) => (
        <div className="data-origin-set" key={d.name}>
          <div className="data-origin-name">{d.label}</div>
          <dl>
            {d.grain && <><dt>Detail</dt><dd>{d.grain}</dd></>}
            {d.source && <><dt>Source</dt><dd>{d.source}</dd></>}
            <dt>Data as of</dt><dd>{d.asOf ? formatDate(d.asOf) : 'as-of date not recorded'}</dd>
            {dev && <><dt>Dataset</dt><dd><code>{d.name}</code>{d.rows !== null && ` · ${d.rows.toLocaleString()} rows`}{d.script && <> · written by <code>Pipeline/{d.script}</code></>}</dd></>}
            {dev && d.columns.length > 0 && <><dt>Columns</dt><dd>{d.columns.join(', ')}</dd></>}
          </dl>
        </div>
      ))}
      {filters.length > 0 && (
        <div className="data-origin-filters">
          <span>Filters:</span>{' '}
          {filters.map((f, i) => (
            <span key={f.name}>
              {i > 0 && ' · '}
              {f.label}: <b>{f.value === ALL ? 'All' : f.value}</b>
              {f.locked ? ' (fixed for this report)' : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
