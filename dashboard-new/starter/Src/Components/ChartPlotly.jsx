// Plotly fallback wrapper. Only for (a) Dash charts needing an exact match, (b) raw-distribution stats charts.
// Plotly is dynamically imported, so it is a separate chunk in the dashboard and is bundled into an
// export only when that export includes a section that renders this component.
// Partial build: plotly.js-cartesian-dist-min (scatter, bar, box, violin, histogram, heatmap, pie, ...).
import { useEffect, useRef, useState } from 'react';
import { plotlyTemplate } from '../Lib/theme.js';

let plotly;
const loadPlotly = () => (plotly ??= import('plotly.js-cartesian-dist-min').then((m) => m.default ?? m));

export default function ChartPlotly({ data, layout, config, height = 320 }) {
  const el = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    const node = el.current;
    loadPlotly()
      .then((Plotly) => {
        if (!alive) return;
        Plotly.react(
          node,
          data,
          { template: plotlyTemplate(), height, autosize: true, margin: { t: 16, r: 16, b: 48, l: 64 }, ...layout },
          { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'], ...config },
        );
      })
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [data, layout, config, height]);

  useEffect(() => {
    const node = el.current;
    return () => plotly?.then((P) => P.purge(node));
  }, []);

  if (error) return <div className="section-error">Chart failed to load: {error}</div>;
  return <div ref={el} className="chart" style={{ minHeight: height }} />;
}
