// Loads the selected theme's tokens.json and derives everything else at runtime:
// page CSS variables, the ECharts theme, the Plotly layout template, and fx() style helpers.
// Edit themes/<name>/tokens.json only; nothing here needs changing per theme.
//
// tokens.effects (all optional, default off): { glow, gradients, grid, animation }
// Sections call fx() for fills/glows so the same code looks flat in a plain theme and lit in an effects theme.
import * as echarts from 'echarts/core';

const all = import.meta.glob('../../Themes/*/tokens.json', { eager: true, import: 'default' });
const themes = Object.fromEntries(Object.values(all).map((t) => [t.name, t]));

let current = null;
let override = null; // dev only: the agent's theme preview (full tokens object), set by setThemeOverride()

export function getTokens(name) {
  const t = themes[name];
  if (!t) throw new Error(`Theme "${name}" not found. Available: ${Object.keys(themes).join(', ')}`);
  return t;
}

/** "#00E5FF", 0.3 -> "rgba(0,229,255,0.3)" */
export function alpha(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? [...h].map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const kebab = (k) => k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());

/** Dev only (section agent theme preview): tokens to use instead of themes/<name>/tokens.json, or null. */
export function setThemeOverride(tokens) {
  override = tokens;
}

/** Report mode: the report's themeOverrides ({ "colors.accent": "#C62828", ... }) on top of its theme. */
export function setReportThemeOverrides(name, changes) {
  if (override?.name === name && override.__report) return;
  const t = structuredClone(getTokens(name));
  for (const [path, value] of Object.entries(changes ?? {})) {
    const keys = path.split('.');
    let node = t;
    for (const k of keys.slice(0, -1)) node = node && typeof node === 'object' ? (node[k] ??= {}) : node; // colors.named may be new
    if (node && typeof node === 'object') node[keys.at(-1)] = value;
  }
  override = Object.assign(t, { __report: true });
}

export function applyTheme(name) {
  const t = override && override.name === name ? override : getTokens(name);
  if (current === t) return current;
  const root = document.documentElement;
  for (const [k, v] of Object.entries(t.colors)) if (typeof v === 'string') root.style.setProperty(`--${kebab(k)}`, v);
  t.colors.series.forEach((c, i) => root.style.setProperty(`--series-${i}`, c));
  root.style.setProperty('--accent-soft', alpha(t.colors.accent, 0.18));
  root.style.setProperty('--accent-glow', alpha(t.colors.accent, 0.45));
  root.style.setProperty('--accent-line', alpha(t.colors.accent, 0.22));
  root.style.setProperty('--grid-line', alpha(t.colors.accent, 0.05));
  root.style.setProperty('--glass', alpha(t.colors.background, 0.72));
  root.style.setProperty('--accent-2', t.colors.series[1] ?? t.colors.accent);
  root.style.setProperty('--font-family', t.font.family);
  root.style.setProperty('--font-heading', t.font.heading ?? t.font.family);
  root.style.setProperty('--font-mono', t.font.mono ?? 'Consolas, monospace');
  root.style.setProperty('--font-size', `${t.font.size}px`);
  root.dataset.theme = t.name;
  root.dataset.effects = Object.entries(t.effects ?? {}).filter(([, on]) => on).map(([k]) => k).join(' ');
  echarts.registerTheme(t.name, echartsTheme(t));
  current = t;
  return t;
}

export const currentTheme = () => current;

/** Style helpers for section code. Respect the theme's effects flags. */
export function fx(t = current) {
  const c = t.colors;
  const e = t.effects ?? {};
  const linear = (x2, y2, stops) => ({ type: 'linear', x: 0, y: 0, x2, y2, colorStops: stops.map(([offset, color]) => ({ offset, color })) });
  return {
    colors: c,
    series: c.series,
    color: (i) => c.series[i % c.series.length],
    /** a category's color: its named theme color (colors.named.<name>, same in every chart), else series color i.
     *  Cards that color series by category use this and return the names as data.color_keys (Analysis). */
    colorOf: (name, i) => c.named?.[name] ?? c.series[i % c.series.length],
    /** area fill under a line */
    area: (color, top = 0.35) => (e.gradients ? linear(0, 1, [[0, alpha(color, top)], [1, alpha(color, 0)]]) : alpha(color, 0.12)),
    /** bar fill; horizontal bars fade left -> right */
    bar: (color, horizontal = false) =>
      e.gradients ? linear(horizontal ? 1 : 0, horizontal ? 0 : 1, horizontal ? [[0, alpha(color, 0.35)], [1, color]] : [[0, color], [1, alpha(color, 0.35)]]) : color,
    /** spread into itemStyle / lineStyle */
    glow: (color, blur = 14) => (e.glow ? { shadowBlur: blur, shadowColor: alpha(color, 0.85) } : {}),
    animated: Boolean(e.animation),
    sequential: c.sequential ?? [c.surface, c.accent],
    diverging: c.diverging ?? [c.series[1], c.surface, c.bad ?? c.series[0]],
    good: c.good ?? c.series[0],
    bad: c.bad ?? c.series[1],
  };
}

export function echartsTheme(t) {
  const c = t.colors;
  const e = t.effects ?? {};
  const axis = {
    axisLine: { lineStyle: { color: c.border } },
    axisTick: { lineStyle: { color: c.border } },
    axisLabel: { color: c.textMuted },
    splitLine: { lineStyle: { color: c.border, type: 'dashed', opacity: 0.6 } },
    nameTextStyle: { color: c.textMuted },
  };
  return {
    color: c.series,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: t.font.family, fontSize: t.font.size, color: c.text },
    animationDuration: e.animation ? 1400 : 500,
    animationEasing: e.animation ? 'cubicOut' : 'linear',
    animationDurationUpdate: 500,
    title: { textStyle: { color: c.text }, subtextStyle: { color: c.textMuted } },
    legend: { textStyle: { color: c.textMuted }, inactiveColor: c.border, icon: 'roundRect', itemWidth: 14, itemHeight: 6 },
    tooltip: {
      backgroundColor: e.glow ? alpha(c.background, 0.88) : c.background,
      borderColor: e.glow ? c.accent : c.border,
      textStyle: { color: c.text },
      extraCssText: e.glow ? `box-shadow: 0 0 18px ${alpha(c.accent, 0.35)}; backdrop-filter: blur(6px); border-radius: 6px;` : '',
      axisPointer: { lineStyle: { color: c.accent, opacity: 0.6 }, crossStyle: { color: c.accent }, shadowStyle: { color: alpha(c.accent, 0.08) } },
    },
    categoryAxis: { ...axis, splitLine: { show: false } },
    valueAxis: axis,
    timeAxis: axis,
    logAxis: axis,
    line: { symbol: 'circle', symbolSize: 5, lineStyle: { width: 2 }, smooth: e.gradients ? 0.25 : false },
    bar: { itemStyle: { borderRadius: [3, 3, 0, 0] } },
    visualMap: { textStyle: { color: c.textMuted }, inRange: { color: c.sequential ?? [c.surface, c.accent] } },
    dataZoom: {
      borderColor: c.border,
      textStyle: { color: c.textMuted },
      fillerColor: alpha(c.accent, 0.15),
      handleStyle: { color: c.accent, borderColor: c.accent },
      moveHandleStyle: { color: c.accent },
      dataBackground: { lineStyle: { color: c.textMuted, opacity: 0.5 }, areaStyle: { color: alpha(c.textMuted, 0.15) } },
      selectedDataBackground: { lineStyle: { color: c.accent }, areaStyle: { color: alpha(c.accent, 0.25) } },
      brushStyle: { color: alpha(c.accent, 0.15) },
    },
    radar: {
      axisName: { color: c.textMuted },
      axisLine: { lineStyle: { color: c.border } },
      splitLine: { lineStyle: { color: c.border } },
      splitArea: { areaStyle: { color: ['transparent', alpha(c.border, 0.25)] } },
    },
    gauge: { title: { color: c.textMuted }, detail: { color: c.text } },
    sankey: { label: { color: c.text }, lineStyle: { color: 'gradient', opacity: 0.35 } },
    treemap: { breadcrumb: { itemStyle: { color: c.surface, textStyle: { color: c.text } } } },
  };
}

export function plotlyTemplate(t = current) {
  const c = t.colors;
  const axis = { automargin: true, gridcolor: c.border, linecolor: c.border, zerolinecolor: c.border, tickfont: { color: c.textMuted }, title: { font: { color: c.textMuted } } };
  return {
    layout: {
      colorway: c.series,
      font: { family: t.font.family, size: t.font.size, color: c.text },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: axis,
      yaxis: axis,
      legend: { font: { color: c.textMuted } },
      hoverlabel: { bgcolor: c.background, bordercolor: c.accent, font: { color: c.text } },
    },
  };
}
