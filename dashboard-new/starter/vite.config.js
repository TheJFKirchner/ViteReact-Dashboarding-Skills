// Live dashboard config (npm run dev / dev:agent / build).
// Data comes from the Analysis server: Vite forwards /api to it (Tools/dev.mjs starts both).
// The dashboard agent is added only by `npm run dev:agent` (Tools/agent-loader.js).
// @precomputed is an empty stub here; the export config points it at the report's precomputed results.
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import dashboardAgent from './Tools/agent-loader.js';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const config = JSON.parse(fs.readFileSync(here('./dashboard.config.json'), 'utf8'));
const apiPort = process.env.DASH_API_PORT || config.server?.port || 8765;

export default defineConfig({
  plugins: [react(), ...(await dashboardAgent({ root: here('.') }))],
  resolve: { alias: { '@precomputed': here('./Src/Lib/no-precomputed.js') } },
  server: {
    proxy: { '/api': `http://127.0.0.1:${apiPort}` },
    // Python, data and exports never reload the page (the Analysis server picks up its own edits)
    watch: { ignored: ['**/Exports/**', '**/.export/**', '**/Data/**', '**/Analysis/**', '**/Pipeline/**', '**/__pycache__/**'] },
  },
  build: { outDir: 'Dist', chunkSizeWarningLimit: 5000 },
  // Plotly is imported lazily (only sections that use it load it). Pre-bundle it at dev-server start,
  // otherwise its first load triggers a re-optimize and the chart fails with "Outdated Optimize Dep".
  optimizeDeps: { include: ['plotly.js-cartesian-dist-min'] },
  // A second dev server on the same project (tests) must not share the dependency cache:
  // set VITE_CACHE_DIR=node_modules/.vite-test for it.
  cacheDir: process.env.VITE_CACHE_DIR || 'node_modules/.vite',
});
