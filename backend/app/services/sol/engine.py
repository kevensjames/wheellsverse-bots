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
    """Webhook-driven: record a contribution transfer's outcome.

    success → processed. failure → failed; if it has already exhausted its
    retries, the member is marked delinquent (loses payout position)."""
    contrib = st.get_contribution(contribution_id)
    if success:
        c = st.update_contribution(contribution_id, status="processed")
        return {"contribution": c.as_dict(), "member_delinquent": False}

    c = st.update_contribution(contribution_id, status="failed")
    became_delinquent = False
    if c.retry_count >= MAX_RETRIES:
        st.update_member(c.member_id, status="delinquent")
        became_delinquent = True
        logger.info("sol: member %s delinquent (contribution %s failed after %s retries)",
                    c.member_id, contribution_id, c.retry_count)
    return {"contribution": c.as_dict(), "member_delinquent": became_delinquent}


def record_retry(contribution_id: int, transfer_url: str | None = None) -> st.Contribution:
    """Orchestration issued a fresh transfer for a failed contribution."""
    c = st.get_contribution(contribution_id)
    if c.status not in ("failed", "returned"):
        raise SolStateError(f"contribution {contribution_id} is {c.status}; not retryable")
    if c.retry_count >= MAX_RETRIES:
        raise SolStateError(f"contribution {contribution_id} has exhausted retries")
    return st.update_contribution(contribution_id, status="processing",
                                  retry_count=c.retry_count + 1,
                                  dwolla_transfer_url=transfer_url)


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
    status = collection_status(cycle_id)
    if not status["majority_met"]:
        raise SolStateError(
            f"cycle {cycle_id}: majority not met "
            f"({status['processed']}/{status['majority_threshold']}); cannot pay out")

    existing = st.get_payout_for_cycle(cycle_id)
    if existing:
        return {"cycle": st.get_cycle(cycle_id).as_dict(), "payout": existing.as_dict(),
                "already_staged": True}

    st.set_cycle_status(cycle_id, "collected")
    recipient = st.get_member(cycle.recipient_member_id) if cycle.recipient_member_id else None
    if not recipient or recipient.status == "delinquent":
        # Recipient forfeited their position — no payout is created. Operator
        # decides what to do with the collected pool (rollover/refund).
        return {"cycle": st.get_cycle(cycle_id).as_dict(), "payout": None,
                "recipient_delinquent": True,
                "uncollected_pool_cents": status["processed_cents"]}

    payout = st.create_payout(cycle_id, recipient.id, status["processed_cents"])
    return {"cycle": st.get_cycle(cycle_id).as_dict(), "payout": payout.as_dict(),
            "already_staged": False}


def mark_payout_result(payout_id: int, success: bool) -> dict[str, Any]:
    """Webhook-driven: record the payout transfer's outcome → cycle paid/failed."""
    payout = st.get_payout(payout_id)
    if success:
        p = st.update_payout(payout_id, status="processed")
        st.set_cycle_status(payout.cycle_id, "paid", paid=True)
    else:
        p = st.update_payout(payout_id, status="failed")
        st.set_cycle_status(payout.cycle_id, "failed")
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
    if last.status != "paid":
        raise SolStateError(f"current cycle {last.cycle_number} is {last.status}, not paid")
    if last.cycle_number >= circle.member_target:
        st.set_circle_status(circle_id, "completed")
        return {"completed": True, "circle": st.get_circle(circle_id).as_dict()}
    nxt = open_cycle(circle_id, last.cycle_number + 1)
    return {"completed": False, **nxt}


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
