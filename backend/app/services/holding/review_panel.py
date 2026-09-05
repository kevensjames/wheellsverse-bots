"""§89 Multi-agent review panel — planner / domain-expert / security-reviewer / independent-verifier
roles over a plan or a worker result. This EXTENDS the certified ``capability/coding`` seam, it does not
fork it: the identity rule is ``assert_independent_reviewer`` (the same one ``certify_worker_result``
enforces) and, for a WorkerResult subject, the INDEPENDENT_VERIFIER role's approval IS
``certify_worker_result`` (tests must have run and passed) — a panel cannot be softer than the seam.

Hard rules (all deterministic, no LLM inside this module — each role's reviewer is an injectable seam):
  • no role may hold the author's identity (§0 #11 / §89: nobody approves their own output) -> ValueError.
    Identities are compared as ``assert_independent_reviewer`` normalizes them (strip + casefold), so
    'Codex ' / 'CODEX' are the author 'codex'; an empty/None identity anywhere -> ValueError (fail closed)
  • the INDEPENDENT_VERIFIER identity must differ from every other panelist (it is the independent one)
  • a missing required role -> INCOMPLETE (never a partial approval)
  • fewer than MIN_DISTINCT_REVIEWERS (3) distinct identities across the 4 roles -> INCOMPLETE with reason:
    one identity wearing three hats is not a panel (the verifier is already distinct by rule, so the other
    three roles must be held by at least two identities). Nobody is invoked.
  • an APPROVE with no sourced evidence (§58 evidence_quality LOW) is downgraded to NEEDS_CHANGES
  • aggregate: any REJECT -> REJECTED; any NEEDS_CHANGES -> NEEDS_CHANGES; all APPROVE -> APPROVED
  • a WorkerResult is left certified ONLY when the aggregate outcome is APPROVED (which implies the verifier
    said APPROVE and the seam certified it); any other outcome leaves ``certified=False`` — a rejected panel
    never leaves a certified record behind (a2_framework gates READY_FOR_REVIEW on that flag)
The panel is ADVISORY: KAI (the caller) remains the final governed coordinator (§165); nothing here
executes, merges, or deploys. Bounded: exactly one call per role (§79).
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from app.services.capability.coding import WorkerResult, assert_independent_reviewer, certify_worker_result
from app.services.holding.health_score import evidence_quality

PANEL_RULES_VERSION = "1.1.0"
ROLES = ("PLANNER", "DOMAIN_EXPERT", "SECURITY_REVIEWER", "INDEPENDENT_VERIFIER")
VERDICTS = ("APPROVE", "REJECT", "NEEDS_CHANGES")
COORDINATOR = "KAI coordinator (caller)"
MIN_DISTINCT_REVIEWERS = 3      # across the 4 roles; the verifier is distinct by rule, the other 3 need >= 2 identities


def _subject_view(subject) -> dict:
    if isinstance(subject, WorkerResult):
        return {"kind": "worker_result", **asdict(subject)}
    if is_dataclass(subject):
        return {"kind": "plan", **asdict(subject)}
    return {"kind": "plan", **dict(subject or {})}


def convene(subject, *, author: str = "", panel: dict, tests_ok: bool | None = None) -> dict:
    """Run the panel. ``panel`` = {role: (reviewer_id, fn)} with ``fn(subject_view, role) ->
    {verdict, findings[], evidence[]}``. ``author`` is the plan's author; for a WorkerResult the author is
    always ``result.worker`` (the record is the truth, a caller cannot relabel it). ``tests_ok`` feeds the
    verifier's certify_worker_result call (defaults to tests_failed == 0)."""
    if isinstance(subject, WorkerResult):
        author = subject.worker
    author = str(author or "")
    if not author.strip():
        raise ValueError("panel needs the author's identity to enforce reviewer≠author (§89) — refused")
    ids = {role: str(spec[0] or "") for role, spec in (panel or {}).items() if role in ROLES}
    # the ONE rule (raises on self-review / unknown identity) also hands back each identity as it compared
    # it (strip + casefold); the panel compares and counts identities with THAT normalization, no second one
    norm = {role: assert_independent_reviewer(author, rid)[1] for role, rid in ids.items()}
    ver = norm.get("INDEPENDENT_VERIFIER")
    if ver and any(n == ver for role, n in norm.items() if role != "INDEPENDENT_VERIFIER"):
        raise ValueError("the INDEPENDENT_VERIFIER must not also hold another panel role (§89)")
    distinct = len(set(norm.values()))
    base = {"version": PANEL_RULES_VERSION, "author": author, "coordinator": COORDINATOR,
            "final_decision_by": COORDINATOR, "advisory": True, "panel": ids, "distinct_reviewers": distinct}
    missing = [r for r in ROLES if r not in ids]
    if missing:
        return {**base, "outcome": "INCOMPLETE", "missing_roles": missing,
                "reason": f"missing roles: {missing}", "reviews": []}
    if distinct < MIN_DISTINCT_REVIEWERS:
        return {**base, "outcome": "INCOMPLETE", "missing_roles": [],
                "reason": f"only {distinct} distinct reviewer identities across {len(ROLES)} roles; "
                          f">= {MIN_DISTINCT_REVIEWERS} required — one identity wearing several hats is not a panel",
                "reviews": []}

    view = _subject_view(subject)
    reviews = []
    for role in ROLES:
        rid, fn = ids[role], panel[role][1]
        raw = fn(view, role)
        raw = raw if isinstance(raw, dict) else {}
        verdict = raw.get("verdict")
        findings = [str(f) for f in (raw.get("findings") or [])]
        evidence = [e for e in (raw.get("evidence") or []) if isinstance(e, dict)]
        flags = []
        if verdict not in VERDICTS:
            verdict, flags = "REJECT", ["malformed verdict"]
        if role == "INDEPENDENT_VERIFIER" and isinstance(subject, WorkerResult):
            ok = (subject.tests_failed == 0) if tests_ok is None else bool(tests_ok)
            certify_worker_result(subject, reviewed_by=rid, tests_ok=ok)   # the existing seam, unchanged
            if verdict == "APPROVE" and not subject.certified:
                verdict, flags = "REJECT", flags + ["certify_worker_result refused: tests failed or none ran"]
        q = evidence_quality(evidence)
        if verdict == "APPROVE" and q == "LOW":
            verdict, flags = "NEEDS_CHANGES", flags + ["APPROVE carried no sourced evidence (§58 LOW)"]
        reviews.append({"role": role, "reviewer": rid, "verdict": verdict, "findings": findings,
                        "evidence": evidence, "evidence_quality": q, "flags": flags})
    verdicts = [r["verdict"] for r in reviews]
    outcome = ("REJECTED" if "REJECT" in verdicts else
               "NEEDS_CHANGES" if "NEEDS_CHANGES" in verdicts else "APPROVED")
    certified = None
    if isinstance(subject, WorkerResult):
        # a panel that did not APPROVE leaves NOTHING certified — the seam's tests-based flag stands only
        # under an APPROVED aggregate (APPROVED ⇒ the verifier said APPROVE); ``reviewed`` stays the truth
        subject.certified = bool(subject.certified and outcome == "APPROVED")
        certified = subject.certified
    return {**base, "outcome": outcome, "reviews": reviews, "certified": certified}


if __name__ == "__main__":
    from app.services.holding.test_review_panel import run
    run()
