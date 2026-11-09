// Dev-only dashboard agent, v2 (loaded lazily by App.jsx only when import.meta.env.DEV).
//
// One agent for every presentation change. What you click is context: a card (its chart and
// commentary become "current") or the page (header, tabs, filters, background). Clicking is
// optional: you can name any card ("the PMPM chart"). The agent decides where each request goes;
// one combined preview spans every file it touched:
//   card chart    - preview copy Src/Sections/<id>.agent-preview.jsx, imported into the card per
//                   version; this provider reports "rendered OK / error" and a picture of the chart
//   commentary    - preview text passed to the card (SectionFrame reads view.commentary)
//   page text, custom.css, theme tokens - applied in memory (text overrides, injected stylesheet,
//                   theme override)
//   shared component - the dev server serves the preview code in place of the real file; this
//                   provider asks it to hot-swap the module (React Fast Refresh updates every
//                   card), then reports render errors
//   layout        - order / tab / width / hidden, applied in memory through setAgentLayout
//                   (App.jsx reads it with useAgentLayout); the view jumps to the moved card
// Keep writes every changed file; Discard drops all of it. Clicking another card (or the page),
// or the agent's open_card for a request about another card, starts a fresh chat; unkept changes
// are kept or discarded first, then the request is passed on.
//
// Inspect: while the panel is open, hovering shows where an element comes from; clicking selects
// its card (or the page), pins high-level origin info and makes it "this" for the next message.
import { Component, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import config from '@dash-config';
import { applyTheme, setThemeOverride } from '@dash/Lib/theme.js';
import * as agentContext from '@dash/Lib/agent-context.js';
import registry from '@dash/Sections/index.js';
import { agentApi } from './api.js';
import { captureChart, chartSettled, watchClicks } from './capture.js';
import { AGENT_UI, approxLine, describe, parseSrc, usageText } from './inspect.js';
import AgentPanel from './AgentPanel.jsx';
import './agent.css';

const { AgentContext } = agentContext;
const setAgentLayout = agentContext.setAgentLayout ?? null; // missing in projects whose App.jsx predates layout previews
const POLL_MS = 400;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const targetOf = (origin) => (origin.target === 'theme' ? 'page' : origin.target); // background = the page

/** Wait for the next hot update to be applied (or give up after ms). Start it before triggering the update. */
function nextHotUpdate(ms = 3000) {
  const hot = import.meta.hot;
  let finish;
  const promise = new Promise((resolve) => {
    let done = false;
    finish = () => {
      if (done) return;
      done = true;
      hot?.off?.('vite:afterUpdate', finish);
      resolve();
    };
    hot?.on('vite:afterUpdate', finish);
    setTimeout(finish, hot ? ms : 800);
  });
  return { promise, cancel: () => finish() };
}

/** Ask the dev server to serve the component preview (or the original) and hot-swap what changed. */
async function syncComponents(view = 'agent') {
  const hmr = nextHotUpdate();
  const r = await fetch('/__dashboard-agent/component-sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ view }) })
    .then((res) => res.json())
    .catch(() => ({ reloaded: [] }));
  if (!r.reloaded?.length) {
    hmr.cancel();
    return false;
  }
  await hmr.promise;
  return true;
}

/** Catches a broken component preview anywhere in the page (e.g. the header) so the agent panel
 *  survives; Fast Refresh retries it when the last good version is swapped back in. */
class PageBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error) {
    this.props.onError?.(error);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <div className="section-error">The page failed to render ({this.state.error.message}). If an agent preview caused it, the last good version comes back in a moment.</div>
      </div>
    );
  }
}

/** An error in the agent UI must never take the dashboard down with it. */
class AgentBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <button type="button" className="agent-fab" title={`Dashboard agent crashed: ${this.state.error.message}. Reload to retry.`} onClick={() => this.setState({ error: null })}>
        !
      </button>
    );
  }
}

const EMPTY = { version: 0, has_preview: false, dirty: false, pending: [], file: null, preview: null, section: null, commentary: null, component: null };

/** Shared component info for a data-src value ("Src/Components/KpiTile.jsx:30"), if any. */
const sharedOf = (components, src) => components[parseSrc(src)?.file ?? ''] ?? null;

/** Floating origin chip + outline for the element under the cursor. */
function InspectChip({ hover, components, sections }) {
  if (!hover) return null;
  const { origin, x, y, rect } = hover;
  const shared = sharedOf(components, origin.src);
  const target = targetOf(origin);
  const section = sections.find((s) => s.meta.id === target);
  const left = Math.min(x + 14, window.innerWidth - 340);
  const top = y + 18 + 70 > window.innerHeight ? y - 78 : y + 18;
  return (
    <>
      {rect && <div className="agent-inspect agent-inspect-box" style={{ left: rect.left - 3, top: rect.top - 3, width: rect.width + 6, height: rect.height + 6 }} />}
      <div className="agent-inspect agent-inspect-chip" style={{ left, top }}>
        <b>{origin.what}</b>
        {origin.src && (
          <span>
            <code>{origin.src.replace(/^Src\//, '')}</code>
            {shared && <> · shared component{shared.modified && <span className="agent-tag">modified</span>}</>}
          </span>
        )}
        {origin.valueFrom && <span>text from {origin.valueFrom}</span>}
        {origin.numbersFrom && <span>numbers from {origin.numbersFrom}</span>}
        <span className="agent-inspect-owner">
          {section ? `${section.meta.title} (${target})` : 'Page'} · {origin.navigates ? 'click opens the tab' : 'click to select'}
        </span>
      </div>
    </>
  );
}

// meta = the Analysis server's /api/meta (v2 projects): which Analysis module computes each card's numbers
export default function AgentProvider({ sections, tabs = [], meta = null, children }) {
  const [open, setOpen] = useState(false);
  const [health, setHealth] = useState(null);
  const [selected, setSelected] = useState(null); // card (section id) | "page" | null
  const [server, setServer] = useState(EMPTY);
  const [preview, setPreview] = useState(null); // card chart preview: { version, module }
  const [lastGood, setLastGood] = useState(null); // module of the last chart preview that rendered OK
  const [overrides, setOverrides] = useState({}); // id -> kept chart module (until the next full reload)
  const [kept, setKept] = useState({ text: {}, css: null, tokens: null, commentary: {}, layout: null }); // kept edits shown until reload
  const [extraModules, setExtraModules] = useState({}); // hidden cards shown again by a layout preview (not in the registry)
  const [viewMode, setViewMode] = useState('agent'); // 'agent' | 'original'
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [chatCents, setChatCents] = useState(0); // estimated cost of this chat (server-side assumptions)
  const [clicked, setClicked] = useState(null); // "this" sent with the next message
  const [pinned, setPinned] = useState(null); // origin of the last clicked element
  const [hover, setHover] = useState(null);
  const [approx, setApprox] = useState(null); // ≈ source line of a clicked chart part
  const [pendingSwitch, setPendingSwitch] = useState(null); // { to, closePanel, pin, click }
  const [components, setComponents] = useState({}); // shared components: file -> { name, editable, used_by, modified }
  const [confirmKeep, setConfirmKeep] = useState(false); // Keep asks first when a shared component changes
  const [panelTab, setPanelTab] = useState('edit'); // 'edit' (this agent) | 'reports' (report templates; its own agent)
  const picking = open && panelTab === 'edit'; // Inspect + click-to-select only on the Edit tab
  const renderErrors = useRef({});
  const compErrors = useRef({}); // shared component: version -> first render error anywhere on the page
  const card = selected && selected !== 'page' ? selected : null;
  const section = server.section;
  const comp = server.component;
  const compLive = useRef({ active: false, version: 0 });
  compLive.current = { active: Boolean(comp), version: comp?.version ?? 0 };

  const loadComponents = useCallback(() => agentApi.get('components').then((r) => setComponents(r.components ?? {})).catch(() => {}), []);

  // ---- a session left from before a page reload: end it (the panel starts with nothing selected)
  useEffect(() => {
    agentApi
      .get('state')
      .then((s) => s.section_id && agentApi.post('close').then(() => syncComponents()))
      .catch(() => {});
  }, []);

  // ---- shared component list (who uses what, locked or editable, modified)
  useEffect(() => {
    if (open) loadComponents();
  }, [open, loadComponents]);

  // ---- health check when the panel opens
  useEffect(() => {
    if (!open) return;
    agentApi
      .get('health')
      .then(setHealth)
      .catch(() => setHealth({ ok: false, problems: ["The agent server isn't running. Restart with `npm run dev:agent` and check its [agent] lines."] }));
  }, [open]);

  // ---- poll server state while something is selected
  useEffect(() => {
    if (!open || !selected || !health?.ok) return;
    // keep the same object when nothing changed, so a poll never re-renders (or redraws) anything
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const t = setInterval(() => agentApi.get('state').then((s) => s.section_id === selected && setServer((prev) => (same(prev, s) ? prev : s))).catch(() => {}), POLL_MS);
    return () => clearInterval(t);
  }, [open, selected, health]);

  // ---- any new preview switches the view back to "Agent"
  useEffect(() => {
    if (server.has_preview) setViewMode('agent');
  }, [server.version]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- card chart: load each new preview version
  useEffect(() => {
    if (!card || !section) return;
    if (!section.has_preview) return setPreview(null);
    let cancelled = false;
    import(/* @vite-ignore */ `/Src/Sections/${card}.agent-preview.jsx?agentv=${section.version}`)
      .then((module) => !cancelled && setPreview({ version: section.version, module }))
      .catch((e) => report('section', section.version, false, `preview failed to load: ${e.message}`));
    return () => {
      cancelled = true;
    };
  }, [card, section?.version, section?.has_preview]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- card chart: after the card shows a version, report render result, then a picture
  const shownVersion = section ? (section.has_preview ? preview?.version : section.version) : null;
  useEffect(() => {
    if (!card || shownVersion === undefined || shownVersion === null || !health?.ok) return;
    const el = document.getElementById(card);
    if (!el) return;
    let cancelled = false;
    const onWindowError = (e) => (renderErrors.current[shownVersion] ??= e.message);
    window.addEventListener('error', onWindowError);
    const stopWatching = watchClicks(el, setClicked);
    (async () => {
      await sleep(700);
      if (cancelled) return;
      const error = renderErrors.current[shownVersion];
      await report('section', shownVersion, !error, error ?? null);
      if (!error && preview?.version === shownVersion) setLastGood(preview.module);
      await chartSettled(el);
      if (cancelled) return;
      const image = await captureChart(el).catch(() => null);
      if (image && !cancelled) await report('section', shownVersion, null, null, image);
    })();
    return () => {
      cancelled = true;
      window.removeEventListener('error', onWindowError);
      stopWatching();
    };
  }, [card, shownVersion, health]); // eslint-disable-line react-hooks/exhaustive-deps

  function report(part, version, ok, error, image) {
    return agentApi.post('render', { section_id: selected, part, version, ok, error, image }).catch(() => {});
  }

  // ---- shared component: serve each new version (or the original), let the page re-render, report errors
  useEffect(() => {
    if (!comp || !health?.ok) return;
    const version = comp.version;
    let cancelled = false;
    const onWindowError = (e) => (compErrors.current[version] ??= e.message);
    window.addEventListener('error', onWindowError);
    (async () => {
      const swapped = await syncComponents(viewMode);
      if (cancelled) return;
      await sleep(swapped ? 700 : 150);
      if (cancelled || viewMode !== 'agent') return;
      const error = compErrors.current[version];
      await report('component', version, !error, error ?? null);
    })();
    return () => {
      cancelled = true;
      window.removeEventListener('error', onWindowError);
    };
  }, [comp?.version, viewMode, health]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- ≈ source line for a clicked chart part (series / category name searched in the section file)
  useEffect(() => {
    setApprox(null);
    if (!card || !clicked || clicked.element) return;
    let cancelled = false;
    const url = section?.has_preview ? `/Src/Sections/${card}.agent-preview.jsx?raw&agentv=${section.version}` : `/Src/Sections/${card}.jsx?raw`;
    import(/* @vite-ignore */ url)
      .then((m) => !cancelled && setApprox(approxLine(m.default, clicked)))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [clicked]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- selection: a card or the page; a new selection is a new chat
  const resetFor = (id, state, extra = {}) => {
    setSelected(id);
    setServer(state ?? EMPTY);
    setPreview(null);
    setLastGood(null);
    setViewMode('agent');
    setMessages([]);
    setChatCents(0);
    setClicked(extra.click ?? null);
    setPinned(extra.pin ?? null);
    setConfirmKeep(false);
    renderErrors.current = {};
    compErrors.current = {};
  };

  const switchTo = useCallback(async (id, extra) => {
    const hadComponent = compLive.current.active;
    if (id === null) {
      await agentApi.post('close').catch(() => {});
      if (hadComponent) await syncComponents(); // back to the real component files
      return resetFor(null);
    }
    const state = await agentApi.post('select', { section_id: id }).catch(() => null);
    if (hadComponent) await syncComponents();
    resetFor(id, state, extra);
  }, []);

  const requestSwitch = useCallback(
    (id, { closePanel = false, pin, click } = {}) => {
      if (server.dirty) return setPendingSwitch({ to: id, closePanel, pin, click });
      switchTo(id, { pin, click });
      if (closePanel) setOpen(false);
    },
    [server.dirty, switchTo],
  );

  const resolveSwitch = async (choice) => {
    const pending = pendingSwitch;
    setPendingSwitch(null);
    if (choice === 'cancel') {
      if (pending.then) setMessages((m) => [...m, { role: 'agent', text: `Stayed here; nothing was sent to ${titleOf(pending.to)}.` }]);
      return;
    }
    if (choice === 'keep') await keep();
    await switchTo(pending.to, pending);
    if (pending.closePanel) setOpen(false);
    if (pending.then) forward(pending.to, pending.then);
  };

  // ---- open_card: the agent passed a request about another card; that card gets a fresh chat
  const titleOf = (id) => sections.find((s) => s.meta.id === id)?.meta.title ?? id;
  const jumpToCard = (id) => jumpTo({ id, tab: sections.find((s) => s.meta.id === id)?.meta.tab });
  function forward(id, request) {
    jumpToCard(id);
    send(request, id);
  }
  function followSwitch({ card: id, request }, dirty) {
    if (dirty) return setPendingSwitch({ to: id, then: request });
    switchTo(id).then(() => forward(id, request));
  }

  // ---- Inspect: hover chip + click to select (capture phase, before the page's own handlers)
  const live = useRef({});
  live.current = { selected, pendingSwitch, requestSwitch, meta };
  useEffect(() => {
    if (!picking) {
      setHover(null);
      return;
    }
    let frame = 0;
    let last = null;
    const onMove = (e) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const el = e.target instanceof Element ? e.target : null;
        if (!el || el.closest(AGENT_UI) || live.current.pendingSwitch) {
          last = null;
          return setHover(null);
        }
        const origin = describe(el, live.current.meta);
        const rect = origin.box?.getBoundingClientRect() ?? null;
        last = el;
        setHover({ origin, x: e.clientX, y: e.clientY, rect });
      });
    };
    const onLeave = () => setHover(null);
    const onScroll = () => last && setHover(null);
    const onClick = (e) => {
      const el = e.target instanceof Element ? e.target : null;
      const { selected: current, pendingSwitch: pending, requestSwitch: pick } = live.current;
      if (!el || pending || el.closest(AGENT_UI)) return;
      if (el.closest('.tab-bar button[aria-selected="false"], select, option, .segmented button')) return; // navigation still works
      const origin = describe(el, live.current.meta);
      const { box, ...pin } = origin; // eslint-disable-line no-unused-vars
      const click = origin.inChart || origin.generic ? null : { element: origin.what, ...(origin.src && { source: origin.src }) };
      const target = targetOf(origin);
      if (target === current) {
        setPinned(pin);
        if (click) setClicked(click);
      } else {
        pick(target, { pin, click });
      }
    };
    document.addEventListener('mousemove', onMove, { passive: true });
    document.addEventListener('mouseleave', onLeave);
    window.addEventListener('scroll', onScroll, { passive: true });
    document.addEventListener('click', onClick, true);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseleave', onLeave);
      window.removeEventListener('scroll', onScroll);
      document.removeEventListener('click', onClick, true);
    };
  }, [picking]);

  // ---- keep / discard (every changed file at once)
  async function keep() {
    setConfirmKeep(false);
    const state = await agentApi.post('keep');
    if (state.error) {
      setMessages((m) => [...m, { role: 'agent', text: state.error, error: true }]);
    } else {
      const p = server.preview;
      if (card && preview) setOverrides((o) => ({ ...o, [card]: preview.module }));
      const l = server.layout;
      setKept((k) => ({
        text: p?.text ?? k.text,
        css: p?.css ?? k.css,
        tokens: p?.tokens ?? k.tokens,
        commentary: card && server.commentary != null ? { ...k.commentary, [card]: server.commentary } : k.commentary,
        layout: l ? { order: l.order, cards: l.cards, tabs: l.tabs } : k.layout,
      }));
      if (comp?.dirty) loadComponents(); // "modified" tag
    }
    setServer((s) => ({ ...s, ...state }));
  }
  async function discard() {
    const state = await agentApi.post('discard');
    setServer((s) => ({ ...s, ...state }));
  }

  // ---- chat
  async function send(text, target = selected) {
    if (!target) {
      await switchTo('page'); // nothing clicked: the page session (it can still reach any card)
      target = 'page';
    }
    setMessages((m) => [...m, { role: 'user', text }]);
    setBusy(true);
    try {
      const r = await agentApi.post('chat', { section_id: target, message: text, clicked: target === selected ? clicked : null });
      setMessages((m) => [...m, { role: 'agent', text: r.reply ?? r.error, cost: r.cost, card: r.card }]);
      if (r.version !== undefined) {
        const { reply, cost, chat_cents, card: _card, switch_to: _switch, ...state } = r; // eslint-disable-line no-unused-vars
        setServer((s) => ({ ...s, ...state }));
      }
      if (typeof r.chat_cents === 'number') setChatCents(r.chat_cents);
      if (r.switch_to) setTimeout(() => followSwitch(r.switch_to, r.dirty), 600); // let the reply show first
    } catch (e) {
      setMessages((m) => [...m, { role: 'agent', text: `Couldn't reach the agent: ${e.message}`, error: true }]);
    } finally {
      setBusy(false);
      setClicked(null);
    }
  }

  // ---- control cards: apply a tweak, then show the new preview right away (don't wait for the poll)
  async function control(cardId, controlId, value, final) {
    try {
      const r = await agentApi.post('control', { card_id: cardId, control_id: controlId, value, final });
      if (r.version !== undefined) {
        const { ok, value: _v, verdict, error, ...state } = r; // eslint-disable-line no-unused-vars
        setServer((s) => ({ ...s, ...state }));
      }
      return r;
    } catch (e) {
      return { error: e.message };
    }
  }

  // ---- Esc deselects
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && open && selected && !pendingSwitch && requestSwitch(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, selected, pendingSwitch, requestSwitch]);

  // ---- page text / styles / theme preview applied in memory (kept edits stay applied until the next reload)
  // compared by content: a new copy of the same preview must not count as a change (it would redraw every chart)
  const previewJson = server.preview && viewMode === 'agent' ? JSON.stringify(server.preview) : 'null';
  const globalPreview = useMemo(() => JSON.parse(previewJson), [previewJson]);
  const text = useMemo(() => ({ ...kept.text, ...(globalPreview?.text ?? {}) }), [kept.text, globalPreview]);
  const css = globalPreview?.css ?? kept.css;
  const tokens = globalPreview?.tokens ?? kept.tokens;

  // theme: set before children render so charts and fx() pick it up; remount charts when it changes
  setThemeOverride(tokens);
  const appliedTheme = applyTheme(config.theme);
  const themeRef = useRef({ theme: appliedTheme, rev: 0 });
  if (themeRef.current.theme !== appliedTheme) themeRef.current = { theme: appliedTheme, rev: themeRef.current.rev + 1 };
  const themeRev = themeRef.current.rev;

  // styles: inject the preview stylesheet and switch off the real custom.css while it's shown
  useEffect(() => {
    const base = document.querySelector('style[data-vite-dev-id$="/Src/custom.css"]');
    let el = document.getElementById('agent-css-preview');
    if (css === null || css === undefined) {
      el?.remove();
      if (base) base.media = '';
      return;
    }
    if (!el) {
      el = Object.assign(document.createElement('style'), { id: 'agent-css-preview' });
      document.head.appendChild(el);
    }
    el.textContent = css;
    if (base) base.media = 'not all';
  }, [css]);

  // ---- layout: order / tab / width / hidden applied in memory (kept layout stays until the next reload)
  const layoutJson = JSON.stringify((viewMode === 'agent' && server.layout) || kept.layout || null);
  useEffect(() => {
    if (!setAgentLayout) return;
    const value = JSON.parse(layoutJson);
    if (!value) return setAgentLayout(null);
    const known = new Set(registry.map((m) => m.meta.id));
    const missing = value.order.filter((id) => !known.has(id) && !extraModules[id]);
    if (missing.length) {
      Promise.all(missing.map((id) => import(/* @vite-ignore */ `/Src/Sections/${id}.jsx`).then((m) => [id, m])))
        .then((pairs) => setExtraModules((e) => ({ ...e, ...Object.fromEntries(pairs) })))
        .catch(() => {});
    }
    setAgentLayout({ ...value, extra: extraModules });
  }, [layoutJson, extraModules]);
  useEffect(() => () => setAgentLayout?.(null), []);

  // a new layout preview: show the card that moved (switching tab if needed)
  useEffect(() => {
    const l = server.layout;
    if (!l?.focus || viewMode !== 'agent') return;
    const t = setTimeout(() => jumpTo({ id: l.focus, tab: l.cards[l.focus]?.tab }), 250);
    return () => clearTimeout(t);
  }, [server.layout?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- one page banner for the whole preview: what's pending, Original / Agent, Keep, Discard
  const previewControls = (
    <>
      <span className="segmented" role="group" aria-label="Show">
        <button type="button" className={viewMode === 'original' ? 'on' : ''} onClick={() => setViewMode('original')}>Original</button>
        <button type="button" className={viewMode === 'agent' ? 'on' : ''} onClick={() => setViewMode('agent')}>Agent</button>
      </span>
      <button type="button" className="agent-btn primary" onClick={() => (comp?.dirty ? setConfirmKeep(true) : keep())}>Keep</button>
      <button type="button" className="agent-btn" onClick={discard}>Discard</button>
    </>
  );

  // a changed shared component: who it changes, with links that jump to each card (switching tab if needed)
  const usedBy = comp?.dirty ? comp.used_by : null;
  const usage = usedBy ? usageText(usedBy, tabs) : '';
  const jumpTo = (s) => {
    const go = () => {
      const el = document.getElementById(s.id);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el?.classList.add('agent-flash');
      setTimeout(() => el?.classList.remove('agent-flash'), 1200);
    };
    if (s.tab && document.getElementById(s.id) === null) {
      window.location.hash = `tab=${s.tab}`;
      setTimeout(go, 200);
    } else go();
  };
  const jumpLinks = usedBy && !usedBy.all_sections && usedBy.sections.length > 0 && (
    <span className="agent-jumps">
      {usedBy.sections.map((s) => (
        <button key={s.id} type="button" className="agent-link" onClick={() => jumpTo(s)} title={`Show ${s.title}`}>
          {s.title}
        </button>
      ))}
    </span>
  );

  // ---- what SectionFrame and the page shell ask for
  const ctx = useMemo(
    () => ({
      picking: open,
      themeRev,
      text: (slot) => text[slot],
      setCardFilters: () => {},
      view: (id) => {
        const isCard = id === card;
        const showPreview = isCard && preview && viewMode === 'agent';
        const commentary = isCard && viewMode === 'agent' && server.commentary != null ? server.commentary : kept.commentary[id];
        if (!open && !overrides[id] && commentary === undefined && !showPreview) return null;
        return {
          module: showPreview ? preview.module : overrides[id],
          fallback: lastGood ?? overrides[id],
          version: showPreview ? preview.version : 'base',
          selected: open && isCard,
          commentary,
          onRenderError: (err) => {
            if (showPreview) renderErrors.current[preview.version] ??= err.message;
            if (compLive.current.active) compErrors.current[compLive.current.version] ??= `${id}: ${err.message}`;
          },
          banner: null,
        };
      },
    }),
    [open, card, preview, viewMode, overrides, lastGood, server.commentary, kept.commentary, text, themeRev], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const selectedTitle = card ? sections.find((s) => s.meta.id === card)?.meta.title ?? card : 'the page';

  return (
    <AgentContext.Provider value={ctx}>
      <div className={picking ? `agent-picking${selected === 'page' ? ' agent-target-page' : ''}` : undefined}>
        <PageBoundary onError={(err) => compLive.current.active && (compErrors.current[compLive.current.version] ??= `page: ${err.message}`)}>{children}</PageBoundary>
      </div>
      {server.dirty && (
        <div className="agent-page-banner" role="status">
          {previewControls}
          <span className="agent-banner-label">
            Previewing: {server.pending.join(' · ')}
            {usedBy && <> · affects {usage}</>} · future exports {jumpLinks}
            {server.layout && !setAgentLayout && <> · this project&apos;s App.jsx can&apos;t preview layout (Keep still works)</>}
          </span>
        </div>
      )}
      {confirmKeep && (
        <div className="agent-modal" role="dialog" aria-label="Keep changes">
          <div className="agent-modal-card">
            <p>
              Keep these changes, including <b>{comp?.name}</b> for every place it&apos;s used?
            </p>
            <p className="agent-modal-detail">The {comp?.name} change affects {usage}, and every report exported from now on.</p>
            <div className="agent-modal-actions">
              <button type="button" className="agent-btn primary" onClick={keep}>Keep for all</button>
              <button type="button" className="agent-btn ghost" onClick={() => setConfirmKeep(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
      {picking && <InspectChip hover={hover} components={components} sections={sections} />}
      <AgentBoundary>
        <AgentPanel
          open={open}
          kind={card ? 'card' : selected ? 'page' : null}
          previewControls={server.dirty ? previewControls : null}
          onToggle={() => (open ? requestSwitch(null, { closePanel: true }) : setOpen(true))}
          onEditPage={() => requestSwitch('page')}
          health={health}
          selected={selected}
          selectedTitle={selectedTitle}
          file={server.file}
          chatCents={chatCents}
          liveCardId={server.live_card_id}
          onControl={control}
          messages={messages}
          busy={busy}
          clicked={clicked}
          approx={approx}
          pinned={pinned}
          pinnedShared={pinned && sharedOf(components, pinned.src)}
          componentUsage={(info) => usageText(info?.used_by, tabs)}
          sections={sections}
          tabs={tabs}
          onClearPinned={() => setPinned(null)}
          onClearClicked={() => setClicked(null)}
          onSend={send}
          pendingSwitch={pendingSwitch && { title: selectedTitle, next: pendingSwitch.then ? titleOf(pendingSwitch.to) : null }}
          onResolveSwitch={resolveSwitch}
          panelTab={panelTab}
          onPanelTab={setPanelTab}
        />
      </AgentBoundary>
    </AgentContext.Provider>
  );
}
