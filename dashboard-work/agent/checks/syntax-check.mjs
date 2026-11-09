// Dashboard agent check: parse JSX from stdin, print "OK" or the parse error (exit 1).
// Run by section_agent.run_check as `node --input-type=module -e` with cwd = the project, so
// `vite` below resolves to the project's node_modules (the skill folder has none).
import { transformWithOxc } from 'vite';

let src = '';
for await (const chunk of process.stdin) src += chunk;
try {
  await transformWithOxc(src, 'section.jsx', { lang: 'jsx' });
  console.log('OK');
} catch (e) {
  console.log(String(e.message).replace(/\x1b\[[0-9;]*m/g, '').split('\n').slice(0, 12).join('\n'));
  process.exit(1);
}
