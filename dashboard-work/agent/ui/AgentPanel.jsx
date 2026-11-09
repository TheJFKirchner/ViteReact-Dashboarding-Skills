// Presentational part of the dashboard agent: floating button, chat panel, pinned origin,
// keep/discard prompt.
import { useEffect, useRef, useState } from 'react';
import ControlCard from './ControlCard.jsx';
import ReportsPanel from './ReportsPanel.jsx';
import { openInEditor, parseSrc } from './inspect.js';

const Spark = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
    <path fill="currentColor" d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 14l.9 2.6 2.6.9-2.6.9L19 21l-.9-2.6-2.6-.9 2.6-.9z" />
  </svg>
);

// Cost estimates are in US cents; tiny values keep 3 decimals so they don't round to 0.
const cents = (c) => `${c < 0.001 ? '<0.001' : c < 1 ? c.toFixed(3) : c.toFixed(2)}¢`;
const tokens = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

const PLACEHOLDER = {
  card: 'e.g. make the line amber, italicize this description, swap this with the heatmap',
  page: 'e.g. make the PMPM chart a bar chart, swap two cards, warmer accent',
  none: 'Ask about any card by name, or the page: e.g. swap the PMPM chart and the heatmap',
};

/** file:line with an Open-in-editor link. approx marks a name-search match (≈). */
function SourceLink({ src, approx = false }) {
  const s = parseSrc(src);
  if (!s) return null;
  const short = s.file.replace(/^Src\//, '');
  return (
    <button type="button" className="agent-src" title={`Open ${s.file} at line ${s.line} in your editor`} onClick={() => openInEditor(s.file, s.line)}>
      <code>{short}:{approx ? '≈' : ''}{s.line}</code>
      {s.preview && <span> (preview)</span>} ↗
    </button>
  );
}

/** High-level origin of the clicked element: what, where it's drawn, where its text comes from, which card. */
function PinnedOrigin({ pinned, shared, sharedUsage, sections, tabs, onClear }) {
  const section = sections.find((s) => s.meta.id === pinned.target);
  const tab = section?.meta.tab && (tabs.find((t) => t.id === section.meta.tab)?.label ?? section.meta.tab);
  return (
    <div className="agent-origin">
      <div className="agent-origin-head">
        <b>{pinned.what}</b>
        <button type="button" onClick={onClear} aria-label="Unpin">×</button>
      </div>
      <div className="agent-origin-row">
        {section ? <>Card <b>{section.meta.title}</b> <code>{section.meta.id}</code>{tab && <> · {tab} tab</>}</> : 'Page'}
      </div>
      {pinned.src && <div className="agent-origin-row">Drawn by <SourceLink src={pinned.src} /></div>}
      {pinned.valueFrom && <div className="agent-origin-row">Text from <code>{pinned.valueFrom}</code></div>}
      {pinned.numbersFrom && <div className="agent-origin-row">Numbers from <code>{pinned.numbersFrom}</code> <i>(Python: a Claude Code job)</i></div>}
      {shared && (
        <div className="agent-origin-row agent-shared">
          Shared component <b>{shared.name}</b>
          {shared.modified && <span className="agent-tag" title="Changed by the agent: differs from the version the project started with">modified</span>}
          {' · '}used by {sharedUsage}
          {!shared.editable && <> · <i>locked (a Claude Code job)</i></>}
        </div>
      )}
    </div>
  );
}

export default function AgentPanel({
  open, kind, previewControls, chatCents, liveCardId, onControl, onToggle, onEditPage, health, selected, selectedTitle, file,
  messages, busy, clicked, approx, pinned, pinnedShared, componentUsage, sections, tabs, onClearPinned, onClearClicked, onSend,
  pendingSwitch, onResolveSwitch, panelTab = 'edit', onPanelTab,
}) {
  const [draft, setDraft] = useState('');
  const listRef = useRef(null);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, busy]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    onSend(text);
  };

  const thisLabel = clicked && (clicked.element ?? [clicked.series, clicked.name].filter(Boolean).join(' · '));
  const cardPath = kind === 'card' ? `Src/Sections/${selected}.jsx` : null;

  return (
    <>
      {open && (
        <aside className="agent-panel" aria-label="Dashboard agent">
          <header className="agent-head">
            <span className="agent-title">Dashboard agent</span>
            <span className="agent-chip" title="Agent v2 (layout, cards by name, reports), on test">v2</span>
            <span className="segmented agent-tabs" role="tablist" aria-label="Panel">
              <button type="button" role="tab" aria-selected={panelTab === 'edit'} className={panelTab === 'edit' ? 'on' : ''} onClick={() => onPanelTab('edit')}>Edit</button>
              <button type="button" role="tab" aria-selected={panelTab === 'reports'} className={panelTab === 'reports' ? 'on' : ''} onClick={() => onPanelTab('reports')}>Reports</button>
            </span>
            {health?.model && <span className="agent-chip">{health.test_mode ? 'test mode' : health.model.replace('claude-', '')}</span>}
            <button type="button" className="agent-x" onClick={onToggle} aria-label="Close">×</button>
          </header>

          {panelTab === 'reports' && health?.ok && <ReportsPanel />}
          {panelTab === 'reports' && health && !health.ok && <div className="agent-body"><div className="agent-note error">{health.problems.map((p) => <p key={p}>{p}</p>)}</div></div>}
          {panelTab === 'edit' && <>
          <div className="agent-body" ref={listRef}>
            {health && !health.ok ? (
              <div className="agent-note error">{health.problems.map((p) => <p key={p}>{p}</p>)}</div>
            ) : !selected ? (
              <div className="agent-note">
                Ask for any change: name a card (&quot;make the PMPM chart a bar chart&quot;, &quot;swap the PMPM chart and the heatmap&quot;), or click a <b>card</b> first. Charts, descriptions, where cards sit, fonts, colors, the theme. Hover anything to see where it comes from. Changes show as a preview you keep or discard.
                <div>
                  <button type="button" className="agent-link" onClick={onEditPage}>Or edit the whole page</button>
                </div>
              </div>
            ) : (
              <>
                {!messages.length && (
                  <div className="agent-note">
                    {kind === 'card' ? (
                      <>Working on <b>{selectedTitle}</b>. Ask for anything: this chart or its description, where cards sit, all cards, the page or the theme. Click a bar, line or point to point at it as &quot;this&quot;. A request about another card opens a fresh chat for it.</>
                    ) : (
                      <>Working on <b>the page</b>: where cards sit, titles, tabs, filters, styles for every card, the theme. Name or click a card to work on its chart or description.</>
                    )}
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={`agent-msg ${m.role}${m.error ? ' error' : ''}`}>
                    {m.text}
                    {m.card && <ControlCard card={m.card} live={m.card.id === liveCardId} onControl={onControl} />}
                    {m.cost && (
                      <div className="agent-cost" title="Estimate from token usage and the pricing assumptions in dashboard.config.json">
                        ≈{cents(m.cost.cents)} · {tokens(m.cost.input_tokens)} in / {tokens(m.cost.output_tokens)} out
                      </div>
                    )}
                  </div>
                ))}
                {busy && <div className="agent-msg agent working"><span /><span /><span /></div>}
              </>
            )}
          </div>

          {pinned && (
            <PinnedOrigin pinned={pinned} shared={pinnedShared} sharedUsage={pinnedShared && componentUsage(pinnedShared)} sections={sections} tabs={tabs} onClear={onClearPinned} />
          )}
          {previewControls && <div className="agent-preview-bar">{previewControls}</div>}
          {clicked && (
            <div className="agent-clicked">
              <span>
                this = {thisLabel}
                {approx && cardPath && <> · <SourceLink src={`${cardPath}:${approx}`} approx /></>}
              </span>
              <button type="button" onClick={onClearClicked} aria-label="Clear">×</button>
            </div>
          )}
          <div className="agent-input">
            <textarea
              rows={2}
              value={draft}
              disabled={busy || !health?.ok}
              placeholder={PLACEHOLDER[kind ?? 'none']}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <button type="button" className="agent-btn primary" disabled={!draft.trim() || busy || !health?.ok} onClick={submit}>Send</button>
          </div>
          <footer className="agent-file">
            {selected ? <code>{kind === 'card' ? file ?? `${selected}.jsx` : 'whole page'}</code> : 'Nothing clicked: ask by name'}
            {selected && <span> · Esc to deselect</span>}
            {selected && chatCents > 0 && <span className="agent-total" title="Estimated cost of this chat (approximate)">≈{cents(chatCents)} this chat</span>}
          </footer>
          </>}
        </aside>
      )}

      <button type="button" className={`agent-fab${open ? ' on' : ''}`} onClick={onToggle} aria-label="Dashboard agent" title="Dashboard agent">
        <Spark />
      </button>

      {pendingSwitch && (
        <div className="agent-modal" role="dialog" aria-label="Unsaved preview">
          <div className="agent-modal-card">
            <p>
              Keep the agent&apos;s changes (working on <b>{pendingSwitch.title}</b>)
              {pendingSwitch.next && <> before opening <b>{pendingSwitch.next}</b></>}?
            </p>
            <div className="agent-modal-actions">
              <button type="button" className="agent-btn primary" onClick={() => onResolveSwitch('keep')}>Keep</button>
              <button type="button" className="agent-btn" onClick={() => onResolveSwitch('discard')}>Discard</button>
              <button type="button" className="agent-btn ghost" onClick={() => onResolveSwitch('cancel')}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
