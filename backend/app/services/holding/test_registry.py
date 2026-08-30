"""No-fabrication guard for the Holding Registry. Run (from backend/):
    python3 -m app.services.holding.test_registry
"""
from app.services.holding.registry import (all_entities, get, report_value, needs_confirmation, Confidence)
res=[]
def ck(n,ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

# A money/customer/compliance field may report ONLY if explicitly operator-confirmed;
# anything else must disclaim (None). This forbids silent fabrication of un-confirmed values.
FIN = ("revenue_metrics","expense_metrics","customers","banking_provider_reference","payment_provider_reference","compliance_items")
leaks=[]
for e in all_entities():
    for f in FIN:
        v,_ = report_value(e.entity_id, f)
        if v is not None and "operator-confirmed" not in v.lower():
            leaks.append(f"{e.entity_id}.{f}={v}")
ck("no UN-confirmed financial/customer/compliance values (only operator-confirmed may report)", not leaks)
ck("needs_confirmation still lists remaining money/legal fields", len(needs_confirmation()) >= len(all_entities()))

# operator-confirmed values ARE reported, WITH the confirmation provenance
v,_ = report_value("kai","revenue_metrics")
ck("operator-confirmed KAI revenue reports (internal, provenance-marked)",
   v is not None and "operator-confirmed" in v.lower())
v,_ = report_value("sol","customers")
ck("operator-confirmed SOL customers reports (pre-revenue/mock)",
   v is not None and "operator-confirmed" in v.lower())

# VERIFIED repo/deployment facts ARE reported (with provenance)
v,prov = report_value("kai","deployment")
ck("verified deployment fact is reported with provenance", v is not None and "kai-prod" in v.lower() and "source:" in prov)
v,_ = report_value("sol","stage")
ck("SOL stage reflects MOCK money (no real revenue claim)", v is not None and "MOCK" in v)

# unknown entity + unknown field fail closed
ck("unknown entity -> None", report_value("does_not_exist","revenue_metrics")[0] is None)
# an UN-confirmed entity's money field still disclaims (bots infra VERIFIED, money never confirmed)
ck("un-confirmed revenue still None (wheellsverse_bots)", report_value("wheellsverse_bots","revenue_metrics")[0] is None)

# confidence markers present, nothing silently 'verified' for un-confirmed money
ck("bots VERIFIED (infra) yet its money stays unconfirmed",
   get("wheellsverse_bots").confidence==Confidence.VERIFIED and report_value("wheellsverse_bots","revenue_metrics")[0] is None)

n=len(res); ok=sum(res)
print(f"\nHOLDING REGISTRY TESTS: {ok}/{n} —", "PASS" if ok==n else "FAIL")
raise SystemExit(0 if ok==n else 1)
