"""§11 ProactiveBriefingEngine — the ONE proactive engine.

CONSOLIDATION, not a new detector/ranker/queue/sender. It READS the already-certified streams and
routes EVERY emission through the ONE §31 NotificationPolicy:
  • §18 holding_problems.detect_problems()      → security / repeated-failure / material-change / decision triggers
  • §20 opportunity_engine.detect_opportunities → high-confidence-opportunity trigger
  • injected mission/revenue/arrival signals    → mission-complete / customer-revenue / dashboard-open triggers
It orders candidates with the SINGLE §22 ranker (priorities.rank_key) and adds NO parallel sender: the
policy (notification_policy.notify) is the one funnel that dedups + delegates delivery to delivery.send_alert
(opt-in, default OFF — unchanged). No second store, no per-feature sender.

The full §11 trigger taxonomy (10 triggers) maps onto the 7 (and only 7) §31 reasons via TRIGGER_REASON.
A candidate that is not notify-worthy (routine health, a MEDIUM verification, a MEDIUM/LOW opportunity)
is simply NOT built — so a routine world emits nothing. The policy additionally suppresses
duplicate/unchanged/low-confidence/no-evidence, so an unchanged world re-emits nothing.

Zero-fabrication (§0 #16-19): every event's evidence_ref is a REAL citation (a problem root_signature /
opportunity signature / injected event id). mission_events and revenue_changes have NO fabricating default
source (missions are §27/Phase 4; revenue is operator-provisioned) — they default to [] and emit only what
a real caller injects. Bounded/no-LLM-loop (§79): evaluate() is pure over injected state; run() is a single
bounded pass — no daemon, no loop, no LLM.

  evaluate()  pure preview  — decisions only, state injected, NEVER delivers, NEVER writes.
  run()       stateful funnel — flag-gated (KAI_PROACTIVE_ENABLED); records dedup + delegates delivery.

Pure/injectable so the whole thing is a plain python3 self-test (mirrors holding_problems.demo /
opportunity_engine.demo). Run: python3 -m app.services.holding.test_proactive_engine
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.holding.notification_policy import (
    NotificationEvent, NotificationPolicy, InMemoryNotificationStore,
    CRITICAL_MATERIAL_CHANGE, HIGH_VALUE_OPPORTUNITY, REQUIRED_DECISION, MISSION_COMPLETION,
    REPEATED_FAILURE, SECURITY_FINDING, SCHEDULED_EXECUTIVE_BRIEF)
from app.services.holding.priorities import rank_key   # §22: the ONE ranker (no local severity map)

# ── §11 trigger taxonomy (10 triggers) → the 7 §31 reasons (the ONLY reasons an owner may be alerted) ──
DASHBOARD_OPEN            = "dashboard_open"
MATERIAL_CHANGE          = "material_change"
CRITICAL_DEGRADE         = "critical_degrade"
CUSTOMER_REVENUE_CHANGE  = "customer_revenue_change"
MISSION_COMPLETE         = "mission_complete"
APPROVAL_NEEDED          = "approval_needed"
REPEATED_FAILURE_TRIGGER = "repeated_failure"
SECURITY_TRIGGER         = "security_finding"
DEADLINE                 = "deadline"
HIGH_CONF_OPPORTUNITY    = "high_confidence_opportunity"

TRIGGER_REASON = {
    DASHBOARD_OPEN:           SCHEDULED_EXECUTIVE_BRIEF,
    MATERIAL_CHANGE:          CRITICAL_MATERIAL_CHANGE,
    CRITICAL_DEGRADE:         CRITICAL_MATERIAL_CHANGE,
    CUSTOMER_REVENUE_CHANGE:  CRITICAL_MATERIAL_CHANGE,
    MISSION_COMPLETE:         MISSION_COMPLETION,
    APPROVAL_NEEDED:          REQUIRED_DECISION,
    REPEATED_FAILURE_TRIGGER: REPEATED_FAILURE,
    SECURITY_TRIGGER:         SECURITY_FINDING,
    DEADLINE:                 REQUIRED_DECISION,
    HIGH_CONF_OPPORTUNITY:    HIGH_VALUE_OPPORTUNITY,
}

# problem category → the §11 trigger a HIGH/CRITICAL instance fires. A category absent here (or below
# severity) is routine → no event built → silent (the empty/routine-world property).
_DEGRADE_CATEGORIES = {"HEALTH", "INCIDENT", "MONITORING", "DEPLOYMENT_DRIFT"}
_NOTIFY_SEVERITY = {"CRITICAL", "HIGH"}


def _get(o, key, default=""):
    v = o.get(key) if isinstance(o, dict) else getattr(o, key, default)
    return v if v is not None else default


@dataclass
class Emission:
    """One proactive candidate: the §11 trigger it came from + the NotificationEvent it produced."""
    trigger: str
    event: NotificationEvent

    def as_dict(self) -> dict:
        return {"trigger": self.trigger, "event": self.event.as_dict()}


def _classify_problem(p) -> str | None:
    """Which §11 trigger (if any) a HoldingProblem fires. None → routine (no event, silent)."""
    cat = _get(p, "category")
    sev = _get(p, "severity", "MEDIUM") or "MEDIUM"
    owner = bool(_get(p, "owner_required", False))
    if cat == "SECURITY":
        return SECURITY_TRIGGER
    if cat == "MISSION_FAILURE":
        return REPEATED_FAILURE_TRIGGER
    if cat == "STALE_PLAN":
        return DEADLINE
    if cat in _DEGRADE_CATEGORIES and sev in _NOTIFY_SEVERITY:
        return CRITICAL_DEGRADE if cat != "DEPLOYMENT_DRIFT" else MATERIAL_CHANGE
    if owner and sev in _NOTIFY_SEVERITY:
        return APPROVAL_NEEDED               # an owner-gated HIGH/CRITICAL problem is a required decision
    return None                              # routine → silent


def _event_from_problem(p) -> Emission | None:
    trig = _classify_problem(p)
    if trig is None:
        return None
    sig = _get(p, "root_signature") or _get(p, "problem_id")
    if not sig:
        return None                          # no stable citation → cannot dedup/cite → drop (zero-fabrication)
    ev = NotificationEvent(
        category=TRIGGER_REASON[trig],
        title=_get(p, "observed_facts")[:120] or _get(p, "category"),
        summary=_get(p, "impact"),
        severity=_get(p, "severity", "MEDIUM") or "MEDIUM",
        company=_get(p, "company", "holding") or "holding",
        evidence_ref=sig,                    # REAL citation (the problem's deterministic root signature)
        owner_action_required=bool(_get(p, "owner_required", False)),
        confidence=_get(p, "confidence", "MEDIUM") or "MEDIUM",
        dedupe_key=sig)                      # stable per root → cooldown/unchanged handled by the policy
    return Emission(trig, ev)


def _event_from_opportunity(o) -> Emission | None:
    # §11 fires ONLY on a HIGH-confidence opportunity (more conservative than the policy's 0.5 floor).
    if str(_get(o, "confidence", "MEDIUM")).upper() != "HIGH":
        return None
    sig = _get(o, "signature")
    if not sig:
        return None
    ev = NotificationEvent(
        category=HIGH_VALUE_OPPORTUNITY,
        title=_get(o, "title"),
        summary=_get(o, "expected_benefit") or _get(o, "why_now"),
        severity="INFO",
        company=_get(o, "company", "holding") or "holding",
        evidence_ref=sig,
        owner_action_required=bool(_get(o, "owner_impact", False)),
        confidence="HIGH",
        dedupe_key=sig)
    return Emission(HIGH_CONF_OPPORTUNITY, ev)


def _event_from_injected(item, trigger: str, *, default_severity="HIGH") -> Emission | None:
    """A caller-injected mission-complete / revenue-change / dashboard-open signal. Requires a real
    evidence_ref (id/citation) — NEVER fabricated. Missing evidence → dropped."""
    ref = _get(item, "evidence_ref") or _get(item, "id") or _get(item, "mission") or _get(item, "signature")
    if not ref:
        return None
    ev = NotificationEvent(
        category=TRIGGER_REASON[trigger],
        title=_get(item, "title") or trigger,
        summary=_get(item, "summary"),
        severity=_get(item, "severity", default_severity) or default_severity,
        company=_get(item, "company", "holding") or "holding",
        mission=_get(item, "mission"),
        evidence_ref=str(ref),
        owner_action_required=bool(_get(item, "owner_action_required", False)),
        confidence=_get(item, "confidence", "HIGH") or "HIGH",
        dedupe_key=_get(item, "dedupe_key") or str(ref))
    return Emission(trigger, ev)


def _build_candidates(*, problems, opportunities, mission_events, revenue_changes, arrival) -> list:
    """Build the notify-worthy candidate Emissions from all sources, ordered by the SINGLE §22 ranker
    (rank_key on severity). Pure — no state, no I/O."""
    cands: list = []
    for p in problems or []:
        e = _event_from_problem(p)
        if e:
            cands.append(e)
    for o in opportunities or []:
        e = _event_from_opportunity(o)
        if e:
            cands.append(e)
    for m in mission_events or []:
        e = _event_from_injected(m, MISSION_COMPLETE)
        if e:
            cands.append(e)
    for r in revenue_changes or []:
        e = _event_from_injected(r, CUSTOMER_REVENUE_CHANGE)
        if e:
            cands.append(e)
    if arrival:
        e = _event_from_injected(arrival, DASHBOARD_OPEN, default_severity="INFO")
        if e:
            cands.append(e)
    # order by THE §22 ladder (rank_key derives the rung from severity); stable within a rung.
    cands.sort(key=lambda c: rank_key({"severity": c.event.severity}))
    return cands


def evaluate(*, problems=None, opportunities=None, mission_events=None, revenue_changes=None,
             arrival=None, state: dict | None = None, now: str | None = None,
             policy: NotificationPolicy | None = None) -> dict:
    """PURE preview (§79): build candidates from injected state and ask the ONE §31 policy whether each
    WOULD notify — records nothing, delivers nothing, writes nothing. ``state`` is the policy's notified-key
    map (inject a prior state to preview dedup/cooldown). Returns:
        {candidates: N, would_notify: [{trigger, reason, event}...], suppressed: [{trigger, reason, event}...]}
    An empty/routine world → 0 candidates. An unchanged world (state carries the same keys) → all suppressed."""
    pol = policy or NotificationPolicy(store=InMemoryNotificationStore())
    cands = _build_candidates(problems=problems, opportunities=opportunities,
                              mission_events=mission_events, revenue_changes=revenue_changes, arrival=arrival)
    would, supp = [], []
    st = dict(state or {})
    for c in cands:
        ok, reason = pol.should_notify(c.event, state=st, now=now)
        row = {"trigger": c.trigger, "reason": reason, "event": c.event.as_dict()}
        (would if ok else supp).append(row)
    return {"candidates": len(cands), "would_notify": would, "suppressed": supp}


# ── fail-open default sources (each only runs when its arg is None) ─────────────────────────────────
def _default_problems() -> list:
    try:
        from app.services.holding.holding_problems import detect_problems
        return detect_problems()
    except Exception:
        return []


def _default_opportunities() -> list:
    try:
        from app.services.holding.opportunity_engine import detect_opportunities
        return detect_opportunities()
    except Exception:
        return []


def run(*, problems=None, opportunities=None, mission_events=None, revenue_changes=None, arrival=None,
        policy: NotificationPolicy | None = None, now: str | None = None) -> dict:
    """Stateful funnel — flag-gated by KAI_PROACTIVE_ENABLED. Loads the real sources (fail-open), builds
    candidates ordered by the §22 ranker, and funnels EACH through the ONE §31 policy.notify (which records
    dedup/cooldown and delegates delivery to delivery.send_alert — opt-in, default OFF; NOT bypassed here).
    Adds no new sender/store. mission_events/revenue_changes have no fabricating default (missions=§27/Phase 4,
    revenue=operator-provisioned) → [] unless injected. Never raises fatally."""
    try:
        from app.config import settings
        if not getattr(settings, "KAI_PROACTIVE_ENABLED", False):
            return {"ran": False, "reason": "KAI_PROACTIVE_ENABLED off"}
        probs = problems if problems is not None else _default_problems()
        opps = opportunities if opportunities is not None else _default_opportunities()
        cands = _build_candidates(problems=probs, opportunities=opps,
                                  mission_events=mission_events or [], revenue_changes=revenue_changes or [],
                                  arrival=arrival)
        pol = policy or NotificationPolicy()   # real store + real (opt-in default OFF) delivery
        emitted, suppressed = [], []
        for c in cands:
            res = pol.notify(c.event)          # the ONE funnel: dedup recorded on decision + delegated send
            row = {"trigger": c.trigger, "reason": res.get("reason"), "event": res.get("event")}
            (emitted if res.get("notified") else suppressed).append(row)
        return {"ran": True, "candidates": len(cands), "emitted": emitted, "suppressed": suppressed}
    except Exception as e:
        return {"ran": False, "reason": f"proactive error: {str(e)[:120]}"}


def demo() -> None:
    """Pure self-check (no DB/network). Proves: each source becomes the right §11 trigger → §31 reason;
    routine world → 0 candidates; an unchanged state suppresses re-emission; every event cites evidence;
    ordered by the single §22 ranker."""
    problems = [
        {"root_signature": "security:authz_denial:sol.transfer", "category": "SECURITY", "severity": "CRITICAL",
         "company": "sol", "observed_facts": "1 authz_denial on sol.transfer", "impact": "sec", "confidence": "HIGH",
         "owner_required": True},
        {"root_signature": "failing_suite:x", "category": "MISSION_FAILURE", "severity": "HIGH", "company": "kai",
         "observed_facts": "3 repeated job failures", "impact": "mf", "confidence": "HIGH", "owner_required": False},
        {"root_signature": "deploy_drift:PRODUCTION_BEHIND", "category": "DEPLOYMENT_DRIFT", "severity": "HIGH",
         "company": "holding", "observed_facts": "prod behind head", "impact": "drift", "confidence": "HIGH",
         "owner_required": True},
        {"root_signature": "stale_plan:reg:sol.risks", "category": "STALE_PLAN", "severity": "MEDIUM",
         "company": "sol", "observed_facts": "plan open 30d", "impact": "stale", "confidence": "HIGH",
         "owner_required": True},
        # routine: a MEDIUM verification problem → NO event (silent)
        {"root_signature": "priority:registry:x.confidence", "category": "VERIFICATION", "severity": "MEDIUM",
         "company": "x", "observed_facts": "re-verify", "impact": "v", "confidence": "MEDIUM", "owner_required": False},
    ]
    opps = [
        {"signature": "opp:goal:1:customers", "title": "Close customers gap", "expected_benefit": "40→100",
         "company": "sol", "confidence": "HIGH", "owner_impact": False},
        {"signature": "opp:goal:2:x", "title": "medium opp", "confidence": "MEDIUM", "company": "kai"},  # not HIGH → silent
    ]

    prev = evaluate(problems=problems, opportunities=opps)
    triggers = {r["trigger"] for r in prev["would_notify"]}
    reasons = {r["reason"] for r in prev["would_notify"]}
    assert {SECURITY_TRIGGER, REPEATED_FAILURE_TRIGGER, MATERIAL_CHANGE, DEADLINE,
            HIGH_CONF_OPPORTUNITY} <= triggers, triggers
    assert SECURITY_FINDING in reasons and HIGH_VALUE_OPPORTUNITY in reasons, reasons
    # routine (VERIFICATION MEDIUM) + MEDIUM opportunity → never candidates (silent)
    assert not any("VERIFICATION" in str(r) or "opp:goal:2" in str(r) for r in prev["would_notify"]), prev
    # every emitted event cites real evidence
    assert all(r["event"]["evidence_ref"] for r in prev["would_notify"]), prev
    # ordered by the §22 ranker (CRITICAL before HIGH before INFO)
    from app.services.holding.priorities import rank_key as rk
    order = [rk({"severity": r["event"]["severity"]}) for r in prev["would_notify"]]
    assert order == sorted(order), order

    # empty world → 0 candidates
    assert evaluate(problems=[], opportunities=[])["candidates"] == 0

    # unchanged world: replay with the state carrying the same keys (same content_hash) → all suppressed
    from app.services.holding.notification_policy import NotificationEvent as NE
    state = {}
    for r in prev["would_notify"]:
        e = r["event"]
        ne = NE(**{k: e[k] for k in ("category", "title", "summary", "severity", "company", "mission",
                                     "evidence_ref", "owner_action_required", "confidence", "dedupe_key")})
        state[ne.key()] = {"sent_at": "2000-01-01T00:00:00+00:00", "hash": ne.content_hash()}
    replay = evaluate(problems=problems, opportunities=opps, state=state)
    assert replay["would_notify"] == [] and all(r["reason"] == "unchanged" for r in replay["suppressed"]), replay

    # injected mission-complete + revenue-change fire their reasons; a signal with NO evidence_ref is dropped
    inj = evaluate(problems=[], opportunities=[],
                   mission_events=[{"mission": "m1", "title": "mission done", "confidence": "HIGH"},
                                   {"title": "no-ref mission"}],   # no id/mission ref → dropped
                   revenue_changes=[{"id": "rev:sol:2026-09", "title": "MRR change", "confidence": "HIGH"}])
    inj_reasons = {r["reason"] for r in inj["would_notify"]}
    assert MISSION_COMPLETION in inj_reasons and CRITICAL_MATERIAL_CHANGE in inj_reasons, inj
    assert inj["candidates"] == 2, "the evidence-less mission signal must be dropped (zero-fabrication)"

    print(f"proactive_engine.demo OK — {prev['candidates']} candidates across "
          f"{len(triggers)} triggers → §31 reasons; routine/MEDIUM-opp silent; unchanged suppressed; "
          f"evidence-less injected signal dropped; ordered by the single ranker")


if __name__ == "__main__":
    demo()
