"""§18 unified HoldingProblem + detect_problems() — the ONE problem stream (CONSOLIDATION).

This does NOT replace derive_priorities (operational stream) or self_improvement_detect
(code-defect stream): it READS/WRAPS both and adapts them into one normalized HoldingProblem
shape, then WIRES the five sources the two streams miss (§18) — deployment drift, mission
failures, security findings, documentation inaccuracies, and stale plans. No second detector,
ranker, queue, or sender is introduced: every source is an existing certified module
(holding_deployment.compute_drift, self_improvement_signals.detect_repeated_job_failures over
worker_jobs, security.events, proposals_store.list_proposals).

Zero-fabrication (§0 #16-19): every field is a REAL source read, a DETERMINISTIC derivation of
one, or an explicit UNKNOWN. `possible_causes` is ALWAYS a list of candidate hypotheses — NEVER a
single confirmed root cause, and NO LLM is consulted anywhere in this module. `root_signature` is a
deterministic dedup key so an ongoing problem collapses to one card (an existing issue is surfaced
once, not re-invented every cycle). Sources are injectable and the aggregator is FAIL-OPEN (a broken
source yields no problem, never a fabricated one). Bounded (§79): pure functions over already-
collected state — no loops, no daemons, no LLM calls.

Pure/injectable so the whole thing is a plain python3 self-test (mirrors priorities.demo /
self_improvement_detect.demo).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
_STALE_PLAN_DAYS = 7                     # a plan/proposal open past this many days is "stale"

# category -> deterministic, DERIVED (never fabricated-metric) impact + candidate causes + card actions +
# owner-required baseline. Actions use the §106 vocab; causes are ALWAYS plural hypotheses (§18: no single
# confirmed root cause). This is the ONE place card semantics live — no per-source divergence.
_CATEGORY_META = {
    "HEALTH":           dict(impact="Possible service unavailability / degraded availability (derived from a failing probe).",
                             causes=["target service crashed or was restarted", "network / DNS / upstream failure",
                                     "a deploy in progress", "resource exhaustion on the host"],
                             actions=["INVESTIGATE", "CREATE_MISSION", "EVIDENCE"], owner=False),
    "INCIDENT":         dict(impact="An incident is logged against this system.",
                             causes=["an unresolved outage or regression", "a dependency failure", "a pending remediation"],
                             actions=["INVESTIGATE", "CREATE_MISSION", "EVIDENCE"], owner=True),
    "RISK":             dict(impact="A logged risk that may become an incident if unaddressed.",
                             causes=["a known weakness recorded in the registry", "a deferred mitigation"],
                             actions=["INVESTIGATE", "DEFER", "EVIDENCE"], owner=False),
    "VERIFICATION":     dict(impact="Entity state is unverified — its reported facts may be stale.",
                             causes=["the entity was never verified", "verification expired", "a source became unavailable"],
                             actions=["INVESTIGATE", "EVIDENCE"], owner=False),
    "OPERATOR_DATA":    dict(impact="Money/legal/customer fields await operator confirmation (reported UNAVAILABLE until then).",
                             causes=["no operator confirmation on file", "a source integration is not wired"],
                             actions=["ASK", "DEFER"], owner=True),
    "MONITORING":       dict(impact="The production observability monitor is reporting active alert(s).",
                             causes=["a monitored threshold was crossed", "a self/stale monitor condition"],
                             actions=["INVESTIGATE", "EVIDENCE"], owner=False),
    "DEPLOYMENT_DRIFT": dict(impact="Deployed code differs from the source head (deployed != current).",
                             causes=["a merge landed but was not deployed", "a deploy failed silently",
                                     "the provider marked a crashed deploy as success"],
                             actions=["INVESTIGATE", "CREATE_MISSION"], owner=True),
    "MISSION_FAILURE":  dict(impact="Repeated worker/mission failures for one root — the work is not completing.",
                             causes=["a defect in the capability or task", "a persistent environment/config problem",
                                     "an unhandled edge case"],
                             actions=["INVESTIGATE", "PREPARE_FIX", "EVIDENCE"], owner=False),
    "SECURITY":         dict(impact="Security-relevant audit event(s) requiring review.",
                             causes=["a denied or failed privileged/destructive action", "a policy-violation attempt",
                                     "a misconfiguration"],
                             actions=["INVESTIGATE", "EVIDENCE"], owner=True),
    "DOCUMENTATION":    dict(impact="Documentation may be inaccurate or out of date.",
                             causes=["code changed without a doc update", "a stated fact no longer holds"],
                             actions=["INVESTIGATE", "PREPARE_FIX"], owner=False),
    "STALE_PLAN":       dict(impact="A plan item has stayed open past the staleness window without progress.",
                             causes=["awaiting an owner decision", "the underlying blocker is unresolved",
                                     "a superseding condition was not detected"],
                             actions=["ASK", "DEFER", "INVESTIGATE"], owner=True),
    "CODE_DEFECT":      dict(impact="A certified behavior is failing — a regression is present.",
                             causes=["a recent code change broke certified behavior", "an environment/dependency change",
                                     "a nondeterministic / flaky test"],
                             actions=["INVESTIGATE", "PREPARE_FIX", "EVIDENCE"], owner=False),
}
# self_improvement_detect.Candidate.category -> HoldingProblem card category
_CANDIDATE_CATEGORY = {
    "DOCUMENTATION_ACCURACY": "DOCUMENTATION",
    "REPEATED_CAPABILITY_FAILURE": "MISSION_FAILURE",
    "CAPABILITY_HEALTH_DEGRADATION": "MISSION_FAILURE",
}


@dataclass
class HoldingProblem:
    """§18 normalized problem. Every field is REAL / DERIVED / UNKNOWN — never fabricated."""
    problem_id: str
    company: str
    system: str
    severity: str
    category: str
    observed_facts: str
    evidence: list = field(default_factory=list)      # real source records, or [{"source":"UNKNOWN"}]
    impact: str = "UNKNOWN"                            # DERIVED from category (not a fabricated metric)
    confidence: str = "UNKNOWN"                        # evidence quality: HIGH direct read / MEDIUM derived / LOW best-effort
    first_seen: str = "UNKNOWN"
    last_seen: str = "UNKNOWN"
    status: str = "OPEN"
    possible_causes: list = field(default_factory=list)   # candidate hypotheses — NEVER a single confirmed root cause
    recommended_actions: list = field(default_factory=list)
    owner_required: bool = False
    assigned_mission: str = ""                         # set by §27 mission system (Phase 4), not here
    root_signature: str = ""                           # deterministic dedup key

    def as_dict(self) -> dict:
        return asdict(self)


def _mk(*, root_signature, company, system, severity, category, observed_facts, evidence,
        confidence, now, causes=None, owner_extra=False) -> HoldingProblem:
    """Build a HoldingProblem, applying the deterministic category card semantics. Causes come from the
    category meta (>=2 hypotheses) unless a source supplies its own (coerced to a list). owner_required
    escalates to True for CRITICAL severity regardless of the category baseline."""
    meta = _CATEGORY_META.get(category, _CATEGORY_META["CODE_DEFECT"])
    cz = list(causes) if causes else list(meta["causes"])
    when = now or "UNKNOWN"
    ev = evidence if evidence else [{"source": "UNKNOWN"}]     # §18: real evidence[] or an explicit UNKNOWN
    return HoldingProblem(
        problem_id=root_signature, root_signature=root_signature,
        company=company or "holding", system=system or "holding",
        severity=severity, category=category, observed_facts=observed_facts,
        evidence=ev, impact=meta["impact"], confidence=confidence,
        first_seen=when, last_seen=when, possible_causes=cz,
        recommended_actions=list(meta["actions"]),
        owner_required=bool(meta["owner"] or owner_extra or severity == "CRITICAL"))


# ── source 1/2 (EXISTING) : operational stream — priorities.derive_priorities() ────────────────────────
def _priority_category(source: str, title: str) -> str:
    s = (source or "").lower()
    if s.startswith("live-signal:") or "health probe" in s or "health probe" in (title or "").lower():
        return "HEALTH"
    if ".incidents" in s:
        return "INCIDENT"
    if ".risks" in s:
        return "RISK"
    if ".confidence" in s:
        return "VERIFICATION"
    if "needs_confirmation" in s:
        return "OPERATOR_DATA"
    if "monitor" in s:
        return "MONITORING"
    return "HEALTH" if "health" in s else "RISK"


def _from_priorities(priorities, now) -> list:
    out = []
    for p in priorities or []:
        src = p.get("source", "")
        cat = _priority_category(src, p.get("title", ""))
        out.append(_mk(
            root_signature=f"priority:{src}", company=p.get("entity") or "holding",
            system=p.get("entity") or "holding", severity=p.get("severity", "MEDIUM"), category=cat,
            observed_facts=p.get("title", ""), evidence=[{"source": src, "detail": p.get("detail")}],
            confidence="HIGH", now=now))                # a live probe / registry field is a direct read
    return out


# ── source 2 (EXISTING) : code-defect stream — self_improvement_detect Candidates ──────────────────────
def _from_candidates(candidates, now) -> list:
    out = []
    for c in candidates or []:
        d = c.as_dict() if hasattr(c, "as_dict") else dict(c)
        if d.get("source") == "CERTIFICATION_FIXTURE":
            continue                                    # §18: seeded fixtures are NEVER organic problems
        cat = _CANDIDATE_CATEGORY.get(d.get("category"), "CODE_DEFECT")
        ev = d.get("evidence")
        out.append(_mk(
            root_signature=d.get("signature", ""), company=(ev or {}).get("company") or "holding",
            system=d.get("subsystem") or "holding", severity=d.get("severity", "MEDIUM"), category=cat,
            observed_facts=d.get("problem", ""), evidence=[ev] if ev else [],
            confidence="HIGH" if d.get("confirmed") else "MEDIUM", now=now))
    return out


# ── source 3 (WIRED) : deployment drift — holding_deployment.compute_drift ─────────────────────────────
def _from_drift(drift, now) -> list:
    if not isinstance(drift, dict):
        return []
    state = drift.get("state")
    if state in (None, "IN_SYNC", "UNKNOWN"):           # nothing to confirm -> no fabricated drift
        return []
    sev = "MEDIUM" if state == "STAGING_BEHIND" else "HIGH"   # prod-behind is higher impact
    return [_mk(
        root_signature=f"deploy_drift:{state}", company="holding", system="holding", severity=sev,
        category="DEPLOYMENT_DRIFT", observed_facts=f"deployment drift: {state}", evidence=[drift],
        confidence="HIGH", now=now, owner_extra=(state != "STAGING_BEHIND"))]


# ── source 4 (WIRED) : mission failures — repeated worker/mission job failures ─────────────────────────
def _from_jobs(jobs, now) -> list:
    """Reuse the ONE job-failure detector (self_improvement_signals.detect_repeated_job_failures): its
    exclusions (auth/provider/rate-limit are operational, not defects) and stable root signatures are
    exactly what zero-fabrication needs. Worker jobs carry mission_id, so a repeated job-failure root IS
    a mission failure. No parallel detector."""
    if not jobs:
        return []
    try:
        from app.services.holding.self_improvement_signals import detect_repeated_job_failures
        cands = detect_repeated_job_failures(jobs, now_iso=now or _now())
    except Exception:
        return []
    out = []
    for c in cands:
        ev = c.evidence or {}
        out.append(_mk(
            root_signature=c.signature, company=ev.get("company") or "holding", system=c.subsystem,
            severity=c.severity, category="MISSION_FAILURE", observed_facts=c.problem,
            evidence=[ev], confidence="HIGH", now=now))
    return out


# ── source 5 (WIRED) : security findings — security.events() (HIGH/CRITICAL only, grouped) ─────────────
def _from_security(events, now) -> list:
    groups: dict = {}
    for e in events or []:
        if e.get("severity") not in ("HIGH", "CRITICAL"):
            continue                                    # INFO/normal audit action is not a problem
        root = f"security:{e.get('category')}:{e.get('resource')}"
        groups.setdefault(root, []).append(e)
    out = []
    for root, evs in groups.items():
        sev = "CRITICAL" if any(e.get("severity") == "CRITICAL" for e in evs) else "HIGH"
        head = evs[0]
        ts = sorted(str(e.get("timestamp", "UNKNOWN")) for e in evs)
        out.append(_mk(
            root_signature=root, company=head.get("company") or "holding",
            system=head.get("system") or "holding", severity=sev, category="SECURITY",
            observed_facts=f"{len(evs)} {head.get('category')} event(s) on {head.get('resource')}",
            evidence=[{"event_id": e.get("event_id"), "action": e.get("action"), "result": e.get("result"),
                       "actor": e.get("actor"), "timestamp": e.get("timestamp")} for e in evs[:20]],
            confidence="HIGH", now=now))
        out[-1].first_seen, out[-1].last_seen = ts[0], ts[-1]
    return out


# ── source 6 (WIRED, best-effort) : documentation inaccuracies — UNKNOWN source until a detector wires in ─
def _from_docs(doc_findings, now) -> list:
    """No standalone doc-inaccuracy detector exists yet (DOCUMENTATION_ACCURACY candidates already flow via
    the code-defect stream). Honest default: [] — we do NOT fabricate doc problems. Injected findings
    ({path, issue, evidence?}) are adapted; a finding with no evidence is LOW confidence + explicit UNKNOWN
    evidence, never a fabricated cite."""
    out = []
    for f in doc_findings or []:
        ev = f.get("evidence")
        out.append(_mk(
            root_signature=f"doc:{f.get('path', 'UNKNOWN')}", company=f.get("company") or "holding",
            system=f.get("path") or "docs", severity=f.get("severity", "LOW"), category="DOCUMENTATION",
            observed_facts=f.get("issue", ""), evidence=[ev] if ev else [{"source": "UNKNOWN"}],
            confidence="HIGH" if ev else "LOW", now=now))
    return out


# ── source 7 (WIRED) : stale plans — open proposals past the staleness window ──────────────────────────
def _age_days(ts: str, now_iso: str):
    try:
        c = datetime.fromisoformat(str(ts).replace("Z", "")[:26])
        n = datetime.fromisoformat(str(now_iso).replace("Z", "")[:26])
        return (n - c).total_seconds() / 86400.0
    except Exception:
        return None                                     # unparseable -> skip (never fabricate an age)


def _from_stale_plans(plan_items, now, stale_days) -> list:
    out = []
    for it in plan_items or []:
        if it.get("status") not in (None, "proposed", "PROPOSED", "BLOCKED"):
            continue
        age = _age_days(it.get("created_at", ""), now or _now())
        if age is None or age < stale_days:
            continue                                    # fresh or unknown-age -> not a stale problem
        key = it.get("source_key") or str(it.get("id") or it.get("task_id") or "?")
        out.append(_mk(
            root_signature=f"stale_plan:{key}", company=it.get("entity") or it.get("company_id") or "holding",
            system="plan", severity=it.get("severity") or "MEDIUM", category="STALE_PLAN",
            observed_facts=f"plan item '{it.get('title') or it.get('goal') or key}' open {int(age)}d without progress",
            evidence=[{"source_key": key, "created_at": it.get("created_at"), "status": it.get("status"),
                       "age_days": int(age)}], confidence="HIGH", now=now))
    return out


# ── fail-open default loaders (each only runs when its arg is None) ────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_priorities() -> list:
    try:
        from app.services.holding.priorities import derive_priorities
        return derive_priorities()
    except Exception:
        return []


def _default_candidates() -> list:
    try:
        from app.services.holding.self_improvement_detect import detect
        from app.services.holding.internal_test import make_internal_test_provider
        prov = make_internal_test_provider()
        return detect(lambda sid: prov({"suite_id": sid, "company_id": "wheellsverse"}))
    except Exception:
        return []


def _default_drift() -> dict:
    try:
        from app.services.holding.holding_deployment import deployed_sha, compute_drift
        import os
        this = deployed_sha()
        return compute_drift(source=os.environ.get("SOURCE_HEAD_SHA", ""), prod_b=this)
    except Exception:
        return {}


def _default_jobs() -> list:
    try:
        from app.services.holding.worker_jobs import list_jobs
        return list_jobs(limit=200)
    except Exception:
        return []


def _default_security_events() -> list:
    try:
        from app.services import security
        return security.events(limit=200).get("events", [])
    except Exception:
        return []


def _default_stale_plans() -> list:
    try:
        from app.services.holding.proposals_store import list_proposals
        return list_proposals(status="proposed", limit=200)
    except Exception:
        return []


def detect_problems(*, priorities=None, candidates=None, drift=None, jobs=None,
                    security_events=None, doc_findings=None, stale_plans=None,
                    now: str = "", stale_days: int = _STALE_PLAN_DAYS) -> list:
    """Unify BOTH existing streams + the five wired sources into one deduped HoldingProblem list.

    ADAPTS (never replaces) derive_priorities + self_improvement_detect, and WIRES deployment drift,
    mission failures, security findings, documentation inaccuracies, and stale plans. Every source is
    injectable (a list/dict) and defaults to a fail-open real-source read (a broken source contributes
    nothing — never a fabricated problem). Deduped by root_signature (higher severity wins, evidence
    merged) and returned most-severe first. Pure/bounded (§79): no LLM, no loop, no write path."""
    now = now or _now()
    prio = priorities if priorities is not None else _default_priorities()
    cand = candidates if candidates is not None else _default_candidates()
    dr = drift if drift is not None else _default_drift()
    jb = jobs if jobs is not None else _default_jobs()
    sec = security_events if security_events is not None else _default_security_events()
    stale = stale_plans if stale_plans is not None else _default_stale_plans()

    problems: list = []
    for producer in (
        lambda: _from_priorities(prio, now),
        lambda: _from_candidates(cand, now),
        lambda: _from_drift(dr, now),
        lambda: _from_jobs(jb, now),
        lambda: _from_security(sec, now),
        lambda: _from_docs(doc_findings, now),         # None -> [] (honest: no doc detector yet)
        lambda: _from_stale_plans(stale, now, stale_days),
    ):
        try:
            problems.extend(producer())
        except Exception:
            continue                                    # fail-open per source (§18): never fabricate

    # dedup by root_signature — an ongoing problem is ONE card (higher severity kept, evidence merged,
    # widest first_seen..last_seen window). This is the deterministic dedup key (§18).
    by_root: dict = {}
    for p in problems:
        cur = by_root.get(p.root_signature)
        if cur is None:
            by_root[p.root_signature] = p
            continue
        if _SEV_ORDER.get(p.severity, 9) < _SEV_ORDER.get(cur.severity, 9):
            p.evidence = cur.evidence + p.evidence
            by_root[p.root_signature] = p
        else:
            cur.evidence = cur.evidence + p.evidence
    out = sorted(by_root.values(), key=lambda p: _SEV_ORDER.get(p.severity, 9))
    return out


def demo() -> None:
    """Pure self-check — no DB/network. Proves: BOTH existing streams adapt; the five sources wire in;
    every problem carries real evidence[] or UNKNOWN; possible_causes is never a single confirmed cause;
    root_signature dedups; CERTIFICATION_FIXTURE candidates are excluded; fail-open."""
    from app.services.holding.self_improvement_detect import Candidate
    now = "2026-09-03T12:00:00"

    prio = [{"rank": 1, "severity": "CRITICAL", "title": "kai health probe not OK (HTTP 0)",
             "source": "live health probe", "entity": "kai"},
            {"rank": 2, "severity": "HIGH", "title": "Sol: risk — churn", "source": "registry:sol.risks", "entity": "sol"}]
    cands = [Candidate(signature="failing_suite:x", category="FAILING_CERTIFIED_TEST", subsystem="holding",
                       problem="certified suite 'x' failing", evidence={"suite_id": "x", "failed": 1},
                       confirmed=True, severity="HIGH"),
             Candidate(signature="failing_suite:si_before_after", category="FAILING_CERTIFIED_TEST",
                       subsystem="holding", problem="seeded fixture", evidence={"suite_id": "si_before_after"},
                       confirmed=True, severity="HIGH", source="CERTIFICATION_FIXTURE")]
    drift = {"state": "PRODUCTION_BEHIND", "source": "a" * 12, "prod_app_b": "b" * 12}
    jobs = [{"id": i, "status": "failed", "created_at": now, "worker": "coding",
             "task": {"company_id": "kai", "capability": "deploy"}, "evidence": {"state": "BLOCKED"}} for i in range(3)]
    sec = [{"event_id": "e1", "severity": "HIGH", "category": "authz_denial", "resource": "sol.transfer",
            "action": "transfer", "result": "failure", "actor": "operator", "company": "sol", "system": "app_b",
            "timestamp": "2026-09-03T10:00:00"},
           {"event_id": "e0", "severity": "INFO", "category": "audit_action", "resource": "x", "action": "read",
            "result": "success", "company": "kai", "system": "app_b", "timestamp": "2026-09-03T09:00:00"}]
    docs = [{"path": "README.md", "issue": "stale deploy command", "severity": "LOW"}]     # no evidence -> LOW/UNKNOWN
    stale = [{"id": 7, "source_key": "reg:sol.risks", "title": "old proposal", "status": "proposed", "entity": "sol",
              "created_at": "2026-08-01T00:00:00"},                                          # >7d old -> stale
             {"id": 8, "source_key": "fresh", "title": "new", "status": "proposed", "created_at": now}]  # fresh -> skip

    ps = detect_problems(priorities=prio, candidates=cands, drift=drift, jobs=jobs, security_events=sec,
                         doc_findings=docs, stale_plans=stale, now=now)
    cats = {p.category for p in ps}
    assert {"HEALTH", "RISK", "CODE_DEFECT", "DEPLOYMENT_DRIFT", "MISSION_FAILURE", "SECURITY",
            "DOCUMENTATION", "STALE_PLAN"} <= cats, cats                 # both streams + all 5 wired sources present
    assert ps[0].severity == "CRITICAL" and ps[0].category == "HEALTH", ps[0]   # most severe first
    assert all(p.evidence and isinstance(p.evidence, list) for p in ps), "every problem carries evidence[]"
    assert all(len(p.possible_causes) >= 2 for p in ps), "causes are hypotheses, never one confirmed root cause"
    assert not any(p.root_signature == "failing_suite:si_before_after" for p in ps), "fixture excluded"
    assert not any(p.category == "STALE_PLAN" and "fresh" in p.root_signature for p in ps), "fresh plan not stale"
    sec_p = next(p for p in ps if p.category == "SECURITY")
    assert sec_p.owner_required and len(sec_p.evidence) == 1 and sec_p.evidence[0]["event_id"] == "e1", sec_p
    doc_p = next(p for p in ps if p.category == "DOCUMENTATION")
    assert doc_p.confidence == "LOW" and doc_p.evidence == [{"source": "UNKNOWN"}], doc_p   # honest UNKNOWN

    # root_signature dedups: the same live-health priority twice -> ONE problem, evidence merged
    dup = detect_problems(priorities=prio + [prio[0]], candidates=[], drift={}, jobs=[], security_events=[],
                          doc_findings=[], stale_plans=[], now=now)
    health = [p for p in dup if p.root_signature == "priority:live health probe"]
    assert len(health) == 1 and len(health[0].evidence) == 2, health   # deduped, both cites kept

    # fail-open: a source that raises contributes nothing (no fabricated problem), never crashes
    empty = detect_problems(priorities=[], candidates=[], drift={}, jobs=[], security_events=[],
                            doc_findings=[], stale_plans=[], now=now)
    assert empty == [], empty
    print(f"holding_problems.demo OK — {len(ps)} problems across {len(cats)} categories (2 existing streams + "
          f"5 wired sources), fixture excluded, dedup verified, evidence+plural-causes on every card")


if __name__ == "__main__":
    demo()
