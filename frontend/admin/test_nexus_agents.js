// Phase 5AF — agent registry tests. Run: node test_nexus_agents.js
const assert = require('assert');
const A = require('./kai-nexus-agents.js');

let pass = 0;
const test = (n, fn) => { try { fn(); pass++; console.log('  ok  ' + n); } catch (e) { console.error('FAIL  ' + n + '\n      ' + e.message); process.exitCode = 1; } };

test('normalizeStatus: source-specific → canonical; unknown → UNKNOWN', () => {
  assert.equal(A.normalizeStatus('running'), 'ACTIVE');
  assert.equal(A.normalizeStatus('done'), 'SUCCESS');
  assert.equal(A.normalizeStatus('ACTIVE'), 'ACTIVE');
  assert.equal(A.normalizeStatus('busy', { busy: 'ACTIVE' }), 'ACTIVE');
  assert.equal(A.normalizeStatus('weird-thing'), 'UNKNOWN');
  assert.equal(A.normalizeStatus(null), 'UNKNOWN');
});

test('duplicate reconciliation: same id from two sources → one agent, merged tools', () => {
  const r = A.createRegistry();
  r.upsert({ agent_id: 'research', name: 'Research', tools: ['Browser'], provenance: 'REAL' });
  r.upsert({ agent_id: 'research', tools: ['GitHub'], capabilities: ['search'] });
  assert.equal(r.all().length, 1);                       // not rendered twice
  const a = r.get('research');
  assert.deepEqual(a.tools.sort(), ['Browser', 'GitHub']);
  assert.deepEqual(a.capabilities, ['search']);
  assert.equal(a.name, 'Research');                       // preserved
});

test('summary counts exclude SUGGESTED (§5T)', () => {
  const r = A.createRegistry();
  r.upsert({ agent_id: 'a1', status: 'ACTIVE' });
  r.upsert({ agent_id: 'a2', status: 'BLOCKED' });
  r.upsert({ agent_id: 'a3', status: 'IDLE' });
  r.upsert({ agent_id: 's1', status: 'IDLE', suggested: true });
  const c = r.summarize();
  assert.equal(c.TOTAL, 3); assert.equal(c.ACTIVE, 1); assert.equal(c.BLOCKED, 1); assert.equal(c.SUGGESTED, 1);
});

test('agent.started event: ACTIVE + mission/task/delegated_by + activity logged', () => {
  const r = A.createRegistry();
  r.applyEvent({ topic: 'agent.registered', ts: 1, payload: { agent_id: 'research', name: 'Research', provenance: 'DEMO' } });
  r.applyEvent({ topic: 'agent.started', ts: 10, payload: { agent_id: 'research', mission_id: 'M1', task: 'Check deploys', delegated_by: 'KAI' } });
  const a = r.get('research');
  assert.equal(a.status, 'ACTIVE'); assert.equal(a.current_mission_id, 'M1');
  assert.equal(a.current_task, 'Check deploys'); assert.equal(a.delegated_by, 'KAI');
  assert.equal(a.started_at, 10); assert.ok(a.activity.length >= 2);
});

test('blocked event carries a real reason (§5O)', () => {
  const r = A.createRegistry();
  r.applyEvent({ topic: 'agent.blocked', ts: 5, payload: { agent_id: 'deploy', reason: 'WAITING_FOR_APPROVAL' } });
  assert.equal(r.get('deploy').status, 'BLOCKED');
  assert.equal(r.get('deploy').blocking_reason, 'WAITING_FOR_APPROVAL');
});

test('failed ≠ stale; completed carries result + cost provenance', () => {
  const r = A.createRegistry();
  r.applyEvent({ topic: 'agent.started', ts: 1, payload: { agent_id: 'x', mission_id: 'M1' } });
  r.applyEvent({ topic: 'agent.completed', ts: 9, payload: { agent_id: 'x', result: 'done', cost: 0.0, provider: 'ollama', model: 'llama3.1' } });
  const a = r.get('x');
  assert.equal(a.status, 'SUCCESS'); assert.equal(a.last_result, 'done');
  assert.equal(a.cost, 0.0); assert.equal(a.provider, 'ollama');
});

test('stale detection: ACTIVE beyond ttl → health STALE, status unchanged (§5N)', () => {
  const r = A.createRegistry();
  r.applyEvent({ topic: 'agent.started', ts: 1000, payload: { agent_id: 'r' } });
  r.detectStale(1000 + 400000, 300000);   // 400s idle, ttl 300s
  const a = r.get('r');
  assert.equal(a.health, 'STALE'); assert.equal(a.status, 'ACTIVE'); assert.ok(a.stale_for >= 300000);
  // a fresh agent is not stale
  r.applyEvent({ topic: 'agent.started', ts: 1000000, payload: { agent_id: 'fresh' } });
  r.detectStale(1000100, 300000); assert.notEqual(r.get('fresh').health, 'STALE');
});

test('event ordering: activity timeline is append-order', () => {
  const r = A.createRegistry();
  ['agent.started', 'agent.tool.started', 'agent.result.returned', 'agent.completed'].forEach((t, i) =>
    r.applyEvent({ topic: t, ts: i + 1, payload: { agent_id: 'z', tool: 'Browser' } }));
  const ev = r.get('z').activity.map(x => x.event);
  assert.deepEqual(ev, ['agent.started', 'agent.tool.started', 'agent.result.returned', 'agent.completed']);
});

test('unknown / offline states honest', () => {
  const r = A.createRegistry();
  r.upsert({ agent_id: 'u' });                            // no status
  assert.equal(r.get('u').status, 'UNKNOWN'); assert.equal(r.get('u').provenance, 'UNKNOWN');
  r.applyEvent({ topic: 'agent.offline', ts: 1, payload: { agent_id: 'u' } });
  assert.equal(r.get('u').status, 'OFFLINE');
});

test('DEMO isolation: provenance is explicit, never silently REAL', () => {
  const r = A.createRegistry();
  const a = r.upsert({ agent_id: 'd', provenance: 'DEMO' });
  assert.equal(a.provenance, 'DEMO');
  const u = r.upsert({ agent_id: 'e' });
  assert.equal(u.provenance, 'UNKNOWN');   // default is UNKNOWN, not REAL
});

// ── §5AE security ────────────────────────────────────────────────────────────
test('security: XSS-ish agent label stored as inert data (UI renders via textContent)', () => {
  const r = A.createRegistry();
  const a = r.upsert({ agent_id: 'x', name: '<img src=x onerror=alert(1)>', current_task: '`;drop table' });
  assert.equal(a.name, '<img src=x onerror=alert(1)>');   // stored verbatim; never eval'd/innerHTML'd
  assert.equal(a.current_task, '`;drop table');
});

test('security: applyEvent never elevates provenance to REAL from an unlabeled event', () => {
  const r = A.createRegistry();
  r.upsert({ agent_id: 'd', provenance: 'DEMO', status: 'IDLE' });
  r.applyEvent({ topic: 'agent.started', ts: 1, payload: { agent_id: 'd' } });   // no provenance in payload
  assert.equal(r.get('d').provenance, 'DEMO');            // stays DEMO — not silently REAL
});

test('security: client status is display-only — model holds no backend write path', () => {
  const r = A.createRegistry();
  // The registry has upsert/applyEvent (local view mutation) but NO invoke/execute
  // method — real actions must go through the governed backend (§5S/§5AE).
  ['invoke', 'execute', 'run', 'delegate', 'kill'].forEach(m => assert.equal(typeof r[m], 'undefined'));
});

console.log('\n' + pass + ' passed');
