// Vite plugin for the dashboard agent. Lives in the integrated-dashboards skill (one copy for
// every project); a project loads it through its Tools/agent-loader.js, only with
// `npm run dev:agent` / Start dashboard.cmd. Plain `npm run dev`, builds and exports never load it.
// - starts <skill>/agent/server.py for the project and stops it with the dev server
// - proxies /agent/* to it
// - serves the panel UI (<skill>/agent/ui) as the virtual module "virtual:dashboard-agent";
//   the UI reaches project code through the aliases @dash (Src/) and @dash-config
// - keeps *.agent-preview.jsx out of the file watcher (the app loads previews itself)
// - skips the reload Vite would do when Keep writes a file the app already shows (section file,
//   or the Page / Theme target's files, listed in <project>/.dashboard-agent/kept-writes.json)
// - Inspect: stamps every HTML element in Src/ with data-src="<file>:<line>"
// - component target: serves the preview code of a shared component in place of the real file
//   (<project>/.dashboard-agent/component-preview.json) and hot-swaps it on request from the tab
// This file must not import npm packages (the skill folder has no node_modules): the loader
// passes the project's own `vite` module in.
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const AGENT_DIR = path.dirname(fileURLToPath(import.meta.url));
const VIRTUAL = 'virtual:dashboard-agent';
const sha1 = (text) => crypto.createHash('sha1').update(text).digest('hex');

/** Insert data-src="Src/x.jsx:<line>" after the tag name of every lowercase JSX element. */
export function stampSource(parseAst, code, relPath) {
  let ast;
  try {
    ast = parseAst(code, { lang: 'jsx' });
  } catch {
    return null; // let the normal pipeline report the syntax error
  }
  const lineStarts = [0];
  for (let i = 0; i < code.length; i++) if (code.charCodeAt(i) === 10) lineStarts.push(i + 1);
  const lineOf = (pos) => {
    let lo = 0;
    let hi = lineStarts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (lineStarts[mid] <= pos) lo = mid;
      else hi = mid - 1;
    }
    return lo + 1;
  };
  const inserts = [];
  const walk = (node) => {
    if (!node || typeof node.type !== 'string') return;
    if (node.type === 'JSXOpeningElement' && node.name?.type === 'JSXIdentifier' && /^[a-z]/.test(node.name.name)) {
      const has = node.attributes.some((a) => a.type === 'JSXAttribute' && a.name?.name === 'data-src');
      if (!has) inserts.push([node.name.end, ` data-src="${relPath}:${lineOf(node.start)}"`]);
    }
    for (const key in node) {
      if (key === 'parent') continue;
      const v = node[key];
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v);
    }
  };
  walk(ast);
  if (!inserts.length) return null;
  inserts.sort((a, b) => b[0] - a[0]);
  let out = code;
  for (const [pos, text] of inserts) out = out.slice(0, pos) + text + out.slice(pos);
  return out;
}

export default function dashboardAgent({ root, vite, port = Number(process.env.DASH_AGENT_PORT || 8787) }) {
  const keptWrites = path.join(root, '.dashboard-agent', 'kept-writes.json');
  const componentPreview = path.join(root, '.dashboard-agent', 'component-preview.json');
  const srcDir = path.join(root, 'Src') + path.sep; // v2 layout: capitalized folders
  const same = (a, b) => path.normalize(a).toLowerCase() === path.normalize(b).toLowerCase();
  let child = null;

  // Component target: server.py writes { file, code } to component-preview.json; while it exists
  // (and the tab isn't showing "Original") that code is served in place of the real file.
  let showOriginal = false;
  let served = null; // { file, hash } of the preview code last served, null = real files
  const readPreview = () => {
    try {
      const p = JSON.parse(fs.readFileSync(componentPreview, 'utf8'));
      return { file: path.join(root, p.file), code: p.code };
    } catch {
      return null;
    }
  };
  const previewFor = (file) => {
    if (showOriginal) return null;
    const p = readPreview();
    return p && same(p.file, file) ? p.code : null;
  };
  const diskHash = (file) => {
    try {
      return sha1(fs.readFileSync(file, 'utf8'));
    } catch {
      return null;
    }
  };

  const python = () => process.env.DASH_AGENT_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

  const stamps = {
    name: 'dashboard-agent-source-stamps',
    apply: 'serve',
    enforce: 'pre',
    transform(code, id, options) {
      if (options?.ssr) return null;
      const file = path.normalize(id.split('?')[0]);
      if (!file.endsWith('.jsx') || !file.startsWith(srcDir)) return null;
      const out = stampSource(vite.parseAst, code, path.relative(root, file).split(path.sep).join('/'));
      return out ? { code: out, map: null } : null;
    },
  };

  const main = {
    name: 'dashboard-agent',
    apply: 'serve',
    config: () => ({
      define: { __DASHBOARD_AGENT__: 'true' },
      resolve: {
        alias: { '@dash-config': path.join(root, 'dashboard.config.json'), '@dash': path.join(root, 'Src') },
        dedupe: ['react', 'react-dom', 'echarts', 'zrender', 'plotly.js-cartesian-dist-min'], // the UI uses the project's copies
      },
      server: {
        fs: { allow: [root, AGENT_DIR] },
        proxy: { '/agent': { target: `http://127.0.0.1:${port}`, timeout: 120_000, proxyTimeout: 120_000 } },
        watch: { ignored: ['**/*.agent-preview.jsx', '**/.dashboard-agent/**'] },
      },
    }),
    resolveId: (id) => (id === VIRTUAL ? '\0' + VIRTUAL : null),
    load(id) {
      if (id === '\0' + VIRTUAL) return `export { default } from ${JSON.stringify(path.join(AGENT_DIR, 'ui', 'AgentProvider.jsx').split(path.sep).join('/'))};`;
      const file = path.normalize(id.split('?')[0]);
      if (!file.endsWith('.jsx') || !file.startsWith(srcDir)) return null;
      return previewFor(file); // component preview, else the real file
    },
    configureServer(server) {
      if (!server.httpServer) return; // absent when scripts load the project (check/export)
      fs.rmSync(componentPreview, { force: true });
      // The tab calls this after every component-target change: hot-swap the component module(s)
      // whose served code changed. React Fast Refresh then re-renders every place that uses it.
      server.middlewares.use('/__dashboard-agent/component-sync', (req, res) => {
        let body = '';
        req.on('data', (c) => (body += c));
        req.on('end', async () => {
          try {
            showOriginal = JSON.parse(body || '{}').view === 'original';
            const p = showOriginal ? null : readPreview();
            const next = p ? { file: p.file, hash: sha1(p.code) } : null;
            const files = [served?.file, next?.file].filter(Boolean).filter((f, i, all) => all.findIndex((g) => same(f, g)) === i);
            const env = server.environments?.client;
            const graph = env?.moduleGraph ?? server.moduleGraph;
            const reloaded = [];
            for (const f of files) {
              const before = served && same(served.file, f) ? served.hash : diskHash(f);
              const after = next && same(next.file, f) ? next.hash : diskHash(f);
              if (before === after) continue;
              for (const mod of graph.getModulesByFile(path.normalize(f)) ?? graph.getModulesByFile(f.split(path.sep).join('/')) ?? []) {
                await (env ? env.reloadModule(mod) : server.reloadModule(mod));
              }
              reloaded.push(path.relative(root, f).split(path.sep).join('/'));
            }
            served = next;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ reloaded }));
          } catch (e) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: e.message }));
          }
        });
      });
      const env = { ...process.env, DASH_PROJECT_ROOT: root, PYTHONDONTWRITEBYTECODE: '1' }; // no __pycache__ in the skill folder
      child = spawn(python(), [path.join(AGENT_DIR, 'server.py'), '--port', String(port)], { cwd: root, env });
      const log = (buf) => buf.toString().trim().split('\n').forEach((l) => l && server.config.logger.info(`[agent] ${l}`));
      child.stdout.on('data', log);
      child.stderr.on('data', log);
      child.on('error', (e) => server.config.logger.warn(`[agent] could not start Python (${e.message}); the dashboard runs without the agent`));
      const stop = () => child && !child.killed && child.kill();
      server.httpServer.on('close', stop);
      process.on('exit', stop);
    },
    handleHotUpdate({ file }) {
      // Page / Theme Keep: the app already shows the kept text, styles or theme; skip the reload
      try {
        const kept = JSON.parse(fs.readFileSync(keptWrites, 'utf8'));
        const hash = kept[path.normalize(file).toLowerCase()];
        if (hash && hash === sha1(fs.readFileSync(file, 'utf8'))) return [];
      } catch {
        /* no kept writes */
      }
      // Keep writes Src/Sections/<id>.jsx with the same text as the preview copy: no reload needed
      if (!file.endsWith('.jsx') || file.endsWith('.agent-preview.jsx')) return;
      const preview = file.replace(/\.jsx$/, '.agent-preview.jsx');
      try {
        if (fs.existsSync(preview) && fs.readFileSync(preview, 'utf8') === fs.readFileSync(file, 'utf8')) return [];
      } catch {
        /* fall through to a normal update */
      }
    },
  };
  return [stamps, main];
}
