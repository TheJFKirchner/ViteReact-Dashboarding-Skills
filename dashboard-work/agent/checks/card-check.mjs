// Dashboard agent check (card chart edits, v2 projects). stdin: JSON { original, candidate }.
// Run by section_agent.run_check as `node --input-type=module -e` with cwd = the project, so `vite`
// resolves to the project's node_modules. Prints "OK" or the problems (exit 1).
// In v2 a card only DISPLAYS: its numbers arrive computed from Python (Analysis/) as the `data` and
// `metrics` props. A chart edit may restyle and reshape for display, but must not add:
//   - data loading: fetch / XHR / WebSocket / EventSource / storage / window / document / eval /
//     dynamic import() / import.meta / require
//   - arithmetic over data: math operators (- * / % **, + between non-strings, ++, +=, ...), array
//     computations (reduce, filter, sort, flatMap, find, some, every, ...), Math.* other than display
//     rounding (round, floor, ceil, abs), parseFloat / parseInt
// Compared with the original by source text: code that was already there may stay or move; anything new
// of these kinds is rejected. New numbers belong in the card's Analysis function (a Claude Code job).
import { parseAst } from 'vite';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const { original, candidate } = JSON.parse(input);

const LOADING = new Set(['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'localStorage', 'sessionStorage', 'indexedDB', 'caches',
  'eval', 'Function', 'require', 'importScripts', 'Worker', 'SharedWorker', 'window', 'document', 'globalThis', 'navigator', 'location']);
const ARRAY_MATH = new Set(['reduce', 'reduceRight', 'filter', 'sort', 'toSorted', 'flatMap', 'find', 'findLast', 'findIndex', 'findLastIndex',
  'some', 'every', 'groupBy', 'splice', 'fill', 'copyWithin']);
const DISPLAY_MATH = new Set(['round', 'floor', 'ceil', 'abs']);
const ARITH = new Set(['-', '*', '/', '%', '**', '+']);
const isText = (n) => (n.type === 'Literal' && typeof n.value === 'string') || n.type === 'TemplateLiteral';
const isNumber = (n) => n.type === 'Literal' && typeof n.value === 'number';
const name = (n) => (n?.type === 'Identifier' ? n.name : n?.type === 'Literal' ? String(n.value) : null);

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

/** { "<kind>|<normalized source>": count } for every data-loading / arithmetic construct in code. */
function constructs(code) {
  const ast = parseAst(code, { lang: 'jsx' });
  const out = {};
  const add = (kind, node) => {
    const text = code.slice(node.start, node.end).replace(/\s+/g, '');
    const k = `${kind}|${text.length > 80 ? text.slice(0, 80) + '…' : text}`;
    out[k] = (out[k] ?? 0) + 1;
  };
  walk(ast, (n, parent, key) => {
    if (n.type === 'Identifier' && LOADING.has(n.name)) {
      const isProp = (parent?.type === 'MemberExpression' && key === 'property' && !parent.computed) || (parent?.type === 'Property' && key === 'key' && !parent.computed);
      if (!isProp) add(`uses ${n.name}`, n);
    } else if (n.type === 'ImportExpression') add('dynamic import()', n);
    else if (n.type === 'MetaProperty') add('import.meta', n);
    else if (n.type === 'BinaryExpression' && ARITH.has(n.operator)) {
      if (n.operator === '+' && (isText(n.left) || isText(n.right))) return; // string building
      if (isNumber(n.left) && isNumber(n.right)) return; // constant styling value
      add('arithmetic', n);
    } else if (n.type === 'UpdateExpression') add('arithmetic', n);
    else if (n.type === 'AssignmentExpression' && n.operator !== '=' && /^[-+*/%]|\*\*/.test(n.operator)) add('arithmetic', n);
    else if (n.type === 'CallExpression') {
      const c = n.callee;
      if (c.type === 'MemberExpression' && !c.computed && ARRAY_MATH.has(name(c.property))) add(`data operation .${name(c.property)}()`, n);
      else if (c.type === 'MemberExpression' && name(c.object) === 'Math' && !DISPLAY_MATH.has(name(c.property))) add(`Math.${name(c.property)}()`, n);
      else if (c.type === 'Identifier' && ['parseFloat', 'parseInt'].includes(c.name)) add(`${c.name}()`, n);
    }
  });
  return out;
}

let before;
let after;
try {
  before = constructs(original);
  after = constructs(candidate);
} catch (e) {
  console.log(`could not read the card: ${String(e.message).split('\n')[0]}`);
  process.exit(1);
}
const problems = [];
for (const [k, n] of Object.entries(after)) {
  if (n <= (before[k] ?? 0)) continue;
  const [kind, text] = k.split('|');
  problems.push(kind.startsWith('uses') || kind.includes('import') ? `${kind} is not allowed in a card (cards never load data)` : `adds ${kind} \`${text}\` (cards don't compute numbers)`);
}
if (problems.length) {
  console.log([...new Set(problems)].slice(0, 6).join('\n'));
  process.exit(1);
}
console.log('OK');
