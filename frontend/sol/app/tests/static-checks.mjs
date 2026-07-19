// SOL member app — static regression checks (pure Node, zero dependencies).
//   node frontend/sol/app/tests/static-checks.mjs
//
// The app is a BUILDLESS multi-file split: 19 classic <script src> files that
// share ONE global scope (not ES modules). Per-file syntax passing is necessary
// but NOT sufficient — two files each declaring a top-level `let x` parse alone
// yet throw "Identifier 'x' has already been declared" when the browser loads
// them together. These checks catch exactly that, on every change.
import { readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..');                 // frontend/sol/app
const HTML = join(APP, '..', 'app.html');     // frontend/sol/app.html

let fails = 0;
const fail = (m) => { fails++; console.log('  ✗', m); };
const ok = (m) => console.log('  ✓', m);
const check = (file) => execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' });

// 1. Load order comes from app.html itself (single source of truth).
const html = readFileSync(HTML, 'utf8');
const order = [...html.matchAll(/<script src="\/sol\/app\/([^"]+?)"><\/script>/g)].map(m => m[1]);
if (order.length < 15) fail(`expected the full module list in app.html, found ${order.length}`);
else ok(`load order read from app.html (${order.length} modules)`);

// 2. Per-file syntax.
console.log('\n[1] per-file syntax (node --check)');
let synOk = true;
for (const rel of order) {
  try { check(join(APP, rel)); }
  catch (e) { synOk = false; fail(`syntax: ${rel}\n${e.stderr}`); }
}
if (synOk) ok('all files parse');

// 3. Concatenation parse — the global-scope collision gate.
console.log('\n[2] concatenation parse (shared global scope)');
const concat = order.map(rel => `// ==== ${rel} ====\n` + readFileSync(join(APP, rel), 'utf8')).join('\n');
const tmp = join(HERE, '.concat.tmp.js');
try {
  writeFileSync(tmp, concat);
  check(tmp);
  ok('concat parses — no duplicate top-level let/const/class across the split');
} catch (e) {
  fail(`concat parse failed (a top-level identifier is declared in two files):\n${e.stderr}`);
} finally { try { unlinkSync(tmp); } catch {} }

// 4. Duplicate top-level symbol scan — two `function foo(){}` in different files
// is LEGAL (second silently wins) but is almost always an accidental clobber, and
// check [2] can't catch it (duplicate function/var don't throw). Duplicate
// let/const/class ARE caught by [2]; this scan is the extra net for function/var.
// Column-0 declarations only (the codebase's convention for globals); generators
// included. Multi-declarations (`let a, b`) intentionally not split — a colliding
// name in one is still caught by [2].
console.log('\n[3] duplicate top-level symbol scan');
const seen = new Map();
const dups = [];
for (const rel of order) {
  const src = readFileSync(join(APP, rel), 'utf8');
  for (const m of src.matchAll(/^(?:async\s+function\*?|function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)/gm)) {
    const name = m[1];
    if (seen.has(name)) dups.push(`${name}  (${seen.get(name)} + ${rel})`);
    else seen.set(name, rel);
  }
}
if (dups.length) dups.forEach(d => fail(`duplicate top-level symbol: ${d}`));
else ok(`no duplicate top-level symbols (${seen.size} unique)`);

console.log(`\n${fails ? '✗ ' + fails + ' FAILURE(S)' : '✓ all static checks passed'}`);
process.exit(fails ? 1 : 0);
