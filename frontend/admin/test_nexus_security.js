/* Node tests for kai-nexus-security.js — the alert doctrine.
 * Run: node test_nexus_security.js   (no framework, assert-based) */
const assert = require('assert');
const S = require('./kai-nexus-security.js');

let pass = 0;
function test(name, fn) { try { S._resetSeq(); fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

// ── severity ladder ──────────────────────────────────────────────────────────
test('severity ordering matches the backend ladder', () => {
  assert.strictEqual(S.worstSeverity(['low', 'critical', 'medium']), 'critical');
  assert.strictEqual(S.worstSeverity(['info', 'low']), 'low');
  assert.strictEqual(S.worstSeverity([]), 'unknown');
  assert.ok(S.sevRank('critical') > S.sevRank('high'));
  assert.ok(S.sevRank('unknown') === 0);
});

// ── normalize: measured vs none, never silently REAL ─────────────────────────
test('measured severity when the source carries one', () => {
  const f = S.normalizeHostFinding({ id: 'disk-space', severity: 'high', category: 'disk_space', title: 'Low disk' });
  assert.strictEqual(f.severity, 'high');
  assert.strictEqual(f.severity_origin, 'measured');
  assert.strictEqual(f.provenance, 'REAL');
  assert.strictEqual(f.untrusted, true);
});
test('no severity + no inference → unknown/none (never invented)', () => {
  const f = S.normalizeFinding({ id: 'x', title: 'mystery' }, { source: 'governance' });
  assert.strictEqual(f.severity, 'unknown');
  assert.strictEqual(f.severity_origin, 'none');
});
test('provenance defaults to DERIVED, never silently REAL', () => {
  const f = S.normalizeFinding({ title: 't' });
  assert.strictEqual(f.provenance, 'DERIVED');
});

// ── the inference rule (alert doctrine) ──────────────────────────────────────
test('destructive-without-approval infers HIGH', () => {
  const r = S.inferGovernanceSeverity({ success: false, destructive: true, approved: false, error: 'destructive action invoked without approved=True' });
  assert.strictEqual(r.severity, 'high');
});
test('scope-denied infers MEDIUM', () => {
  const r = S.inferGovernanceSeverity({ success: false, destructive: false, error: "scope 'sol.transfer' not enabled" });
  assert.strictEqual(r.severity, 'medium');
});
test('successful governed action is not alert-worthy (info)', () => {
  const r = S.inferGovernanceSeverity({ success: true, destructive: true, approved: true });
  assert.strictEqual(r.severity, 'info');
});
test('governance severity is ALWAYS labeled inferred, never measured', () => {
  const f = S.normalizeGovernanceRow({ id: 'a1', action: 'sol.transfer', scope: 'sol.transfer', destructive: true, approved: false, success: false, error: 'destructive action invoked without approved=True', actor: 'operator' });
  assert.strictEqual(f.severity, 'high');
  assert.strictEqual(f.severity_origin, 'inferred');   // NOT 'measured'
  assert.strictEqual(f.category, 'governance_denial');
  assert.ok(f.title.startsWith('DENIED'));
  assert.strictEqual(f.decision.destructive, true);
  assert.strictEqual(f.decision.approved, false);
});
test('actor is preserved but is a caller string, not authenticated identity', () => {
  const f = S.normalizeGovernanceRow({ action: 'x', success: true, actor: 'operator' });
  assert.strictEqual(f.actor, 'operator');   // the pane must caveat this; the model just carries it
});

// ── dedupe + correlate ───────────────────────────────────────────────────────
test('exact dupes collapse by source|id', () => {
  const a = S.normalizeHostFinding({ id: 'port-kai', severity: 'critical', title: 'port down' });
  const b = S.normalizeHostFinding({ id: 'port-kai', severity: 'critical', title: 'port down' });
  const out = S.dedupeFindings([a, b]);
  assert.strictEqual(out.length, 1);
});
test('repeated scope-denials for the same scope correlate with a real count', () => {
  const rows = [
    S.normalizeGovernanceRow({ id: 'g1', action: 'sol.transfer', scope: 'sol.transfer', success: false, error: "scope 'sol.transfer' not enabled" }),
    S.normalizeGovernanceRow({ id: 'g2', action: 'sol.transfer', scope: 'sol.transfer', success: false, error: "scope 'sol.transfer' not enabled" }),
    S.normalizeGovernanceRow({ id: 'g3', action: 'kg.add_edge', scope: 'kg.write', success: false, error: "scope 'kg.write' not enabled" }),
  ];
  const out = S.dedupeFindings(rows);
  assert.strictEqual(out.length, 2);                       // two distinct (scope,title) groups
  const sol = out.find((f) => f.decision.scope === 'sol.transfer');
  assert.strictEqual(sol.correlation_count, 2);
});

// ── posture: never green unless real; inert gate is CRITICAL ─────────────────
test('missing inputs → UNKNOWN/UNAVAILABLE, never a fabricated CLEAR', () => {
  const p = S.posture({});
  assert.strictEqual(p.gate.value, 'UNKNOWN');
  assert.strictEqual(p.gate.provenance, 'UNAVAILABLE');
  assert.strictEqual(p.bridge.value, 'UNKNOWN');
  assert.strictEqual(p.principal.value, 'UNKNOWN');
});
test('an INERT owner gate (API_KEY unset) is a CRITICAL posture', () => {
  const p = S.posture({ apiKeyArmed: false, bridge: { enabled: true, upstream_configured: true } });
  assert.strictEqual(p.gate.value, 'INERT');
  assert.strictEqual(p.gate.severity, 'critical');
  assert.strictEqual(p.worst, 'critical');
});
test('inferred severities do NOT drive the top-line posture', () => {
  const denial = S.normalizeGovernanceRow({ action: 'sol.transfer', scope: 'sol.transfer', destructive: true, approved: false, success: false, error: 'no approval' }); // inferred high
  const p = S.posture({ apiKeyArmed: true, bridge: { enabled: true, upstream_configured: true }, findings: [denial] });
  assert.strictEqual(p.worst, 'info');   // inferred-high denial must not make posture 'high'
});

// ── promotion to the existing alert strip ────────────────────────────────────
test('measured critical → header critical; inferred high → only warning', () => {
  const measuredCrit = S.normalizeDefensiveFinding({ id: 'm1', severity: 'critical', title: 'reverse shell' });
  const inferredHigh = S.normalizeGovernanceRow({ action: 'dwolla.transfer', scope: 'dwolla.transfer', destructive: true, approved: false, success: false, error: 'no approval' });
  assert.strictEqual(S.promoteToStoreAlert(measuredCrit).sev, 'critical');
  assert.strictEqual(S.promoteToStoreAlert(inferredHigh).sev, 'warning');   // inference never screams CRITICAL
  assert.strictEqual(S.promoteToStoreAlert(S.normalizeFinding({ severity: 'low', title: 'x' }, { source: 'host-scan' })), null);
});

// ── summarize ────────────────────────────────────────────────────────────────
test('summarize counts by severity/source/origin and denials', () => {
  const fs = [
    S.normalizeHostFinding({ id: 'a', severity: 'high', title: 'x' }),
    S.normalizeGovernanceRow({ id: 'b', action: 'y', success: false, error: "scope 'z' not enabled" }),
    S.normalizeFinding({ id: 'c', title: 'q' }, { source: 'posture' }),
  ];
  const s = S.summarize(fs);
  assert.strictEqual(s.total, 3);
  assert.strictEqual(s.byOrigin.measured, 1);
  assert.strictEqual(s.byOrigin.inferred, 1);
  assert.strictEqual(s.byOrigin.none, 1);
  assert.strictEqual(s.denials, 1);
});

// ── security: untrusted content stays inert data ─────────────────────────────
test('injection in a governance error is preserved as data + escaped inert', () => {
  const evil = "scope 'x' not enabled <img src=x onerror=alert(1)>";
  const f = S.normalizeGovernanceRow({ action: 'a', success: false, error: evil });
  assert.strictEqual(f.detail, evil);                 // stored verbatim (data)
  assert.ok(f.untrusted);
  const html = S.escapeHtml(f.detail);
  assert.ok(html.indexOf('<img') === -1);             // escaped — inert when rendered
  assert.ok(html.indexOf('&lt;img') !== -1);
});

// ── posture: the security-incident invariant (measured critical + inferred high) ─
test('measured critical + inferred high together → posture critical (measurement wins)', () => {
  const measuredCrit = S.normalizeDefensiveFinding({ id: 'rs', severity: 'critical', title: 'reverse shell' });
  const inferredHigh = S.normalizeGovernanceRow({ action: 'dwolla.transfer', scope: 'dwolla.transfer', destructive: true, approved: false, success: false, error: 'no approval' });
  const p = S.posture({ apiKeyArmed: true, bridge: { enabled: true, upstream_configured: true }, findings: [measuredCrit, inferredHigh] });
  assert.strictEqual(p.worst, 'critical');
});

// ── posture: never green unless fully REAL-probed ────────────────────────────
test('fully REAL-probed armed posture → probed true, worst info', () => {
  const p = S.posture({ apiKeyArmed: true, bridge: { enabled: true, upstream_configured: true }, principal: { role: 'owner', scopes: [] } });
  assert.strictEqual(p.probed, true);
  assert.strictEqual(p.worst, 'info');
});
test('partial probe (gate UNAVAILABLE, bridge REAL) → probed false even if worst is info', () => {
  const p = S.posture({ bridge: { enabled: true, upstream_configured: true } });  // no apiKeyArmed → gate UNKNOWN/UNAVAILABLE
  assert.strictEqual(p.gate.provenance, 'UNAVAILABLE');
  assert.strictEqual(p.worst, 'info');       // worstSeverity ranks unknown below info
  assert.strictEqual(p.probed, false);       // ⇒ header must NOT show green CLEAR
});

// ── promoteToStoreAlert boundaries ───────────────────────────────────────────
test('promoteToStoreAlert: measured high → warning, medium → caution, null input → null', () => {
  assert.strictEqual(S.promoteToStoreAlert(S.normalizeHostFinding({ severity: 'high', title: 'x' })).sev, 'warning');
  assert.strictEqual(S.promoteToStoreAlert(S.normalizeFinding({ severity: 'medium', title: 'x' }, { source: 'host-scan' })).sev, 'caution');
  assert.strictEqual(S.promoteToStoreAlert(null), null);
});

// ── inferGovernanceSeverity: the remaining documented branches ───────────────
test('inferGovernanceSeverity: non-destructive failure → medium; destructive+approved failure → high; empty → unknown', () => {
  assert.strictEqual(S.inferGovernanceSeverity({ success: false, destructive: false, error: 'upstream timeout' }).severity, 'medium');
  assert.strictEqual(S.inferGovernanceSeverity({ success: false, destructive: true, approved: true }).severity, 'high');
  assert.strictEqual(S.inferGovernanceSeverity({}).severity, 'unknown');
  const f = S.normalizeGovernanceRow({ action: 'x' });   // no success/error → no signal
  assert.strictEqual(f.severity, 'unknown');
  assert.strictEqual(f.severity_origin, 'none');
});

// ── dedupe negatives: only same-(scope,title) denials correlate; nothing else ─
test('dedupe never merges distinct events (diff action, actions, or host-scan)', () => {
  const diffAction = S.dedupeFindings([
    S.normalizeGovernanceRow({ id: 'a', action: 'sol.transfer', scope: 'x', success: false, error: "scope 'x' not enabled" }),
    S.normalizeGovernanceRow({ id: 'b', action: 'kg.add_edge', scope: 'x', success: false, error: "scope 'x' not enabled" }),
  ]);
  assert.strictEqual(diffAction.length, 2);   // same scope, different action → not merged
  const successes = S.dedupeFindings([
    S.normalizeGovernanceRow({ id: 'c', action: 'digest.run', scope: 'digest', success: true }),
    S.normalizeGovernanceRow({ id: 'd', action: 'digest.run', scope: 'digest', success: true }),
  ]);
  assert.strictEqual(successes.length, 2);    // governance_action (not denial) → never correlated
  const hosts = S.dedupeFindings([
    S.normalizeHostFinding({ id: 'h1', severity: 'high', title: 'disk' }),
    S.normalizeHostFinding({ id: 'h2', severity: 'high', title: 'disk' }),
  ]);
  assert.strictEqual(hosts.length, 2);        // host-scan never correlated
});

// ── dedupe idempotency: re-running preserves the correlation count ───────────
test('dedupeFindings is idempotent — re-run keeps correlation_count', () => {
  const rows = [
    S.normalizeGovernanceRow({ id: 'g1', action: 'sol.transfer', scope: 'sol.transfer', success: false, error: "scope 'sol.transfer' not enabled" }),
    S.normalizeGovernanceRow({ id: 'g2', action: 'sol.transfer', scope: 'sol.transfer', success: false, error: "scope 'sol.transfer' not enabled" }),
  ];
  const once = S.dedupeFindings(rows);
  assert.strictEqual(once[0].correlation_count, 2);
  const twice = S.dedupeFindings(once);
  assert.strictEqual(twice.length, 1);
  assert.strictEqual(twice[0].correlation_count, 2);   // NOT reset to 1
});

console.log('\n' + pass + ' passed');
