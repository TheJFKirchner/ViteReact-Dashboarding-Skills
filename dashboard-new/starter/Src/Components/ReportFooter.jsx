import { formatDate } from '../Lib/dates.js';

export default function ReportFooter({ reportName, exportDate, asOf }) {
  return (
    <footer className="report-footer">
      Report: {reportName} · Exported {formatDate(exportDate)}{asOf && <> · Data as of {formatDate(asOf)}</>}
    </footer>
  );
}
