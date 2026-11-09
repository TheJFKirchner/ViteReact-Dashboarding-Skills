// Section registry: the ONLY list of sections, in display order, plus the tabs they are grouped under.
// Add a section: create Src/Sections/s<N>_<name>.jsx (next unused number), import it here, add it to the array.
// Pages: list them in `tabs` and give each section a meta.tab. For a single page, leave `tabs` as [] and omit meta.tab.
import * as s1_summary from './s1_summary.jsx';
import * as s2_revenue_trend from './s2_revenue_trend.jsx';

export const tabs = [
  { id: 'overview', label: 'Overview' },
];

export default [
  s1_summary, s2_revenue_trend,
];
