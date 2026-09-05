"""§154 audit experience — "What did you do today?" reconstructed ONLY from recorded history.

Sources are the five REAL feeds ``eval_harness.collect_sources`` already reads (no new collector, §79):
governance ``audit_log`` (observations / safe actions / approvals / failures / deployments),
``mission`` headers (missions — normalized through the SAME ``timeline.events_from_missions`` adapter),
``worker_jobs`` (worker executions + results), ``cycle_store`` runs (bounded cycles) and
``proposals_store`` (owner approvals/rejections). Every line cites its record id; nothing is narrated
from memory and NO hidden reasoning is exposed (the §61 ``_contains_cot`` boundary is asserted on the
output). An empty day is an honest "nothing recorded", never a filled-in story.

Pure/deterministic over injected record lists; ``collect()`` is the only storage touch. Testable as a
plain ``python3`` script (mirrors test_registry.py).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.holding.eval_harness import _ts
from app.services.holding.mission import _job_verified
from app.services.holding.timeline import _contains_cot, events_from_missions

WHAT_I_DID_VERSION = "1.0.0"
CATEGORIES = ("observation", "mission", "safe_action", "worker_execution", "approval", "result",
              "failure", "deployment")
_DEPLOY_WORDS = ("deploy", "release", "rollout")                      # token STEMS (deployment, released, rollouts)
_OBSERVE_VERBS = frozenset(("read", "list", "get", "observe", "inspect", "status", "view", "query"))   # whole tokens
_PROPOSAL_DECIDED = {"approved": "approved", "rejected": "rejected", "executed": "approved (executed)"}


def _day_of(ts_str) -> str | None:
    d = _ts(ts_str)
    return d.astimezone(timezone.utc).date().isoformat() if d else None    # the day is UTC, not the record's offset


def _entry(ts, category, summary, source, ref) -> dict:
    return {"ts": ts or "UNAVAILABLE", "category": category, "summary": summary, "source": source, "ref": ref}


def _from_audit(records: list) -> list:
    out = []
    for r in records:
        rid, action, scope = r.get("id"), r.get("action") or "action", r.get("scope") or "holding"
        if not rid:
            continue
        ok = r.get("success") is True
        verbs = set(re.findall(r"[a-z]+", str(action).lower()))    # tokens, so 'get' never hides in 'budget'
        if not ok:
            cat, txt = "failure", f"{action} ({scope}) FAILED" + (f": {r['error']}" if r.get("error") else "")
        elif r.get("destructive") is True and r.get("approved") is not True:
            # success=True here: it RAN without approval — say so first, never soften it into a deploy/observation
            cat, txt = "failure", f"destructive {action} ({scope}) ran WITHOUT owner approval — security violation (§0 #11)"
        elif any(v.startswith(w) for v in verbs for w in _DEPLOY_WORDS):
            cat, txt = "deployment", f"{action} ({scope}) succeeded"
        elif verbs & _OBSERVE_VERBS:            # a read is an observation whether or not it was pre-approved
            cat, txt = "observation", f"{action} ({scope})"
        elif r.get("approved") is True:
            cat, txt = "approval", f"owner-approved {action} ({scope}) → success"
        else:
            cat, txt = "safe_action", f"{action} ({scope}) by {r.get('actor') or 'UNKNOWN'}"
        out.append(_entry(r.get("ts"), cat, txt, "governance.audit_log", f"audit_id:{rid}"))
    return out


def _from_jobs(jobs: list) -> list:
    out = []
    for j in jobs:
        jid, status = j.get("id"), j.get("status")
        if jid is None:
            continue
        w = j.get("claimed_by") or j.get("worker") or "UNKNOWN"
        if status in ("claimed", "running"):
            out.append(_entry(j.get("created_at"), "worker_execution", f"job {jid} {status} by {w}",
                              "holding.worker_jobs", f"job_id:{jid}"))
        elif status == "succeeded":
            verified = _job_verified(j)      # the ONE §26 rule: succeeded AND verified evidence
            out.append(_entry(j.get("done_at") or j.get("created_at"), "result",
                              f"job {jid} by {w} succeeded — evidence {'VERIFIED' if verified else 'UNVERIFIED (code-only / none)'}",
                              "holding.worker_jobs", f"job_id:{jid}"))
        elif status in ("failed", "expired", "cancelled"):
            out.append(_entry(j.get("done_at") or j.get("created_at"), "failure", f"job {jid} by {w} {status}",
                              "holding.worker_jobs", f"job_id:{jid}"))
        else:
            out.append(_entry(j.get("created_at"), "worker_execution", f"job {jid} {status or 'queued'} for {w}",
                              "holding.worker_jobs", f"job_id:{jid}"))
    return out


def _from_cycles(cycles: list) -> list:
    out = []
    for c in cycles:
        cid = c.get("cycle_id")
        if not cid:
            continue
        # DbCycleStore.list_runs returns the STORED manual_cycle.normalize_record shape; a raw CycleRecord is the
        # fallback (eval_harness._failed_in reads the same pair). A count that is on neither is UNAVAILABLE, never 0.
        def g(stored, raw):
            v = c.get(stored, c.get(raw))
            return v if v is not None else "UNAVAILABLE"
        out.append(_entry(c.get("completed_at") or c.get("started_at"), "observation",
                          f"bounded holding cycle {cid}: status {g('status', 'verdict')}, "
                          f"{g('companies_reviewed', 'companies_reviewed')} companies reviewed, "
                          f"{g('material_changes_count', 'material_changes')} material change(s), "
                          f"{g('auto_actions_executed', 'tasks_executed')} executed, "
                          f"{g('auto_actions_failed', 'tasks_failed')} failed, "
                          f"{g('owner_actions_created', 'owner_actions_created')} owner action(s) queued",
                          "holding.cycle_store", f"cycle_id:{cid}"))
    return out


def _from_proposals(props: list) -> list:
    out = []
    for p in props:
        pid, st = p.get("id"), p.get("status")
        if pid is None:
            continue
        if st in _PROPOSAL_DECIDED:
            out.append(_entry(p.get("decided_at") or p.get("created_at"), "approval",
                              f"owner {_PROPOSAL_DECIDED[st]} proposal {pid}: {p.get('title') or p.get('source_key') or ''}".rstrip(": "),
                              "holding.proposals_store", f"proposal_id:{pid}"))
        else:
            out.append(_entry(p.get("created_at"), "safe_action",
                              f"prepared proposal {pid} ({st or 'proposed'}, nothing executed): {p.get('title') or ''}".rstrip(": "),
                              "holding.proposals_store", f"proposal_id:{pid}"))
    return out


def _from_missions(headers: list) -> list:
    return [_entry(e["ts"], "mission", e["summary"], e["source"], f"mission_id:{e['refs'][0]['mission_id']}")
            for e in events_from_missions(headers)]


def reconstruct(*, audit=None, jobs=None, missions=None, cycles=None, proposals=None, day: str = "") -> dict:
    """§154: the day's activity from records ONLY. ``day`` = 'YYYY-MM-DD' (UTC); '' = every day in the
    records. ``None`` for a feed = source not connected (reported, not guessed). Newest-first."""
    src = {"audit": audit, "jobs": jobs, "missions": missions, "cycles": cycles, "proposals": proposals}
    lists = {k: [r for r in (v or []) if isinstance(r, dict)] for k, v in src.items()}
    entries = (_from_audit(lists["audit"]) + _from_jobs(lists["jobs"]) + _from_missions(lists["missions"])
               + _from_cycles(lists["cycles"]) + _from_proposals(lists["proposals"]))
    if day:
        entries = [e for e in entries if _day_of(e["ts"]) == day]
    entries.sort(key=lambda e: (_ts(e["ts"]) is None, -( _ts(e["ts"]).timestamp() if _ts(e["ts"]) else 0), e["ref"]))
    counts = {c: sum(1 for e in entries if e["category"] == c) for c in CATEGORIES}
    nothing = not entries
    out = {"version": WHAT_I_DID_VERSION, "day": day or "ALL_RECORDED",
           "sources": {k: ("NOT_CONNECTED" if v is None else "CONNECTED") for k, v in src.items()},
           "nothing_recorded": nothing,
           "summary": (f"nothing recorded for {day or 'any day'} — no observation, mission, action, worker execution, "
                       f"approval, result, failure or deployment is on record" if nothing
                       else ", ".join(f"{n} {c}" for c, n in counts.items() if n)),
           "counts": counts, "entries": entries,
           "reconstructed_from": "audit_log + worker_jobs + mission + cycle_store + proposals_store records only",
           "hidden_reasoning_exposed": False}
    assert not _contains_cot(out)        # §61/§154 boundary — the answer never carries hidden reasoning
    return out


def collect(limit: int = 500) -> dict:
    """The five real feeds, via the ONE existing reader (eval_harness.collect_sources)."""
    from app.services.holding.eval_harness import collect_sources
    return collect_sources(limit)


def today(now: str = "") -> dict:
    """Live 'what did you do today?' — records only; ``now`` ISO overrides the clock (tests)."""
    day =(_day_of(now) if now else None) or datetime.now(timezone.utc).date().isoformat()
    return reconstruct(**collect(), day=day)


if __name__ == "__main__":
    from app.services.holding.test_what_i_did import run
    raise SystemExit(0 if run() else 1)
