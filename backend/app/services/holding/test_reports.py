"""Report-layer no-fabrication + report-only tests. Run (from backend/):
    python3 -m app.services.holding.test_reports
"""
from app.services.holding import reports
from app.services.holding.briefing import run_morning_briefing
res=[]
def ck(n,ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

ov = reports.executive_overview()
ck("overview does NOT summarize financials (requires confirmation)",
   "REQUIRES_OPERATOR_CONFIRMATION" in ov["financials"] and ov["counts"]["needs_confirmation_fields"] > 0)
ck("overview lists entities + verified count", ov["counts"]["total"] >= 10 and ov["counts"]["verified"] >= 1)

port = reports.company_portfolio("kai")
bots = reports.company_portfolio("wheellsverse_bots")   # money never operator-confirmed
ck("un-confirmed portfolio financial fields are disclaimer objects (value None)",
   bots["revenue_metrics"] == {"value": None, "status": "REQUIRES_OPERATOR_CONFIRMATION"}
   and bots["customers"]["value"] is None)
ck("portfolio shows verified deployment fact", port["deployment"] and "kai-prod" in port["deployment"].lower())
ck("unknown entity -> None", reports.company_portfolio("nope") is None)

b = run_morning_briefing(now_iso="2026-08-30T09:00:00-04:00")   # fetch_health=False → no network
ck("briefing timezone America/New_York", b["timezone"] == "America/New_York")
ck("briefing does NOT invent KPI movement or priorities",
   "REQUIRES_OPERATOR_CONFIRMATION" in b["kpi_movement"] and "No source-backed priorities" in b["todays_priorities"])
ck("briefing health disclaimed when none supplied", "UNVERIFIED" in str(b["system_health"]))
ck("briefing is report-only (no external send)", "requires explicit approval" in b["delivery"])

# audit callable invoked, still no external send
seen=[]
run_morning_briefing(audit=lambda name,payload: seen.append((name,payload)))
ck("briefing records an audit event", len(seen)==1 and seen[0][0]=="holding.morning_briefing.generated"
   and "no external send" in seen[0][1]["delivery"])

n=len(res); ok=sum(res)
print(f"\nHOLDING REPORTS TESTS: {ok}/{n} —", "PASS" if ok==n else "FAIL")
raise SystemExit(0 if ok==n else 1)
