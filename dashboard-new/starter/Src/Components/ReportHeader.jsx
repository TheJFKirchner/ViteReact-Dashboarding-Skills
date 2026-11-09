import { formatDate } from '../Lib/dates.js';
import { useShellText } from '../Lib/agent-context.js';

// data-edit marks page text the dev agent's Page target may change (dashboard.config.json values).
export default function ReportHeader({ title, audience, asOf, source, staleDays, editable }) {
  const text = useShellText();
  return (
    <header className="report-header">
      <h1 data-edit={editable ? 'title' : undefined}>{editable ? text('title', title) : title}</h1>
      {audience && <div className="audience">Prepared for {audience}</div>}
      <div className="meta-line">
        {asOf && <>Data as of {formatDate(asOf)}</>}
        {source && (
          <>
            {asOf ? ' · Source: ' : 'Source: '}
            <span data-edit={editable ? 'dataSource' : undefined}>{editable ? text('dataSource', source) : source}</span>
          </>
        )}
      </div>
      {staleDays !== null && (
        <div className="stale-banner" role="status">
          Data was pulled {staleDays} days ago. Refresh with <code>python Pipeline/run_all.py</code>.
        </div>
      )}
    </header>
  );
}
