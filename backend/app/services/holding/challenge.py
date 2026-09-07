"""§88 Challenge mode — independently RE-EVALUATE a recommendation/problem with a SEPARATE reviewer that
is briefed to REFUTE it. The acceptance rules here are deterministic and versioned; NO LLM runs inside
this module — the ``reviewer`` seam is injectable (a different certified model, a human, a test stub) and
its output is ACCEPTED or REJECTED by rule, never by trust.

Sycophancy is refused mechanically: an AGREE that merely restates the claim (or its rationale), or
carries no independent sourced check, is REJECTED_SYCOPHANTIC. Restatement is measured as COVERAGE OF THE
CLAIM (|argument ∩ claim| / |claim|) — padding a verbatim restatement with filler words cannot dilute it.
An empty or under-3-word argument is REJECTED_MALFORMED (nothing to evaluate). A REFUTE with no sourced
counter-evidence is an opinion, not a challenge, and is downgraded to INSUFFICIENT_EVIDENCE. A number in
the reviewer's argument that appears in none of its evidence (nor the claim) is an unsourced number ->
REJECTED_UNSOURCED (§0 #16-19). A check/counter item vouches only if it carries a REF in the known
vocabulary — a ``reader:key`` source (repo_inspect:…, kpi_history:…, audit:<event_id>), an id key from
``explain._REF_KEYS`` (audit_id/event_id/job_id/mission_id/…) or a URL; a free string ('trust me') is a note.

The reviewer≠author rule is ``capability.coding.assert_independent_reviewer`` — the SAME rule that
certifies worker results (no second rule; it also refuses an empty/None author or reviewer and compares
identities normalized). Evidence quality is ``health_score.evidence_quality`` (§58) — the same grader the
rest of the holding OS uses. The challenge is ADVISORY: KAI (the caller) stays the final governed
coordinator (§165); this module executes nothing (§79 bounded: one reviewer call).
"""
from __future__ import annotations

import re

from app.services.capability.coding import assert_independent_reviewer
from app.services.holding.explain import _ref_of
from app.services.holding.health_score import evidence_quality, _source_of

CHALLENGE_RULES_VERSION = "1.1.0"

STANCES = ("AGREE", "REFUTE", "INSUFFICIENT_EVIDENCE")
# outcomes
REFUTED = "REFUTED"
UPHELD = "UPHELD"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
REJECTED_SYCOPHANTIC = "REJECTED_SYCOPHANTIC"
REJECTED_MALFORMED = "REJECTED_MALFORMED"
REJECTED_UNSOURCED = "REJECTED_UNSOURCED"

# An AGREE argument covering this fraction of the claim's words is a restatement, not a review.
SYCOPHANCY_OVERLAP = 0.6
MIN_ARGUMENT_WORDS = 3
_WORD = re.compile(r"[a-z0-9]{3,}")
_TOKEN = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"(?<![a-z§#\w])\d+(?:[.,]\d+)?%?")
# A ref in the known vocabulary: ``reader:key`` (the shape the holding readers emit) or a URL.
_REF = re.compile(r"^(?:[a-z][a-z0-9_]*:\S+|https?://\S+)$", re.I)


def refute_brief(recommendation: dict) -> dict:
    """The contract handed to the reviewer seam: it is told to REFUTE, and told what an acceptable
    answer must contain. Pure; deterministic."""
    return {
        "instruction": ("Your job is to REFUTE this recommendation. Find the strongest counter-evidence. "
                        "Restating or praising the claim is not a review. If you cannot refute it, say "
                        "AGREE only with the INDEPENDENT checks you ran (each with a source), or say "
                        "INSUFFICIENT_EVIDENCE. Never introduce a number you cannot source."),
        "claim": str(recommendation.get("claim", "")),
        "rationale": str(recommendation.get("rationale", "")),
        "evidence": list(recommendation.get("evidence") or []),
        "required_output": {"stance": list(STANCES), "argument": "str",
                            "counter_evidence": "[{source, ...}]", "checks": "[{source, ...}]"},
        "rules_version": CHALLENGE_RULES_VERSION,
    }


def _words(s) -> set:
    return set(_WORD.findall(str(s or "").lower()))


def _coverage(argument: str, claim: str) -> float:
    """Fraction of the CLAIM's words that the argument repeats (|arg ∩ claim| / |claim|). Measured over the
    claim, not the argument, so padding a verbatim restatement with filler words cannot dilute it."""
    wa, wb = _words(argument), _words(claim)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wb)


def _sourced(items) -> list:
    """Only items carrying a REF in the known vocabulary vouch: the source ``health_score._source_of`` reads
    (source/source_type/source_key/evidence_ref, event_id→audit:, state→drift:) or an id key from
    ``explain._REF_KEYS`` (audit_id/job_id/mission_id/…), and the ref must be ``reader:key``-shaped or a URL.
    Placeholders (UNKNOWN/UNAVAILABLE) and free strings ('trust me') are notes, not sources."""
    out = []
    for e in items or []:
        if isinstance(e, dict):
            ref = _source_of(e) or _ref_of(e)          # the two existing readers, composed — no third one
            if ref and _REF.match(str(ref)):
                out.append(e)
    return out


def _unsourced_numbers(argument: str, *texts) -> list:
    pool = " ".join(str(t) for t in texts)
    have = set(_NUMBER.findall(pool.lower()))
    return sorted({n for n in _NUMBER.findall(str(argument or "").lower()) if n not in have})


def challenge(recommendation: dict, *, reviewer, reviewer_id: str) -> dict:
    """Re-evaluate ``recommendation`` ({id, author, claim, rationale?, evidence[]}) through an INDEPENDENT
    ``reviewer(brief) -> {stance, argument, counter_evidence[], checks[]}``. Raises ValueError if
    reviewer_id is the author (same rule as certify_worker_result). Returns an advisory verdict dict."""
    author = str(recommendation.get("author") or "")
    assert_independent_reviewer(author, reviewer_id)
    brief = refute_brief(recommendation)
    raw = reviewer(brief)
    base = {"version": CHALLENGE_RULES_VERSION, "recommendation_id": recommendation.get("id"),
            "author": author, "reviewer": reviewer_id, "final_decision_by": "KAI coordinator (caller)",
            "advisory": True}
    def _malformed(flag: str, argument: str = "") -> dict:
        return {**base, "outcome": REJECTED_MALFORMED, "flags": [flag], "argument": argument,
                "counter_evidence": [], "checks": [], "counter_evidence_quality": "LOW"}
    if not isinstance(raw, dict) or raw.get("stance") not in STANCES:
        return _malformed("stance missing or not in STANCES")
    stance = raw["stance"]
    argument = str(raw.get("argument") or "")
    if len(_TOKEN.findall(argument.lower())) < MIN_ARGUMENT_WORDS:
        return _malformed(f"argument empty or under {MIN_ARGUMENT_WORDS} words — nothing to evaluate", argument)
    counter = _sourced(raw.get("counter_evidence"))
    checks = _sourced(raw.get("checks"))
    flags = []
    # only SOURCED reviewer items may vouch for a number (an unsourced note is not a source)
    unsourced = _unsourced_numbers(argument, brief["claim"], brief["rationale"], brief["evidence"],
                                   counter, checks)
    if unsourced:
        flags.append(f"argument introduces numbers found in no evidence: {unsourced}")
        outcome = REJECTED_UNSOURCED
    elif stance == "REFUTE":
        if counter:
            outcome = REFUTED
        else:
            flags.append("REFUTE without sourced counter-evidence is an opinion, not a challenge")
            outcome = INSUFFICIENT_EVIDENCE
    elif stance == "AGREE":
        # restating EITHER the claim or its rationale is a restatement; take the larger coverage
        ov = max(_coverage(argument, brief["claim"]), _coverage(argument, brief["rationale"]))
        if not checks:
            flags.append("AGREE without an independent sourced check")
            outcome = REJECTED_SYCOPHANTIC
        elif ov >= SYCOPHANCY_OVERLAP:
            flags.append(f"AGREE argument restates the claim (coverage {ov:.2f} >= {SYCOPHANCY_OVERLAP})")
            outcome = REJECTED_SYCOPHANTIC
        else:
            outcome = UPHELD
    else:
        outcome = INSUFFICIENT_EVIDENCE
    return {**base, "outcome": outcome, "stance": stance, "argument": argument, "flags": flags,
            "counter_evidence": counter, "checks": checks,
            "counter_evidence_quality": evidence_quality(counter if stance == "REFUTE" else checks)}


if __name__ == "__main__":
    from app.services.holding.test_challenge import run
    run()
