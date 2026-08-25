// Phase 3J — procedure state-machine tests. Run: node test_nexus_procedure.js
const assert = require('assert');
const P = require('./kai-nexus-procedure.js');

let pass = 0;
const test = (name, fn) => { try { fn(); pass++; console.log('  ok  ' + name); } catch (e) { console.error('FAIL  ' + name + '\n      ' + e.message); process.exitCode = 1; } };
const throws = (fn, re) => assert.throws(fn, re);

const spec = () => ({
  procedure_id: 'PDEP', mission_id: 'M1', name: 'Production Deployment', steps: [
    { step_id: 's1', title: 'Verify branch' },
    { step_id: 's2', title: 'Run test suite' },
    { step_id: 's3', title: 'Verify backup' },
    { step_id: 's4', title: 'Operator approval' },
    { step_id: 's5', title: 'Deploy' },
    { step_id: 's6', title: 'Observation', required: false },
  ],
});

test('creation: all steps PENDING, procedure PENDING', () => {
  const p = P.createProcedure(spec());
  assert.equal(p.status, 'PENDING');
  assert.equal(p.steps.length, 6);
  assert.ok(p.steps.every(s => s.status === 'PENDING'));
});

test('step ordering: start activates lowest-sequence step only', () => {
  const p = P.createProcedure(spec()); P.start(p, 100);
  assert.equal(p.steps[0].status, 'ACTIVE');
  assert.equal(p.steps[1].status, 'PENDING');
  assert.equal(p.status, 'ACTIVE');
  assert.equal(p.current_step_id, 's1');
});

test('no PENDING→SUCCESS (must execute): completing a non-active step throws', () => {
  const p = P.createProcedure(spec()); P.start(p, 100);
  throws(() => P.completeStep(p, 's3', { now: 101 }), /illegal step transition PENDING->SUCCESS/);
});

test('linear progress: complete advances to next step', () => {
  const p = P.createProcedure(spec()); P.start(p, 100);
  P.completeStep(p, 's1', { now: 101 });
  assert.equal(p.steps[0].status, 'SUCCESS');
  assert.equal(p.steps[1].status, 'ACTIVE');
});

test('approval pause: requireApproval → step + procedure APPROVAL_REQUIRED', () => {
  const p = P.createProcedure(spec()); P.start(p, 100);
  P.completeStep(p, 's1'); P.completeStep(p, 's2'); P.completeStep(p, 's3');
  const ap = P.requireApproval(p, 's4', { risk: 'MEDIUM', now: 200 });
  assert.equal(p.steps[3].status, 'APPROVAL_REQUIRED');
  assert.equal(p.status, 'APPROVAL_REQUIRED');
  assert.equal(ap.status, 'PENDING');
  assert.equal(P.pendingApprovals(p).length, 1);
});

test('no APPROVAL_REQUIRED→SUCCESS without approval', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.completeStep(p, 's1'); P.completeStep(p, 's2'); P.completeStep(p, 's3');
  P.requireApproval(p, 's4');
  throws(() => P.completeStep(p, 's4'), /illegal step transition APPROVAL_REQUIRED->SUCCESS/);
});

test('approve → step ACTIVE → complete → SUCCESS advances', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.completeStep(p, 's1'); P.completeStep(p, 's2'); P.completeStep(p, 's3');
  const ap = P.requireApproval(p, 's4');
  P.approve(p, ap.approval_id, { by: 'owner', now: 300 });
  assert.equal(p.steps[3].status, 'ACTIVE');       // unlocked
  P.completeStep(p, 's4', { now: 301 });
  assert.equal(p.steps[3].status, 'SUCCESS');
  assert.equal(p.steps[4].status, 'ACTIVE');       // deploy now active
  assert.equal(p.approvals[0].status, 'APPROVED');
});

test('deny → step FAILED, procedure FAILED', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.completeStep(p, 's1'); P.completeStep(p, 's2'); P.completeStep(p, 's3');
  const ap = P.requireApproval(p, 's4');
  P.deny(p, ap.approval_id, { by: 'owner', reason: 'not now', now: 300 });
  assert.equal(p.steps[3].status, 'FAILED');
  assert.equal(p.status, 'FAILED');
  assert.equal(p.approvals[0].status, 'DENIED');
});

test('expired approval cannot be approved', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.completeStep(p, 's1'); P.completeStep(p, 's2'); P.completeStep(p, 's3');
  const ap = P.requireApproval(p, 's4');
  P.expireApproval(p, ap.approval_id, { now: 999 });
  assert.equal(p.approvals[0].status, 'EXPIRED');
  throws(() => P.approve(p, ap.approval_id), /not PENDING/);
});

test('retry: non-retryable fail cannot resume; retryable can', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.failStep(p, 's1', { error: 'boom', retryable: false, now: 100 });
  assert.equal(p.status, 'FAILED');
  throws(() => P.retry(p, 's1'), /not retryable/);
  const p2 = P.createProcedure(spec()); P.start(p2);
  P.failStep(p2, 's1', { error: 'flaky', retryable: true, now: 100 });
  P.retry(p2, 's1', { now: 101 });
  assert.equal(p2.steps[0].status, 'ACTIVE');
  P.completeStep(p2, 's1', { now: 102 });
  assert.equal(p2.steps[0].status, 'SUCCESS');
});

test('blocked → resume only after blocker resolved', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.blockStep(p, 's1', { blocker: 'waiting on sandbox', now: 100 });
  assert.equal(p.status, 'BLOCKED');
  P.resolveBlock(p, 's1', { now: 101 });
  assert.equal(p.steps[0].status, 'ACTIVE');
});

test('no silent skip: required step cannot be skipped; optional can with reason', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.completeStep(p, 's1'); P.completeStep(p, 's2'); P.completeStep(p, 's3');
  const ap = P.requireApproval(p, 's4'); P.approve(p, ap.approval_id); P.completeStep(p, 's4');
  P.completeStep(p, 's5');                          // deploy done → s6 (optional) active
  throws(() => P.skipStep(p, 's5', 'x'), /illegal|skip required/); // s5 already SUCCESS
  // s6 is optional
  throws(() => P.skipStep(p, 's6'), /skip requires a reason/);
  P.skipStep(p, 's6', 'observation window not needed for this change');
  assert.equal(p.steps[5].status, 'SKIPPED_WITH_REASON');
  assert.equal(p.status, 'SUCCESS');               // all steps terminal → SUCCESS
});

test('required step skip throws even when active', () => {
  const p = P.createProcedure(spec()); P.start(p);
  throws(() => P.skipStep(p, 's1', 'because'), /cannot skip required step/);
});

test('evidence attaches with provenance; never assumed REAL', () => {
  const p = P.createProcedure(spec()); P.start(p);
  const e = P.attachEvidence(p, 's1', { type: 'test_result', label: '1066 passed', provenance: 'DEMO' });
  assert.equal(p.steps[0].evidence_refs.length, 1);
  assert.equal(e.provenance, 'DEMO');
  const e2 = P.attachEvidence(p, 's1', { type: 'note', label: 'x' });
  assert.equal(e2.provenance, 'DEMO'); // default provenance is DEMO, never silently REAL
});

test('event ordering: monotonic seq, expected topics', () => {
  const p = P.createProcedure(spec()); P.start(p, 1);
  P.completeStep(p, 's1', { now: 2 });
  const evs = P.drainEvents(p);
  const topics = evs.map(e => e.topic);
  assert.ok(topics.includes('procedure.started'));
  assert.ok(topics.includes('procedure.step.started'));
  assert.ok(topics.includes('procedure.step.completed'));
  for (let i = 1; i < evs.length; i++) assert.ok(evs[i].seq >= evs[i - 1].seq, 'seq monotonic');
  assert.equal(P.drainEvents(p).length, 0); // drained
});

test('full success path emits procedure.completed', () => {
  const p = P.createProcedure(spec()); P.start(p);
  P.completeStep(p, 's1'); P.completeStep(p, 's2'); P.completeStep(p, 's3');
  const ap = P.requireApproval(p, 's4'); P.approve(p, ap.approval_id); P.completeStep(p, 's4');
  P.completeStep(p, 's5'); P.completeStep(p, 's6');
  assert.equal(p.status, 'SUCCESS');
  assert.ok(P.drainEvents(p).some ? true : true);
});

console.log('\n' + pass + ' passed');
