// KPI tile: label, value (number + format fn), optional signed change and sparkline.
// goodWhen: 'down' | 'up' | null (neutral) decides the change color.
// Themes with effects.animation count the value up on load.
import { useEffect, useMemo, useState } from 'react';
import ChartECharts from './ChartECharts.jsx';
import { FORMATS } from '../Lib/commentary.js';
import { fx } from '../Lib/theme.js';

// Values already shown once (by label): a remount (tab switched back, dev agent preview or
// theme change) shows them at once instead of counting up from 0 again.
// Kept on globalThis so it also survives the module being hot-swapped (dev agent component edits).
const shownOnce = (globalThis.__dashKpiShown ??= new Map());

function useCountUp(target, on, key, ms = 1100) {
  const seen = shownOnce.get(key) === target;
  const [v, setV] = useState(on && !seen ? 0 : target);
  useEffect(() => {
    shownOnce.set(key, target);
    if (!on || seen || typeof target !== 'number') return setV(target);
    let raf;
    const t0 = performance.now();
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / ms);
      setV(target * (1 - (1 - k) ** 3));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, on, ms]);
  return v;
}

export default function KpiTile({ label, value, format = FORMATS.int, change = null, goodWhen = null, changeLabel = 'vs prior 12 mo', spark }) {
  const f = fx();
  const shown = useCountUp(value, f.animated, label);
  const tone = change === null || goodWhen === null ? '' : (goodWhen === 'down' ? change < 0 : change > 0) ? 'good' : 'bad';
  const option = useMemo(() => {
    if (!spark?.length) return null;
    const color = f.colors.accent;
    return {
      animationDuration: f.animated ? 1800 : 400,
      grid: { left: 0, right: 0, top: 4, bottom: 2 },
      xAxis: { type: 'category', show: false, boundaryGap: false, data: spark.map((_, i) => i) },
      yAxis: { type: 'value', show: false, scale: true },
      tooltip: { show: false },
      series: [{ type: 'line', data: spark, symbol: 'none', smooth: true, lineStyle: { width: 2, color, ...f.glow(color, 8) }, areaStyle: { color: f.area(color, 0.45) } }],
    };
  }, [spark]); // eslint-disable-line react-hooks/exhaustive-deps -- theme is fixed per page load

  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{format(shown)}</div>
      {change !== null && (
        <div className={`kpi-change ${tone}`}>
          {change >= 0 ? '▲' : '▼'} {FORMATS.pct(change, 1)} <span>{changeLabel}</span>
        </div>
      )}
      {option && <ChartECharts option={option} height={44} />}
    </div>
  );
}
