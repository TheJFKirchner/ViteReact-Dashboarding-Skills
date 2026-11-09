// Shared shell for both outputs:
//   dashboard mode (Src/main.jsx): every registered section, data from the Analysis server (/api); fast filters
//     recompute cards, slow parameters (e.g. "Data as of") re-run the pipeline after a confirmation
//   report mode (.export/entry.jsx): chosen sections, results precomputed for the report's filter combinations,
//     header + footer stamp, plus the report's own settings: theme overrides, hidden parts, a notice line, text tabs
// Tabs: sections with meta.tab are grouped under the tabs defined in Src/Sections/index.js.
// The current tab and the reader's fast filter choices live in the URL hash (#tab=<id>&region=East), so links
// and reloads keep them, in exports too (Src/Lib/hash.js).
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import config from '../dashboard.config.json';
import { getMeta, getStatus, runPipeline } from './Lib/source.js';
import { applyTheme, setReportThemeOverrides } from './Lib/theme.js';
import { dataAsOf, daysBetween, todayIso } from './Lib/dates.js';
import { ALL, FilterProvider, useFilters } from './Filters/FilterContext.jsx';
import { readHash, writeHash } from './Lib/hash.js';
import FilterBar from './Controls/FilterBar.jsx';
import TabBar from './Controls/TabBar.jsx';
import SectionFrame from './Components/SectionFrame.jsx';
import ReportHeader from './Components/ReportHeader.jsx';
import ReportFooter from './Components/ReportFooter.jsx';
import { useAgentLayout } from './Lib/agent-context.js';
import './styles.css';
import './custom.css'; // style overrides (hand-written or kept from the dev agent's Page target)

export function mount(props) {
  createRoot(document.getElementById('root')).render(<App {...props} />);
}

// Dashboard agent: lives in the dashboard-work skill and is plugged in only by
// `npm run dev:agent` / Start dashboard.cmd (Tools/agent-loader.js). Everywhere else
// __DASHBOARD_AGENT__ is false, this import is dropped, and builds and exports carry no agent code.
const AgentProvider = import.meta.env.DEV && __DASHBOARD_AGENT__ ? lazy(() => import('virtual:dashboard-agent')) : null;

const hashTab = () => readHash().tab ?? null;

/** Keeps the URL hash in step with the tab and the filter choices. `names` = filters the reader may change
 *  (locked report filters are never written or read); `valid(name, value)` = the value is one of its options.
 *  A hash edited by hand (or set by the dev agent) applies the filters it names and keeps the others. */
function HashSync({ tab, names, valid }) {
  const { values, setFilter } = useFilters();
  const latest = useRef(null);
  latest.current = { tab, names, valid, values };
  const pick = (vals, ns) => Object.fromEntries(ns.map((n) => [n, vals[n]]));

  useEffect(() => {
    writeHash(tab, pick(values, names));
  }, [tab, values, names.join('|')]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onHash = () => {
      const { tab: current, names: ns, valid: ok, values: vals } = latest.current;
      const h = readHash();
      const next = pick(vals, ns);
      for (const n of ns) {
        if (h[n] !== undefined && ok(n, h[n]) && h[n] !== vals[n]) {
          next[n] = h[n];
          setFilter(n, h[n]);
        }
      }
      writeHash(h.tab ?? current, next);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
// Card id badges (s1, s2, ...) are for whoever builds the dashboard: shown only when it runs with the
// dev agent (npm run dev:agent / Start dashboard.cmd). Viewers (npm run dev, builds, exports) don't see them.
const SHOW_IDS = import.meta.env.DEV && __DASHBOARD_AGENT__;

/** A report's text tab: plain paragraphs, "- " lines become a list. */
function TextTab({ text }) {
  return (
    <section className="card report-text">
      {text.trim().split(/\n\s*\n/).map((block, i) => {
        const lines = block.split('\n');
        return lines.every((l) => l.trim().startsWith('- ')) ? (
          <ul key={i}>{lines.map((l, j) => <li key={j}>{l.trim().slice(2)}</li>)}</ul>
        ) : (
          <p key={i}>{block}</p>
        );
      })}
    </section>
  );
}

/** Slow-parameter confirmation, pipeline progress and pipeline failure, above the cards. */
function PipelineBanner({ pending, status, lastSeconds, onConfirm, onCancel, onDismiss }) {
  if (status?.state === 'running') {
    return (
      <div className="pipeline-banner" role="status">
        <span className="grow">
          Re-pulling data ({status.elapsed ?? 0}s{lastSeconds ? ` of about ${lastSeconds}s` : ''})… Cards keep showing the current data until it finishes.
        </span>
        {status.log?.length > 0 && <code>{status.log.at(-1)}</code>}
      </div>
    );
  }
  if (status?.state === 'failed') {
    return (
      <div className="pipeline-banner failed" role="alert">
        <span className="grow">The pipeline run failed, so the data was not changed: {status.error}</span>
        <button type="button" onClick={onDismiss}>Dismiss</button>
      </div>
    );
  }
  if (!pending) return null;
  return (
    <div className="pipeline-banner" role="dialog" aria-label="Re-pull data">
      <span className="grow">
        Change <b>{pending.label}</b> to <b>{pending.valueLabel}</b>? This re-runs the pipeline and re-pulls the source data
        {lastSeconds ? ` (last run took about ${lastSeconds}s)` : ''}.
      </span>
      <button type="button" className="primary" onClick={onConfirm}>Re-pull data</button>
      <button type="button" onClick={onCancel}>Cancel</button>
    </div>
  );
}

function App({ sections: registry, tabs: tabDefs = [], commentary, report = null }) {
  const { sections, tabs } = useAgentLayout(registry, tabDefs); // dev agent layout preview; unchanged in builds
  const [state, setState] = useState({ loading: true });
  const [tab, setTab] = useState(hashTab);
  const [pending, setPending] = useState(null); // slow parameter change waiting for confirmation
  const [status, setStatus] = useState(null); // pipeline run status (live dashboard only)

  const reload = () =>
    getMeta().then(
      (meta) => {
        setState({ meta });
        if (meta.pipeline?.state === 'running') setStatus(meta.pipeline);
      },
      (error) => setState({ error }),
    );

  useEffect(() => {
    reload();
    const onHash = () => setTab(hashTab());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // while the pipeline runs: poll its status; when it finishes, reload meta (new data version -> cards refetch)
  useEffect(() => {
    if (status?.state !== 'running') return undefined;
    const timer = setInterval(() => {
      getStatus().then(
        (s) => {
          setStatus(s);
          if (s.state !== 'running') reload();
        },
        () => {},
      );
    }, 1500);
    return () => clearInterval(timer);
  }, [status?.state]);

  if (state.error) return <div className="page"><div className="section-error">Could not load data: {state.error.message}</div></div>;
  if (state.loading) return <div className="page loading">Loading…</div>;

  const { meta } = state;
  const { manifest } = meta;
  const themeName = report?.theme ?? config.theme;
  if (report?.themeOverrides) setReportThemeOverrides(themeName, report.themeOverrides);
  applyTheme(themeName);
  const hidden = new Set(report?.hide ?? []);
  const cardInfo = (id) => meta.cards[id];

  const tabList = tabs.filter((t) => t.text || sections.some((s) => s.meta.tab === t.id));
  const activeTab = tabList.some((t) => t.id === tab) ? tab : tabList[0]?.id;
  const visible = tabList.length ? sections.filter((s) => s.meta.tab === activeTab) : sections;
  const selectTab = (id) => {
    setTab(id); // HashSync writes it to the URL
    window.scrollTo({ top: 0 });
  };

  // filter state covers every section; the bar shows only filters used on the current tab
  const filtersOf = (s) => cardInfo(s.meta.id)?.filters ?? [];
  const usedFilters = [...new Set(sections.flatMap(filtersOf))].filter((n) => meta.filters[n]);
  const reportFilters = report?.filters ?? {};
  // filters the reader may change, so the URL may carry them; a value must be one of the filter's options
  const changeable = hidden.has('filters') ? [] : usedFilters.filter((n) => !reportFilters[n]?.locked);
  const validChoice = (n, v) => (meta.filters[n]?.options ?? []).includes(v);
  const fromHash = readHash();
  const initial = Object.fromEntries(usedFilters.map((n) => [
    n,
    changeable.includes(n) && validChoice(n, fromHash[n]) ? fromHash[n] : reportFilters[n]?.value ?? ALL,
  ]));
  const tabFilters = new Set(visible.flatMap(filtersOf));
  const visibleFilters = hidden.has('filters') ? [] : usedFilters.filter((n) => tabFilters.has(n) && !reportFilters[n]?.locked);
  const params = report ? [] : Object.keys(meta.parameters ?? {});
  const textTab = tabList.find((t) => t.id === activeTab)?.text;

  const usedTables = [...new Set(sections.flatMap((s) => cardInfo(s.meta.id)?.tables ?? []))];
  const asOf = dataAsOf(manifest, usedTables);
  const pulled = manifest.generated_at ? daysBetween(manifest.generated_at, todayIso()) : null;
  const sources = [...new Set(usedTables.map((n) => manifest.tables[n]?.source).filter(Boolean))];

  const askParam = (name, value) => {
    const p = meta.parameters[name];
    if (value === p.value) return setPending(null);
    setPending({ name, value, label: p.label, valueLabel: p.options.find((o) => o.value === value)?.label ?? value });
  };
  const confirmParam = () => {
    const { name, value } = pending;
    setPending(null);
    runPipeline({ [name]: value }).then(
      (r) => setStatus(r.error ? { state: 'failed', error: r.error } : { state: 'running', elapsed: 0, log: [] }),
      (e) => setStatus({ state: 'failed', error: e.message }),
    );
  };

  // meta.size "half" is honored only when two half sections are adjacent; a lone half goes full width
  const half = visible.map((s) => s.meta.size === 'half');
  const paired = half.map(() => false);
  for (let i = 0; i < half.length - 1; i++) {
    if (half[i] && half[i + 1]) {
      paired[i] = paired[i + 1] = true;
      i++;
    }
  }

  document.title = report?.title ?? config.title;

  const page = (
    <FilterProvider initial={initial}>
      <HashSync tab={tabList.length > 1 ? activeTab : null} names={changeable} valid={validChoice} />
      <div className="page">
        <ReportHeader
          title={report?.title ?? config.title}
          audience={report?.audience}
          asOf={asOf}
          source={hidden.has('source') ? null : config.dataSource || sources.join('; ')}
          editable={!report}
          staleDays={!report && pulled !== null && pulled > (config.staleDays ?? 7) ? pulled : null}
        />
        {report?.notice && <div className="report-notice" role="note">{report.notice}</div>}
        {tabList.length > 1 && <TabBar tabs={tabList} active={activeTab} onSelect={selectTab} />}
        <FilterBar names={visibleFilters} meta={meta} params={params} onParam={askParam} busy={status?.state === 'running'} />
        <PipelineBanner
          pending={pending}
          status={status}
          lastSeconds={status?.last_seconds ?? meta.pipeline?.last_seconds}
          onConfirm={confirmParam}
          onCancel={() => setPending(null)}
          onDismiss={() => setStatus(null)}
        />
        <main className="sections" key={activeTab}>
          {textTab && <TextTab text={textTab} />}
          {visible.map((mod, i) => (
            <SectionFrame
              key={mod.meta.id}
              module={mod}
              info={cardInfo(mod.meta.id)}
              version={meta.version}
              commentary={hidden.has('commentary') ? undefined : commentary[mod.meta.id]}
              half={paired[i]}
              showId={!report && SHOW_IDS}
              inspect={report?.inspect ? { meta, reportFilters } : null}
            />
          ))}
        </main>
        {report && !hidden.has('footer') && <ReportFooter reportName={report.name} exportDate={report.exportDate} asOf={asOf} />}
      </div>
    </FilterProvider>
  );

  if (!AgentProvider || report) return page;
  return (
    <Suspense fallback={page}>
      <AgentProvider sections={sections} manifest={manifest} meta={meta} tabs={tabList}>{page}</AgentProvider>
    </Suspense>
  );
}
