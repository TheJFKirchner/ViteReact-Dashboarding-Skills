// The panel's Reports tab (agent v2): saved report templates (Reports/<name>.json), Generate (node
// Tools/export.mjs, no model call), Open the file, Duplicate / Delete, "change with instructions" (one headless
// call, shown as a proposal you apply or not), and the report builder (its own agent: New / Edit).
import { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi } from './api.js';

const cents = (c) => `${c < 0.001 ? '<0.001' : c < 1 ? c.toFixed(3) : c.toFixed(2)}¢`;

function Summary({ s }) {
  if (!s) return null;
  return (
    <div className="agent-report-summary">
      {s.audience && <div>Prepared for {s.audience}</div>}
      {s.cards.length > 0 && (
        <div>
          <b>Cards</b> {s.cards.map((c) => c.title).join(' · ')}
        </div>
      )}
      {s.tabs.length > 0 && (
        <div>
          <b>Tabs</b> {s.tabs.join(' · ')}
        </div>
      )}
      {s.filters.length > 0 && (
        <div>
          <b>Filters</b> {s.filters.join(' · ')}
        </div>
      )}
      {s.combinations && (
        <div className="agent-report-combos">
          <b>Combinations</b> {s.combinations}
        </div>
      )}
      {s.settings.length > 0 && (
        <div>
          <b>Look &amp; parts</b> {s.settings.join(' · ')}
        </div>
      )}
    </div>
  );
}

/** Buttons for the builder's question; multi = pick several, then Send. */
function Question({ q, onAnswer, disabled }) {
  const [picked, setPicked] = useState([]);
  if (!q) return null;
  return (
    <div className="agent-question">
      {q.options.map((o) => (
        <button
          key={o}
          type="button"
          disabled={disabled}
          className={`agent-option${picked.includes(o) ? ' on' : ''}`}
          onClick={() => (q.multi ? setPicked((p) => (p.includes(o) ? p.filter((x) => x !== o) : [...p, o])) : onAnswer(o))}
        >
          {o}
        </button>
      ))}
      {q.multi && (
        <button type="button" className="agent-btn primary" disabled={disabled || !picked.length} onClick={() => onAnswer(picked.join(', '))}>
          Send
        </button>
      )}
    </div>
  );
}

function Builder({ start, onBack }) {
  const [state, setState] = useState(start);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState('');
  const [total, setTotal] = useState(0);
  const listRef = useRef(null);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); // scrollTo may return a Promise: never return it from an effect
  }, [messages, busy]);

  async function send(text) {
    if (!text.trim() || busy) return;
    setMessages((m) => [...m, { role: 'user', text }]);
    setQuestion(null);
    setBusy(true);
    try {
      const r = await agentApi.post('report/chat', { message: text });
      setMessages((m) => [...m, { role: 'agent', text: r.reply ?? r.error, cost: r.cost, saved: r.saved }]);
      if (r.draft !== undefined) setState((s) => ({ ...s, name: r.name, draft: r.draft, summary: r.summary, dirty: r.dirty }));
      setQuestion(r.question ?? null);
      if (typeof r.chat_cents === 'number') setTotal(r.chat_cents);
    } catch (e) {
      setMessages((m) => [...m, { role: 'agent', text: `Couldn't reach the report agent: ${e.message}`, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="agent-body agent-reports" ref={listRef}>
        <div className="agent-reports-head">
          <button type="button" className="agent-link" onClick={() => onBack(state.name)}>← Reports</button>
          <b>{state.name ? `Editing ${state.name}` : 'New report'}</b>
          {state.dirty && <span className="agent-tag">not saved</span>}
        </div>
        {state.summary ? (
          <div className="agent-report-card">
            <div className="agent-report-title">{state.summary.title}</div>
            <Summary s={state.summary} />
          </div>
        ) : (
          <div className="agent-note">
            Describe the report: who it&apos;s for, which cards or tabs, and anything special (&quot;red theme, no footer, an Info tab saying Internal only&quot;). The agent asks about filters as it goes.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`agent-msg ${m.role}${m.error ? ' error' : ''}`}>
            {m.text}
            {m.cost && <div className="agent-cost">≈{cents(m.cost.cents)}</div>}
          </div>
        ))}
        {busy && <div className="agent-msg agent working"><span /><span /><span /></div>}
        <Question q={question} onAnswer={send} disabled={busy} />
      </div>
      <div className="agent-input">
        <textarea
          rows={2}
          value={draft}
          disabled={busy}
          placeholder={state.name ? 'e.g. add the Pharmacy tab, fix region to East, rename it' : 'e.g. a monthly finance report with the overview cards, Commercial only'}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send(draft);
              setDraft('');
            }
          }}
        />
        <button type="button" className="agent-btn primary" disabled={!draft.trim() || busy} onClick={() => (send(draft), setDraft(''))}>
          Send
        </button>
      </div>
      <footer className="agent-file">
        Report builder (its own agent){total > 0 && <span className="agent-total">≈{cents(total)} this chat</span>}
      </footer>
    </>
  );
}

export default function ReportsPanel() {
  const [list, setList] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [working, setWorking] = useState(null); // 'generate' | 'instructions' | 'apply' | null
  const [result, setResult] = useState({}); // name -> generate result
  const [instructions, setInstructions] = useState('');
  const [proposal, setProposal] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [builder, setBuilder] = useState(null);

  const load = useCallback(async (select) => {
    try {
      const r = await agentApi.get('reports');
      setList(r.reports);
      setError(null);
      if (select !== undefined) setSelected(select);
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    load();
    return () => {
      agentApi.post('report/close').catch(() => {});
    };
  }, [load]);

  const pick = (name) => {
    setSelected(name === selected ? null : name);
    setProposal(null);
    setInstructions('');
    setConfirmDelete(false);
  };
  async function openBuilder(name) {
    const state = await agentApi.post('report/start', { name: name ?? null }).catch((e) => ({ error: e.message }));
    if (state.error) return setError(state.error);
    setBuilder(state);
  }
  async function generate(name) {
    setWorking('generate');
    const r = await agentApi.post('reports/generate', { name }).catch((e) => ({ error: e.message }));
    setResult((x) => ({ ...x, [name]: r }));
    setWorking(null);
    if (r.ok) load();
  }
  async function propose(name) {
    setWorking('instructions');
    setProposal(null);
    const r = await agentApi.post('reports/instructions', { name, text: instructions }).catch((e) => ({ error: e.message }));
    setProposal(r);
    setWorking(null);
  }
  async function applyProposal(name) {
    setWorking('apply');
    const r = await agentApi.post('reports/apply', { name, report: proposal.proposed }).catch((e) => ({ error: e.message }));
    setWorking(null);
    if (r.error) return setProposal((p) => ({ ...p, applyError: r.error }));
    setProposal(null);
    setInstructions('');
    load(name);
  }
  async function duplicate(name) {
    const r = await agentApi.post('reports/duplicate', { name });
    if (r.name) load(r.name);
  }
  async function remove(name) {
    await agentApi.post('reports/delete', { name });
    setConfirmDelete(false);
    load(null);
  }

  if (builder)
    return (
      <Builder
        start={builder}
        onBack={(name) => {
          agentApi.post('report/close').catch(() => {});
          setBuilder(null);
          load(name ?? selected);
        }}
      />
    );

  const current = list?.find((r) => r.name === selected);
  const res = current && result[current.name];
  return (
    <div className="agent-body agent-reports">
      <div className="agent-reports-head">
        <b>Reports</b>
        <button type="button" className="agent-btn primary" onClick={() => openBuilder(null)}>New report</button>
      </div>
      {error && <div className="agent-note error">{error}</div>}
      {!list && !error && <div className="agent-note">Loading reports…</div>}
      {list?.length === 0 && <div className="agent-note">No saved reports yet. Click New report to build one.</div>}
      {list?.map((r) => (
        <div key={r.name} className={`agent-report-card${r.name === selected ? ' on' : ''}`}>
          <button type="button" className="agent-report-row" onClick={() => pick(r.name)} aria-expanded={r.name === selected}>
            <span className="agent-report-title">{r.summary?.title ?? r.name}</span>
            <span className="agent-report-meta">
              <code>{r.name}</code>
              {r.summary && ` · ${r.summary.cards.length} card${r.summary.cards.length === 1 ? '' : 's'}`}
              {r.last ? ` · generated ${r.last.at}` : ' · not generated yet'}
            </span>
          </button>
          {r.error && <div className="agent-note error">{r.error}</div>}
          {r.name === selected && current && (
            <div className="agent-report-details">
              <Summary s={current.summary} />
              <div className="agent-report-actions">
                <button type="button" className="agent-btn primary" disabled={working !== null} onClick={() => generate(r.name)}>
                  {working === 'generate' ? 'Generating…' : 'Generate'}
                </button>
                <button type="button" className="agent-btn" disabled={working !== null} onClick={() => openBuilder(r.name)}>Edit</button>
                <button type="button" className="agent-btn" disabled={working !== null} onClick={() => duplicate(r.name)}>Duplicate</button>
                <button type="button" className="agent-btn ghost" disabled={working !== null} onClick={() => setConfirmDelete(true)}>Delete</button>
              </div>
              {confirmDelete && (
                <div className="agent-confirm">
                  Delete <b>{r.name}</b>? It moves to .dashboard-agent/deleted-reports (recoverable).
                  <button type="button" className="agent-btn" onClick={() => remove(r.name)}>Delete</button>
                  <button type="button" className="agent-btn ghost" onClick={() => setConfirmDelete(false)}>Cancel</button>
                </div>
              )}
              {res?.ok && (
                <div className="agent-report-result">
                  Generated <code>{res.file}</code> ({res.size}{res.combinations ? `; ${res.combinations} filter combination${res.combinations === 1 ? '' : 's'}` : ''}){' '}
                  <a className="agent-link" href={res.url} target="_blank" rel="noreferrer">Open ↗</a>
                  {res.warnings?.length > 0 && <div className="agent-note">{res.warnings.join(' · ')}</div>}
                </div>
              )}
              {res?.error && (
                <div className="agent-note error">
                  {res.error}
                  {res.log?.map((l) => <div key={l}>{l}</div>)}
                </div>
              )}
              {!res?.ok && r.last && (
                <div className="agent-report-result">
                  Last generated <code>{r.last.file}</code>{' '}
                  <a className="agent-link" href={r.last.url} target="_blank" rel="noreferrer">Open ↗</a>
                </div>
              )}
              <div className="agent-instructions">
                <textarea
                  rows={2}
                  value={instructions}
                  disabled={working !== null}
                  placeholder="Changes for this report, e.g. red theme, no footer, an Info tab saying Internal only for finance team"
                  onChange={(e) => setInstructions(e.target.value)}
                />
                <button type="button" className="agent-btn" disabled={!instructions.trim() || working !== null} onClick={() => propose(r.name)}>
                  {working === 'instructions' ? 'Working…' : 'Propose changes'}
                </button>
              </div>
              {proposal && (
                <div className="agent-proposal">
                  {proposal.error ? (
                    <div className="agent-note error">{proposal.error}</div>
                  ) : (
                    <>
                      <div>{proposal.reply}</div>
                      {proposal.changes?.length > 0 ? (
                        <ul>{proposal.changes.map((c) => <li key={c}>{c}</li>)}</ul>
                      ) : (
                        <div className="agent-note">No changes.</div>
                      )}
                      {proposal.applyError && <div className="agent-note error">{proposal.applyError}</div>}
                      <div className="agent-report-actions">
                        <button type="button" className="agent-btn primary" disabled={!proposal.changed || working !== null} onClick={() => applyProposal(r.name)}>
                          {working === 'apply' ? 'Saving…' : 'Apply'}
                        </button>
                        <button type="button" className="agent-btn ghost" onClick={() => setProposal(null)}>Discard</button>
                        {proposal.cost && <span className="agent-cost">≈{cents(proposal.cost.cents)}</span>}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
