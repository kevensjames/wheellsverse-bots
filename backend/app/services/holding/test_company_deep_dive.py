"""§85 company deep-dive guard. Run (from backend/):
    python3 -m app.services.holding.test_company_deep_dive

Mirrors test_reports.py: a flat ck() ledger + injectable sources. Proves company_deep_dive EXTENDS
company_portfolio (never loosens its money/customer disclaiming), folds live signals/health/deploy-truth/
problems/opportunities/proposals/§82 goal-gap/timeline for ONE company from real data, and fails closed on
an unknown entity.
"""
from app.services.holding import reports

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

SIG = {"ok": True, "http": 200, "source": "https://app/x/health", "detail": {"git_sha": "abc123", "deploy_id": "d9"}}
PROBS = [
    {"root_signature": "p:sol", "category": "HEALTH", "severity": "HIGH", "company": "sol", "system": "sol",
     "observed_facts": "sol down", "impact": "i", "confidence": "HIGH", "owner_required": False,
     "recommended_actions": ["INVESTIGATE"], "evidence": [{"x": 1}]},
    {"root_signature": "p:kai", "category": "HEALTH", "severity": "HIGH", "company": "kai", "system": "kai",
     "observed_facts": "kai other", "impact": "i", "confidence": "HIGH", "owner_required": False,
     "recommended_actions": [], "evidence": []},
]
OPPS = [
    {"signature": "opp:sol", "title": "grow sol", "company": "sol", "category": "GROWTH", "why_now": "gap",
     "expected_benefit": "x", "confidence": "HIGH", "recommended_next_step": "do", "evidence": [{"x": 1}]},
    {"signature": "opp:kai", "title": "grow kai", "company": "kai", "category": "GROWTH", "confidence": "HIGH",
     "evidence": [{"y": 1}]},
]
PROPS = [
    {"id": 7, "entity": "sol", "title": "fix sol", "status": "proposed",
     "created_at": "2026-09-06T00:00:00+00:00", "decided_at": None},
    {"id": 8, "entity": "kai", "title": "kai thing", "status": "approved",
     "created_at": "2026-09-01T00:00:00+00:00", "decided_at": "2026-09-02T00:00:00+00:00"},
]
GAPS = [{"goal_id": 1, "company": "sol", "metric": "customers", "verdict": "GAP"}]

dd = reports.company_deep_dive("sol", signals=SIG, problems=PROBS, opportunities=OPPS, proposals=PROPS,
                               goal_gaps=GAPS, now_iso="2026-09-08T00:00:00+00:00")
port = reports.company_portfolio("sol")

# ── EXTENDS company_portfolio: money/customer disclaiming preserved EXACTLY (never loosened) ─────────────
ck("deep-dive preserves company_portfolio money/customer handling exactly",
   all(dd.get(f) == port.get(f) for f in ("revenue_metrics", "expense_metrics", "customers",
                                          "banking_provider_reference", "payment_provider_reference")))
bots = reports.company_deep_dive("wheellsverse_bots", signals={"ok": None}, problems=[], opportunities=[],
                                 proposals=[], goal_gaps=[])
ck("an un-confirmed entity's money/customers stay disclaimer objects (value None)",
   bots["revenue_metrics"] == {"value": None, "status": "REQUIRES_OPERATOR_CONFIRMATION"}
   and bots["customers"]["value"] is None)

# ── folds live signals + health + deploy-truth from the real probe ──────────────────────────────────────
ck("folds live_signals + health (reachable from the real probe)",
   dd["live_signals"] == SIG and dd["health"]["reachable"] is True and dd["health"]["http"] == 200)
ck("deploy-truth folds registry facts + the live git_sha/deploy_id from the probe",
   dd["deploy_truth"]["live_git_sha"] == "abc123" and dd["deploy_truth"]["deploy_id"] == "d9"
   and dd["deploy_truth"]["deployment"] == port["deployment"])

# ── per-company filter: only THIS company's problems/opps/proposals/gaps are folded ─────────────────────
ck("problems filtered to this company (cited by root_signature)",
   [p["source"] for p in dd["problems"]] == ["p:sol"])
ck("opportunities filtered to this company (cited by signature)",
   [o["source"] for o in dd["opportunities"]] == ["opp:sol"])
ck("proposals filtered to this company", [p["id"] for p in dd["proposals"]] == [7])
ck("§82 goal-gap folded for this company", dd["goal_gap"] == GAPS)

# ── timeline is real + timestamped (from this company's proposals), newest-first, cited ──────────────────
ck("timeline built from real proposal events, cited, newest-first",
   dd["timeline"] and dd["timeline"][0]["source"] == "proposal:7"
   and all(t.get("at") and t.get("source") for t in dd["timeline"]))

# ── fail-closed on unknown entity (same as company_portfolio) ───────────────────────────────────────────
ck("unknown entity → None (fail-closed)",
   reports.company_deep_dive("does_not_exist", signals={}, problems=[], opportunities=[],
                             proposals=[], goal_gaps=[]) is None)

# ── default (live/DB) path fails open, never raises ─────────────────────────────────────────────────────
ddd = reports.company_deep_dive("kai", signals={"ok": None}, now_iso="2026-09-08T00:00:00+00:00")
ck("default live/DB deep-dive builds without raising (fail-open)", isinstance(ddd, dict) and "timeline" in ddd)

n = len(res); ok = sum(res)
print(f"\nCOMPANY DEEP-DIVE TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
