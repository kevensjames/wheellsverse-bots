"""§21 Idea mode tests — pure idea_disposition + DB sync_ideas/list_ideas on the SHARED table.

Proves: ideas share holding_proposals (kind='idea') but NEVER leak into a proposal consumer
(list_proposals / build_daily_plan / owner-queue) with a mixed table; a re-seen rejected evidence
signature does NOT reappear while a genuinely-new one does; and resolve_absent never touches an idea.

Needs local Postgres. Run (from backend/):
    DATABASE_URL=... python3 -m app.services.holding.test_ideas
"""
from app.services.holding import proposals as prop, proposals_store as store
from app.services.holding.opportunity_engine import detect_opportunities
from sqlalchemy import text
from app.database import SessionLocal

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def _clean():
    try:
        s = SessionLocal(); s.execute(text("DELETE FROM holding_proposals")); s.commit(); s.close()
    except Exception:
        pass


_clean()

# ── 0) pure idea_disposition (no DB) ────────────────────────────────────────────────────────────────
ck("idea_disposition: unseen signature → present",
   store.idea_disposition("sigB", {"sigA"}) == "present")
ck("idea_disposition: already-seen signature → suppress",
   store.idea_disposition("sigA", {"sigA", "sigB"}) == "suppress")
ck("idea_disposition: reverting to a previously-seen sig (A→B→A) → suppress (the fix)",
   store.idea_disposition("sigA", {"sigA", "sigB"}) == "suppress")
ck("idea_disposition: blank signature → suppress (no generic idea)",
   store.idea_disposition("", {"sigA"}) == "suppress")
ck("evidence_signature is stable + order-insensitive",
   store.evidence_signature([{"a": 1}, {"b": 2}]) == store.evidence_signature([{"b": 2}, {"a": 1}])
   and store.evidence_signature([{"a": 1}]) != store.evidence_signature([{"a": 2}]))

# ── 1) build real opportunities → sync as ideas ──────────────────────────────────────────────────────
gaps = [{"goal_id": 1, "company": "sol", "metric": "customers", "verdict": "GAP",
         "gap": {"current": 40, "target": 100, "remaining_to_target": 60},
         "evidence": [{"claim": "current customers", "value": 40, "source": "registry:sol.customers"}],
         "recommended_actions": [{"action": "grow by 60", "source": "computed"}], "blockers": []}]
issues = [{"issue_type": "DUPLICATE_CAPABILITY", "companies": ["holding"], "shared_resource": "send_email",
           "recommended_actions": ["INVESTIGATE"], "confidence": "MEDIUM", "owner_required": False,
           "observed_facts": "dup send_email", "evidence": [{"capability_id": "cap-a", "provides": "send_email"}],
           "root_signature": "DUPLICATE_CAPABILITY:send_email"}]
opps = detect_opportunities(goal_gaps=gaps, shared_issues=issues, problems=[])
ideas_in = [o.as_dict() for o in opps]
n_ideas = store.sync_ideas(ideas_in)
ck("sync_ideas inserts the opportunities as ideas", n_ideas == 2)
ck("sync_ideas re-run inserts 0 (same evidence signatures → suppressed)", store.sync_ideas(ideas_in) == 0)

# ── 2) ALSO seed real PROPOSALS into the SAME table (mixed-table run) ─────────────────────────────────
PRIOS = [{"severity": "HIGH", "title": "Nexora: risk", "source": "registry:nexora.risks", "entity": "nexora"},
         {"severity": "MEDIUM", "title": "Re-verify SOL", "source": "registry:solcircle.confidence", "entity": "solcircle"}]
n_props = store.sync_open(prop.build_proposals(PRIOS))
ck("sync_open inserts proposals into the same table", n_props == 2)

# ── 3) KIND SCOPING — the whole point ────────────────────────────────────────────────────────────────
open_props = store.list_proposals(status="proposed")
open_ideas = store.list_ideas(status="proposed")
ck("list_proposals returns ONLY proposals (2), no ideas leak", len(open_props) == 2
   and all(p["source_key"] in ("registry:nexora.risks", "registry:solcircle.confidence") for p in open_props))
ck("list_ideas returns ONLY ideas (2), no proposals leak", len(open_ideas) == 2
   and all(i["source_key"].startswith("opp:") for i in open_ideas))
# an idea NEVER appears in the owner-facing daily plan (built from list_proposals)
plan = prop.build_daily_plan(open_props)
ck("build_daily_plan (owner queue) contains NO idea", plan["count"] == 2
   and not any(str(s.get("entity")) in ("holding", "sol") and "opp:" in str(s) for s in plan["steps"]))
# list_proposals with no status filter still excludes ideas (supreme dashboard path)
ck("list_proposals(all statuses) still excludes ideas",
   all(p["source_key"].startswith("registry:") for p in store.list_proposals()))

# ── 4) resolve_absent (proposal auto-close) NEVER touches an idea ─────────────────────────────────────
store.resolve_absent([])                                     # supersede ALL open proposals
ck("resolve_absent superseded the proposals", len(store.list_proposals(status="proposed")) == 0)
ck("resolve_absent left the ideas untouched (still open)", len(store.list_ideas(status="proposed")) == 2)

# ── 5) reject an idea, then re-sync — a re-seen rejected sig does NOT reappear ────────────────────────
idea_id = open_ideas[0]["id"]
rej = store.decide(idea_id, "rejected", reason="not now")
ck("an idea can be decided (rejected) via the shared decide()", rej and rej["status"] == "rejected")
ck("re-syncing the SAME evidence after rejection does NOT reappear", store.sync_ideas(ideas_in) == 0)

# genuinely-NEW evidence for that same source_key (the customers metric moved 40→55) DOES reappear.
# opportunity dicts key their stable id on `signature`, which sync_ideas stores as the row's source_key.
rejected_sk = open_ideas[0]["source_key"]
moved = dict(next(o for o in ideas_in if o["signature"] == rejected_sk))
moved["evidence"] = [{"claim": "current customers", "value": 55, "source": "registry:sol.customers"}]
ck("genuinely-UNSEEN evidence signature for a rejected idea DOES reappear", store.sync_ideas([moved]) == 1)

# ── 6) the reappeared idea reverts to the OLD (rejected) evidence — must NOT reappear again ───────────
old_again = dict(next(o for o in ideas_in if o["signature"] == rejected_sk))
ck("reverting to the previously-rejected signature does NOT reappear (SET tracked, not newest row)",
   store.sync_ideas([old_again]) == 0)

_clean()

n = len(res); ok = sum(res)
print(f"\nHOLDING IDEAS TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
