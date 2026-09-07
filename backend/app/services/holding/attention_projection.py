"""ONE executive attention projection (CEO truth gate, Phase 0).

THE DEFECT THIS REMOVES. Production reported `focus_state: MONITORING` while the same payload carried
one HIGH problem and one owner-required problem. Worker activity was idle, and the header inherited
the worker's calm. But an operating surface answers "does this need me?", not "is a worker busy?" —
those are different questions with different answers, and only one of them belongs in the header.

Every surface that makes an attention claim — header, Today For You, Current Attention, KAI Brief, the
owner-action count, the problem stream, priorities, proposals, missions, and KAI's arrival message —
must derive from THIS function. A second, independently computed calm state is how a dashboard ends up
reassuring an operator on one line and alarming them on the next.

Pure. No I/O. Plain python3 self-test.
"""
from __future__ import annotations

# Executive states, ordered by escalation. Never collapse these into a boolean.
CALM = "NOTHING_REQUIRES_YOU"
MONITORING = "MONITORING"
ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
DECISION_REQUIRED = "DECISION_REQUIRED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

_RANK = {CALM: 0, MONITORING: 1, INSUFFICIENT_EVIDENCE: 2, ATTENTION_REQUIRED: 3, DECISION_REQUIRED: 4}

ACTIONABLE_SEVERITIES = frozenset({"HIGH", "CRITICAL"})


def _sev(p) -> str:
    return str((p or {}).get("severity") or "").strip().upper()


def project(*, problems=None, owner_decisions=None, proposals=None, missions=None,
            sources_missing=None, sources_stale=None, worker_state: str = "") -> dict:
    """Derive the ONE executive attention state, with the reasons that produced it.

    worker_state is accepted and deliberately NOT used to lower the result. A quiet worker cannot make
    an owner-required problem stop requiring the owner; it is reported alongside so the surface can say
    "workers idle, but you are needed" instead of choosing one and hiding the other."""
    problems = list(problems or [])
    owner_decisions = list(owner_decisions or [])
    proposals = list(proposals or [])
    missions = list(missions or [])
    sources_missing = list(sources_missing or [])
    sources_stale = list(sources_stale or [])

    owner_required = [p for p in problems if (p or {}).get("owner_required") is True]
    actionable = [p for p in problems if _sev(p) in ACTIONABLE_SEVERITIES]
    open_decisions = [d for d in owner_decisions if str((d or {}).get("status", "open")).lower()
                      in ("open", "pending", "awaiting_owner", "ready_for_review")]
    blocked = [m for m in missions if str((m or {}).get("state", "")).upper() in ("BLOCKED", "OVERDUE")]

    reasons: list[dict] = []
    state = CALM

    def escalate(to: str, why: str, evidence) -> None:
        nonlocal state
        reasons.append({"state": to, "reason": why, "evidence": evidence})
        if _RANK[to] > _RANK[state]:
            state = to

    if sources_missing or sources_stale:
        escalate(INSUFFICIENT_EVIDENCE,
                 "required sources are missing or stale, so an all-clear cannot be established",
                 {"missing": sources_missing, "stale": sources_stale})
    if actionable:
        escalate(ATTENTION_REQUIRED, f"{len(actionable)} actionable HIGH/CRITICAL problem(s)",
                 [p.get("problem_id") or p.get("root_signature") for p in actionable])
    if owner_required:
        escalate(ATTENTION_REQUIRED, f"{len(owner_required)} problem(s) require the owner",
                 [p.get("problem_id") or p.get("root_signature") for p in owner_required])
    if blocked:
        escalate(ATTENTION_REQUIRED, f"{len(blocked)} mission(s) blocked or overdue",
                 [m.get("id") or m.get("mission_id") for m in blocked])
    if open_decisions:
        escalate(DECISION_REQUIRED, f"{len(open_decisions)} open owner decision(s)",
                 [d.get("id") for d in open_decisions])
    if state == CALM and (problems or proposals):
        escalate(MONITORING, "items are being tracked but none needs the owner now",
                 {"problems": len(problems), "proposals": len(proposals)})

    needs_owner = state in (ATTENTION_REQUIRED, DECISION_REQUIRED)
    return {
        "state": state,
        "needs_owner": needs_owner,
        # The ONE sentence every surface must use. No surface composes its own.
        "headline": _headline(state, len(owner_required), len(actionable), len(open_decisions)),
        "counts": {"problems": len(problems), "actionable": len(actionable),
                   "owner_required": len(owner_required), "open_decisions": len(open_decisions),
                   "blocked_missions": len(blocked)},
        "reasons": reasons,
        # Reported, never used to soften the state above.
        "worker_state": str(worker_state or "UNKNOWN"),
        "worker_note": ("worker activity is separate from executive attention; an idle worker does not "
                        "mean nothing needs you"),
    }


def _headline(state, n_owner, n_action, n_dec) -> str:
    if state == DECISION_REQUIRED:
        return f"{n_dec} decision{'' if n_dec == 1 else 's'} need{'s' if n_dec == 1 else ''} you now."
    if state == ATTENTION_REQUIRED:
        bits = []
        if n_owner:
            bits.append(f"{n_owner} problem{'' if n_owner == 1 else 's'} require"
                        f"{'s' if n_owner == 1 else ''} the owner")
        if n_action:
            bits.append(f"{n_action} actionable HIGH/CRITICAL")
        return (" and ".join(bits) or "something requires attention") + ". This is not an all-clear."
    if state == INSUFFICIENT_EVIDENCE:
        return "Required sources are missing or stale — no all-clear can be given."
    if state == MONITORING:
        return "Tracked and quiet: nothing needs you right now."
    return "Nothing requires you right now."


def assert_consistent(projection: dict, *, claim: str) -> tuple[bool, str]:
    """Reject a surface claim that contradicts the projection. The invariant, in one place.

    `claim` is the reassuring text a surface wants to show. If the projection says the owner is needed,
    no surface may say otherwise — regardless of which store it read."""
    c = (claim or "").strip().lower()
    reassuring = any(k in c for k in (
        "nothing requires", "nothing needs", "no action required", "all clear", "all-clear",
        "no material action", "nothing to do"))
    # An all-clear is also impossible on incomplete evidence: "nothing is wrong" and "I cannot see"
    # are different statements, and only the first is a reassurance the surface is entitled to make.
    blocked = projection.get("needs_owner") or projection.get("state") == INSUFFICIENT_EVIDENCE
    if reassuring and blocked:
        return False, (f"claim '{claim}' contradicts attention state {projection['state']}: "
                       f"{projection['headline']}")
    return True, "OK"


# ── self-test ─────────────────────────────────────────────────────────────────────────────────────
_res: list = []


def ck(name, ok):
    _res.append((name, bool(ok)))


def demo() -> None:
    OWNER = {"problem_id": "p1", "severity": "HIGH", "owner_required": True}
    HIGH = {"problem_id": "p2", "severity": "HIGH", "owner_required": False}
    LOW = {"problem_id": "p3", "severity": "LOW", "owner_required": False}

    # THE PRODUCTION SNAPSHOT: workers idle, one HIGH, one owner-required.
    live = project(problems=[OWNER] + [LOW] * 7 + [HIGH], worker_state="IDLE")
    ck("the live production shape yields ATTENTION_REQUIRED, not MONITORING",
       live["state"] == ATTENTION_REQUIRED)
    ck("...and needs_owner is true", live["needs_owner"] is True)
    ck("...while the idle worker state is still REPORTED, not hidden", live["worker_state"] == "IDLE")
    ck("...and an idle worker does not lower the state",
       project(problems=[OWNER], worker_state="IDLE")["state"] == ATTENTION_REQUIRED)

    # The five invariants the brief requires.
    ck("INV1: 'nothing requires attention' is rejected while an owner-required item exists",
       assert_consistent(project(problems=[OWNER]), claim="Nothing requires you right now.")[0] is False)
    ck("INV1b: ...and while an actionable HIGH exists",
       assert_consistent(project(problems=[HIGH]), claim="nothing needs attention")[0] is False)
    ck("INV2: 'nothing needs a decision' is rejected while an open owner decision exists",
       assert_consistent(project(owner_decisions=[{"id": 1, "status": "open"}]),
                         claim="No action required right now.")[0] is False)
    ck("INV3: 'no material action' is rejected while a mission is blocked/overdue",
       assert_consistent(project(missions=[{"id": "m1", "state": "BLOCKED"}]),
                         claim="no material action")[0] is False)
    ck("INV4: 'all clear' is rejected while required sources are missing or stale",
       assert_consistent(project(sources_missing=["finance"]), claim="all clear")[0] is False)
    ck("INV5: counts come from the canonical items, so a summary cannot drift",
       live["counts"]["owner_required"] == 1 and live["counts"]["actionable"] == 2
       and live["counts"]["problems"] == 9)

    # Escalation ordering.
    ck("an open decision outranks a mere problem",
       project(problems=[OWNER], owner_decisions=[{"id": 1}])["state"] == DECISION_REQUIRED)
    ck("missing sources alone are INSUFFICIENT_EVIDENCE, never CALM",
       project(sources_missing=["x"])["state"] == INSUFFICIENT_EVIDENCE)
    ck("genuinely nothing -> CALM", project()["state"] == CALM)
    ck("...and CALM permits a reassuring claim",
       assert_consistent(project(), claim="Nothing requires you right now.")[0] is True)
    ck("tracked but quiet -> MONITORING, not CALM",
       project(problems=[LOW])["state"] == MONITORING)
    ck("...and MONITORING still permits a calm claim (nothing is actionable)",
       assert_consistent(project(problems=[LOW]), claim="nothing needs you")[0] is True)

    # The headline is the single sentence every surface reuses.
    ck("the headline names the real cause", "require" in live["headline"] and "all-clear" in live["headline"])
    ck("every escalation records its reason and evidence",
       all("reason" in r and "evidence" in r for r in live["reasons"]))

    bad = [n for n, ok in _res if not ok]
    for n in bad:
        print("  FAIL:", n)
    print(f"ATTENTION PROJECTION TESTS: {len(_res) - len(bad)}/{len(_res)} — {'PASS' if not bad else 'FAIL'}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    demo()
