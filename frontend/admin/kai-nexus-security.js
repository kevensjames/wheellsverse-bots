/* KAI Adaptive Mission Nexus — Security & Governance Posture (Phase 8, §20/§21)
 *
 * Pure UMD logic (browser + node), no DOM — unit-testable. This is the "alert
 * doctrine": the ONE place a severity may be *inferred*, and it is always labeled
 * as such. Ground truth (docs/KAI_SECURITY_SOURCES.md):
 *   - Only the host/ops scanner (Supreme) and App A defensive scanner carry a REAL
 *     severity IN the data ("measured").
 *   - Governance audit rows (scope-denied / destructive-without-approval) are the
 *     richest REAL security *facts* but have NO severity → any severity is INFERRED
 *     by the explicit rule below, never claimed as a source fact.
 *   - Unmeasured posture is UNKNOWN/UNAVAILABLE, never a fabricated "CLEAR".
 * External/log text (audit error, scanner detail, action names) is UNTRUSTED data
 * (can embed attacker-influenced input, e.g. a path in a scope-denied action) — every
 * finding is untrusted:true and rendered via textContent/escapeHtml, never eval'd.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.NexusSecurity = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Severity ladder mirrors backend/app/services/supreme/scanner.py SEVERITY_LEVELS
  // (plus 'unknown' for the honest no-severity case).
  const SEVERITY = ['unknown', 'info', 'low', 'medium', 'high', 'critical'];
  const sevRank = (s) => { const i = SEVERITY.indexOf(String(s == null ? 'unknown' : s).toLowerCase()); return i < 0 ? 0 : i; };
  const worstSeverity = (list) => (list || []).reduce((w, s) => (sevRank(s) > sevRank(w) ? String(s).toLowerCase() : w), 'unknown');

  const escapeHtml = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let _seq = 0;
  const nextId = (p) => (p || 'sec') + '-' + (++_seq);
  function _resetSeq() { _seq = 0; }   // test-only determinism

  // ── canonical finding/event model ──────────────────────────────────────────
  // severity_origin: 'measured' (source carries a real severity field)
  //                | 'inferred' (we applied an explicit documented rule — NOT a fact)
  //                | 'none'     (no severity available and none inferred → UNKNOWN)
  // provenance: REAL | DERIVED | DEMO | UNAVAILABLE  (defaults DERIVED, never silently REAL)
  function normalizeFinding(raw, opts) {
    raw = raw || {}; opts = opts || {};
    const source = opts.source || raw.source || 'unknown';
    const provenance = opts.provenance || raw.provenance || 'DERIVED';
    let severity, severity_origin;
    if (opts.severity != null) {                       // explicit (inferred) severity
      severity = String(opts.severity).toLowerCase();
      severity_origin = opts.severity_origin || 'inferred';
    } else if (raw.severity != null && String(raw.severity).length) {  // measured field
      severity = String(raw.severity).toLowerCase();
      severity_origin = 'measured';
    } else {                                           // honest no-severity
      severity = 'unknown'; severity_origin = 'none';
    }
    return {
      finding_id: raw.finding_id || raw.id || nextId(source),
      source,                                   // governance | host-scan | defensive-scan | posture
      category: raw.category || opts.category || 'general',
      severity, severity_origin,
      provenance,
      title: opts.title || raw.title || raw.action || '(untitled)',
      detail: raw.detail != null ? raw.detail : (raw.error || ''),
      ts: raw.ts || raw.scanned_at || null,
      actor: raw.actor != null ? raw.actor : null,     // caller-supplied string, NOT authenticated identity
      decision: opts.decision || raw.decision || null, // {scope,approved,success,error,destructive}
      correlation_count: raw.correlation_count || 1,
      untrusted: true,
    };
  }

  // ── ALERT DOCTRINE — the ONE inference rule (explicit, documented, tested) ───
  // A governance audit row (data/governance/audit.jsonl) has no severity. We infer
  // one ONLY from structural fields; the result is always severity_origin:'inferred'.
  function inferGovernanceSeverity(record) {
    record = record || {};
    if (record.success === true) return { severity: 'info', reason: 'successful governed action' };
    const destructive = !!record.destructive;
    const err = String(record.error || '').toLowerCase();
    if (destructive && record.approved !== true) return { severity: 'high', reason: 'destructive action invoked without approval' };
    if (err.indexOf('scope') !== -1 && err.indexOf('not enabled') !== -1) return { severity: 'medium', reason: 'scope-denied' };
    if (record.success === false) return { severity: destructive ? 'high' : 'medium', reason: destructive ? 'destructive action failed' : 'governed action failed' };
    return { severity: 'unknown', reason: 'insufficient signal' };
  }

  // Normalize a governance audit.jsonl row → finding (severity ALWAYS inferred).
  function normalizeGovernanceRow(row, provenance) {
    row = row || {};
    const inf = inferGovernanceSeverity(row);
    const isDenial = row.success === false;
    return normalizeFinding(row, {
      source: 'governance',
      category: isDenial ? 'governance_denial' : 'governance_action',
      provenance: provenance || 'REAL',
      severity: inf.severity,
      severity_origin: inf.severity === 'unknown' ? 'none' : 'inferred',
      title: (isDenial ? 'DENIED · ' : '') + (row.action || 'action'),
      decision: { scope: row.scope || null, approved: !!row.approved, success: row.success === true, error: row.error || null, destructive: !!row.destructive, reason: inf.reason },
    });
  }

  // Host/ops scanner (Supreme) finding — severity is MEASURED, but it is host/ops
  // health, NOT external threat intel. Caller labels the pane accordingly.
  function normalizeHostFinding(raw, provenance) {
    return normalizeFinding(raw, { source: 'host-scan', provenance: provenance || 'REAL' });
  }
  // App A defensive file scanner finding — severity MEASURED (per-pattern table).
  function normalizeDefensiveFinding(raw, provenance) {
    return normalizeFinding(raw, { source: 'defensive-scan', provenance: provenance || 'REAL' });
  }

  // ── dedupe + correlate ──────────────────────────────────────────────────────
  // Exact dupes collapse by (source|finding_id). Governance denials for the SAME
  // (scope, action-title) correlate into one row with a real count — no fabricated
  // correlation across unrelated events.
  function dedupeFindings(list) {
    list = list || [];
    const byId = new Map();
    for (const f of list) {
      const k = f.source + '|' + f.finding_id;
      if (!byId.has(k)) byId.set(k, f);
    }
    const uniq = [...byId.values()];
    const groups = new Map();
    const out = [];
    for (const f of uniq) {
      if (f.source === 'governance' && f.category === 'governance_denial' && f.decision) {
        const gk = 'gov|' + (f.decision.scope || '') + '|' + f.title;
        // idempotent: preserve the incoming count so re-running dedupe never resets correlation to 1
        if (groups.has(gk)) { const g = groups.get(gk); g.correlation_count += (f.correlation_count || 1); if (sevRank(f.severity) > sevRank(g.severity)) g.severity = f.severity; continue; }
        const clone = Object.assign({}, f, { correlation_count: f.correlation_count || 1 });
        groups.set(gk, clone); out.push(clone);
      } else out.push(f);
    }
    return out;
  }

  // ── posture summary ─────────────────────────────────────────────────────────
  // Each field carries its own provenance. NEVER green unless a real source confirms it;
  // unmeasured → UNKNOWN/UNAVAILABLE. An INERT owner gate (API_KEY unset) is itself a
  // CRITICAL posture alert (measured — os env is a real fact).
  function posture(p) {
    p = p || {};
    const field = (val, prov, detail, sev) => ({ value: val, provenance: prov, detail: detail || '', severity: sev });
    const gate = (p.apiKeyArmed == null)
      ? field('UNKNOWN', 'UNAVAILABLE', 'owner gate state not reported', 'unknown')
      : (p.apiKeyArmed
        ? field('ARMED', 'REAL', 'owner API-key gate active', 'info')
        : field('INERT', 'REAL', 'API_KEY unset — owner gate disabled', 'critical'));
    let bridge;
    if (p.bridge == null) bridge = field('UNKNOWN', 'UNAVAILABLE', 'bridge health not reported', 'unknown');
    else if (!p.bridge.enabled) bridge = field('DISABLED', 'REAL', 'governed bridge disabled', 'medium');
    else if (!p.bridge.upstream_configured) bridge = field('NO_UPSTREAM', 'REAL', 'bridge enabled but upstream not configured', 'medium');
    else bridge = field('ENABLED', 'REAL', 'governed bridge enabled + upstream configured', 'info');
    const principal = (p.principal == null)
      ? { value: 'UNKNOWN', provenance: 'UNAVAILABLE', role: null, scopes: [], source: null }
      : { value: (p.principal.role || 'unknown').toUpperCase(), provenance: 'REAL', role: p.principal.role || null, scopes: p.principal.scopes || [], source: p.principal.source || null };
    const findings = p.findings || [];
    const scanCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0, unknown: 0 };
    for (const f of findings) scanCounts[f.severity] = (scanCounts[f.severity] || 0) + 1;
    // worst = worst of {gate/bridge posture severities, measured finding severities}.
    // Inferred severities do NOT drive the top-line posture (honesty: inference ≠ measurement).
    const measuredSevs = findings.filter((f) => f.severity_origin === 'measured').map((f) => f.severity);
    const worst = worstSeverity([gate.severity, bridge.severity].concat(measuredSevs));
    // probed = the security-critical dimensions (gate + bridge) are both REAL-confirmed.
    // A green "CLEAR" is only honest when probed is true (see syncSecurityHeader).
    const probed = gate.provenance === 'REAL' && bridge.provenance === 'REAL';
    return { gate, bridge, principal, scanCounts, worst, probed, finding_count: findings.length };
  }

  // ── summary counts (for the left-rail cells) ────────────────────────────────
  function summarize(findings) {
    findings = findings || [];
    const bySeverity = {}, bySource = {}, byOrigin = { measured: 0, inferred: 0, none: 0 };
    for (const f of findings) {
      bySeverity[f.severity] = (bySeverity[f.severity] || 0) + 1;
      bySource[f.source] = (bySource[f.source] || 0) + 1;
      byOrigin[f.severity_origin] = (byOrigin[f.severity_origin] || 0) + 1;
    }
    const denials = findings.filter((f) => f.category === 'governance_denial').length;
    return { total: findings.length, bySeverity, bySource, byOrigin, denials, worst: worstSeverity(findings.map((f) => f.severity)) };
  }

  // ── promote to the existing store.alerts strip (reuse, don't rebuild) ────────
  // Honesty: the header goes CRITICAL only for a MEASURED critical (or the INERT
  // owner gate). An INFERRED high never escalates past 'warning'.
  function promoteToStoreAlert(f) {
    if (!f) return null;
    let sev;
    if (f.severity === 'critical' && f.severity_origin === 'measured') sev = 'critical';
    else if (f.severity === 'critical' || f.severity === 'high') sev = 'warning';
    else if (f.severity === 'medium') sev = 'caution';
    else return null;   // low/info/unknown are not alert-worthy
    return { sev, system: f.source, title: f.title, detail: f.detail || (f.decision && f.decision.reason) || '', source: f.provenance };
  }

  return {
    SEVERITY, sevRank, worstSeverity, escapeHtml,
    normalizeFinding, inferGovernanceSeverity, normalizeGovernanceRow,
    normalizeHostFinding, normalizeDefensiveFinding,
    dedupeFindings, posture, summarize, promoteToStoreAlert,
    _resetSeq,
  };
});
