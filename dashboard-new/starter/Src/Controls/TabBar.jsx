import { useShellText } from '../Lib/agent-context.js';

export default function TabBar({ tabs, active, onSelect }) {
  const text = useShellText();
  return (
    <nav className="tab-bar" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" data-edit={`tab:${t.id}`} aria-selected={t.id === active} className={t.id === active ? 'on' : ''} onClick={() => onSelect(t.id)}>
          {text(`tab:${t.id}`, t.label)}
        </button>
      ))}
    </nav>
  );
}
