"""Wave 2 tests: proposal engine (pure) + store dedup + approve/reject state machine.
Needs local Postgres. Run (from backend/): DATABASE_URL=... python3 -m app.services.holding.test_proposals
"""
from app.services.holding import proposals as prop, proposals_store as store
from sqlalchemy import text
from app.database import SessionLocal

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

# clean slate
try:
    s = SessionLocal(); s.execute(text("DELETE FROM holding_proposals")); s.commit(); s.close()
except Exception:
    pass

PRIOS = [
    {"severity": "HIGH", "title": "Nexora: risk — money-theft vuln", "source": "registry:nexora.risks", "entity": "nexora"},
    {"severity": "MEDIUM", "title": "Re-verify SOLCIRCLE", "source": "registry:solcircle.confidence", "entity": "solcircle"},
    {"severity": "LOW", "title": "Confirm 62 operator data field(s)", "source": "registry.needs_confirmation()"},
]

# 1) engine: every proposal is read-only/investigative with a reversible plan (no consequential action)
drafts = prop.build_proposals(PRIOS)
ck("engine drafts one read-only proposal per priority, each with a plan",
   len(drafts) == 3 and all(d["reversible"] and d["plan"] and
       d["action_class"] in (prop.INVESTIGATE, prop.VERIFY, prop.REQUEST_INFO, prop.REVIEW) for d in drafts))

# 2) store: sync inserts new; re-sync dedups (no duplicate open proposals for the same priority)
n1 = store.sync_open(drafts)
n2 = store.sync_open(drafts)
ck("sync inserts 3, re-sync inserts 0 (dedup on source_key)", n1 == 3 and n2 == 0)
open_props = store.list_proposals(status="proposed")
ck("3 open proposals listed", len(open_props) == 3)

# 3) daily plan ranks the open proposals most-severe first
plan = prop.build_daily_plan(open_props)
ck("daily plan ranks CRITICAL/HIGH first", plan["count"] == 3 and plan["steps"][0]["severity"] == "HIGH")

# 4) approve: records decision, removes from open; a second approve of the same id is a no-op
pid = open_props[0]["id"]
appr = store.decide(pid, "approved")
ck("approve records the decision", appr and appr["status"] == "approved")
ck("approved proposal leaves the open queue", len(store.list_proposals(status="proposed")) == 2)
ck("re-deciding an already-decided proposal is a no-op (guarded)", store.decide(pid, "rejected") is None)

# 5) reject with a reason
pid2 = store.list_proposals(status="proposed")[0]["id"]
rej = store.decide(pid2, "rejected", reason="not now")
ck("reject records the decision", rej and rej["status"] == "rejected")

# 6) invalid status is refused
ck("invalid decision status refused", store.decide(pid2, "executed") is None)

# 7) re-sync right after deciding: decided source_keys are within the 24h cooldown, so they do NOT
#    re-propose — only the 1 still-open proposal remains open (no re-nagging rejected items).
store.sync_open(drafts)
open_after = store.list_proposals(status="proposed")
ck("recently-decided proposals do NOT re-propose (24h cooldown); only the still-open one remains",
   len(open_after) == 1 and open_after[0]["status"] == "proposed")

# cleanup
s = SessionLocal(); s.execute(text("DELETE FROM holding_proposals")); s.commit(); s.close()

n = len(res); ok = sum(res)
print(f"\nHOLDING PROPOSALS TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
