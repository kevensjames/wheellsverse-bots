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
const APP = join(HERE, '..', '..', 'frontend', 'sol', 'app');   // repo/frontend/sol/app
const HTML = join(APP, '..', 'app.html');                       // frontend/sol/app.html

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

// 5. Member session storage (core/session.js). Every page that reads or writes the member
// session loads core/session.js first, and nothing deletes a stored session except the
// user's own sign-out (logout()) and a sign-in replacing it (_solWriteSession): a tab's
// copy of localStorage can be behind the others', so a delete decided from it can remove
// a newer session (review 3, RV3-N1).
console.log('\n[4] member session storage');
const sessionIdx = order.indexOf('core/session.js'), stateIdx = order.indexOf('core/state.js');
if (sessionIdx === -1 || sessionIdx > stateIdx) fail(`app.html must load core/session.js before core/state.js (order: ${order.slice(0, 4).join(', ')})`);
else ok('app.html loads core/session.js before core/state.js');
const indexHtml = readFileSync(join(APP, '..', 'index.html'), 'utf8');
const tagAt = indexHtml.indexOf('<script src="/sol/app/core/session.js"></script>'), finishAt = indexHtml.indexOf('function finishAuth(');
if (tagAt === -1 || finishAt === -1 || tagAt > finishAt) fail('index.html must load core/session.js before the script with finishAuth()');
else ok('index.html loads core/session.js before finishAuth()');
const bodyOf = (src, name) => { const i = src.indexOf(`function ${name}(`); return i === -1 ? '' : src.slice(i, src.indexOf('\n}\n', i) + 2); };
const allowed = { 'core/router.js': ['logout'], 'core/session.js': ['_solWriteSession'] };
let deletes = 0;
for (const rel of order) {
  const src = readFileSync(join(APP, rel), 'utf8');
  const all = (src.match(/removeItem\(\s*['"]sol_(?:token|refresh)['"]\s*\)/g) || []).length;
  const inAllowed = (allowed[rel] || []).reduce((n, fn) => n + (bodyOf(src, fn).match(/removeItem\(\s*['"]sol_(?:token|refresh)['"]\s*\)/g) || []).length, 0);
  if (all > inAllowed) { deletes++; fail(`${rel}: deletes a stored member token outside ${JSON.stringify(allowed[rel] || [])} (${all - inAllowed} place(s))`); }
}
if (!deletes) ok('stored member tokens are deleted only by logout() and when a sign-in replaces them');

// 6. The member account pages. The pages an email link opens (reset-password.html,
// verify.html) hold a one-time token in memory: their own scripts never log it or store it.
// Every page that uses window.SolAccount (core/account.js) loads it first, and the inline
// scripts of the standalone pages parse.
console.log('\n[5] member account pages');
const SOL_DIR = join(APP, '..');
const ACCOUNT_TAG = '<script src="/sol/app/core/account.js"></script>';
const accIdx = order.indexOf('core/account.js');
const usesAccount = ['pages/settings.js', 'pages/onboarding.js', 'pages/dashboard.js'].map(r => order.indexOf(r)).filter(i => i !== -1);
if (accIdx === -1) fail('app.html must load core/account.js');
else if (usesAccount.some(i => i < accIdx)) fail('app.html must load core/account.js before the pages that use it');
else ok('app.html loads core/account.js before the pages that use it');
for (const rel of ['pages/settings.js', 'pages/onboarding.js', 'core/a11y.js']) {
  if (order.indexOf(rel) === -1) fail(`app.html must load ${rel}`);
}
const inlineScripts = src => [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
for (const [file, mustHoldToken] of [['index.html', false], ['reset-password.html', true], ['verify.html', true]]) {
  let src;
  try { src = readFileSync(join(SOL_DIR, file), 'utf8'); } catch { fail(`frontend/sol/${file} is missing`); continue; }
  const tagAt = src.indexOf(ACCOUNT_TAG), inlineAt = src.search(/<script>/);
  if (tagAt === -1 || inlineAt === -1 || tagAt > inlineAt) { fail(`${file}: must load core/account.js before its own script`); continue; }
  const inline = inlineScripts(src).join('\n');
  const tmpInline = join(HERE, '.inline.tmp.js');
  try { writeFileSync(tmpInline, inline); check(tmpInline); }
  catch (e) { fail(`${file}: inline script does not parse\n${e.stderr}`); continue; }
  finally { try { unlinkSync(tmpInline); } catch {} }
  if (mustHoldToken && /\bconsole\s*\.|\blocalStorage\b|\bsessionStorage\b|\bdocument\.cookie\b/.test(inline)) { fail(`${file}: the page holds an email-link token; its script must not use console, localStorage, sessionStorage or cookies`); continue; }
  ok(`${file}: loads core/account.js first; inline script parses${mustHoldToken ? '; no console or storage use' : ''}`);
}

console.log(`\n${fails ? '✗ ' + fails + ' FAILURE(S)' : '✓ all static checks passed'}`);
process.exit(fails ? 1 : 0);
