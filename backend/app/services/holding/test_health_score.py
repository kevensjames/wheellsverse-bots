"""No-fabrication guard for §57 HoldingHealthScore + §58 evidence_quality. Run (from backend/):
    python3 -m app.services.holding.test_health_score
"""
from app.services.holding.health_score import (
    compute_health, evidence_quality, HEALTH_FORMULA_VERSION, INSUFFICIENT_DATA, NO_SCORE,
)
res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

PERFECT = dict(availability={"healthy": 3, "total": 3}, security={"high": 0, "critical": 0},
               deployment_health="IN_SYNC", mission_blockers=0, data_freshness={"fresh": 4, "stale": 0})

# determinism + versioning: same inputs -> identical score AND version (never LLM-varying)
a = compute_health(**PERFECT); b = compute_health(**PERFECT)
ck("same inputs -> byte-identical result", a == b)
ck("carries HEALTH_FORMULA_VERSION", a["version"] == HEALTH_FORMULA_VERSION == "1.0.0")
ck("all-healthy measured set -> 100 / HEALTHY", a["score"] == 100 and a["band"] == "HEALTHY")

# money/customer are UNAVAILABLE today -> INSUFFICIENT_DATA, not a fabricated healthy contribution
ck("customer+financial default to INSUFFICIENT_DATA (twin UNAVAILABLE)",
   a["insufficient_data"] == ["customer_impact", "financial_status"])

# a dimension with no source does NOT silently score healthy: INSUFFICIENT_DATA, 0 pts, excluded
nc = compute_health(**{**PERFECT, "security": "NOT_CONNECTED"})
sec = next(c for c in nc["components"] if c["dimension"] == "security")
ck("security NOT_CONNECTED -> INSUFFICIENT_DATA + 0 points (a missing feed is never 'secure')",
   sec["status"] == INSUFFICIENT_DATA and sec["points"] == 0 and "security" in nc["insufficient_data"])
ck("un-sourced dimension dropped from the average (measured count falls 5 -> 4)",
   nc["measured_dimensions"] == 4)

# every component states its dimension, status, points and cap (per-dimension contributions)
ck("every component carries dimension/status/points/max_points",
   all({"dimension", "status", "points", "max_points"} <= set(c) for c in a["components"]))

# too few measurable dimensions -> NO SCORE (never a fake number)
thin = compute_health(availability={"healthy": 2, "total": 2})
ck("only 1 measurable dimension -> NO SCORE / INSUFFICIENT_DATA (no fabricated number)",
   thin["score"] == NO_SCORE and thin["band"] == INSUFFICIENT_DATA and thin["measured_dimensions"] == 1)

# a measured-but-degraded set yields a real, lower, deterministic number (not omitted)
mid = compute_health(availability={"healthy": 1, "total": 2}, security={"high": 2, "critical": 1},
                     deployment_health="STAGING_BEHIND", mission_blockers=2,
                     data_freshness={"fresh": 1, "stale": 3})
ck("degraded-but-measured set scores a real number in (0,100)", isinstance(mid["score"], int)
   and 0 < mid["score"] < 100 and mid["band"] in ("AT_RISK", "FAIR"))
ck("score is bounded 0..100", all(0 <= compute_health(**{**PERFECT, "mission_blockers": n})["score"] <= 100
                                  for n in (0, 3, 99)))

# §58 evidence_quality — deterministic HIGH/MEDIUM/LOW from EXPLICIT evidence (not token probability)
rich = [{"source": "live health probe", "freshness": "FRESH"}, {"event_id": "e1", "timestamp": "t"}]
ck("rich evidence (2+ distinct real sources, fresh) -> HIGH", evidence_quality(rich) == "HIGH")
ck("thin evidence (empty) -> LOW", evidence_quality([]) == "LOW")
ck("placeholder-only evidence -> LOW", evidence_quality([{"source": "UNKNOWN"}]) == "LOW")
ck("single real source -> MEDIUM (corroboration-of-one)",
   evidence_quality([{"source_key": "reg:sol.risks"}]) == "MEDIUM")
ck("2+ sources but one STALE caps at MEDIUM",
   evidence_quality([{"source": "a", "freshness": "STALE"}, {"source": "b"}]) == "MEDIUM")
ck("evidence_quality is deterministic (same set -> same verdict)",
   evidence_quality(rich) == evidence_quality(rich))

n = len(res); ok = sum(res)
print(f"\nHEALTH SCORE TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
