"""Executor (Wave 3) — turn an APPROVED proposal into a real, read-only, evidence-producing action.

The final step of the loop, and the most-gated. Hard invariants:
  · BOUND TO APPROVAL — only a proposal the OWNER already approved can execute (status must be
    'approved'); a 'proposed'/'rejected' proposal is refused. An agent never approves its own action.
  · READ-ONLY — every action re-probes live state or gathers context. No writes, no money, no deploys,
    no unbounded calls. Consistent with the collectors that already run in App B.
  · AUDITED + RECORDED — evidence is stored and the proposal moves to 'executed'.
Untrusted / agentic execution is NOT here — that stays in the isolated, certified workers (browser +
GitHub), a separate surface. This executor runs only the trusted deterministic read-only actions the
Holding OS itself owns.
"""
from __future__ import annotations


def _verify(proposal):
    entity = proposal.get("entity")
    ev = {"kind": "VERIFY", "entity": entity}
    try:
        from app.services.holding.entity_status import collect_live_entity_status
        ev["live"] = collect_live_entity_status().get(entity, {"note": "no live probe for this entity"})
    except Exception as e:
        ev["live_error"] = str(e)[:80]
    try:
        from app.services.holding import registry as reg
        e = reg.get(entity) if entity else None
        if e:
            ev["registry"] = {"status": e.operational_status, "confidence": e.confidence.value,
                              "source": e.data_source, "repo": e.repository}
    except Exception as ex:
        ev["registry_error"] = str(ex)[:80]
    return ev


def _investigate(_proposal):
    ev = {"kind": "INVESTIGATE"}
    try:
        from app.services.holding.signals import collect_live_signals
        failing = [s for s in collect_live_signals() if not s.get("ok")]
        ev["failing_signals"] = failing or "all signals OK"
    except Exception as e:
        ev["error"] = str(e)[:80]
    return ev


def _request_info(_proposal):
    try:
        from app.services.holding import registry as reg
        return {"kind": "REQUEST_INFO", "fields_awaiting_confirmation": reg.needs_confirmation()}
    except Exception as e:
        return {"kind": "REQUEST_INFO", "error": str(e)[:80]}


def _review(proposal):
    return {"kind": "REVIEW", "note": "read-only review — summarized context, recommend next step",
            "context": {"title": proposal.get("title"), "severity": proposal.get("severity"),
                        "source": proposal.get("source_key")}}


_RUNNERS = {"VERIFY": _verify, "INVESTIGATE": _investigate, "REQUEST_INFO": _request_info, "REVIEW": _review}


def _github_slug(entity: str) -> str:
    """Resolve an entity to a GitHub owner/repo for a read-only worker task."""
    return "kevensjames/chenara" if entity == "nurtelle" else "kevensjames/wheellsverse-bots"


def _dispatch_worker(proposal_id: int, worker: str, entity) -> dict:
    """Enqueue a READ-ONLY isolated-worker job for the approved proposal (executed by the colima
    worker-runner, not prod). Returns the dispatch evidence."""
    if worker == "github":
        task = {"action": "list_prs", "repo": _github_slug(entity or "")}
    elif worker == "browser":
        task = {"action": "read_page", "url": "https://app.wheellsverse.com",
                "allowed_domains": ["app.wheellsverse.com"]}
    else:
        return {"kind": "DISPATCH_SKIPPED", "reason": f"unknown worker '{worker}'"}
    from app.services.holding import worker_jobs
    job_id = worker_jobs.enqueue(proposal_id, worker, task)
    return {"kind": "DISPATCHED", "worker": worker, "job_id": job_id, "task": task,
            "note": "queued for the isolated worker-runner (read-only, runs in an isolated container)"}


def execute_approved(proposal_id: int) -> dict:
    """Execute an APPROVED proposal's read-only action → record evidence → mark 'executed'.
    Refuses anything not already approved. Never raises fatally."""
    try:
        from app.services.holding import proposals_store
        p = proposals_store.get(proposal_id)
        if not p:
            return {"executed": False, "reason": "no such proposal"}
        if p.get("status") != "approved":
            return {"executed": False,
                    "reason": f"proposal is '{p.get('status')}', not 'approved' — execution requires a prior approval"}
        action = p.get("action") or {}
        ac = action.get("action_class")
        worker = action.get("worker")
        if worker:
            # dispatch to an isolated worker (executed off-prod by the colima worker-runner)
            evidence = _dispatch_worker(proposal_id, worker, p.get("entity"))
        else:
            evidence = _RUNNERS.get(ac, _review)(p)
        evidence["read_only"] = True
        ok = proposals_store.record_execution(proposal_id, evidence)
        if not ok:
            return {"executed": False, "reason": "state changed — proposal no longer approved"}
        return {"executed": True, "action_class": ac, "evidence": evidence,
                "note": "read-only action executed; evidence recorded. No writes, money, or deploys."}
    except Exception as e:
        return {"executed": False, "reason": f"execute error: {str(e)[:100]}"}
