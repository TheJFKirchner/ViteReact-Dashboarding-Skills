// Thin ECharts wrapper. Modular imports keep bundles small:
// add a chart type or component to the lists below only when a section needs it.
import { useEffect, useLayoutEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import {
  DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import { currentTheme } from '../Lib/theme.js';

// Minimal common set. Other types (sankey, radar, gauge, sunburst, themeRiver, polar, markPoint/markArea...) are added here when a card needs them (the Dashboard 1 example project shows them).
echarts.use([
  BarChart, HeatmapChart, LineChart, PieChart, ScatterChart,
  DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent,
  SVGRenderer,
]);

// A section's body is remounted when the dev agent shows a new preview version or theme. So that
// this doesn't flash (blank frame + intro animation), an unmounting chart is parked for a moment
// and the chart that mounts in the same place (same card, same position) picks it up and only
// updates. Nothing is parked on a normal page (tab switches just dispose after the timeout).
const parked = new Map(); // slot -> { host, chart, theme, timer }
const PARK_MS = 1500;

function slotOf(box) {
  const card = box.closest('.card[id]');
  return card ? `${card.id}:${[...card.querySelectorAll('.chart-box')].indexOf(box)}` : null;
}

/** option: ECharts option (memoize it). onEvents: optional { click: (params) => ... } (memoize it too). */
export default function ChartECharts({ option, height = 320, onEvents }) {
  const box = useRef(null);
  const chart = useRef(null);

  useLayoutEffect(() => {
    const outer = box.current;
    const slot = slotOf(outer);
    const theme = currentTheme();
    const reuse = slot && parked.get(slot);
    let host;
    if (reuse) {
      parked.delete(slot);
      clearTimeout(reuse.timer);
      host = reuse.host;
      chart.current = reuse.chart;
      if (reuse.theme !== theme) chart.current.setTheme(theme?.name);
    } else {
      host = Object.assign(document.createElement('div'), { className: 'chart' });
      host.style.height = '100%';
    }
    outer.appendChild(host);
    chart.current ??= echarts.init(host, theme?.name, { renderer: 'svg' });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(outer);
    return () => {
      ro.disconnect();
      const c = chart.current;
      chart.current = null;
      host.remove();
      if (!slot) return c.dispose();
      const old = parked.get(slot);
      if (old) {
        clearTimeout(old.timer);
        old.chart.dispose();
      }
      parked.set(slot, { host, chart: c, theme, timer: setTimeout(() => parked.delete(slot) && c.dispose(), PARK_MS) });
    };
  }, []);

  useLayoutEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onEvents) return;
    const entries = Object.entries(onEvents);
    for (const [name, fn] of entries) c.on(name, fn);
    return () => entries.forEach(([name, fn]) => c.off(name, fn));
  }, [onEvents]);

  return <div ref={box} className="chart-box" style={{ height, width: '100%' }} />;
}
