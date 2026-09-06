"""§154 'What did you do today?' — records-only reconstruction guard. Zero-framework (mirrors
test_registry.py). Fixtures are in the EXACT shapes the five real readers emit. Run (from backend/):
    python3 -m app.services.holding.test_what_i_did
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import what_i_did as wid                     # noqa: E402
from app.services.holding.what_i_did import reconstruct, CATEGORIES, WHAT_I_DID_VERSION   # noqa: E402
from app.services.holding import mission as mission_mod                # noqa: E402
from app.services.holding.timeline import _contains_cot                # noqa: E402

# ── fixtures in the emitted shapes ────────────────────────────────────────────────────────────────────
AUDIT = [   # governance.audit_log.record_action shape (id = uuid hex)
    {"id": "a1", "ts": "2026-09-01T10:00:00+00:00", "action": "read", "scope": "holding", "actor": "kai",
     "destructive": False, "approved": True, "success": True},
    {"id": "a2", "ts": "2026-09-01T10:01:00+00:00", "action": "patch", "scope": "repo", "actor": "kai",
     "destructive": False, "approved": False, "success": True},
    {"id": "a3", "ts": "2026-09-01T10:02:00+00:00", "action": "merge", "scope": "repo", "actor": "worker-x",
     "destructive": True, "approved": False, "success": False, "error": "refused by the gate"},
    {"id": "a4", "ts": "2026-09-01T10:03:00+00:00", "action": "deploy", "scope": "staging", "actor": "owner",
     "destructive": False, "approved": True, "success": True},
    {"id": "a5", "ts": "2026-09-01T10:04:00+00:00", "action": "rotate_key", "scope": "kai", "actor": "owner",
     "destructive": False, "approved": True, "success": True},
    {"id": "a6", "ts": "2026-09-02T01:00:00+00:00", "action": "list", "scope": "holding", "actor": "kai",
     "destructive": False, "approved": True, "success": True},                       # the NEXT day
    {"ts": "2026-09-01T10:05:00+00:00", "action": "no_id", "success": True},           # no id -> not citable -> skipped
]
JOBS = [    # holding.worker_jobs.list_jobs shape
    {"id": 1, "created_at": "2026-09-01 09:00:00+00:00", "done_at": "2026-09-01 09:10:00+00:00", "worker": "codex",
     "claimed_by": "codex:host1", "status": "succeeded", "evidence": {"verified": True}},
    {"id": 2, "created_at": "2026-09-01 09:00:00+00:00", "done_at": "2026-09-01 09:20:00+00:00", "worker": "codex",
     "claimed_by": None, "status": "succeeded", "evidence": {"branch": "kai/x"}},           # code-only 'done'
    {"id": 3, "created_at": "2026-09-01 09:00:00+00:00", "done_at": "2026-09-01 09:30:00+00:00", "worker": "cline",
     "claimed_by": "cline", "status": "failed", "evidence": {"error": "tests"}},
    {"id": 4, "created_at": "2026-09-01 09:40:00+00:00", "done_at": None, "worker": "cline", "claimed_by": "cline",
     "status": "running", "evidence": None},
    {"id": 5, "created_at": "2026-09-01 09:50:00+00:00", "done_at": None, "worker": "codex", "claimed_by": None,
     "status": "queued", "evidence": None},
]
CYCLES = [  # DbCycleStore.list_runs -> the STORED manual_cycle.normalize_record shape
    {"cycle_id": "cy-1", "status": "OK", "started_at": "2026-09-01T07:50:00+00:00", "completed_at": "2026-09-01T08:00:00+00:00",
     "companies_reviewed": 3, "material_changes_count": 1, "auto_actions_executed": 2, "auto_actions_failed": 2,
     "owner_actions_created": 1},
    {"cycle_id": "cy-2", "verdict": "NO_MATERIAL_CHANGE", "completed_at": "2026-09-01T08:30:00+00:00",    # raw CycleRecord
     "companies_reviewed": 2, "material_changes": 0, "tasks_executed": 0, "tasks_failed": 1, "owner_actions_created": 0},
    {"cycle_id": "cy-3", "completed_at": "2026-09-01T08:45:00+00:00"},                                   # no counts on record
]
MISSIONS = [  # holding.mission._row_to_header shape
    {"mission_id": "ms-1", "created_at": "2026-09-01 07:00:00+00:00", "completed_at": "2026-09-01 08:00:00+00:00",
     "cancelled": False, "objective": "certify SOL staging"},
    {"mission_id": "ms-2", "created_at": "2026-09-01 07:00:00+00:00", "completed_at": "", "cancelled": False},
    {"mission_id": "ms-3", "created_at": "2026-09-01 07:30:00+00:00", "completed_at": "", "cancelled": True,
     "updated_at": "2026-09-01 07:45:00+00:00"},
]
PROPOSALS = [  # holding.proposals_store.list_proposals shape
    {"id": 10, "created_at": "2026-09-01 06:00:00+00:00", "status": "approved", "decided_at": "2026-09-01 06:30:00+00:00",
     "title": "Rotate the API key", "source_key": "risk:kai:api-key"},
    {"id": 11, "created_at": "2026-09-01 06:00:00+00:00", "status": "rejected", "decided_at": "2026-09-01 06:40:00+00:00",
     "title": "Retire the old bot", "thoughts": "secret plan"},                        # a stray hidden-reasoning field
    {"id": 12, "created_at": "2026-09-01 06:00:00+00:00", "status": "proposed", "decided_at": None, "title": "Re-verify Nurtelle"},
]
ALL = dict(audit=AUDIT, jobs=JOBS, missions=MISSIONS, cycles=CYCLES, proposals=PROPOSALS)


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    def by_ref(out, ref):
        return next(e for e in out["entries"] if e["ref"] == ref)

    all_days = reconstruct(**ALL)
    day1 = reconstruct(**ALL, day="2026-09-01")

    # ── deterministic + versioned ─────────────────────────────────────────────────────────────────
    ck("same records -> byte-identical reconstruction, versioned",
       reconstruct(**ALL) == all_days and all_days["version"] == WHAT_I_DID_VERSION == "1.0.0")

    # ── an empty day is an honest 'nothing recorded', never a narrative ──────────────────────────
    none = reconstruct()
    empty = reconstruct(audit=[], jobs=[], missions=[], cycles=[], proposals=[])
    ck("no source connected -> history UNAVAILABLE naming every source, NOT 'nothing recorded' (an unread store has recorded nothing? unknown)",
       none["nothing_recorded"] is False and none["entries"] == [] and set(none["sources"].values()) == {"NOT_CONNECTED"}
       and none["summary"].startswith("history UNAVAILABLE (sources not connected: ")
       and all(s in none["summary"] for s in ("audit", "jobs", "missions", "cycles", "proposals"))
       and "nothing recorded" not in none["summary"] and all(v == 0 for v in none["counts"].values()))
    part = reconstruct(audit=AUDIT, jobs=None, missions=None, cycles=None, proposals=None)
    ck("partly connected -> what IS on record is listed AND the unread sources are named; never 'nothing recorded'",
       part["nothing_recorded"] is False and len(part["entries"]) == 6
       and part["summary"].startswith("history UNAVAILABLE (sources not connected: jobs, missions, cycles, proposals)")
       and "; on record from the connected sources: " in part["summary"] and "observation" in part["summary"]
       and "nothing recorded" not in part["summary"])
    ck("connected-but-empty -> still 'nothing recorded' (sources CONNECTED) — no story is filled in",
       empty["nothing_recorded"] is True and set(empty["sources"].values()) == {"CONNECTED"} and empty["entries"] == [])
    ck("a day with no records -> 'nothing recorded for <day>' — the summary names the day, invents nothing",
       reconstruct(**ALL, day="2026-08-30")["nothing_recorded"] is True
       and "nothing recorded for 2026-08-30" in reconstruct(**ALL, day="2026-08-30")["summary"])

    # ── every entry is a cited record from one of the five feeds ─────────────────────────────────
    feeds = {"governance.audit_log", "holding.worker_jobs", "holding.mission", "holding.cycle_store", "holding.proposals_store"}
    ids = ({f"audit_id:{r['id']}" for r in AUDIT if r.get("id")} | {f"job_id:{j['id']}" for j in JOBS}
           | {f"mission_id:{m['mission_id']}" for m in MISSIONS} | {f"cycle_id:{c['cycle_id']}" for c in CYCLES}
           | {f"proposal_id:{p['id']}" for p in PROPOSALS})
    ck("every entry names one of the five real feeds and cites a record id that exists in the input",
       all(e["source"] in feeds and e["ref"] in ids and e["category"] in CATEGORIES for e in all_days["entries"]))
    ck("an audit record without an id is not citable -> skipped (never narrated)",
       not any("no_id" in e["summary"] for e in all_days["entries"]) and sum(1 for e in all_days["entries"] if e["source"] == "governance.audit_log") == 6)

    # ── audit categorization ──────────────────────────────────────────────────────────────────────
    cat = {r: by_ref(all_days, r)["category"] for r in ("audit_id:a1", "audit_id:a2", "audit_id:a3", "audit_id:a4", "audit_id:a5")}
    ck("audit: read->observation, patch->safe_action, failed merge->failure(+error), deploy->deployment, approved->approval",
       cat == {"audit_id:a1": "observation", "audit_id:a2": "safe_action", "audit_id:a3": "failure",
               "audit_id:a4": "deployment", "audit_id:a5": "approval"}
       and "refused by the gate" in by_ref(all_days, "audit_id:a3")["summary"]
       and "by kai" in by_ref(all_days, "audit_id:a2")["summary"])
    viol = reconstruct(audit=[{"id": "v1", "ts": "2026-09-01T11:00:00+00:00", "action": "drop_table", "scope": "db",
                               "destructive": True, "approved": False, "success": True}])
    ck("a destructive action that RAN without approval is reported as a security violation, never softened",
       viol["entries"][0]["category"] == "failure" and "WITHOUT owner approval" in viol["entries"][0]["summary"])
    # 'approved' is a CALLER kwarg (governance/actions.py approved=body.approved; actor defaults to 'operator'):
    # only an owner PRINCIPAL ('owner:<source>', as brakes._mutate writes) is narrated as owner-approved.
    flag = reconstruct(audit=[{"id": "f1", "ts": "2026-09-01T11:00:00+00:00", "action": "rotate_key", "scope": "kai",
                               "actor": "operator", "destructive": False, "approved": True, "success": True},
                              {"id": "f2", "ts": "2026-09-01T11:01:00+00:00", "action": "rotate_key", "scope": "kai",
                               "actor": "owner:api_key", "destructive": False, "approved": True, "success": True}])
    f1, f2 = by_ref(flag, "audit_id:f1")["summary"], by_ref(flag, "audit_id:f2")["summary"]
    ck("approved=True by actor 'operator' -> 'rotate_key (kai) by operator, approved flag set by caller', NOT 'owner-approved'",
       "owner-approved" not in f1 and f1.startswith("rotate_key (kai) by operator, approved flag set by caller")
       and by_ref(flag, "audit_id:f1")["category"] == "approval")
    ck("approved=True by an owner principal 'owner:api_key' -> 'owner-approved ... by owner:api_key'",
       f2.startswith("owner-approved rotate_key (kai) by owner:api_key"))
    ck("fixture a5 (actor 'owner' — a bare word, not a principal) is narrated as the caller's flag, not an owner approval",
       "approved flag set by caller" in by_ref(all_days, "audit_id:a5")["summary"]
       and "owner-approved" not in by_ref(all_days, "audit_id:a5")["summary"])

    # ── worker jobs: the ONE §26 verified rule ────────────────────────────────────────────────────
    ck("§26 verified rule is mission._job_verified itself (no second copy)", wid._job_verified is mission_mod._job_verified)
    ck("job 1 (verified evidence) -> result VERIFIED by its claimant; job 2 (code-only) -> result UNVERIFIED",
       by_ref(all_days, "job_id:1")["category"] == "result" and "evidence VERIFIED" in by_ref(all_days, "job_id:1")["summary"]
       and "by codex:host1" in by_ref(all_days, "job_id:1")["summary"]
       and "UNVERIFIED" in by_ref(all_days, "job_id:2")["summary"])
    ck("job 3 failed -> failure; job 4 running -> worker_execution; job 5 queued -> worker_execution",
       by_ref(all_days, "job_id:3")["category"] == "failure" and by_ref(all_days, "job_id:4")["category"] == "worker_execution"
       and "running by cline" in by_ref(all_days, "job_id:4")["summary"] and "queued" in by_ref(all_days, "job_id:5")["summary"])

    # ── cycles: the STORED shape is read (no fabricated zeros) ───────────────────────────────────
    s1, s2, s3 = (by_ref(all_days, f"cycle_id:cy-{i}")["summary"] for i in (1, 2, 3))
    ck("stored normalize_record shape: status OK, 3 companies, 1 material change, 2 executed, 2 failed, 1 owner action",
       "status OK" in s1 and "3 companies reviewed" in s1 and "1 material change" in s1 and "2 executed, 2 failed" in s1
       and "1 owner action" in s1)
    ck("raw CycleRecord shape is the fallback (verdict / tasks_failed): NO_MATERIAL_CHANGE, 0 executed, 1 failed",
       "status NO_MATERIAL_CHANGE" in s2 and "0 executed, 1 failed" in s2)
    ck("a count that is on neither shape is UNAVAILABLE — never a default 0",
       "UNAVAILABLE executed, UNAVAILABLE failed" in s3 and "status UNAVAILABLE" in s3 and " 0 " not in s3)

    # ── missions via the SAME timeline adapter; proposals as owner decisions ──────────────────────
    ms = {e["ref"]: e for e in all_days["entries"] if e["category"] == "mission"}
    ck("missions: COMPLETE / CREATED / CANCELLED transitions from headers via timeline.events_from_missions",
       set(ms) == {"mission_id:ms-1", "mission_id:ms-2", "mission_id:ms-3"}
       and "mission COMPLETE: certify SOL staging" in ms["mission_id:ms-1"]["summary"]
       and "CREATED" in ms["mission_id:ms-2"]["summary"] and "CANCELLED" in ms["mission_id:ms-3"]["summary"]
       and all(e["source"] == "holding.mission" for e in ms.values()))
    ck("proposals: approved/rejected -> owner approval entries; proposed -> safe_action 'nothing executed'",
       by_ref(all_days, "proposal_id:10")["category"] == "approval" and "owner approved proposal 10: Rotate the API key" in by_ref(all_days, "proposal_id:10")["summary"]
       and "owner rejected" in by_ref(all_days, "proposal_id:11")["summary"]
       and by_ref(all_days, "proposal_id:12")["category"] == "safe_action" and "nothing executed" in by_ref(all_days, "proposal_id:12")["summary"])

    # ── day filter is UTC; ordering newest-first; counts partition ───────────────────────────────
    ck("day filter keeps only that UTC day's records (a6 on 09-02 excluded; only a6 on 09-02)",
       "audit_id:a6" not in {e["ref"] for e in day1["entries"]}
       and [e["ref"] for e in reconstruct(**ALL, day="2026-09-02")["entries"]] == ["audit_id:a6"])
    tz = reconstruct(audit=[{"id": "tz", "ts": "2026-09-02T01:00:00+03:00", "action": "read", "success": True}], day="2026-09-01")
    ck("the day is UTC, not the record's local offset (+03:00 01:00 on 09-02 is 22:00Z on 09-01)",
       [e["ref"] for e in tz["entries"]] == ["audit_id:tz"])
    stamps = [wid._ts(e["ts"]) for e in all_days["entries"]]
    ck("entries are newest-first", stamps == sorted(stamps, reverse=True))
    ck("counts partition the entries; summary lists only non-zero categories",
       sum(all_days["counts"].values()) == len(all_days["entries"]) and set(all_days["counts"]) == set(CATEGORIES)
       and all(f"{n} {c}" in all_days["summary"] for c, n in all_days["counts"].items() if n)
       and all(f" {c}" not in all_days["summary"] for c, n in all_days["counts"].items() if not n))
    ck("day '' = every recorded day, labelled ALL_RECORDED", all_days["day"] == "ALL_RECORDED" and day1["day"] == "2026-09-01")

    # ── §61/§154 boundary: no hidden reasoning, in or out ─────────────────────────────────────────
    ck("a hidden-reasoning field on an input record never reaches the answer",
       not _contains_cot(all_days) and "secret plan" not in json.dumps(all_days) and all_days["hidden_reasoning_exposed"] is False)
    _cc = wid._contains_cot
    try:
        wid._contains_cot = lambda o: True               # simulate the scan finding hidden reasoning in the OUTPUT
        try:
            reconstruct(**ALL); leaked = "returned"
        except ValueError:
            leaked = "raised"
        except AssertionError:
            leaked = "assert"
    finally:
        wid._contains_cot = _cc
    ck("hidden_reasoning_exposed is the SCAN result and a positive scan RAISES ValueError (no stripped assert, nothing returned)",
       leaked == "raised" and "assert " not in Path(wid.__file__).read_text())
    ck("non-dict junk rows are ignored, not crashed on", reconstruct(audit=[None, "x", 3, AUDIT[0]])["counts"]["observation"] == 1)

    # ── live: records only, through the ONE existing reader ───────────────────────────────────────
    src = Path(wid.__file__).read_text()
    ck("collect() is eval_harness.collect_sources (the five real readers; no new collector, §79)",
       "from app.services.holding.eval_harness import collect_sources" in src and "reconstruct(**collect()" in src)
    ck("reconstruct() reads no clock and runs no model; the clock is touched only by today()",
       src.count("datetime.now") == 1 and src.index("datetime.now") > src.index("def today")
       and all(t not in src for t in ("openai", "ollama", "httpx", "requests", "capability.brain", "nai_brain")))
    live = wid.today(now="2026-09-01T12:00:00+00:00")
    ck("today(): live reconstruction over the real feeds (honest: cited entries, 'nothing recorded', or history UNAVAILABLE)",
       live["day"] == "2026-09-01" and live["version"] == WHAT_I_DID_VERSION
       and (live["nothing_recorded"] or "NOT_CONNECTED" in live["sources"].values()
            or all(e["source"] in feeds for e in live["entries"])))
    import app.database as _db
    _sl = _db.SessionLocal
    def _down(*a, **k): raise RuntimeError("db down")
    try:
        _db.SessionLocal = _down
        down = wid.today(now="2026-09-01T12:00:00+00:00")
    finally:
        _db.SessionLocal = _sl
    ck("DB DOWN: today() says history UNAVAILABLE naming the 4 DB feeds — never 'nothing recorded' while the store is unreachable",
       all(down["sources"][k] == "NOT_CONNECTED" for k in ("jobs", "missions", "cycles", "proposals"))
       and "UNAVAILABLE" in down["summary"] and "nothing recorded" not in down["summary"] and down["nothing_recorded"] is False)

    n = len(res); ok = sum(res)
    print(f"\nWHAT I DID (§154) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
