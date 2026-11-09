// npm run dev [-- vite options]        viewer: Analysis server + dashboard (no agent, no card badges)
// npm run dev:agent [-- vite options]  builder: same, plus the dashboard agent (DASHBOARD_AGENT=on)
//
// Starts the Analysis server (python Analysis/server.py) first, then Vite, which forwards /api to it.
// Closing this window (or Ctrl+C) stops both.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const agent = args[0] === '--agent';
const viteArgs = agent ? args.slice(1) : args;
const config = JSON.parse(fs.readFileSync(path.join(root, 'dashboard.config.json'), 'utf8'));
let port = Number(process.env.DASH_API_PORT || config.server?.port || 8765);
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

const inUse = (p) =>
  new Promise((resolve) => {
    const s = net.connect(p, '127.0.0.1');
    s.once('connect', () => (s.destroy(), resolve(true)));
    s.once('error', () => resolve(false));
  });

/** Is the server on this port this project's Analysis server? (anything else: another dashboard, another app) */
async function ours(p) {
  try {
    const r = await fetch(`http://127.0.0.1:${p}/api/project`, { signal: AbortSignal.timeout(1500) });
    const { root: theirs } = await r.json();
    return path.resolve(theirs).toLowerCase() === path.resolve(root).toLowerCase();
  } catch {
    return false;
  }
}

let reuse = false;
if (await inUse(port)) {
  if (await ours(port)) {
    reuse = true;
  } else {
    const wanted = port;
    let free = null;
    for (let p = wanted + 1; p <= wanted + 50 && free === null; p++) if (!(await inUse(p))) free = p;
    if (free === null) {
      console.log(`[analysis] port ${wanted} is used by something else and no free port was found nearby. Set "server": { "port": ... } in dashboard.config.json.`);
      process.exit(1);
    }
    console.log(`[analysis] port ${wanted} is used by something else (not this dashboard); using ${free} instead. To make it stick, set "server": { "port": ${free} } in dashboard.config.json.`);
    port = free;
  }
}

const children = [];
const stop = (code = 0) => {
  for (const c of children) if (!c.killed) c.kill();
  process.exit(code);
};

if (reuse) {
  console.log(`[analysis] this dashboard's server is already running on port ${port}; using it`);
} else {
  const api = spawn(python, [path.join(root, 'Analysis', 'server.py'), '--port', String(port)], { cwd: root, stdio: 'inherit' });
  api.on('exit', (code) => {
    if (code) console.log(`[analysis] server stopped (exit ${code}). Python 3 with fastapi, uvicorn, duckdb, pandas, pyarrow is needed.`);
  });
  children.push(api);
  for (let i = 0; i < 60 && !(await inUse(port)); i++) await new Promise((r) => setTimeout(r, 250));
}

const vite = path.join(root, 'node_modules', 'vite', 'bin', 'vite.js');
const ui = spawn(process.execPath, [vite, ...viteArgs], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, DASH_API_PORT: String(port), ...(agent ? { DASHBOARD_AGENT: 'on' } : {}) },
});
children.push(ui);
ui.on('exit', (code) => stop(code ?? 0));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => stop(0));
