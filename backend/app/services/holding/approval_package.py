"""§60 generalized approval evidence package — the ONE shape for EVERY approval type.

An "approval evidence package" is the full owner-review dossier KAI assembles BEFORE a consequential
action runs: what it is, why, the evidence, the exact change, how it was tested + independently reviewed,
how to roll back, in what environment, and the exact authority being requested. Until now only
``self_improvement.owner_review_package`` produced this (for code fixes). This module lifts that shape
into a single reusable builder so a finance / deploy / merge / generic-proposal approval yields the SAME
canonical §60 fields — no fourth parallel package shape.

Canonical §60 field set (always present):
    objective, problem, evidence, proposed_action, risk, diff_artifact, tests,
    independent_review, rollback, environment, authority_requested

Plus fixed governance markers: approval_type, authority=OWNER_REQUIRED, decision=REQUIRE_APPROVAL,
provenance=REAL. The package carries NO authority to execute — it is descriptive only.

Zero-fabrication (§0 #16-19): nothing here invents a test result, a review, or a rollback that did not
happen. A field with no real value disclaims honestly (NOT_APPLICABLE / NOT_PERFORMED / REVERSIBLE_UNKNOWN
/ UNAVAILABLE) rather than fabricating reassurance. Pure/DB-free — a plain ``python3`` self-test.
"""
from __future__ import annotations

# What is honestly said when a field has no real backing value — never a fabricated positive.
_NO_DIFF = "NONE — non-code approval (no diff/artifact)"
_NO_TESTS = "NOT_APPLICABLE — no automated tests for this approval type"
_NO_REVIEW = "NOT_PERFORMED — no independent review recorded"
_REVERSIBLE_UNKNOWN = "REVERSIBLE_UNKNOWN — owner must confirm a rollback plan before this runs"


def build_approval_package(*, approval_type: str, objective: str, problem: str = "",
                           evidence: list | None = None, proposed_action: str = "",
                           risk: str = "UNKNOWN", diff_artifact: str = "", tests: str = "",
                           independent_review: str = "", rollback: str = "",
                           environment: str = "production", authority_requested: str = "") -> dict:
    """Build the canonical §60 approval evidence package for ANY approval type. Descriptive only —
    carries NO execute authority (authority=OWNER_REQUIRED, decision=REQUIRE_APPROVAL). Empty fields
    disclaim honestly; nothing is fabricated. Deterministic + pure."""
    return {
        "approval_type": approval_type or "generic",
        "objective": objective or "UNSPECIFIED",
        "problem": problem or "UNAVAILABLE",
        "evidence": list(evidence or []),
        "proposed_action": proposed_action or objective or "UNSPECIFIED",
        "risk": risk or "UNKNOWN",
        "diff_artifact": diff_artifact or _NO_DIFF,
        "tests": tests or _NO_TESTS,
        "independent_review": independent_review or _NO_REVIEW,
        "rollback": rollback or _REVERSIBLE_UNKNOWN,
        "environment": environment or "UNKNOWN",
        "authority_requested": authority_requested or f"OWNER approval of a {approval_type or 'generic'} action",
        # fixed governance markers — a package never authorizes; the owner does, via the durable gate.
        "authority": "OWNER_REQUIRED",
        "decision": "REQUIRE_APPROVAL",
        "provenance": "REAL",
    }


def from_proposal(proposal: dict, *, approval_type: str | None = None,
                  environment: str = "production") -> dict:
    """Adapt a generic ``proposals_store`` row (finance / deploy / merge / any proposal) to the canonical
    §60 package. The row's ``action`` JSON carries the descriptive fields; missing fields disclaim, never
    guess. Use this for every NON-self-improvement approval — one shape, no fork. Pure."""
    p = proposal or {}
    act = p.get("action") or {}
    reversible = act.get("reversible")
    rollback = act.get("rollback") or ("reversible — action can be undone" if reversible is True else "")
    return build_approval_package(
        approval_type=approval_type or act.get("action_class") or "proposal",
        objective=p.get("title") or act.get("proposed_action") or "",
        problem=act.get("problem") or p.get("source_key") or "",
        evidence=p.get("evidence") or act.get("evidence") or [],
        proposed_action=act.get("proposed_action") or p.get("title") or "",
        risk=act.get("risk") or p.get("severity") or "UNKNOWN",
        diff_artifact=act.get("diff") or act.get("artifact") or "",
        tests=act.get("tests") or "",
        independent_review=act.get("independent_review") or "",
        rollback=rollback,
        environment=environment,
        authority_requested=act.get("authority_requested")
        or f"OWNER approval of {p.get('title') or (approval_type or 'this proposal')}",
    )


# canonical §60 field set — the invariant the generalization guarantees for every approval type.
REQUIRED_FIELDS = frozenset({
    "objective", "problem", "evidence", "proposed_action", "risk", "diff_artifact", "tests",
    "independent_review", "rollback", "environment", "authority_requested",
})


if __name__ == "__main__":
    from app.services.holding.test_approval_package import run
    raise SystemExit(0 if run() else 1)
