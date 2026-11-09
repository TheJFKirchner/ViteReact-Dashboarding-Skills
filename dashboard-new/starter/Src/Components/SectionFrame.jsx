import { Component, useContext, useEffect, useState } from 'react';
import { useFilters } from '../Filters/FilterContext.jsx';
import { AgentContext } from '../Lib/agent-context.js';
import { useCard } from '../Lib/useCard.js';
import Commentary from './Commentary.jsx';
import DataOrigin from './DataOrigin.jsx';
import { dataOrigin } from '../Lib/origin.js';

class ErrorBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error) {
    this.props.onError?.(error);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return this.props.fallback?.(this.state.error) ?? <div className="section-error">This section failed to render: {this.state.error.message}</div>;
  }
}

/** Card around one section: asks the Analysis server (or an export's precomputed results) for the card's
 *  { data, metrics } at the current filters, then renders commentary + the section body.
 *  In dev, the dashboard agent (AgentContext) can swap in a preview module and highlight the card.
 *  info = meta.cards[id] from the server: { filters, tables }.
 *  inspect: { meta, reportFilters } adds an "About this data" button (reports with "inspect": true). */
export default function SectionFrame({ module, info, version, commentary, half, showId, inspect }) {
  const { meta } = module;
  const agent = useContext(AgentContext);
  const view = agent?.view(meta.id);
  const active = view?.module ?? module;
  const { values } = useFilters();
  const [aboutOpen, setAboutOpen] = useState(false);
  const filterNames = info?.filters ?? [];
  const { result, loading } = useCard(meta.id, filterNames, values, version);
  useEffect(() => {
    agent?.setCardFilters?.(meta.id, values); // dev Inspect: data origin
  }, [agent, meta.id, values]);

  const text = view?.commentary ?? commentary; // dev agent: previewed / kept commentary
  const failed = result?.error;
  const body = (mod) => (
    <>
      {text && result && !failed && <Commentary markdown={text} metrics={result.metrics} />}
      {result && !failed && <mod.default data={result.data} metrics={result.metrics} filters={values} />}
    </>
  );
  // A broken preview only affects this card: show the last good version with a note.
  const previewFallback = view?.module
    ? (error) => (
        <>
          <div className="preview-error-note">Preview failed to render ({error.message}); showing the last good version.</div>
          {body(view.fallback ?? module)}
        </>
      )
    : undefined;

  return (
    <section className={`card${half ? ' half' : ''}${view?.selected ? ' agent-selected' : ''}${loading && result ? ' refreshing' : ''}`} id={meta.id}>
      {view?.banner}
      <header className="card-head">
        <h2>{active.meta.title}</h2>
        {showId && <code className="section-id" title={`npm run export -- ${meta.id.split('_')[0]}`}>{meta.id}</code>}
        {inspect && (
          <button type="button" className={`about-btn${aboutOpen ? ' on' : ''}`} aria-expanded={aboutOpen} onClick={() => setAboutOpen((o) => !o)} title="Where this data comes from">
            ⓘ About this data
          </button>
        )}
      </header>
      {inspect && aboutOpen && <DataOrigin origin={dataOrigin(meta.id, inspect.meta, values, inspect.reportFilters)} />}
      {!result && loading && <div className="card-loading" aria-busy="true">Loading…</div>}
      {failed && (
        <div className={result.notIncluded ? 'card-note' : 'section-error'}>
          {result.notIncluded ? result.error : `Analysis failed: ${result.error}`}
        </div>
      )}
      <ErrorBoundary key={`${view?.version ?? 'base'}:${agent?.themeRev ?? 0}`} onError={view?.onRenderError} fallback={previewFallback}>
        {body(active)}
      </ErrorBoundary>
    </section>
  );
}
