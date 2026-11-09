// Plugs in the dashboard agent, which lives in the dashboard-work skill (one copy shared by
// every project, so updating the skill updates the agent everywhere).
//
//   npm run dev                      dashboard only (this loader returns the "off" stub)
//   npm run dev:agent                dashboard + agent  (sets DASHBOARD_AGENT=on)
//   Start dashboard.cmd              same as dev:agent, then opens the browser
//
// Finding the skill: "agent": { "home" } in dashboard.config.json first (dashboard-new's setup writes it; it names the
// exact dashboard-work folder this project was made with), then DASHBOARD_AGENT_HOME (the skill folder or its agent/
// folder; often a machine-wide setting), then Claude Code's standard location ~/.claude/skills/dashboard-work. Not found, or "agent":
// { "enabled": false } in dashboard.config.json -> the dashboard starts without the agent.
// Builds and exports always use the stub, so they never contain agent code.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

/** Stub: App.jsx sees __DASHBOARD_AGENT__ = false and drops the agent import. */
export function agentOff() {
  return {
    name: 'dashboard-agent-off',
    config: () => ({ define: { __DASHBOARD_AGENT__: 'false' } }),
    resolveId: (id) => (id === 'virtual:dashboard-agent' ? '\0dashboard-agent-off' : null),
    load: (id) => (id === '\0dashboard-agent-off' ? 'export default null;' : null),
  };
}

function homeSetting() {
  if (process.env.DASHBOARD_AGENT_HOME) return process.env.DASHBOARD_AGENT_HOME;
  if (process.platform !== 'win32') return null;
  try {
    // set with `setx` but this terminal/app started before that: read the saved user setting
    const out = execFileSync('reg', ['query', 'HKCU\\Environment', '/v', 'DASHBOARD_AGENT_HOME'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    return /DASHBOARD_AGENT_HOME\s+REG_\w+\s+(.+)/.exec(out)?.[1].trim() ?? null;
  } catch {
    return null;
  }
}

/** The skill's agent folder (contains vite-plugin.js), or null. */
export function agentHome(configHome) {
  const candidates = [configHome, homeSetting(), path.join(os.homedir(), '.claude', 'skills', 'dashboard-work')].filter(Boolean);
  for (const c of candidates) {
    for (const dir of [path.join(c, 'agent'), c]) if (fs.existsSync(path.join(dir, 'vite-plugin.js'))) return dir;
  }
  return null;
}

export default async function dashboardAgent({ root }) {
  if (process.env.DASHBOARD_AGENT !== 'on') return [agentOff()];
  const config = JSON.parse(fs.readFileSync(path.join(root, 'dashboard.config.json'), 'utf8'));
  if (config.agent === false || config.agent?.enabled === false) {
    console.log('[agent] off in dashboard.config.json; starting the dashboard only');
    return [agentOff()];
  }
  const home = agentHome(typeof config.agent?.home === 'string' ? config.agent.home : null);
  if (!home) {
    console.log('[agent] not found. Put the dashboard-work skill folder in dashboard.config.json ("agent": { "home": "<dashboard-work folder>" }) or set DASHBOARD_AGENT_HOME; starting the dashboard only');
    return [agentOff()];
  }
  const vite = await import('vite');
  const { default: plugin } = await import(pathToFileURL(path.join(home, 'vite-plugin.js')).href);
  console.log(`[agent] using ${home}`);
  return plugin({ root, vite });
}
