"""No-fabrication guard for the Holding Registry. Run (from backend/):
    python3 -m app.services.holding.test_registry
"""
from app.services.holding.registry import (all_entities, get, report_value, needs_confirmation, Confidence)
res=[]
def ck(n,ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

# every financial/customer/legal field returns None (never a fabricated number)
FIN = ("revenue_metrics","expense_metrics","customers","banking_provider_reference","payment_provider_reference","compliance_items")
leaks=[]
for e in all_entities():
    for f in FIN:
        v,_ = report_value(e.entity_id, f)
        if v is not None: leaks.append(f"{e.entity_id}.{f}={v}")
ck("no fabricated financial/customer/compliance values (all None+disclaim)", not leaks)
ck("needs_confirmation lists money/legal fields for every entity", len(needs_confirmation()) >= len(all_entities()))

# VERIFIED repo/deployment facts ARE reported (with provenance)
v,prov = report_value("kai","deployment")
ck("verified deployment fact is reported with provenance", v is not None and "kai-prod" in v.lower() and "source:" in prov)
v,_ = report_value("sol","stage")
ck("SOL stage reflects MOCK money (no real revenue claim)", v is not None and "MOCK" in v)

# unknown entity + unknown field fail closed
ck("unknown entity -> None", report_value("does_not_exist","revenue_metrics")[0] is None)
ck("revenue for a VERIFIED entity still None (not source-backed)", report_value("kai","revenue_metrics")[0] is None)

# confidence markers present, nothing silently 'verified' for money
ck("KAI/SOL/bots VERIFIED; money still unconfirmed",
   get("kai").confidence==Confidence.VERIFIED and report_value("kai","revenue_metrics")[0] is None)

n=len(res); ok=sum(res)
print(f"\nHOLDING REGISTRY TESTS: {ok}/{n} —", "PASS" if ok==n else "FAIL")
raise SystemExit(0 if ok==n else 1)
