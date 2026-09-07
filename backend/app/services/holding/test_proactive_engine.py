"""§11 ProactiveBriefingEngine guard. Run (from backend/):
    python3 -m app.services.holding.test_proactive_engine

Mirrors test_notification_policy.py: a flat ck() ledger + injectable sources. Proves the ONE proactive
engine maps the full §11 trigger taxonomy onto the 7 §31 reasons, routes EVERY emission through the single
NotificationPolicy (adds no new sender/detector/ranker), is silent on a routine/empty world, suppresses an
unchanged world, drops evidence-less signals (zero-fabrication), orders by the single §22 ranker, and that
run() is flag-gated (KAI_PROACTIVE_ENABLED).
"""
from app.services.holding import proactive_engine as pe
from app.services.holding.proactive_engine import (
    evaluate, run, TRIGGER_REASON, SECURITY_TRIGGER, REPEATED_FAILURE_TRIGGER, MATERIAL_CHANGE,
    CRITICAL_DEGRADE, DEADLINE, APPROVAL_NEEDED, HIGH_CONF_OPPORTUNITY, MISSION_COMPLETE,
    CUSTOMER_REVENUE_CHANGE, DASHBOARD_OPEN)
from app.services.holding.notification_policy import (
    NotificationPolicy, NotificationEvent, InMemoryNotificationStore, ALLOWED_REASONS,
    SECURITY_FINDING, REPEATED_FAILURE, CRITICAL_MATERIAL_CHANGE, REQUIRED_DECISION,
    HIGH_VALUE_OPPORTUNITY, MISSION_COMPLETION, SCHEDULED_EXECUTIVE_BRIEF)
from app.services.holding.priorities import rank_key

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def _p(sig, cat, sev, **kw):
    base = dict(root_signature=sig, category=cat, severity=sev, company=kw.get("company", "holding"),
                observed_facts=kw.get("facts", f"{cat} fact"), impact="i",
                confidence=kw.get("confidence", "HIGH"), owner_required=kw.get("owner", False))
    return base


# ── 1. the 10-trigger taxonomy maps onto exactly the 7 allowed §31 reasons ──────────────────────────────
ck("full §11 taxonomy has 10 triggers", len(TRIGGER_REASON) == 10)
ck("every trigger maps to one of the 7 allowed §31 reasons", set(TRIGGER_REASON.values()) <= ALLOWED_REASONS)
ck("all 7 §31 reasons are reachable from the taxonomy", set(TRIGGER_REASON.values()) == set(ALLOWED_REASONS))

# ── 2. each real source becomes the right trigger → reason, routed through the policy (pure preview) ─────
problems = [
    _p("security:authz:sol.transfer", "SECURITY", "CRITICAL", company="sol", owner=True),
    _p("failing_suite:x", "MISSION_FAILURE", "HIGH", company="kai"),
    _p("deploy_drift:PRODUCTION_BEHIND", "DEPLOYMENT_DRIFT", "HIGH", owner=True),
    _p("priority:live health probe", "HEALTH", "CRITICAL", company="kai"),
    _p("stale_plan:reg:sol.risks", "STALE_PLAN", "MEDIUM", company="sol", owner=True),
    _p("reg:x.confidence", "VERIFICATION", "MEDIUM", company="x"),          # routine → silent
    _p("doc:README", "DOCUMENTATION", "LOW", company="kai", confidence="LOW"),  # routine → silent
]
opps = [
    {"signature": "opp:goal:1:customers", "title": "Close customers gap", "company": "sol",
     "expected_benefit": "40→100", "confidence": "HIGH", "owner_impact": False},
    {"signature": "opp:goal:2:x", "title": "med opp", "company": "kai", "confidence": "MEDIUM"},  # not HIGH → silent
]
prev = evaluate(problems=problems, opportunities=opps)
trigs = {r["trigger"] for r in prev["would_notify"]}
reasons = {r["reason"] for r in prev["would_notify"]}
ck("SECURITY problem → security_finding trigger → SECURITY_FINDING reason",
   SECURITY_TRIGGER in trigs and SECURITY_FINDING in reasons)
ck("MISSION_FAILURE → repeated_failure → REPEATED_FAILURE",
   REPEATED_FAILURE_TRIGGER in trigs and REPEATED_FAILURE in reasons)
ck("DEPLOYMENT_DRIFT/HEALTH(critical) → material/critical-degrade → CRITICAL_MATERIAL_CHANGE",
   (MATERIAL_CHANGE in trigs or CRITICAL_DEGRADE in trigs) and CRITICAL_MATERIAL_CHANGE in reasons)
ck("STALE_PLAN → deadline → REQUIRED_DECISION", DEADLINE in trigs and REQUIRED_DECISION in reasons)
ck("HIGH-confidence opportunity → high_confidence_opportunity → HIGH_VALUE_OPPORTUNITY",
   HIGH_CONF_OPPORTUNITY in trigs and HIGH_VALUE_OPPORTUNITY in reasons)

# ── 3. silent on routine: a MEDIUM verification / LOW doc / MEDIUM opportunity is NEVER a candidate ──────
ck("routine problems (MEDIUM verification, LOW doc) produce no candidate",
   not any("confidence" in str(r) and ("VERIFICATION" in str(r) or "doc:README" in str(r)) for r in prev["would_notify"]))
ck("a MEDIUM opportunity is not emitted (only HIGH-confidence fires §11)",
   not any(r["event"]["evidence_ref"] == "opp:goal:2:x" for r in prev["would_notify"]))

# ── 4. empty world → 0 candidates (no fabrication) ──────────────────────────────────────────────────────
ck("empty world → 0 candidates", evaluate(problems=[], opportunities=[])["candidates"] == 0)

# ── 5. every emission carries a real evidence_ref (citation), routed through the ONE policy ──────────────
ck("every would-notify event cites real evidence_ref", all(r["event"]["evidence_ref"] for r in prev["would_notify"]))

# ── 6. ordered by the single §22 ranker (no local severity map) ─────────────────────────────────────────
order = [rank_key({"severity": r["event"]["severity"]}) for r in prev["would_notify"]]
ck("candidates ordered by the single §22 rank_key", order == sorted(order))

# ── 7. unchanged world suppressed: replay with the policy state carrying the same content hashes ─────────
state = {}
for r in prev["would_notify"]:
    e = r["event"]
    ne = NotificationEvent(**{k: e[k] for k in ("category", "title", "summary", "severity", "company",
                             "mission", "evidence_ref", "owner_action_required", "confidence", "dedupe_key")})
    state[ne.key()] = {"sent_at": "2000-01-01T00:00:00+00:00", "hash": ne.content_hash()}
replay = evaluate(problems=problems, opportunities=opps, state=state)
ck("unchanged world re-emits nothing (all suppressed as 'unchanged')",
   replay["would_notify"] == [] and all(r["reason"] == "unchanged" for r in replay["suppressed"]))

# ── 8. injected mission-complete / revenue-change fire; an evidence-less injected signal is dropped ──────
inj = evaluate(problems=[], opportunities=[],
               mission_events=[{"mission": "m1", "title": "mission done", "confidence": "HIGH"},
                               {"title": "no-ref"}],                      # no id/mission → dropped
               revenue_changes=[{"id": "rev:sol:2026-09", "title": "MRR change", "confidence": "HIGH"}])
inj_reasons = {r["reason"] for r in inj["would_notify"]}
ck("injected mission-complete + revenue-change fire MISSION_COMPLETION + CRITICAL_MATERIAL_CHANGE",
   MISSION_COMPLETION in inj_reasons and CRITICAL_MATERIAL_CHANGE in inj_reasons)
ck("evidence-less injected signal dropped (zero-fabrication)", inj["candidates"] == 2)

# ── 9. run() funnels through the ONE policy and RECORDS dedup (2nd identical pass emits nothing) ─────────
store = InMemoryNotificationStore()
sent = []
pol = NotificationPolicy(store=store, now_fn=lambda: "2026-09-03T12:00:00+00:00",
                         deliver_fn=lambda t: (sent.append(t) or {"delivered": True}))
# run() is flag-gated; call the funnel logic directly with an injected policy + injected sources so the test
# is deterministic regardless of the (default-OFF) flag — this exercises the same policy.notify funnel.
first = [pol.notify(c.event) for c in pe._build_candidates(
    problems=problems, opportunities=opps, mission_events=[], revenue_changes=[], arrival=None)]
emitted1 = [r for r in first if r.get("notified")]
ck("run funnel: first pass emits the notify-worthy candidates via the ONE sender", len(emitted1) == len(sent) >= 4)
second = [pol.notify(c.event) for c in pe._build_candidates(
    problems=problems, opportunities=opps, mission_events=[], revenue_changes=[], arrival=None)]
ck("run funnel: identical second pass emits nothing (dedup recorded in the ONE store)",
   not any(r.get("notified") for r in second))

# ── 10. run() honors the flag (default OFF → does not run) ──────────────────────────────────────────────
r = run(problems=problems, opportunities=opps)   # KAI_PROACTIVE_ENABLED default False
ck("run() is flag-gated by KAI_PROACTIVE_ENABLED (default OFF → no-op)",
   r.get("ran") is False and "KAI_PROACTIVE_ENABLED" in r.get("reason", ""))

n = len(res); ok = sum(res)
print(f"\nPROACTIVE ENGINE TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
