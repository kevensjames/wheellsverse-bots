// SolGuard unit + concurrency tests (pure Node, zero dependencies).
//   node frontend/sol/app/tests/guard.test.mjs
//
// Loads the REAL core/guard.js in a vm sandbox that provides `window`, exactly
// like the browser global, and asserts every documented semantic of the ONE
// duplicate-submit lock: synchronous acquire, duplicate-drop, idempotent release,
// run()/runFor() release-in-finally on success + rejection + sync-throw, and
// per-record concurrency (reading notification A must not block B).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const HERE = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(HERE, '..', '..', 'frontend', 'sol', 'app', 'core', 'guard.js'), 'utf8');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const SolGuard = sandbox.window.SolGuard;

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) pass++; else { fail++; console.log('  ✗ FAIL:', msg); } };
const defer = () => { let r, j; const p = new Promise((res, rej) => { r = res; j = rej; }); return { p, resolve: r, reject: j }; };

// 1. acquire is synchronous, first wins, duplicate dropped
ok(SolGuard.acquire('k1') === true, 'acquire first time returns true');
ok(SolGuard.acquire('k1') === false, 'duplicate acquire returns false');
ok(SolGuard.isLocked('k1') === true, 'isLocked true while held');

// 2. release unlocks; idempotent
SolGuard.release('k1');
ok(SolGuard.isLocked('k1') === false, 'isLocked false after release');
ok(SolGuard.acquire('k1') === true, 're-acquire after release succeeds');
SolGuard.release('k1'); SolGuard.release('k1');   // double release must not throw
ok(true, 'double release is safe');

// 3. release of never-acquired key is safe
SolGuard.release('never-touched');
ok(SolGuard.isLocked('never-touched') === false, 'releasing unknown key is a no-op');

// 4. different keys are independent
ok(SolGuard.acquire('a') && SolGuard.acquire('b'), 'distinct keys both acquire');
SolGuard.release('a'); SolGuard.release('b');

(async () => {
  // 5. run(): returns fn value and releases on success
  const v = await SolGuard.run('r1', async () => 42);
  ok(v === 42, 'run returns fn value');
  ok(SolGuard.isLocked('r1') === false, 'run releases on success');

  // 6. run(): re-throws rejection AND releases
  let threw = false;
  try { await SolGuard.run('r2', async () => { throw new Error('boom'); }); } catch (e) { threw = e.message === 'boom'; }
  ok(threw, 'run re-throws the original error');
  ok(SolGuard.isLocked('r2') === false, 'run releases after rejection');

  // 7. run(): synchronous throw inside fn still releases + propagates
  let syncThrew = false;
  try { await SolGuard.run('r3', () => { throw new Error('sync'); }); } catch (e) { syncThrew = e.message === 'sync'; }
  ok(syncThrew, 'run propagates a synchronous throw');
  ok(SolGuard.isLocked('r3') === false, 'run releases after synchronous throw');

  // 8. run(): same-key duplicate returns undefined WITHOUT invoking fn
  const gate = defer();
  let firstCalls = 0, secondCalls = 0;
  const p1 = SolGuard.run('dup', async () => { firstCalls++; await gate.p; return 'first'; });
  const r2 = await SolGuard.run('dup', async () => { secondCalls++; return 'second'; });
  ok(r2 === undefined, 'duplicate run returns undefined');
  ok(secondCalls === 0, 'duplicate run does NOT invoke fn');
  gate.resolve();
  ok((await p1) === 'first', 'in-flight run still resolves normally');
  ok(firstCalls === 1, 'first run invoked exactly once');
  ok(SolGuard.isLocked('dup') === false, 'lock released after in-flight run settles');

  // 9. different-key concurrency: two long-running runs proceed in parallel
  const gA = defer(), gB = defer();
  let aRunning = false, bRunning = false;
  const pA = SolGuard.run('concA', async () => { aRunning = true; await gA.p; });
  const pB = SolGuard.run('concB', async () => { bRunning = true; await gB.p; });
  await Promise.resolve();
  ok(aRunning && bRunning, 'distinct keys run concurrently');
  gA.resolve(); gB.resolve(); await Promise.all([pA, pB]);

  // 10. per-record: runFor(scope,id) — record A must not block record B, but A blocks a 2nd A
  const gRec = defer();
  let recACalls = 0;
  const recA = SolGuard.runFor('payment:initiate', 'ID-A', async () => { recACalls++; await gRec.p; return 'A'; });
  const recADup = await SolGuard.runFor('payment:initiate', 'ID-A', async () => 'A-dup');
  const recB = await SolGuard.runFor('payment:initiate', 'ID-B', async () => 'B');
  ok(recADup === undefined, 'second acquire on same record dropped');
  ok(recB === 'B', 'different record runs while first record still in flight');
  ok(recACalls === 1, 'first record fn ran once');
  gRec.resolve(); await recA;
  ok(SolGuard.isLocked('payment:initiate:ID-A') === false, 'per-record lock released');

  console.log(`\nSolGuard: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
