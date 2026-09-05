"""No-fabrication guard for §61 the HoldingTimeline event store. Run (from backend/):
    DATABASE_URL=... python3 -m app.services.holding.test_timeline

Mirrors test_registry.py / test_mission.py: a flat ck() ledger. Proves the store admits ONLY observable,
typed, provenance-tagged events and REJECTS hidden chain-of-thought; that events come from the EXISTING
real sources via injectable adapters (empty sources → 0 events, never fabricated); and that the bounded
query is newest-first and filterable. Pure logic is DB-free; a guarded Postgres smoke exercises the
durable append/query + idempotency + the CoT rejection at the write boundary when a DB is reachable.
"""
import uuid

from app.services.holding import timeline as tl
from app.services.holding.timeline import (validate_event, EVENT_TYPES, events_from_audit,
                                           events_from_missions, events_from_deployment,
                                           events_from_security, ingest)

res = []
def ck(n, ok): res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def _ev(**kw):
    base = {"event_id": "e1", "ts": "2026-09-04T00:00:00Z", "type": "deployment", "company": "holding",
            "summary": "deployed x", "source": "test", "provenance": "REAL", "refs": []}
    base.update(kw)
    return base


def _db_up() -> bool:
    try:
        from sqlalchemy import text as _t
        from app.database import SessionLocal
        db = SessionLocal(); db.execute(_t("select 1")); db.close(); return True
    except Exception:
        return False


def run() -> bool:
    # ── admission: only observable, typed, provenance-tagged events are valid ────────────────────────────
    ck("a well-formed observable event validates", validate_event(_ev())[0] is True)
    ck("missing a required field is rejected", validate_event(_ev(summary=""))[0] is False)
    ck("an unknown event type is rejected",
       validate_event(_ev(type="gossip"))[1].startswith("UNKNOWN_TYPE"))
    ck("a bad provenance marker is rejected",
       validate_event(_ev(provenance="MAYBE"))[1].startswith("BAD_PROVENANCE"))
    ck("the 9 §61 event types are exactly the vocabulary",
       EVENT_TYPES == {"deployment", "mission", "incident", "approval", "worker_execution",
                       "customer_milestone", "finance_event", "security_event", "kai_recommendation"})

    # ── the certified boundary: hidden chain-of-thought is REJECTED (top-level AND nested) ──────────────
    ck("a top-level chain_of_thought field is REJECTED",
       validate_event(_ev(chain_of_thought="first I considered..."))[1] == "REJECTED_CHAIN_OF_THOUGHT")
    ck("a NESTED reasoning trace (inside refs) is REJECTED (recursive scan)",
       validate_event(_ev(refs=[{"internal_monologue": "hmm"}]))[1] == "REJECTED_CHAIN_OF_THOUGHT")
    ck("a deeply nested scratchpad is REJECTED",
       validate_event(_ev(refs=[{"detail": {"scratchpad": "x"}}]))[1] == "REJECTED_CHAIN_OF_THOUGHT")
    ck("an OBSERVABLE 'summary' (published text) is NOT mistaken for CoT and IS allowed",
       validate_event(_ev(summary="mission COMPLETE: fix deploy"))[0] is True)

    # ── the key rule is by TOKEN (is_cot_key), not exact spelling — one rule for timeline/explain/what_i_did ──
    ck("is_cot_key catches variants the exact list missed: reasoning_v2 / llm_thoughts / cot_trace / 'reasoning trace' / llmThoughts / COT-Trace",
       all(tl.is_cot_key(k) for k in ("reasoning_v2", "llm_thoughts", "cot_trace", "reasoning trace", "llmThoughts", "COT-Trace",
                                      "Thinking.step", "deliberation_log", "my scratchpad")))
    ck("is_cot_key is token-exact, not substring: summary / rationale / cotangent / thoughtful_note / boycott are observable",
       not any(tl.is_cot_key(k) for k in ("summary", "rationale", "cotangent", "thoughtful_note", "boycott", "refs", "root_signature")))
    ck("every legacy _COT_KEYS spelling is caught by the token rule (the list is examples of the ONE rule, not a second vocabulary)",
       all(tl.is_cot_key(k) for k in tl._COT_KEYS))
    ck("a NESTED reasoning_v2 (a spelling not in the legacy list) is REJECTED at admission",
       validate_event(_ev(refs=[{"reasoning_v2": "x"}]))[1] == "REJECTED_CHAIN_OF_THOUGHT"
       and validate_event(_ev(refs=[{"llmThoughts": "x"}]))[1] == "REJECTED_CHAIN_OF_THOUGHT")
    ck("the §17/§87 attestation key passes ONLY as exactly False; any other value is hidden reasoning",
       not tl._contains_cot({tl.ATTESTATION_KEY: False, "summary": "x"})
       and tl._contains_cot({tl.ATTESTATION_KEY: True}) and tl._contains_cot({tl.ATTESTATION_KEY: "no"})
       and tl._contains_cot({tl.ATTESTATION_KEY: 0}))

    # ── adapters map REAL sources → observable events; no source data → 0 events (never fabricated) ──────
    ck("audit adapter: no records → 0 events (honest empty)", events_from_audit([]) == [])
    ck("audit adapter emits ONLY approved actions as approval events (an owner decision)",
       len(events_from_audit([{"id": "a1", "action": "execute", "scope": "sol.deploy", "approved": True,
                               "success": True, "destructive": True},
                              {"id": "a2", "action": "read", "scope": "kai", "approved": False}])) == 1)
    aud = events_from_audit([{"id": "a1", "action": "execute", "scope": "sol.deploy", "approved": True,
                              "success": True, "destructive": True, "ts": "2026-09-04T01:00:00Z"}])
    ck("audit approval event is typed/provenance-tagged and validates",
       aud[0]["type"] == "approval" and aud[0]["provenance"] == "REAL" and validate_event(aud[0])[0])
    ck("audit event carries NO chain-of-thought (observable summary + refs only)",
       not tl._contains_cot(aud[0]))

    ck("mission adapter: no headers → 0 events", events_from_missions([]) == [])
    mis = events_from_missions([{"mission_id": "m1", "company": "sol", "objective": "fix incident",
                                 "created_at": "2026-09-04T00:00:00Z", "cancelled": False, "completed_at": ""},
                                {"mission_id": "m2", "company": "kai", "objective": "deploy",
                                 "completed_at": "2026-09-04T02:00:00Z"}])
    ck("mission adapter derives observable transitions from header state (CREATED / COMPLETE)",
       {e["refs"][0]["state"] for e in mis} == {"CREATED", "COMPLETE"} and all(validate_event(e)[0] for e in mis))
    ck("a completed mission → a distinct event_id (a later transition is a NEW event, not a mutation)",
       any(e["event_id"] == "mission:m2:COMPLETE" for e in mis))

    ck("deployment adapter: UNKNOWN sha → 0 events (never a fabricated deploy)",
       events_from_deployment("UNKNOWN") == [] and events_from_deployment("") == [])
    dep = events_from_deployment("abc123def456", features=[{"deployed": True}, {"deployed": True}])
    ck("deployment adapter emits ONE typed event for a real sha (provenance DERIVED — ts is observed time)",
       len(dep) == 1 and dep[0]["type"] == "deployment" and dep[0]["provenance"] == "DERIVED"
       and validate_event(dep[0])[0])

    sec = events_from_security([{"event_id": "s1", "timestamp": "2026-09-04T03:00:00Z", "company": "sol",
                                 "category": "authz_denial", "severity": "HIGH", "action": "delete",
                                 "resource": "sol.db", "result": "failure", "actor": "op"}])
    ck("security adapter maps a SecurityEvent → a typed security_event (validates, REAL)",
       len(sec) == 1 and sec[0]["type"] == "security_event" and validate_event(sec[0])[0])

    # ── ingest is fully injectable; empty everywhere → 0 candidates (no fabrication) ─────────────────────
    empty = ingest(audit=[], missions=[], deployment=[], security=[])
    ck("ingest with all sources empty → 0 candidates (events come from real sources only)",
       empty["candidates"] == 0 and empty["inserted"] == 0)

    # ── guarded Postgres smoke: durable append/query + idempotency + CoT rejection at the write boundary ─
    if _db_up():
        tag = "tl-test-" + uuid.uuid4().hex[:8]
        from sqlalchemy import text as _t
        from app.database import SessionLocal

        def _clean():
            db = SessionLocal(); db.execute(_t("DELETE FROM holding_timeline WHERE event_id LIKE :p"),
                                            {"p": f"%{tag}%"}); db.commit(); db.close()

        tl.append(_ev(event_id=f"seed:{tag}"))   # ensure table
        _clean()

        e_dep = _ev(event_id=f"deployment:{tag}", type="deployment", company="holding", ts="2026-09-04T00:00:00Z")
        e_mis = _ev(event_id=f"mission:{tag}", type="mission", company="sol", ts="2026-09-04T05:00:00Z",
                    summary="mission COMPLETE: fix", source="holding.mission")
        r1 = tl.append(e_dep)
        ck("[db] append stores a valid observable event", r1["ok"] and r1["inserted"])
        r2 = tl.append(e_dep)
        ck("[db] append is idempotent — same event_id inserts once (re-ingest never duplicates)",
           r2["ok"] and r2["inserted"] is False)
        tl.append(e_mis)

        cot = _ev(event_id=f"cot:{tag}", refs=[{"chain_of_thought": "secret plan"}])
        r3 = tl.append(cot)
        ck("[db] append REFUSES a hidden-chain-of-thought event at the write boundary (nothing stored)",
           r3["ok"] is False and r3["reason"] == "REJECTED_CHAIN_OF_THOUGHT")
        db = SessionLocal()
        try:
            stored = db.execute(_t("SELECT count(*) FROM holding_timeline WHERE event_id = :i"),
                                {"i": f"cot:{tag}"}).fetchone()[0]
        finally:
            db.close()
        ck("[db] the rejected CoT event is genuinely NOT in the store", stored == 0)

        allrows = [e for e in tl.query(limit=500) if tag in e["event_id"]]
        ck("[db] query is newest-first (mission ts > deployment ts)",
           [e["event_id"] for e in allrows][:2] == [f"mission:{tag}", f"deployment:{tag}"])
        ck("[db] query filters by type", all(e["type"] == "mission"
           for e in tl.query(type="mission", limit=500) if tag in e["event_id"]))
        ck("[db] query filters by company",
           [e["event_id"] for e in tl.query(company="sol", limit=500) if tag in e["event_id"]] == [f"mission:{tag}"])

        # ingest end-to-end from injected REAL-shaped fixtures → durable rows, then honest empty re-ingest
        ing = ingest(audit=[{"id": f"aud-{tag}", "action": "execute", "scope": "sol.deploy",
                             "approved": True, "success": True, "destructive": True,
                             "ts": "2026-09-04T06:00:00Z"}],
                     missions=[], deployment=[], security=[])
        ck("[db] ingest appends real-source events (1 approval from an approved audit record)",
           ing["inserted"] == 1)
        ck("[db] the ingested approval is queryable + observable (no CoT)",
           any(e["event_id"] == f"approval:aud-{tag}" and not tl._contains_cot(e)
               for e in tl.query(type="approval", limit=500)))
        _clean()
    else:
        ck("[db] Postgres smoke skipped (no DB reachable) — pure logic fully covered above", True)

    n = len(res); ok = sum(res)
    print(f"\nHOLDING TIMELINE TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
