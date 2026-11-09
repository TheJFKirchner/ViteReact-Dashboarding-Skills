// Inspect: what is under the cursor and where it comes from.
// Elements carry data-src="Src/<file>.jsx:<line>" (stamped by agent/vite-plugin.js, dev only) and,
// for editable page text, data-edit="<slot>" (ReportHeader, TabBar, FilterBar).
// v2 projects: a card's numbers come from Python; the Analysis server's meta (meta.cards[id].module) says
// which Analysis/<module>.py computes them (shown as "numbers from", high level only: no data details).
import config from '@dash-config';

/** The agent's own UI: never inspected or picked. */
export const AGENT_UI = '.agent-panel, .agent-fab, .agent-modal, .agent-page-banner, .agent-banner, .agent-inspect, .agent-card';
const SHELL = '.report-header, .tab-bar, .filter-bar, .report-footer';

const SLOT_ORIGIN = {
  title: ['Dashboard title', 'dashboard.config.json → title'],
  dataSource: ['Source line', 'dashboard.config.json → dataSource'],
  tab: ['Tab label', 'Src/Sections/index.js → tabs'],
  filter: ['Filter label', 'dashboard.config.json → filters'],
  param: ['Data setting label', 'dashboard.config.json → parameters'],
};

const snippet = (el) => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);

/** Describe an element: { target, what, text, src, valueFrom, numbersFrom, slot, inChart, generic, box }
 *  generic: a container (card, page) rather than a specific element; not worth sending as "this".
 *  meta: the Analysis server's /api/meta (optional). */
export function describe(el, meta = null) {
  const stamped = el.closest('[data-src]');
  const src = stamped?.getAttribute('data-src') ?? null;
  const card = el.closest('.card[id]');
  const slotEl = el.closest('[data-edit]');
  const slot = slotEl?.getAttribute('data-edit') ?? null;
  const chart = el.closest('.chart');
  const target = card ? card.id : el.closest(SHELL) ? 'page' : 'theme';
  const text = snippet(slotEl ?? stamped ?? el);
  let what;
  let valueFrom = null;
  let box = slotEl ?? chart ?? stamped ?? el;
  if (slot) {
    const [label, from] = SLOT_ORIGIN[slot.split(':')[0]] ?? [slot, null];
    what = `${label} "${text}"`;
    valueFrom = from;
  } else if (chart) {
    what = 'Chart';
  } else if (card && el.closest('.card-head h2')) {
    what = `Card title "${text}"`;
    valueFrom = `${card.id}.jsx → meta.title`;
    box = el.closest('.card-head h2');
  } else if (target === 'theme') {
    what = 'Page background';
    valueFrom = `Themes/${config.theme}/tokens.json`;
    box = null;
  } else {
    const tag = (stamped ?? el).tagName.toLowerCase();
    what = text ? `${tag} "${text}"` : tag;
  }
  const generic = !slot && !chart && (target === 'theme' || !stamped || stamped.matches('.card, .sections, .page, main, header.card-head') || Boolean(stamped.querySelector('.chart')));
  const navigates = Boolean(el.closest('.tab-bar button[aria-selected="false"]'));
  // outline only specific elements: charts and whole cards already get the card's hover outline,
  // and a box over a live chart reads as flashing
  if (chart || generic) box = null;
  const module = card ? meta?.cards?.[card.id]?.module : null;
  const numbersFrom = module && (chart || el.closest('.commentary, .kpi, table')) ? `Analysis/${module}.py` : null;
  return { target, what, text, src, valueFrom, numbersFrom, slot, inChart: Boolean(chart), generic: generic && !what.startsWith('Card title'), navigates, box };
}

/** Who uses a shared component: "1 section: Summary (Overview)" / "every section (18)" / "the page itself" */
export function usageText(usedBy, tabs = []) {
  if (!usedBy) return '';
  const tabLabel = (id) => tabs.find((t) => t.id === id)?.label ?? id;
  const parts = [];
  if (usedBy.all_sections) parts.push(`every section (${usedBy.section_count})`);
  else if (usedBy.sections.length) {
    const n = usedBy.sections.length;
    const names = usedBy.sections.slice(0, 4).map((s) => (s.tab ? `${s.title} (${tabLabel(s.tab)})` : s.title));
    parts.push(`${n} section${n === 1 ? '' : 's'}: ${names.join(', ')}${n > 4 ? ` +${n - 4} more` : ''}`);
  }
  if (usedBy.page) parts.push('the page itself (every tab)');
  return parts.join(' and ') || 'nothing on the dashboard yet';
}

/** "Src/Sections/b.agent-preview.jsx:41" -> { file: "Src/Sections/b.jsx", line: 41, preview: true } */
export function parseSrc(src) {
  const m = /^(.*):(\d+)$/.exec(src || '');
  if (!m) return null;
  const preview = m[1].includes('.agent-preview.');
  return { file: m[1].replace('.agent-preview.', '.'), line: Number(m[2]), preview };
}

/** Ask the dev server to open file:line in the running editor (Vite's /__open-in-editor). */
export function openInEditor(file, line) {
  fetch(`/__open-in-editor?file=${encodeURIComponent(`${file}:${line}`)}`).catch(() => {});
}

/** Approximate source line for a clicked chart part: first line quoting its series or category name. */
export function approxLine(source, clicked) {
  if (!source || !clicked) return null;
  const lines = source.split('\n');
  for (const name of [clicked.series, clicked.name]) {
    if (name === undefined || name === null || name === '') continue;
    const needles = [`'${name}'`, `"${name}"`, `\`${name}\``, String(name)];
    for (const needle of needles) {
      const i = lines.findIndex((l) => l.includes(needle));
      if (i >= 0) return i + 1;
    }
  }
  if (clicked.type) {
    const i = lines.findIndex((l) => new RegExp(`type:\\s*['"]${clicked.type}['"]`).test(l));
    if (i >= 0) return i + 1;
  }
  return null;
}
