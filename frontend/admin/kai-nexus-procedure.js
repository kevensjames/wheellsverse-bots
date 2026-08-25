// ============================================================================
// KAI NEXUS — canonical Procedure model + state machine (Phase 3A/3C).
// PURE (no DOM). UMD: window.NexusProcedure in the browser, module.exports in
// node (so the state machine is unit-testable without a browser).
//
// Governance (§3E): this module records + validates execution state ONLY. UI
// "approve" is NOT authorization — the caller must have passed backend
// governance first; approve() merely records the decision + unlocks the step.
// The machine REFUSES illegal transitions (no PENDING→SUCCESS, no
// APPROVAL_REQUIRED→SUCCESS without an APPROVED record, no silent skip of a
// required step) so the UI cannot fake progress.
// ============================================================================
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NexusProcedure = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const PROC = { PENDING: 'PENDING', ACTIVE: 'ACTIVE', WAITING: 'WAITING', BLOCKED: 'BLOCKED', APPROVAL_REQUIRED: 'APPROVAL_REQUIRED', SUCCESS: 'SUCCESS', FAILED: 'FAILED', CANCELLED: 'CANCELLED' };
  const STEP = { PENDING: 'PENDING', ACTIVE: 'ACTIVE', SUCCESS: 'SUCCESS', FAILED: 'FAILED', BLOCKED: 'BLOCKED', APPROVAL_REQUIRED: 'APPROVAL_REQUIRED', SKIPPED: 'SKIPPED_WITH_REASON', CANCELLED: 'CANCELLED' };

  // Allowed step transitions (further guarded below). Notably absent:
  // PENDING→SUCCESS (must execute) and APPROVAL_REQUIRED→SUCCESS (must be
  // approved → ACTIVE → SUCCESS).
  const STEP_EDGES = {
    PENDING: ['ACTIVE', 'SKIPPED_WITH_REASON', 'CANCELLED'],
    ACTIVE: ['SUCCESS', 'FAILED', 'BLOCKED', 'APPROVAL_REQUIRED', 'SKIPPED_WITH_REASON', 'CANCELLED'],
    APPROVAL_REQUIRED: ['ACTIVE', 'FAILED', 'CANCELLED'],
    BLOCKED: ['ACTIVE', 'FAILED', 'CANCELLED'],
    FAILED: ['ACTIVE', 'CANCELLED'],
    SUCCESS: [], SKIPPED_WITH_REASON: [], CANCELLED: [],
  };

  function createProcedure(spec) {
    return {
      procedure_id: spec.procedure_id || 'P1', mission_id: spec.mission_id || null,
      name: spec.name || 'Procedure', version: spec.version || 1,
      status: PROC.PENDING, started_at: null, completed_at: null, current_step_id: null,
      steps: (spec.steps || []).map((s, i) => ({
        step_id: s.step_id || ('s' + (i + 1)), sequence: s.sequence != null ? s.sequence : i + 1,
        title: s.title || ('Step ' + (i + 1)), description: s.description || '',
        status: STEP.PENDING, required: s.required !== false, started_at: null, completed_at: null,
        actor: s.actor || 'system', source: s.source || 'procedure', evidence_refs: [],
        blocker: null, approval_id: s.approval_id || null, error: null, retryable: !!s.retryable,
      })),
      required_approvals: [], approvals: [], evidence: [], correlation_id: spec.correlation_id || null,
      _events: [],
    };
  }

  const _emit = (p, topic, payload) => p._events.push({ topic, payload, seq: p._events.length });
  const _step = (p, id) => { const s = p.steps.find(x => x.step_id === id); if (!s) throw new Error('unknown step ' + id); return s; };
  const _can = (from, to) => (STEP_EDGES[from] || []).includes(to);

  function _recompute(p) {
    const st = p.steps;
    if (st.some(s => s.status === STEP.APPROVAL_REQUIRED)) p.status = PROC.APPROVAL_REQUIRED;
    else if (st.some(s => s.status === STEP.BLOCKED)) p.status = PROC.BLOCKED;
    else if (st.some(s => s.status === STEP.FAILED && !s.retryable)) p.status = PROC.FAILED;
    else if (st.every(s => s.status === STEP.SUCCESS || s.status === STEP.SKIPPED)) { p.status = PROC.SUCCESS; if (!p.completed_at) p.completed_at = p._now || 0; }
    else if (st.some(s => s.status === STEP.ACTIVE)) p.status = PROC.ACTIVE;
    else p.status = p.started_at ? PROC.WAITING : PROC.PENDING;
    const cur = st.slice().sort((a, b) => a.sequence - b.sequence)
      .find(s => s.status === STEP.ACTIVE || s.status === STEP.APPROVAL_REQUIRED || s.status === STEP.BLOCKED);
    p.current_step_id = cur ? cur.step_id : null;
    return p.status;
  }

  function _trans(p, id, to, opts) {
    opts = opts || {}; p._now = opts.now || 0;
    const s = _step(p, id);
    if (!_can(s.status, to)) throw new Error('illegal step transition ' + s.status + '->' + to + ' (' + id + ')');
    if (s.status === STEP.APPROVAL_REQUIRED && to === STEP.ACTIVE) {
      const ok = p.approvals.some(a => a.step_id === id && a.status === 'APPROVED');
      if (!ok) throw new Error('cannot resume approval step without an APPROVED record');
    }
    if (s.status === STEP.BLOCKED && to === STEP.ACTIVE && !opts.blockerResolved) throw new Error('cannot resume blocked step until blocker resolved');
    if (s.status === STEP.FAILED && to === STEP.ACTIVE && !s.retryable) throw new Error('cannot retry a non-retryable failed step');
    const from = s.status; s.status = to;
    if (to === STEP.ACTIVE && !s.started_at) s.started_at = opts.now || 0;
    if ([STEP.SUCCESS, STEP.FAILED, STEP.SKIPPED, STEP.CANCELLED].includes(to)) s.completed_at = opts.now || 0;
    const topic = { ACTIVE: 'started', SUCCESS: 'completed', FAILED: 'failed', BLOCKED: 'blocked', APPROVAL_REQUIRED: 'approval', SKIPPED_WITH_REASON: 'skipped', CANCELLED: 'cancelled' }[to];
    _emit(p, 'procedure.step.' + topic, { step_id: id, from, to });
    _recompute(p);
    return s;
  }

  function start(p, now) { if (p.status !== PROC.PENDING) throw new Error('procedure already started'); p.started_at = now || 0; _emit(p, 'procedure.started', {}); return startNext(p, now); }
  function startNext(p, now) {
    const next = p.steps.slice().sort((a, b) => a.sequence - b.sequence).find(s => s.status === STEP.PENDING);
    if (next) _trans(p, next.step_id, STEP.ACTIVE, { now });
    else { _recompute(p); if (p.status === PROC.SUCCESS) _emit(p, 'procedure.completed', {}); }
    return p;
  }

  function completeStep(p, id, opts) { opts = opts || {}; const s = _trans(p, id, STEP.SUCCESS, opts); startNext(p, opts.now); return s; }
  function failStep(p, id, opts) { opts = opts || {}; const s = _step(p, id); s.error = opts.error || 'error'; s.retryable = !!opts.retryable; const r = _trans(p, id, STEP.FAILED, opts); if (p.status === PROC.FAILED) _emit(p, 'procedure.failed', {}); return r; }
  function blockStep(p, id, opts) { opts = opts || {}; const s = _step(p, id); s.blocker = opts.blocker || 'blocked'; return _trans(p, id, STEP.BLOCKED, opts); }
  function resolveBlock(p, id, opts) { opts = opts || {}; return _trans(p, id, STEP.ACTIVE, Object.assign({}, opts, { blockerResolved: true })); }
  function retry(p, id, opts) { opts = opts || {}; const s = _step(p, id); if (!s.retryable) throw new Error('step is not retryable'); s.error = null; return _trans(p, id, STEP.ACTIVE, opts); }

  function skipStep(p, id, reason, opts) {
    opts = opts || {}; const s = _step(p, id);
    if (s.required) throw new Error('cannot skip required step ' + id);
    if (!reason) throw new Error('skip requires a reason (no silent skip)');
    s.blocker = 'SKIPPED: ' + reason; const r = _trans(p, id, STEP.SKIPPED, opts); startNext(p, opts.now); return r;
  }

  function requireApproval(p, id, opts) {
    opts = opts || {}; const s = _trans(p, id, STEP.APPROVAL_REQUIRED, opts);
    const ap = {
      approval_id: opts.approval_id || ('A' + (p.approvals.length + 1)), mission_id: p.mission_id,
      procedure_id: p.procedure_id, step_id: id, action: opts.action || s.title, requested_by: 'KAI',
      requested_at: opts.now || 0, required_role: opts.required_role || 'owner', required_scope: opts.required_scope || 'kai.ultra',
      risk: opts.risk || 'MEDIUM', summary: opts.summary || '', evidence: opts.evidence || [],
      status: 'PENDING', resolved_by: null, resolved_at: null, decision_reason: null, correlation_id: p.correlation_id,
    };
    s.approval_id = ap.approval_id; p.approvals.push(ap); p.required_approvals.push(ap.approval_id);
    _emit(p, 'approval.required', { approval_id: ap.approval_id, step_id: id });
    return ap;
  }
  function _findApproval(p, id) { const a = p.approvals.find(x => x.approval_id === id); if (!a) throw new Error('unknown approval ' + id); return a; }
  function approve(p, approvalId, opts) {
    opts = opts || {}; const ap = _findApproval(p, approvalId);
    if (ap.status !== 'PENDING') throw new Error('approval is ' + ap.status + ', not PENDING');
    ap.status = 'APPROVED'; ap.resolved_by = opts.by || 'operator'; ap.resolved_at = opts.now || 0; ap.decision_reason = opts.reason || null;
    _emit(p, 'approval.approved', { approval_id: approvalId, step_id: ap.step_id });
    _trans(p, ap.step_id, STEP.ACTIVE, { now: opts.now });   // unlock: APPROVAL_REQUIRED → ACTIVE
    return ap;
  }
  function deny(p, approvalId, opts) {
    opts = opts || {}; const ap = _findApproval(p, approvalId);
    if (ap.status !== 'PENDING') throw new Error('approval is ' + ap.status + ', not PENDING');
    ap.status = 'DENIED'; ap.resolved_by = opts.by || 'operator'; ap.resolved_at = opts.now || 0; ap.decision_reason = opts.reason || null;
    _emit(p, 'approval.denied', { approval_id: approvalId, step_id: ap.step_id });
    const s = _step(p, ap.step_id); s.error = 'approval denied'; _trans(p, ap.step_id, STEP.FAILED, { now: opts.now });
    if (p.status === PROC.FAILED) _emit(p, 'procedure.failed', {});
    return ap;
  }
  function expireApproval(p, approvalId, opts) {
    opts = opts || {}; const ap = _findApproval(p, approvalId);
    if (ap.status !== 'PENDING') throw new Error('approval is ' + ap.status + ', not PENDING');
    ap.status = 'EXPIRED'; ap.resolved_at = opts.now || 0; return ap;
  }
  function pendingApprovals(p) { return p.approvals.filter(a => a.status === 'PENDING'); }

  function attachEvidence(p, stepId, ev) {
    const s = _step(p, stepId);
    const e = Object.assign({ provenance: 'DEMO', type: 'note', label: '' }, ev);
    s.evidence_refs.push(e); p.evidence.push(e); return e;
  }
  function drainEvents(p) { const e = p._events.slice(); p._events.length = 0; return e; }

  return { PROC, STEP, STEP_EDGES, createProcedure, start, startNext, completeStep, failStep, blockStep, resolveBlock, retry, skipStep, requireApproval, approve, deny, expireApproval, pendingApprovals, attachEvidence, drainEvents };
});
