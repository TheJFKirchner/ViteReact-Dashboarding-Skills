// Export config: used only by Tools/export.mjs.
// Builds .export/index.html (written by the export script) into ONE self-contained HTML file.
// @precomputed = the report's card results for every allowed filter combination (Analysis/precompute.py),
// so the export needs no Analysis server (Src/Lib/source.js reads it instead of /api).
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { fileURLToPath } from 'node:url';
import { agentOff } from './Tools/agent-loader.js';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  root: here('./.export'),
  publicDir: false,
  plugins: [react(), viteSingleFile({ removeViteModuleLoader: true }), agentOff()], // exports never include the agent
  resolve: { alias: { '@precomputed': here('./.export/precomputed.json') } },
  json: { stringify: true }, // results are plain data: JSON.parse is faster to load than an object literal
  build: {
    outDir: here('./.export/dist'),
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000,
    chunkSizeWarningLimit: 100_000,
    reportCompressedSize: false,
  },
});
