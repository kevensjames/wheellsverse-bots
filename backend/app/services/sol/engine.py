"""Sol ROSCA engine — the pure state machine over the ledger.

NO Dwolla calls here. The engine decides *what* should happen (who owes what,
who is delinquent, who gets paid, what advances); the audited admin endpoints do
the actual money movement and feed transfer results back via the mark_* fns.
That split keeps the whole rotation logic unit-testable with zero mocking.

ROSCA rules (from Sol's spec / frontend FAQ):
  * N members each contribute a fixed amount per cycle; one member receives the
    pool each cycle, in join_order (position 1 paid cycle 1, etc.).
  * A member whose contribution fails after MAX_RETRIES retries is marked
    delinquent and loses their payout position; remaining members continue.
  * The pool advances once a MAJORITY of the cycle's contributions clear.
  * No one covers a defaulter — the recipient gets what was actually collected.

KNOWN v1 LIMITATIONS (money-SAFE — no loss/double-spend — but deferred polish):
  * Transient orphan: if a Dwolla POST succeeds but its HTTP response is lost,
    the row reverts to pending/failed without the transfer URL. This self-heals
    on the next collect/retry because the Idempotency-Key is STABLE (Dwolla
    returns the same transfer and we capture its URL then) — no double debit.
  * ACH-return-after-payout: a contribution that 'returns' AFTER its payout has
    settled doesn't claw back the already-disbursed pool (the payout amount is
    snapshotted at staging). A failed/returned PAYOUT does roll the pool forward
    and bumps that recipient; re-paying the bumped member is a manual operator
    step. A full clawback/reconciliation subsystem is out of v1 scope.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.services.sol import storage as st

logger = logging.getLogger(__name__)

# A failed contribution may be retried this many times before the member is
# marked delinquent. Spec: "two automatic retries". Configurable for ops.
MAX_RETRIES = int(os.environ.get("SOL_MAX_CONTRIBUTION_RETRIES", "2"))


class SolStateError(ValueError):
    """Invalid state transition (maps to HTTP 400 at the router)."""


# ─── circle setup ────────────────────────────────────────────────────
def create_circle(name: str, contribution_cents: int, member_target: int,
                  fee_bps: int = 0) -> st.Circle:
    return st.create_circle(name, contribution_cents, member_target, fee_bps)


def add_member(circle_id: int, name: str, email: str | None = None,
               dwolla_customer_id: str | None = None,
               funding_source_href: str | None = None) -> st.Member:
    circle = st.get_circle(circle_id)
    if circle.status != "forming":
        raise SolStateError(f"circle {circle_id} is {circle.status}; can only add members while forming")
    existing = st.list_members(circle_id)
    if len(existing) >= circle.member_target:
        raise SolStateError(f"circle {circle_id} is full ({circle.member_target} members)")
    status = "verified" if (dwolla_customer_id and funding_source_href) else "invited"
    return st.add_member(circle_id, name, email, dwolla_customer_id, funding_source_href, status)


def activate_circle(circle_id: int) -> dict[str, Any]:
    """forming → active: require a full roster of funded members, assign payout
    positions (join_order) by join sequence, open cycle 1."""
    circle = st.get_circle(circle_id)
    if circle.status != "forming":
        raise SolStateError(f"circle {circle_id} is already {circle.status}")
    members = st.list_members(circle_id)
    if len(members) != circle.member_target:
        raise SolStateError(
            f"circle needs exactly {circle.member_target} members to activate "
            f"(has {len(members)})")
    unfunded = [m.id for m in members if not (m.dwolla_customer_id and m.funding_source_href)]
    if unfunded:
        raise SolStateError(f"members not funded/verified: {unfunded}")

    # Assign join_order 1..N by join sequence (members already ordered by id).
    for pos, m in enumerate(members, start=1):
        st.update_member(m.id, join_order=pos, status="active")
    st.set_circle_status(circle_id, "active", activated=True)
    cycle = open_cycle(circle_id, 1)
    return {"circle": st.get_circle(circle_id).as_dict(), **cycle}


# ─── cycles & contributions ──────────────────────────────────────────
def open_cycle(circle_id: int, cycle_number: int) -> dict[str, Any]:
    circle = st.get_circle(circle_id)
    if circle.status != "active":
        raise SolStateError(f"circle {circle_id} is {circle.status}; cannot open a cycle")
    if cycle_number < 1 or cycle_number > circle.member_target:
        raise SolStateError(f"cycle_number {cycle_number} out of range 1..{circle.member_target}")

    members = st.list_members(circle_id)
    active = [m for m in members if m.status == "active"]
    recipient = next((m for m in members if m.join_order == cycle_number), None)
    # The recipient is the member at this position; if they've gone delinquent
    # they keep no payout (handled at collection close), but the cycle still runs.
    recipient_id = recipient.id if recipient else None

    cycle = st.create_cycle(circle_id, cycle_number, recipient_id, status="collecting")
    # Everyone active contributes every cycle — including the recipient.
    for m in active:
        st.create_contribution(cycle.id, m.id, circle.contribution_cents)
    return {"cycle": cycle.as_dict(),
            "contributions": [c.as_dict() for c in st.list_contributions(cycle.id)]}


def mark_contribution_result(contribution_id: int, success: bool) -> dict[str, Any]:
    """Webhook-driven: record a contribution transfer's outcome. IDEMPOTENT +
    MONOTONIC — Dwolla retries webhooks and can deliver out of order, so a
    duplicate/stale event must not corrupt a settled row.

    success → processed (no-op if already processed). failure → failed; a failure
    arriving AFTER a completion is an ACH return → 'returned' (compensating). A
    duplicate failure on an already-failed/returned row is a no-op. Delinquency
    fires only when retries are exhausted."""
    contrib = st.get_contribution(contribution_id)
    member = st.get_member(contrib.member_id)

    if success:
        # No-op on a terminal-settled row: 'processed' (already collected) OR
        # 'returned' (money came back — a stale 'completed' must not un-return it).
        if contrib.status in ("processed", "returned"):
            return {"contribution": contrib.as_dict(), "member_delinquent": False, "noop": True}
        c = st.update_contribution(contribution_id, status="processed")
        return {"contribution": c.as_dict(), "member_delinquent": False}

    # failure event
    if contrib.status in ("failed", "returned"):
        return {"contribution": contrib.as_dict(),
                "member_delinquent": member.status == "delinquent", "noop": True}
    # A failure after a completed transfer is an ACH return (R01 etc.), not a
    # first-attempt failure — record it as 'returned' so it's distinguishable.
    new_status = "returned" if contrib.status == "processed" else "failed"
    c = st.update_contribution(contribution_id, status=new_status)
    became_delinquent = False
    if c.retry_count >= MAX_RETRIES and member.status != "delinquent":
        st.update_member(c.member_id, status="delinquent")
        became_delinquent = True
        logger.info("sol: member %s delinquent (contribution %s %s after %s retries)",
                    c.member_id, contribution_id, new_status, c.retry_count)
    return {"contribution": c.as_dict(), "member_delinquent": became_delinquent}


def record_retry(contribution_id: int, transfer_url: str | None = None) -> st.Contribution:
    """Orchestration issued a fresh transfer for a failed contribution. Only sets
    dwolla_transfer_url when a new one is given — never NULLs the prior URL (that
    would orphan a late webhook for the previous attempt)."""
    c = st.get_contribution(contribution_id)
    if c.status not in ("failed", "returned"):
        raise SolStateError(f"contribution {contribution_id} is {c.status}; not retryable")
    if c.retry_count >= MAX_RETRIES:
        raise SolStateError(f"contribution {contribution_id} has exhausted retries")
    fields: dict[str, Any] = {"status": "processing", "retry_count": c.retry_count + 1}
    if transfer_url is not None:
        fields["dwolla_transfer_url"] = transfer_url
    return st.update_contribution(contribution_id, **fields)


def collection_status(cycle_id: int) -> dict[str, Any]:
    """How collection is going + whether a majority has cleared."""
    contribs = st.list_contributions(cycle_id)
    total = len(contribs)
    processed = [c for c in contribs if c.status == "processed"]
    failed = [c for c in contribs if c.status in ("failed", "returned")]
    pending = [c for c in contribs if c.status in ("pending", "processing")]
    # Majority = more than half of the cycle's contributions.
    threshold = (total // 2) + 1 if total else 0
    return {
        "cycle_id": cycle_id,
        "total": total,
        "processed": len(processed),
        "failed": len(failed),
        "pending": len(pending),
        "processed_cents": sum(c.amount_cents for c in processed),
        "majority_threshold": threshold,
        "majority_met": len(processed) >= threshold and total > 0,
    }


def close_collection_and_create_payout(cycle_id: int) -> dict[str, Any]:
    """Once a majority has cleared, freeze collection and stage the payout.

    Payout = the actually-collected pool (sum of processed contributions). No one
    covers a defaulter. Idempotent: returns the existing payout if already staged.
    """
    cycle = st.get_cycle(cycle_id)
    # IDEMPOTENCY GUARD (covers BOTH branches): once collection is closed the
    # cycle is no longer 'collecting' — it's 'collected' (active payout staged),
    # 'skipped' (recipient forfeited, pool rolled forward), 'paid' or 'failed'.
    # A re-invocation (double-click / 502 retry / re-approval) MUST NOT re-fold
    # the rollover or re-stage. Short-circuit to the existing state. (The forfeit
    # branch creates no payout row, so the get_payout_for_cycle guard alone is
    # insufficient — this status guard is what makes the forfeit path idempotent.)
    if cycle.status != "collecting":
        existing = st.get_payout_for_cycle(cycle_id)
        return {"cycle": cycle.as_dict(),
                "payout": existing.as_dict() if existing else None,
                "already_staged": True,
                "recipient_delinquent": cycle.status == "skipped"}

    # Belt-and-suspenders idempotency: if a payout row already exists (e.g. a
    # create-then-crash left the cycle 'collecting' with a staged payout), return
    # it rather than re-staging into the UNIQUE(cycle_id) constraint.
    existing = st.get_payout_for_cycle(cycle_id)
    if existing:
        return {"cycle": cycle.as_dict(), "payout": existing.as_dict(), "already_staged": True}

    status = collection_status(cycle_id)
    if not status["majority_met"]:
        raise SolStateError(
            f"cycle {cycle_id}: majority not met "
            f"({status['processed']}/{status['majority_threshold']}); cannot pay out")

    circle = st.get_circle(cycle.circle_id)
    recipient = st.get_member(cycle.recipient_member_id) if cycle.recipient_member_id else None
    if not recipient or recipient.status == "delinquent":
        # Recipient forfeited their position → mark the cycle "skipped" (terminal,
        # like "paid", so the circle advances). ROLLOVER POLICY: the collected
        # pool is NOT lost or refunded — it accumulates on the circle and is added
        # to the next successful payout. (No one covers a defaulter; equally, the
        # group's contributions aren't stranded by one member's forfeiture.)
        st.set_cycle_status(cycle_id, "skipped")
        rolled = circle.rollover_cents + status["processed_cents"]
        st.set_rollover(circle.id, rolled)
        return {"cycle": st.get_cycle(cycle_id).as_dict(), "payout": None,
                "recipient_delinquent": True,
                "rolled_into_next_cents": status["processed_cents"],
                "circle_rollover_cents": rolled}

    # Active recipient: pay the collected pool PLUS any rolled-forward balance.
    # The accumulator is NOT cleared here — clearing happens only when the payout
    # TRANSFER actually settles (mark_payout_result success). If the payout fails,
    # the whole undelivered pool rolls forward instead of being lost.
    # Create the payout row BEFORE flipping the cycle to 'collected', so a
    # 'collected' cycle ALWAYS has a payout — the status short-circuit above can
    # never trap a payout-less 'collected' cycle. (UNIQUE(cycle_id) keeps it
    # idempotent if somehow re-entered.)
    amount = status["processed_cents"] + circle.rollover_cents
    payout = st.create_payout(cycle_id, recipient.id, amount)
    st.set_cycle_status(cycle_id, "collected")
    return {"cycle": st.get_cycle(cycle_id).as_dict(), "payout": payout.as_dict(),
            "applied_rollover_cents": circle.rollover_cents, "already_staged": False}


def mark_payout_result(payout_id: int, success: bool) -> dict[str, Any]:
    """Webhook-driven: record the payout transfer's outcome → cycle paid/failed.

    IDEMPOTENT: a duplicate/out-of-order webhook on an already-terminal payout is
    a no-op. On SUCCESS the rollover accumulator is cleared (the folded balance
    was disbursed). On FAILURE the entire undelivered pool (this cycle's
    collection + any folded rollover = payout.amount) rolls forward into the
    accumulator so no money is lost."""
    payout = st.get_payout(payout_id)
    cycle = st.get_cycle(payout.cycle_id)

    # ACH RETURN after a completed payout: a FAILURE event on an already-
    # 'processed' payout is a clawback (the credit bounced back). Record it as
    # 'returned', re-open the cycle to 'failed' (advanceable — the rotation isn't
    # stranded) and roll the whole pool forward so the money isn't stranded.
    if payout.status == "processed":
        if success:
            return {"payout": payout.as_dict(), "cycle": cycle.as_dict(), "noop": True}
        p = st.update_payout(payout_id, status="returned")
        st.set_cycle_status(payout.cycle_id, "failed")
        # ADD (not overwrite): this return can land days later, AFTER the circle
        # advanced and a LATER cycle already grew the accumulator. Overwriting
        # would clobber that later rollover and short the group. (Contrast the
        # pending→failed branch below, where overwrite is safe because the cycle
        # hasn't advanced and no later rollover can exist yet.)
        circle = st.get_circle(cycle.circle_id)
        st.set_rollover(cycle.circle_id, circle.rollover_cents + payout.amount_cents)
        logger.info("sol: payout %s RETURNED (ACH clawback) — pool rolled forward", payout_id)
        return {"payout": p.as_dict(), "cycle": st.get_cycle(payout.cycle_id).as_dict(),
                "returned": True}
    if payout.status in ("failed", "returned"):
        return {"payout": payout.as_dict(), "cycle": cycle.as_dict(), "noop": True}

    if success:
        p = st.update_payout(payout_id, status="processed")
        st.set_cycle_status(payout.cycle_id, "paid", paid=True)
        st.set_rollover(cycle.circle_id, 0)  # disbursed → clear accumulator
    else:
        p = st.update_payout(payout_id, status="failed")
        st.set_cycle_status(payout.cycle_id, "failed")
        # Overwrite (not add): payout.amount already includes the staging rollover,
        # so setting rollover = payout.amount carries the full pool forward with
        # no double-count.
        st.set_rollover(cycle.circle_id, payout.amount_cents)
    return {"payout": p.as_dict(), "cycle": st.get_cycle(payout.cycle_id).as_dict()}


def advance_circle(circle_id: int) -> dict[str, Any]:
    """After the current cycle is paid, open the next — or complete the circle."""
    circle = st.get_circle(circle_id)
    if circle.status != "active":
        raise SolStateError(f"circle {circle_id} is {circle.status}")
    cycles = st.list_cycles(circle_id)
    if not cycles:
        raise SolStateError("no cycles to advance")
    last = cycles[-1]
    # Advanceable when the cycle is terminal: "paid" (recipient got the pool),
    # "skipped" (recipient forfeited), or "failed" (payout failed/returned). In
    # the skipped/failed cases the pool already rolled forward, so the rotation
    # continues and the next recipient receives it — the circle is never stranded.
    if last.status not in ("paid", "skipped", "failed"):
        raise SolStateError(f"current cycle {last.cycle_number} is {last.status}, "
                            "not a terminal state (paid/skipped/failed)")
    if last.cycle_number >= circle.member_target:
        st.set_circle_status(circle_id, "completed")
        return {"completed": True, "circle": st.get_circle(circle_id).as_dict()}
    nxt = open_cycle(circle_id, last.cycle_number + 1)
    return {"completed": False, **nxt}


# ─── due-action scan (for the scheduler / operator reminders) ─────────
def scan_due_actions() -> list[dict[str, Any]]:
    """Across all ACTIVE circles, what needs operator attention right now?

    Pure read — surfaces money actions (collect/payout) as reminders only
    (they stay operator-approved) and rotation advances (non-destructive).
    """
    actions: list[dict[str, Any]] = []
    for circle in st.list_circles(status="active"):
        cycles = st.list_cycles(circle.id)
        if not cycles:
            continue
        cyc = cycles[-1]
        base = {"circle_id": circle.id, "circle_name": circle.name,
                "cycle_id": cyc.id, "cycle_number": cyc.cycle_number}
        if cyc.status == "collecting":
            cs = collection_status(cyc.id)
            if cs["pending"] > 0:
                actions.append({**base, "action": "collect_due",
                                "detail": f"{cs['pending']} contribution(s) not yet collected"})
            # Retryable failures: failed/returned contributions still under the
            # retry cap can be re-issued (operator-approved) before the member
            # is marked delinquent.
            retryable = [c for c in st.list_contributions(cyc.id)
                         if c.status in ("failed", "returned") and c.retry_count < MAX_RETRIES]
            if retryable:
                actions.append({**base, "action": "retry_due",
                                "detail": f"{len(retryable)} failed contribution(s) can be retried"})
            if cs["majority_met"] and not st.get_payout_for_cycle(cyc.id):
                actions.append({**base, "action": "payout_ready",
                                "detail": f"majority cleared ({cs['processed']}/{cs['total']}); "
                                          "ready to pay the recipient"})
        elif cyc.status in ("paid", "skipped") and cyc.cycle_number < circle.member_target:
            actions.append({**base, "action": "advance_ready",
                            "detail": f"cycle {cyc.status}; the next cycle can open"})
    return actions


# ─── read model ──────────────────────────────────────────────────────
def circle_detail(circle_id: int) -> dict[str, Any]:
    circle = st.get_circle(circle_id)
    members = st.list_members(circle_id)
    cycles = st.list_cycles(circle_id)
    return {
        "circle": circle.as_dict(),
        "payout_per_cycle_cents": circle.contribution_cents * circle.member_target,
        "members": [m.as_dict() for m in members],
        "cycles": [
            {**cy.as_dict(),
             "contributions": [c.as_dict() for c in st.list_contributions(cy.id)],
             "payout": (p.as_dict() if (p := st.get_payout_for_cycle(cy.id)) else None)}
            for cy in cycles
        ],
    }
