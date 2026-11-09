// Dashboard agent check (component target). stdin: JSON { file, original, candidate, allow }.
// Run by section_agent.run_check as `node --input-type=module -e` with cwd = the project, so
// `vite` resolves to the project's node_modules. Prints "OK" or the problems (exit 1).
// A shared component may change how it looks and works, never its contract with the places that
// use it, and never reach outside the page:
//   - same exports (default + named)
//   - every prop accepted before is still accepted; new props have a default
//   - imports only from `allow` (project-relative paths or package names) or what it already imports
//   - no network, storage, window/document, eval, dynamic import or raw HTML
import path from 'node:path';
import { parseAst } from 'vite';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const { file, original, candidate, allow } = JSON.parse(input);

const FORBIDDEN = new Set(['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'eval', 'Function', 'window', 'document', 'globalThis',
  'localStorage', 'sessionStorage', 'indexedDB', 'navigator', 'location', 'importScripts', 'Worker', 'SharedWorker', 'postMessage']);

function walk(node, visit, parent = null, key = null) {
  if (!node || typeof node.type !== 'string') return;
  visit(node, parent, key);
  for (const k in node) {
    if (k === 'parent') continue;
    const v = node[k];
    if (Array.isArray(v)) v.forEach((c) => walk(c, visit, node, k));
    else if (v && typeof v === 'object' && typeof v.type === 'string') walk(v, visit, node, k);
  }
}

function summarize(code) {
  const ast = parseAst(code, { lang: 'jsx' });
  const imports = [];
  const exports = [];
  const fns = {};
  let defaultNode = null;
  const used = {};
  for (const node of ast.body) {
    if (node.type === 'ImportDeclaration') imports.push(node.source.value);
    if (node.type === 'FunctionDeclaration' && node.id) fns[node.id.name] = node;
    if (node.type === 'VariableDeclaration') for (const d of node.declarations) if (d.id.type === 'Identifier' && d.init) fns[d.id.name] = d.init;
    if (node.type === 'ExportDefaultDeclaration') {
      exports.push('default');
      defaultNode = node.declaration;
    }
    if (node.type === 'ExportNamedDeclaration') {
      if (node.declaration?.id) exports.push(node.declaration.id.name);
      for (const d of node.declaration?.declarations ?? []) exports.push(d.id.name);
      for (const s of node.specifiers ?? []) exports.push(s.exported.name ?? s.exported.value);
      if (node.declaration?.type === 'FunctionDeclaration') fns[node.declaration.id.name] = node.declaration;
    }
  }
  if (defaultNode?.type === 'Identifier') defaultNode = fns[defaultNode.name] ?? null;
  walk(ast, (n, parent, key) => {
    let name = null;
    if (n.type === 'Identifier' && FORBIDDEN.has(n.name)) {
      const isProp = (parent?.type === 'MemberExpression' && key === 'property' && !parent.computed) || (parent?.type === 'Property' && key === 'key' && !parent.computed);
      if (!isProp) name = n.name;
    } else if (n.type === 'JSXAttribute' && n.name?.name === 'dangerouslySetInnerHTML') name = 'dangerouslySetInnerHTML';
    else if (n.type === 'ImportExpression') name = 'import()';
    if (name) used[name] = (used[name] ?? 0) + 1;
  });
  return { imports, exports: exports.sort(), props: propsOf(defaultNode), used };
}

/** { open: true } when props are taken whole or with ...rest; else { keys: {name: hasDefault} } */
function propsOf(fn) {
  if (!fn || !['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'].includes(fn.type)) return { open: true };
  let p = fn.params[0];
  if (!p) return { keys: {} };
  if (p.type === 'AssignmentPattern') p = p.left;
  if (p.type !== 'ObjectPattern') return { open: true };
  const keys = {};
  for (const prop of p.properties) {
    if (prop.type === 'RestElement') return { open: true };
    const name = prop.key?.name ?? prop.key?.value;
    if (name !== undefined) keys[name] = prop.value?.type === 'AssignmentPattern';
  }
  return { keys };
}

const resolveImport = (spec) => (spec.startsWith('.') ? path.posix.normalize(path.posix.join(path.posix.dirname(file), spec)) : spec);

const problems = [];
let before;
let after;
try {
  before = summarize(original);
  after = summarize(candidate);
} catch (e) {
  console.log(`could not read the component: ${String(e.message).split('\n')[0]}`);
  process.exit(1);
}

if (before.exports.join() !== after.exports.join()) problems.push(`exports changed (${before.exports.join(', ')} -> ${after.exports.join(', ')}); keep them exactly`);
// props taken whole or with ...rest accept everything, so only two destructured lists are compared
if (!before.props.open && !after.props.open) {
  for (const k of Object.keys(before.props.keys)) if (!(k in after.props.keys)) problems.push(`prop "${k}" is no longer accepted; places that pass it would break`);
  for (const [k, hasDefault] of Object.entries(after.props.keys)) if (!(k in before.props.keys) && !hasDefault) problems.push(`new prop "${k}" needs a default value (no place passes it)`);
}
const allowed = new Set([...allow, ...before.imports.map(resolveImport)]);
for (const spec of after.imports) if (!allowed.has(resolveImport(spec))) problems.push(`import from "${spec}" is not allowed (allowed: ${[...allowed].join(', ')})`);
for (const [name, n] of Object.entries(after.used)) if (n > (before.used[name] ?? 0)) problems.push(`${name} is not allowed in a shared component`);

if (problems.length) {
  console.log(problems.slice(0, 6).join('\n'));
  process.exit(1);
}
console.log('OK');
