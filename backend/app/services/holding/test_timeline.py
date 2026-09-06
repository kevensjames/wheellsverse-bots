"""No-fabrication guard for §61 the HoldingTimeline event store. Run (from backend/):
    DATABASE_URL=... python3 -m app.services.holding.test_timeline

Mirrors test_registry.py / test_mission.py: a flat ck() ledger. Proves the store admits ONLY observable,
typed, provenance-tagged events and REJECTS hidden chain-of-thought; that events come from the EXISTING
real sources via injectable adapters (empty sources → 0 events, never fabricated); and that the bounded
query is newest-first and filterable. Pure logic is DB-free; a guarded Postgres smoke exercises the
durable append/query + idempotency + the CoT rejection at the write boundary when a DB is reachable.
"""
import pathlib
import uuid
from datetime import datetime, timezone

from app.services.holding import timeline as tl
from app.services.holding.timeline import (validate_event, EVENT_TYPES, events_from_audit,
                                           events_from_missions, events_from_deployment,
                                           events_from_proposals, events_from_security, ingest)

res = []
def ck(n, ok): res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def _ev(**kw):
    base = {"event_id": "e1", "ts": "2026-09-04T00:00:00Z", "type": "deployment", "company": "holding",
            "summary": "deployed x", "source": "test", "provenance": "REAL", "refs": []}
    base.update(kw)
    return base


def _utc(s):
    """The instant a timestamp names — Postgres hands it back in the server's own zone offset."""
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


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

    ck("proposals adapter: no rows → 0 events (honest empty)", events_from_proposals([]) == [])
    props = events_from_proposals([
        {"id": 7, "created_at": "2026-09-04T07:00:00Z", "entity": "sol", "title": "rotate API key",
         "severity": "HIGH", "status": "approved", "decided_at": "2026-09-04T08:00:00Z"},
        {"id": 8, "created_at": "2026-09-04T09:00:00Z", "entity": "kai", "title": "add index",
         "severity": "LOW", "status": "proposed", "decided_at": None}])
    ck("proposals adapter: a DECIDED proposal → recommendation + approval; an OPEN one → recommendation only",
       [e["event_id"] for e in props] == ["proposal:7:PROPOSED", "proposal:7:APPROVED", "proposal:8:PROPOSED"])
    ck("every proposal event traces to its real row id and carries THAT ROW's own timestamp (never synthesized)",
       all(e["refs"][0]["proposal_id"] in (7, 8) and e["provenance"] == "REAL" for e in props)
       and [e["ts"] for e in props] == ["2026-09-04T07:00:00Z", "2026-09-04T08:00:00Z", "2026-09-04T09:00:00Z"]
       and all(validate_event(e)[0] and not tl._contains_cot(e) for e in props))
    ck("a proposal row with no timestamps contributes NOTHING (an absent fact is never a placeholder event)",
       events_from_proposals([{"id": 9, "title": "x", "status": "approved"}]) == [])

    # ── ingest is fully injectable; empty everywhere → 0 candidates (no fabrication) ─────────────────────
    empty = ingest(audit=[], missions=[], proposals=[], deployment=[], security=[])
    ck("ingest with all sources empty → 0 candidates (events come from real sources only)",
       empty["candidates"] == 0 and empty["inserted"] == 0)

    # ── §61 WIRING: the panel is fed on the read path, and an unreadable source is NEVER silently empty ──
    ck("ingest reports one status row per real source (audit / mission / proposals / security / deployment)",
       [s["source"] for s in empty["sources"]] == ["governance.audit_log", "holding.mission",
        "holding.proposals_store", "security.evidence_bus", "holding.holding_deployment"])

    _saved = (tl._read_audit, tl._read_missions, tl._read_proposals, tl._read_security, tl._resolve_deployment)
    tl._read_audit = tl._read_missions = tl._read_proposals = tl._read_security = lambda _l: ([], False)
    tl._resolve_deployment = lambda _d: ([], False)
    dead = ingest()                       # every source unreadable — the "module not in this build" case
    dead_view = tl.view(limit=5)
    tl._read_audit, tl._read_missions, tl._read_proposals, tl._read_security, tl._resolve_deployment = _saved
    ck("a source this build cannot read is reported UNAVAILABLE with 0 events — not a silent empty",
       dead["candidates"] == 0 and all(s["status"] == "UNAVAILABLE" and s["events"] == 0
                                       for s in dead["sources"]))
    ck("view() with every source unreadable exposes it: 0 CONNECTED sources (the panel must NOT read as 'nothing happened')",
       not [s for s in dead_view["sources"] if s["status"] == "CONNECTED"] and len(dead_view["sources"]) == 5)

    live = tl.view(limit=5)               # NO injection: the REAL wiring against this build's sources
    ck("view() returns the panel contract: events + store status + per-source status",
       set(live) == {"events", "store", "sources"} and live["store"] in ("CONNECTED", "UNAVAILABLE")
       and all(set(s) == {"source", "status", "events"} for s in live["sources"]))
    ck("the REAL wiring resolves: the audit log + deployment sources are readable in this build (the panel is fed, not dormant)",
       {s["source"] for s in live["sources"] if s["status"] == "CONNECTED"}
       >= {"governance.audit_log", "holding.holding_deployment"})
    ck("security.evidence_bus is absent from this build → UNAVAILABLE, stated rather than silently empty",
       [s["status"] for s in live["sources"] if s["source"] == "security.evidence_bus"] == ["UNAVAILABLE"])
    ck("every event view() returns is a stored record with a real source + provenance (nothing invented)",
       all(e["source"] and e["provenance"] in ("REAL", "DERIVED", "UNAVAILABLE") and not tl._contains_cot(e)
           for e in live["events"]))

    ck("append_many applies the SAME admission rule (hidden CoT / malformed rejected, nothing stored, no DB touched)",
       tl.append_many([{"bad": 1}, _ev(event_id="cot-batch", reasoning_trace="x")])
       == {"ok": True, "inserted": 0, "rejected": 2} and tl.append_many([])["inserted"] == 0)

    # ── guarded Postgres smoke: durable append/query + idempotency + CoT rejection at the write boundary ─
    if _db_up():
        tag = "tl-test-" + uuid.uuid4().hex[:8]
        from sqlalchemy import text as _t
        from app.database import SessionLocal

        def _clean():
            db = SessionLocal(); db.execute(_t("DELETE FROM holding_timeline WHERE event_id LIKE :p"),
                                            {"p": f"%{tag}%"}); db.commit(); db.close()

        def _tagged():
            return [e for e in tl.query(limit=500) if tag in e["event_id"]]

        tl.append(_ev(event_id=f"seed:{tag}"))   # ensure table
        _clean()
      # Everything below writes REAL rows into the store DATABASE_URL names. try/finally is not tidiness:
      # without it one exception leaves test events in a live timeline, where nothing distinguishes them
      # from real ones. The finally removes them and the check after this block PROVES they are gone.
        try:

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

            # ── the read-path wiring, end to end: a REAL source row → a stored event the panel renders ───────
            batch = [_ev(event_id=f"b1-{tag}"), _ev(event_id=f"b2-{tag}", type="mission",
                                                    summary="mission COMPLETE: x", source="holding.mission"),
                     _ev(event_id=f"b3-{tag}", type="gossip")]              # inadmissible → never stored
            r4 = tl.append_many(batch)
            ck("[db] append_many stores the admissible events in one statement and rejects the rest",
               r4 == {"ok": True, "inserted": 2, "rejected": 1})
            ck("[db] append_many is idempotent — re-ingesting the SAME sources on every read never duplicates",
               tl.append_many(batch)["inserted"] == 0
               and len([e for e in tl.query(limit=500) if e["event_id"] == f"b1-{tag}"]) == 1)
            ck("[db] the inadmissible event is genuinely absent from the store",
               not [e for e in tl.query(limit=500) if e["event_id"] == f"b3-{tag}"])

            prow = {"id": f"p-{tag}", "created_at": "2026-09-04T10:00:00Z", "entity": "sol",
                    "title": "rotate key", "severity": "HIGH", "status": "approved",
                    "decided_at": "2026-09-04T11:00:00Z"}
            ing2 = ingest(audit=[], missions=[], proposals=[prow], deployment=[], security=[])
            got = {e["event_id"]: e for e in tl.query(limit=500) if tag in e["event_id"]}
            ck("[db] a REAL proposal row ingests to stored events that trace back to that row",
               ing2["inserted"] == 2
               and got[f"proposal:p-{tag}:PROPOSED"]["refs"][0]["proposal_id"] == f"p-{tag}"
               and _utc(got[f"proposal:p-{tag}:APPROVED"]["ts"]) == _utc("2026-09-04T11:00:00Z"))
            ck("[db] ingest reports proposals CONNECTED and still 0 candidates from the sources that were empty",
               [s for s in ing2["sources"] if s["source"] == "holding.proposals_store"]
               == [{"source": "holding.proposals_store", "status": "CONNECTED", "events": 2}])
            ck("[db] view() surfaces those stored events with the store CONNECTED",
               tl.view(limit=500)["store"] == "CONNECTED"
               and any(e["event_id"] == f"proposal:p-{tag}:APPROVED" for e in tl.view(limit=500)["events"]))
        finally:
            _clean()
        # Condition: a test run can never leave an event behind for the dashboard to render as real.
        ck("[db] the suite's own events are GONE from the store afterwards (no test event can appear live)",
           _tagged() == [] and not [e for e in tl.view(limit=500)["events"] if tag in e["event_id"]])

        # Condition: ordering is a TOTAL order — two reads of an unchanged store agree, even when a whole
        # batch shares one ts and therefore one created_at.
        same_ts = [_ev(event_id=f"ord{i}-{tag}", ts="2026-09-04T09:00:00Z") for i in range(3)]
        try:
            tl.append_many(same_ts)
            o1 = [e["event_id"] for e in tl.query(limit=500) if f"-{tag}" in e["event_id"]]
            o2 = [e["event_id"] for e in tl.query(limit=500) if f"-{tag}" in e["event_id"]]
            ck("[db] identical-ts events order deterministically and identically across reads",
               o1 == o2 and o1 == sorted([f"ord{i}-{tag}" for i in range(3)], reverse=True))
        finally:
            _clean()
    else:
        ck("[db] Postgres smoke skipped (no DB reachable) — pure logic fully covered above", True)

    # ── condition: an UNREACHABLE store is reported UNAVAILABLE, never as a healthy empty timeline ──
    # This is the fact the panel's third state depends on. Mutation-testing found nothing asserted it:
    # hardcoding store="CONNECTED" left the whole suite green while the dashboard would have rendered an
    # unreachable store as "nothing happened". Simulate the outage at the one seam every read goes through.
    _real_session = tl.SessionLocal

    def _dead_session(*a, **k):
        raise RuntimeError("simulated: Postgres unreachable")

    try:
        tl.SessionLocal = _dead_session
        _down = tl.view(limit=50)
        ck("an unreachable store reports store=UNAVAILABLE with no events (never a healthy empty panel)",
           _down["store"] == "UNAVAILABLE" and _down["events"] == [])
        ck("...and query() still fails soft to [] rather than raising", tl.query(limit=50) == [])
        ck("...and append/append_many fail soft, storing nothing", tl.append(_ev(event_id="down-1"))["ok"] is False
           and tl.append_many([_ev(event_id="down-2")])["ok"] is False)
    finally:
        tl.SessionLocal = _real_session
    ck("the store is reachable again after the simulated outage (the probe restored the real seam)",
       tl.view(limit=1)["store"] in ("CONNECTED", "UNAVAILABLE") and tl.SessionLocal is _real_session)

    # ── the deployment event must name the environment it actually observed ───────────────────────
    # Found on the hosted staging run: the event read "in production" while running on staging, because
    # the live call site omitted env and the keyword defaulted to "production". No test caught it because
    # every existing test injected its own env. These pin BOTH the call site and the default.
    class _S:
        APP_ENV = "staging"
    _ev_stg = tl.events_from_deployment("abc123abc123", features=[], env=_S.APP_ENV)
    ck("deployment event names the environment it was given",
       _ev_stg and "in staging" in _ev_stg[0]["summary"] and "production" not in _ev_stg[0]["summary"])
    ck("an OMITTED env is UNKNOWN, never silently 'production'",
       "in UNKNOWN" in tl.events_from_deployment("abc123abc123", features=[])[0]["summary"])
    _src = (pathlib.Path(__file__).resolve().parent / "timeline.py").read_text()
    ck("the live _resolve_deployment passes APP_ENV through rather than relying on the default",
       "features=feature_registry(settings), env=env" in _src and 'env: str = "production"' not in _src)

    # ── the deployment event's feature count must not depend on request ORDER ────────────────────
    # Observed on staging: two rows for the same 19-feature build, one recording 19 and one recording 0,
    # differing only in which route was served first. The row is durable and first-write-wins, so an
    # order-dependent count is a permanently wrong record. Presence is a property of the build.
    _regA = [{"feature_id": f"f{i}", "deployed": True} for i in range(19)]
    _regB = [{"feature_id": f"f{i}", "deployed": False} for i in range(19)]   # same build, not yet verified
    _a = tl.events_from_deployment("aaa111aaa111", features=_regA, env="staging")[0]
    _b = tl.events_from_deployment("aaa111aaa111", features=_regB, env="staging")[0]
    ck("features_present is identical whether or not the rows are marked deployed",
       _a["refs"][0]["features_present"] == _b["refs"][0]["features_present"] == 19)
    ck("...and the two renderings of the same build produce the SAME event_id and summary",
       _a["event_id"] == _b["event_id"] and _a["summary"] == _b["summary"])
    _rt2 = (pathlib.Path(__file__).resolve().parents[2] / "routers" / "admin_holding.py").read_text()
    ck("hosted-route evidence is recorded by a ROUTER dependency, so every route establishes it",
       "Depends(_record_hosted_route)" in _rt2 and "def _record_hosted_route" in _rt2)
    ck("...and the marker is called ONLY from that dependency, never from an individual handler",
       _rt2.count("mark_hosted_route_served(") == 1
       and "mark_hosted_route_served(request.url.path)" in _rt2)

    # ── boundary: every surface that can expose the timeline is owner-gated ───────────────────────
    # The two readers are GET /admin/holding/timeline and the /view payload's timeline section. Neither
    # carries its own dependency: the gate is declared ONCE on the router, which is what makes it hold
    # for a route someone adds later. Assert the declaration, not one endpoint, so removing it is caught.
    _rt = (pathlib.Path(__file__).resolve().parents[2] / "routers" / "admin_holding.py").read_text()
    ck("timeline surfaces are owner-gated at the ROUTER, so no endpoint on it can be added ungated",
       "dependencies=[Depends(require_kai_ultra)" in _rt        # the gate is FIRST in the dependency list
       and '@router.get("/timeline")' in _rt and '@router.get("/view")' in _rt)
    ck("the timeline query is ordered by a TOTAL order (ts, insertion time, then the primary key)",
       "ORDER BY ts DESC, created_at DESC, event_id DESC" in
       (pathlib.Path(__file__).resolve().parent / "timeline.py").read_text())

    n = len(res); ok = sum(res)
    print(f"\nHOLDING TIMELINE TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
