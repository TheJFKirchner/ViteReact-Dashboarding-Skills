// EXAMPLE section (ECharts line with area fill; colors from fx(), never hex). Replace with real sections.
import { useMemo } from 'react';
import ChartECharts from '../Components/ChartECharts.jsx';
import { FORMATS } from '../Lib/commentary.js';
import { fx } from '../Lib/theme.js';

// Numbers come from Analysis/example.py (revenue_trend): data = { months, revenue }, metrics for commentary.
export const meta = {
  id: 's2_revenue_trend',
  title: 'Monthly revenue',
  tab: 'overview',
  library: 'echarts',
};

// Text above the chart. Numbers only as live references {metric|format}.
export const commentary = `
Revenue in {latest_month|name} was {latest_revenue|compact}, which {yoy_change|direction} {yoy_change|pct:1} versus the same month a year earlier. The strongest month of the trailing year was {peak_month|name}.
`;

export default function Section({ data }) {
  const option = useMemo(() => {
    const f = fx();
    const c0 = f.color(0);
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => FORMATS.compact(v) },
      grid: { left: 64, right: 24, top: 16, bottom: 32 },
      xAxis: { type: 'category', data: data.months, boundaryGap: false },
      yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v) => FORMATS.compact(v) } },
      series: [
        {
          name: 'Revenue',
          type: 'line',
          data: data.revenue,
          color: c0,
          lineStyle: { width: 2.5, ...f.glow(c0) },
          areaStyle: { color: f.area(c0) },
        },
      ],
    };
  }, [data]);

  return <ChartECharts option={option} height={320} />;
}
