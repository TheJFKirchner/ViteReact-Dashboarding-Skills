// Read the selected card's chart: a PNG for the agent's eyes, and what the user clicked ("this").
import * as echarts from 'echarts/core';

const charts = (card) => [...card.querySelectorAll('.chart')].sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight);
const isPlotly = (el) => Boolean(el._fullLayout);

/** Resolve when the card's main ECharts chart finishes drawing (animations included), or after maxMs. */
export function chartSettled(card, maxMs = 2000) {
  const inst = charts(card).map((el) => echarts.getInstanceByDom(el)).find(Boolean);
  return new Promise((resolve) => {
    const done = () => {
      inst?.off('finished', done);
      resolve();
    };
    inst?.on('finished', done);
    setTimeout(done, inst ? maxMs : 600);
  });
}

/** PNG data URL of the card's largest chart, or null (tables, KPI tiles). */
export async function captureChart(card) {
  const el = charts(card)[0];
  if (!el) return null;
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--background').trim() || '#ffffff';
  if (isPlotly(el)) {
    const Plotly = await import('plotly.js-cartesian-dist-min').then((m) => m.default ?? m);
    return Plotly.toImage(el, { format: 'png', width: el.clientWidth, height: el.clientHeight });
  }
  const inst = echarts.getInstanceByDom(el);
  if (!inst) return null;
  return svgToPng(inst.renderToSVGString(), el.clientWidth, el.clientHeight, bg);
}

async function svgToPng(svg, width, height, background) {
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
  try {
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      img.src = url;
    });
    const scale = Math.min(1, 900 / width);
    const canvas = Object.assign(document.createElement('canvas'), { width: Math.round(width * scale), height: Math.round(height * scale) });
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/png');
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Call onPick({ series, name, value }) when the user clicks a data point in the card. Returns cleanup. */
export function watchClicks(card, onPick) {
  const cleanups = [];
  for (const el of charts(card)) {
    if (isPlotly(el) && el.on) {
      const handler = (d) => {
        const p = d.points?.[0];
        if (p) onPick({ series: p.data?.name, name: p.x, value: p.y });
      };
      el.on('plotly_click', handler);
      cleanups.push(() => el.removeListener?.('plotly_click', handler));
      continue;
    }
    const inst = echarts.getInstanceByDom(el);
    if (!inst) continue;
    const handler = (p) => onPick({ series: p.seriesName, name: p.name, value: Array.isArray(p.value) ? p.value.join(', ') : p.value, type: p.seriesType });
    inst.on('click', handler);
    cleanups.push(() => inst.off('click', handler));
  }
  return () => cleanups.forEach((c) => c());
}
