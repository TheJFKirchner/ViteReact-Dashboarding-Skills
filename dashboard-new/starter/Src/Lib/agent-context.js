// Tiny on purpose: SectionFrame and the page shell read this in every build. It stays null unless
// the dev-only AgentProvider is mounted, so builds and exports carry no agent code.
import { createContext, useContext, useMemo, useSyncExternalStore } from 'react';

export const AgentContext = createContext(null);

/** Page-shell text with the agent's preview applied (dev only). In builds: always the fallback.
 *  Slots: "title", "dataSource", "tab:<id>", "filter:<name>". */
export function useShellText() {
  const agent = useContext(AgentContext);
  return (slot, fallback) => agent?.text?.(slot) ?? fallback;
}

// Layout preview from the dev agent: { order: [ids], cards: { id: { tab, size } }, tabs: [tab ids],
// extra: { id: module } }. null (always, in builds) = the registry as written.
let layout = null;
const listeners = new Set();
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

export function setAgentLayout(next) {
  if (next === layout) return;
  layout = next;
  listeners.forEach((fn) => fn());
}

/** Sections and tabs with the agent's layout preview applied (order, tab, width, hidden). */
export function useAgentLayout(sections, tabs) {
  const value = useSyncExternalStore(subscribe, () => layout, () => null);
  return useMemo(() => {
    if (!value) return { sections, tabs };
    const byId = new Map(sections.map((m) => [m.meta.id, m]));
    for (const [id, mod] of Object.entries(value.extra ?? {})) if (!byId.has(id)) byId.set(id, mod);
    const laid = value.order
      .map((id) => byId.get(id))
      .filter(Boolean)
      .map((mod) => {
        const c = value.cards?.[mod.meta.id];
        if (!c || (c.tab === (mod.meta.tab ?? null) && c.size === (mod.meta.size === 'half' ? 'half' : 'full'))) return mod;
        return { ...mod, meta: { ...mod.meta, tab: c.tab ?? mod.meta.tab, size: c.size === 'half' ? 'half' : undefined } };
      });
    const ordered = value.tabs?.length ? value.tabs.map((id) => tabs.find((t) => t.id === id)).filter(Boolean) : tabs;
    return { sections: laid.length ? laid : sections, tabs: ordered.length === tabs.length ? ordered : tabs };
  }, [sections, tabs, value]);
}
