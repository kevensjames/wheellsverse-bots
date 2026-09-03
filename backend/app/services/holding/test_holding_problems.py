"""No-fabrication guard for §18 unified HoldingProblem detection. Run (from backend/):
    python3 -m app.services.holding.test_holding_problems

Mirrors test_registry.py: a flat ck() ledger. Proves the aggregator ADAPTS both existing streams
(priorities + self_improvement_detect) and WIRES the five missing sources, with zero fabrication.
"""
from app.services.holding.holding_problems import detect_problems, HoldingProblem
from app.services.holding.self_improvement_detect import Candidate

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

NOW = "2026-09-03T12:00:00"

# ── inputs: the two EXISTING streams + all five WIRED sources (pure, injected — no DB/network) ──────────
prio = [{"rank": 1, "severity": "CRITICAL", "title": "kai health probe not OK (HTTP 0)",
         "source": "live health probe", "entity": "kai"},
        {"rank": 2, "severity": "HIGH", "title": "Sol: risk — churn", "source": "registry:sol.risks", "entity": "sol"}]
cands = [Candidate(signature="failing_suite:x", category="FAILING_CERTIFIED_TEST", subsystem="holding",
                   problem="certified suite 'x' failing", evidence={"suite_id": "x", "failed": 1},
                   confirmed=True, severity="HIGH"),
         Candidate(signature="failing_suite:si_before_after", category="FAILING_CERTIFIED_TEST", subsystem="holding",
                   problem="seeded fixture", evidence={"suite_id": "si_before_after"}, confirmed=True,
                   severity="HIGH", source="CERTIFICATION_FIXTURE")]
drift = {"state": "PRODUCTION_BEHIND", "source": "a" * 12, "prod_app_b": "b" * 12}
jobs = [{"id": i, "status": "failed", "created_at": NOW, "worker": "coding",
         "task": {"company_id": "kai", "capability": "deploy"}, "evidence": {"state": "BLOCKED"}} for i in range(3)]
sec = [{"event_id": "e1", "severity": "HIGH", "category": "authz_denial", "resource": "sol.transfer",
        "action": "transfer", "result": "failure", "actor": "operator", "company": "sol", "system": "app_b",
        "timestamp": "2026-09-03T10:00:00"},
       {"event_id": "e0", "severity": "INFO", "category": "audit_action", "resource": "x", "action": "read",
        "result": "success", "company": "kai", "system": "app_b", "timestamp": "2026-09-03T09:00:00"}]
docs = [{"path": "README.md", "issue": "stale deploy command", "severity": "LOW"}]
stale = [{"id": 7, "source_key": "reg:sol.risks", "title": "old proposal", "status": "proposed",
          "entity": "sol", "created_at": "2026-08-01T00:00:00"},
         {"id": 8, "source_key": "fresh", "title": "new", "status": "proposed", "created_at": NOW}]

ps = detect_problems(priorities=prio, candidates=cands, drift=drift, jobs=jobs, security_events=sec,
                     doc_findings=docs, stale_plans=stale, now=NOW)
cats = {p.category for p in ps}

# BOTH existing streams are ADAPTED (not replaced) into HoldingProblem
ck("operational stream (derive_priorities) adapted", "HEALTH" in cats and "RISK" in cats)
ck("code-defect stream (self_improvement_detect) adapted", "CODE_DEFECT" in cats)

# the FIVE previously-missing sources are WIRED
ck("wired: deployment drift", "DEPLOYMENT_DRIFT" in cats)
ck("wired: mission failures", "MISSION_FAILURE" in cats)
ck("wired: security findings", "SECURITY" in cats)
ck("wired: documentation inaccuracies", "DOCUMENTATION" in cats)
ck("wired: stale plans", "STALE_PLAN" in cats)

# every field REAL/DERIVED or UNKNOWN — never fabricated
ck("every problem carries real evidence[] or explicit UNKNOWN",
   all(isinstance(p.evidence, list) and p.evidence for p in ps))
ck("possible_causes is ALWAYS >=2 hypotheses (never one confirmed LLM root cause)",
   all(len(p.possible_causes) >= 2 for p in ps))
ck("doc finding with no source is LOW confidence + explicit UNKNOWN evidence (no fabricated cite)",
   any(p.category == "DOCUMENTATION" and p.confidence == "LOW"
       and p.evidence == [{"source": "UNKNOWN"}] for p in ps))

# provenance honesty: seeded certification fixtures are NEVER surfaced as organic problems (§18)
ck("CERTIFICATION_FIXTURE candidate excluded",
   not any(p.root_signature == "failing_suite:si_before_after" for p in ps))

# bounded / no fabrication of stale-ness: a fresh plan item is NOT a stale problem
ck("fresh plan item not surfaced as stale", not any("fresh" in p.root_signature for p in ps))
# INFO security events are not problems (only HIGH/CRITICAL)
ck("INFO audit event is not a problem", not any(p.category == "SECURITY" and "e0" in str(p.evidence) for p in ps))

# ranking + owner routing
ck("ranked most-severe first (CRITICAL health leads)", ps[0].severity == "CRITICAL" and ps[0].category == "HEALTH")
ck("security problem is owner_required", any(p.category == "SECURITY" and p.owner_required for p in ps))
ck("prod deployment drift is owner_required", any(p.category == "DEPLOYMENT_DRIFT" and p.owner_required for p in ps))

# root_signature DEDUPS an ongoing problem into ONE card (evidence merged)
dup = detect_problems(priorities=prio + [prio[0]], candidates=[], drift={}, jobs=[], security_events=[],
                      doc_findings=[], stale_plans=[], now=NOW)
h = [p for p in dup if p.root_signature == "priority:live health probe"]
ck("root_signature dedups duplicates into one problem, evidence merged", len(h) == 1 and len(h[0].evidence) == 2)

# fail-open: all-empty sources yield [] (never a fabricated problem), never raises
ck("fail-open: empty inputs -> [] (no fabricated problems)",
   detect_problems(priorities=[], candidates=[], drift={}, jobs=[], security_events=[],
                   doc_findings=[], stale_plans=[], now=NOW) == [])

# as_dict() round-trips to plain JSON-able primitives with the full §18 field set
d = ps[0].as_dict()
FIELDS = {"problem_id", "company", "system", "severity", "category", "observed_facts", "evidence", "impact",
          "confidence", "first_seen", "last_seen", "status", "possible_causes", "recommended_actions",
          "owner_required", "assigned_mission", "root_signature"}
ck("as_dict() carries the full §18 field set", FIELDS <= set(d) and isinstance(d["possible_causes"], list))

n = len(res); ok = sum(res)
print(f"\nHOLDING PROBLEMS TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
