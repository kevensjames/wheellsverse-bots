"""Deployed-KAI side of hosted A2 (LIMITED_A2_HOSTED). KAI is the GOVERNOR: it never runs git. It
(1) ENQUEUES a governed coding job onto the EXISTING worker plane (worker_jobs) only when staging + all
three brakes + the grant allow it, and (2) independently VERIFIES the evidence the worker returns before
setting the authoritative decision. The colima worker-runner is the EXECUTION RESOURCE — it runs the whole
A2Framework.prepare() (real worktree + real git diff + shared gates + independent test + independent
review) on the host where .git lives. A2 never merges/deploys.

Pure + injectable (enqueue_fn / settings passed in) so the gate + verify logic is a plain python3 test.
"""
from __future__ import annotations


# The A2 job payload carries ONLY non-authoritative routing fields. The grant, the authority denylist, and
# the diff ceilings are SERVER-SIDE invariants (A2Framework) — they must NEVER travel in the task dict, or
# a job author could weaken them. That omission is the security property, not a gap.
def a2_coding_task(*, mission_id: str, base_sha: str, company_id: str = "wheellsverse",
                   suite_id: str = "holding_self_model", repo_slug: str = "", goal: str = "",
                   base_dir: str = "/tmp/kai-a2") -> dict:
    return {"a2_action_type": "EDIT_CODE_IN_WORKTREE", "capability": "coding", "company_id": company_id,
            "environment": "staging", "task_id": mission_id, "base_sha": base_sha, "base_dir": base_dir,
            "suite_id": suite_id, "repo_slug": repo_slug, "goal": goal}


def brakes_all_on(settings) -> bool:
    """§31 — A2 requires ALL of: capability execution (#1), autonomy (#2), A2 (#3). Any false → no dispatch."""
    return (bool(getattr(settings, "KAI_CAPABILITY_EXECUTION_ENABLED", False))
            and bool(getattr(settings, "HOLDING_AUTONOMY_ENABLED", False))
            and bool(getattr(settings, "KAI_A2_EXECUTION_ENABLED", False)))


def enqueue_a2_coding_job(*, mission_id: str, base_sha: str, settings, company_id: str = "wheellsverse",
                          company_autonomy: dict | None = None, suite_id: str = "holding_self_model",
                          repo_slug: str = "", goal: str = "", proposal_id: int = 0,
                          grant_registry=None, enqueue_fn=None, stop_store=None) -> dict:
    """§30/§31/§34/§7 — enqueue a coding job ONLY when: APP_ENV=staging AND all three brakes on AND §97
    STOP is not engaged AND the company kill-switch is on AND base_sha is present AND
    (EDIT_CODE_IN_WORKTREE,coding,company,staging) is granted. Otherwise REFUSE (no job, a typed reason) —
    0 A2 writes. Deployed KAI is the only enqueuer. Returns {enqueued, reason, job, task}."""
    from app.services.holding.a2_wiring import build_a2_grant_registry
    from app.services.holding.brakes import stop_state
    reg = grant_registry or build_a2_grant_registry()
    if str(getattr(settings, "APP_ENV", "")).lower() != "staging":       # §30 staging-only
        return {"enqueued": False, "reason": "STAGING_ONLY"}
    if not brakes_all_on(settings):                                      # §31 three brakes
        return {"enqueued": False, "reason": "BRAKE_OFF"}
    stopped = stop_state(stop_store)                                     # §97 STOP: STOP_ENGAGED | STOP_UNREADABLE (fail closed)
    if stopped:
        return {"enqueued": False, "reason": stopped}
    if (company_autonomy or {}).get(company_id, True) is False:          # §31 company kill-switch
        return {"enqueued": False, "reason": "COMPANY_AUTONOMY_OFF"}
    if not base_sha:                                                     # §7 base_sha required (fail closed)
        return {"enqueued": False, "reason": "BLOCKED_BASE_SHA"}
    if not reg.is_granted("EDIT_CODE_IN_WORKTREE", "coding", company_id, "staging"):   # §34 grant
        return {"enqueued": False, "reason": "NOT_GRANTED"}
    task = a2_coding_task(mission_id=mission_id, base_sha=base_sha, company_id=company_id,
                          suite_id=suite_id, repo_slug=repo_slug, goal=goal)
    enq = enqueue_fn or _default_enqueue
    job = enq(proposal_id, "coding", task, idempotency_key=f"a2:{mission_id}", mission_id=f"a2:{mission_id}")
    return {"enqueued": bool(job), "reason": "OK" if job else "ENQUEUE_FAILED", "job": job, "task": task}


def _default_enqueue(proposal_id, worker, task, *, idempotency_key, mission_id):
    from app.services.holding import worker_jobs
    return worker_jobs.enqueue(proposal_id, worker, task, idempotency_key=idempotency_key, mission_id=mission_id)


# a worker-reported NON-ready governed outcome KAI trusts a fail-closed worker verdict for (carried through)
_NON_READY = frozenset({"OWNER_REQUIRED", "BLOCKED", "NEEDS_CERTIFICATION", "WORKTREE"})


def _safe_int(v) -> int:
    """Coerce an attacker-controlled numeric field defensively — a non-numeric value counts as 'unknown/
    over the cap' so it can never buy a permissive outcome (fail closed)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 10 ** 9   # non-numeric → treat as over any cap (fail closed, never permissive)


def verify_a2_evidence(evidence: dict, *, expected_company: str = "wheellsverse",
                       expected_base_sha: str = "") -> dict:
    """§26/§41 — deployed KAI independently decides the authoritative outcome from the worker's returned
    A2Prepared evidence. KAI cannot re-derive the git diff (no .git in the container), so it re-runs the
    PURE shared gates on the REPORTED changed-file set (defense-in-depth on top of the worker's own
    real-git gate) and rejects any evidence that (a) claims merged/deployed, (b) mismatches the company or
    base_sha KAI enqueued, or (c) reports a diff that hits a shared-gate class while claiming READY. It
    never lets the worker set the final state unchecked. Returns {decision, reasons}. HONEST LIMIT: a fully
    forged 'clean' evidence from a compromised runner is only backstopped by owner review before merge —
    the runner is KAI's owner-authed worker, and A2 is prepare-only (nothing is released without the owner).
    """
    from app.services.holding.a2_framework import (touches_authority, is_dependency_file, is_binary_file,
                                                   MAX_FILES_CHANGED, MAX_TOTAL_DIFF_LINES)
    ev = evidence or {}
    files = list(ev.get("files_changed") or [])
    worker_state = ev.get("state")
    reported_sha = str(ev.get("starting_sha") or (ev.get("evidence") or {}).get("starting_sha") or "")
    # 1. hard invariants — a forged READY that claims release, or a swapped company/base, is REJECTED
    if ev.get("merged") or ev.get("deployed"):
        return {"decision": "REJECTED", "reasons": ["merged/deployed must be False (A2 never releases)"]}
    if expected_company and str(ev.get("company_id", expected_company)) != expected_company:
        return {"decision": "REJECTED", "reasons": [f"company mismatch: {ev.get('company_id')}"]}
    if expected_base_sha and reported_sha and reported_sha != expected_base_sha:
        return {"decision": "REJECTED", "reasons": ["base_sha mismatch (repo/base substitution)"]}
    # 2. re-run the pure shared gates on the reported diff (defense in depth) — a gate hit is OWNER_REQUIRED
    if (touches_authority(files) or [f for f in files if is_dependency_file(f) or is_binary_file(f)]
            or len(files) > MAX_FILES_CHANGED or _safe_int(ev.get("total_diff_lines", 0)) > MAX_TOTAL_DIFF_LINES):
        return {"decision": "OWNER_REQUIRED", "reasons": ["reported diff hits a shared-gate class"]}
    # 3. a worker-reported NON-ready governed state is carried through (trust a fail-closed worker verdict)
    if worker_state in _NON_READY:
        return {"decision": worker_state, "reasons": [(ev.get("reason") or worker_state)[:100]]}
    # 4. a CLAIMED READY must independently re-verify: files present, certified, reviewed by a DIFFERENT id
    if (worker_state == "READY_FOR_REVIEW" and ev.get("ready_for_review") and ev.get("certified")
            and files and ev.get("reviewer") and ev.get("reviewer") != ev.get("worker")):
        return {"decision": "READY_FOR_REVIEW", "reasons": ["independently re-verified"]}
    # 5. anything else — a claimed READY that fails re-verification (empty/uncertified/self-reviewed) — is a
    #    forge or a no-op → BLOCKED (never silently READY).
    return {"decision": "BLOCKED", "reasons": ["claimed READY failed independent re-verification"]}
