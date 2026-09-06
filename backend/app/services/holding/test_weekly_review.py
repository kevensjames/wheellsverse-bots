"""§83 strategic/weekly review guard. Run (from backend/):
    python3 -m app.services.holding.test_weekly_review

Mirrors test_reports.py: a flat ck() ledger + injectable sources. Proves wins/losses come ONLY from real
KPI deltas (honest baseline when no prior week), the period label reflects the ACTUAL baseline age (the
baked-in fix — never a hardcoded 'trailing 7 days'), revenue stays REQUIRES_OPERATOR_CONFIRMATION, and
risks/opportunities/tech-debt/security/next-week are source-cited and report-only.
"""
from app.services.holding import reports

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

CUR = {"as_of": "2026-09-08T00:00:00+00:00", "entities_total": 11, "entities_verified": 5,
       "open_incidents": 1, "open_risks": 4, "fields_awaiting_confirmation": 20}
PRIOR = {"as_of": "2026-09-05T00:00:00+00:00", "entities_total": 11, "entities_verified": 3,
         "open_incidents": 2, "open_risks": 4, "fields_awaiting_confirmation": 22}

wr = reports.build_weekly_review(current_kpis=CUR, prior_kpis=PRIOR, problems=[], opportunities=[],
                                 goal_gaps=[], now_iso="2026-09-08T00:00:00+00:00")

# ── wins/losses from REAL deltas only ───────────────────────────────────────────────────────────────────
wins = {w["metric"] for w in wr["wins"]}
ck("wins are exactly the improved KPIs (verified↑, incidents↓, awaiting-confirmation↓)",
   wins == {"entities_verified", "open_incidents", "fields_awaiting_confirmation"})
ck("every win cites the two KPI snapshots (no invented trend)", all("source" in w and "kpi snapshot" in w["source"] for w in wr["wins"]))
ck("no regression this period → honest 'no measured regressions' note (not a fabricated loss)",
   isinstance(wr["losses"], str) and "no measured regressions" in wr["losses"])
ck("an unchanged KPI (open_risks 4→4) is neither a win nor a loss", not any(w["metric"] == "open_risks" for w in wr["wins"]))

# ── BAKED-IN: the period label reflects the ACTUAL baseline age (3.0 days), NOT a hardcoded 7 ────────────
ck("period label reflects the REAL baseline age (3.0 days of actual history), not 'trailing 7 days'",
   "3.0 day(s) of actual history" in wr["period"] and "7 day" not in wr["period"])

# short history: a 2-day-old baseline labels 2.0 days (never claims a week)
SHORT = dict(PRIOR); SHORT["as_of"] = "2026-09-06T00:00:00+00:00"
wr_short = reports.build_weekly_review(current_kpis=CUR, prior_kpis=SHORT, problems=[], opportunities=[],
                                       goal_gaps=[], now_iso="2026-09-08T00:00:00+00:00")
ck("a shorter (2-day) history labels the real age, never 'trailing 7 days'",
   "2.0 day(s) of actual history" in wr_short["period"])

# ── no prior snapshot → honest baseline, no fabricated wins/losses ──────────────────────────────────────
wr0 = reports.build_weekly_review(current_kpis=CUR, prior_kpis=None, problems=[], opportunities=[],
                                  goal_gaps=[], now_iso="2026-09-08T00:00:00+00:00")
ck("no prior week → baseline period note", "baseline" in wr0["period"])
ck("no prior week → wins/losses are honest baseline notes (not invented)",
   "baseline captured" in wr0["wins"] and "baseline captured" in wr0["losses"])

# ── revenue never invented ──────────────────────────────────────────────────────────────────────────────
ck("revenue stays REQUIRES_OPERATOR_CONFIRMATION (never invented)", wr["revenue"].startswith("REQUIRES_OPERATOR_CONFIRMATION"))

# ── tech-debt / security / next-week source-cited from real problems + goal gaps ────────────────────────
probs = [
    {"root_signature": "security:x", "category": "SECURITY", "severity": "HIGH", "company": "sol",
     "observed_facts": "denied transfer", "impact": "i", "confidence": "HIGH", "owner_required": True,
     "recommended_actions": ["INVESTIGATE"], "evidence": [{"e": 1}]},
    {"root_signature": "doc:README", "category": "DOCUMENTATION", "severity": "LOW", "company": "kai",
     "observed_facts": "stale doc", "impact": "i", "confidence": "LOW", "owner_required": False,
     "recommended_actions": ["PREPARE_FIX"], "evidence": [{"source": "UNKNOWN"}]},
]
gaps = [{"goal_id": 1, "company": "sol", "metric": "customers", "verdict": "GAP",
         "recommended_actions": [{"action": "Increase customers by 60", "source": "computed"}]}]
wr2 = reports.build_weekly_review(current_kpis=CUR, prior_kpis=PRIOR, problems=probs, opportunities=[],
                                  goal_gaps=gaps, now_iso="2026-09-08T00:00:00+00:00")
ck("security section lists the real SECURITY problem (cited)",
   any(s["category"] == "SECURITY" and s["source"] == "security:x" for s in wr2["security"]))
ck("tech_debt lists the DOCUMENTATION problem (cited)", any(t["category"] == "DOCUMENTATION" for t in wr2["tech_debt"]))
ck("next_week is deterministic + cited (owner-required problem + goal-gap next step), not generic advice",
   any("denied transfer" in n["item"] for n in wr2["next_week"])
   and any("customers gap" in n["item"].lower() and n.get("source") for n in wr2["next_week"]))

# ── report-only ─────────────────────────────────────────────────────────────────────────────────────────
ck("weekly review is report-only (no external send)", "requires explicit approval" in wr["delivery"])

# ── default (live/DB) path fails open, never raises ─────────────────────────────────────────────────────
wrd = reports.build_weekly_review(now_iso="2026-09-08T00:00:00+00:00")
ck("default live/DB weekly review builds without raising (fail-open)", isinstance(wrd, dict) and "period" in wrd)

n = len(res); ok = sum(res)
print(f"\nWEEKLY REVIEW TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
