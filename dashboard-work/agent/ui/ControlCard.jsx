// Live controls the agent attached to a reply. Tweaks go straight to the server (no model call):
// live updates while dragging (throttled), a verified commit on release.
import { useEffect, useRef, useState } from 'react';

const LIVE_MS = 120;
const unquote = (v) => String(v).replace(/^['"]|['"]$/g, '');
const isHex = (v) => /^#[0-9a-f]{6}$/i.test(unquote(v));

/** <input> that reports every movement (onLive) and the final value on release (onCommit). */
function LiveInput({ onLive, onCommit, ...props }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    const commit = (e) => onCommit(e.target.value);
    el.addEventListener('change', commit); // native change = released / picker closed
    return () => el.removeEventListener('change', commit);
  }, [onCommit]);
  return <input ref={ref} onInput={(e) => onLive(e.target.value)} {...props} />;
}

export default function ControlCard({ card, live, onControl }) {
  const [values, setValues] = useState(() => Object.fromEntries(card.controls.map((c) => [c.id, c.value])));
  const [status, setStatus] = useState(null);
  const timers = useRef({});

  async function send(control, value, final) {
    const r = await onControl(card.id, control.id, value, final);
    if (r?.error) return setStatus({ error: r.error });
    if (final) {
      setValues((v) => ({ ...v, [control.id]: r.value }));
      setStatus(r.verdict?.startsWith('render error') ? { error: r.verdict } : { ok: true });
    }
  }
  function change(control, value, final) {
    clearTimeout(timers.current[control.id]);
    if (final) return send(control, value, true);
    timers.current[control.id] = setTimeout(() => send(control, value, false), LIVE_MS);
  }

  return (
    <div className={`agent-card${live ? '' : ' superseded'}`} onClick={(e) => e.stopPropagation()}>
      {card.controls.map((c) => {
        const value = values[c.id];
        if (c.kind === 'color') {
          const swatch = card.swatches.find((s) => s.expr === value);
          const custom = !swatch && isHex(value);
          const hex = swatch?.hex ?? (custom ? unquote(value) : '#888888');
          return (
            <div className="agent-control" key={c.id}>
              <span className="agent-control-label">{c.label}</span>
              <div className="agent-swatches">
                {card.swatches.map((s) => (
                  <button
                    key={s.expr}
                    type="button"
                    disabled={!live}
                    title={s.label}
                    aria-label={s.label}
                    className={`agent-swatch${s.expr === value ? ' on' : ''}`}
                    style={{ background: s.hex }}
                    onClick={() => {
                      setValues((v) => ({ ...v, [c.id]: s.expr }));
                      change(c, s.expr, true);
                    }}
                  />
                ))}
              </div>
              <label className="agent-custom">
                <LiveInput
                  type="color"
                  disabled={!live}
                  value={hex}
                  onChange={() => {}}
                  onLive={(h) => {
                    setValues((v) => ({ ...v, [c.id]: `'${h.toUpperCase()}'` }));
                    change(c, h, false);
                  }}
                  onCommit={(h) => change(c, h, true)}
                />
                <span>{custom ? `Custom ${unquote(value)}` : 'Custom'} · {card.custom_note ?? "won't follow the theme"}</span>
              </label>
            </div>
          );
        }
        if (c.kind === 'slider') {
          return (
            <div className="agent-control" key={c.id}>
              <span className="agent-control-label">
                {c.label} <b>{value}</b>
              </span>
              <LiveInput
                type="range"
                disabled={!live}
                min={c.min}
                max={c.max}
                step={c.step}
                value={value}
                onChange={() => {}}
                onLive={(v) => {
                  setValues((s) => ({ ...s, [c.id]: v }));
                  change(c, v, false);
                }}
                onCommit={(v) => change(c, v, true)}
              />
            </div>
          );
        }
        return (
          <label className="agent-control agent-switch" key={c.id}>
            <input
              type="checkbox"
              disabled={!live}
              checked={value === 'true'}
              onChange={(e) => {
                const v = e.target.checked ? 'true' : 'false';
                setValues((s) => ({ ...s, [c.id]: v }));
                change(c, v, true);
              }}
            />
            <span className="agent-control-label">{c.label}</span>
          </label>
        );
      })}
      <div className="agent-card-foot">
        {!live ? 'Superseded by a newer edit' : status?.error ? <span className="bad">{status.error}</span> : status?.ok ? '✓ applied to the preview' : 'Changes apply instantly · no model call'}
      </div>
    </div>
  );
}
