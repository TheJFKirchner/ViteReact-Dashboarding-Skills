// Dashboard agent check (Page target): src/custom.css text from stdin. Run by
// section_agent.run_check as `node --input-type=module -e` with cwd = the project, so
// `postcss` resolves to the project's node_modules (it ships with Vite).
// Prints "OK" or the problem (exit 1). Parses with PostCSS (ships with Vite) and allows only
// plain style rules: no @import, no url(), no styling of the agent's own UI.
import postcss from 'postcss';

let src = '';
for await (const chunk of process.stdin) src += chunk;
const problems = [];
try {
  const root = postcss.parse(src);
  root.walkAtRules((r) => {
    if (!['media', 'supports', 'keyframes', 'container'].includes(r.name.toLowerCase())) problems.push(`@${r.name} is not allowed (only @media, @supports, @keyframes, @container)`);
  });
  root.walkRules((r) => {
    if (/\.agent-|#root\b/.test(r.selector)) problems.push(`selector "${r.selector}" targets the agent's own UI or the app root`);
  });
  root.walkDecls((d) => {
    if (/url\s*\(|expression\s*\(|javascript:/i.test(d.value)) problems.push(`${d.prop}: url()/expression() values are not allowed`);
    if (!d.value.trim()) problems.push(`${d.prop}: empty value`);
  });
} catch (e) {
  problems.push(String(e.reason || e.message) + (e.line ? ` (line ${e.line})` : ''));
}
if (problems.length) {
  console.log([...new Set(problems)].slice(0, 6).join('\n'));
  process.exit(1);
}
console.log('OK');
