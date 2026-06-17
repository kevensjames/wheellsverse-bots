"""Sol ROSCA admin endpoints + the Dwolla webhook.

Two routers:

  router (prefix /admin/sol, admin-token gated) — the operator surface.
    Reads (non-audited):
      GET  /admin/sol/stats
      GET  /admin/sol/circles                  list (optional ?status=)
      GET  /admin/sol/circles/{id}             full detail (members + cycles)
    Management writes (@audited scope=sol.manage, destructive=False):
      POST /admin/sol/circles                  create a circle
      POST /admin/sol/circles/{id}/members     add a member
      POST /admin/sol/circles/{id}/activate    assign positions + open cycle 1
      POST /admin/sol/cycles/{id}/advance      open the next cycle / complete
    Money writes (@audited scope=sol.transfer, destructive=True → approved=True):
      POST /admin/sol/cycles/{id}/collect      ACH-debit each pending contribution
      POST /admin/sol/cycles/{id}/payout       close collection + pay the recipient

  webhook_router (prefix /sol, NO auth — Dwolla calls it) — HMAC-verified events
    that drive contribution/payout state. Fail-closed: rejects unless
    DWOLLA_WEBHOOK_SECRET is set and the signature matches.

Money movement is quadruple-locked: sol.transfer scope (off by default) +
approved=True + the DwollaClient sandbox-lock + (for the model) there is no LLM
tool that reaches these endpoints.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services.dwolla.client import DwollaClient, DwollaError
from app.services.dwolla.client import verify_webhook
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.sol import engine, storage as st

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/sol", tags=["admin", "sol"],
                   dependencies=[Depends(require_admin_token)])
webhook_router = APIRouter(prefix="/sol", tags=["sol"])


def _cents_to_str(cents: int) -> str:
    return f"{cents / 100:.2f}"


def _guard(fn, **kwargs):
    try:
        return fn(**kwargs)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DwollaError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── reads ───────────────────────────────────────────────────────────
@router.get("/stats")
def sol_stats() -> dict[str, Any]:
    circles = st.list_circles()
    by_status: dict[str, int] = {}
    for c in circles:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    return {"total_circles": len(circles), "by_status": by_status}


@router.get("/circles")
def sol_list_circles(status: str | None = None) -> dict[str, Any]:
    circles = st.list_circles(status=status)
    return {"count": len(circles), "circles": [c.as_dict() for c in circles]}


@router.get("/circles/{circle_id}")
def sol_get_circle(circle_id: int) -> dict[str, Any]:
    try:
        return engine.circle_detail(circle_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no circle {circle_id}")


# ─── request models ──────────────────────────────────────────────────
class CreateCircleRequest(BaseModel):
    name: str
    contribution_cents: int
    member_target: int
    fee_bps: int = 0
    approved: bool = False  # accepted but unused (manage is non-destructive)


class AddMemberRequest(BaseModel):
    name: str
    email: str | None = None
    dwolla_customer_id: str | None = None
    funding_source_href: str | None = None


class ApprovedRequest(BaseModel):
    approved: bool = False


class CreateCustomerRequest(BaseModel):
    # Dwolla customer payload: {firstName, lastName, email, type, ...}. Passed
    # through to operations.create_customer (already @audited dwolla.customer).
    customer: dict[str, Any]


class AddFundingSourceRequest(BaseModel):
    # {plaidToken, name} (preferred) or raw {routingNumber, accountNumber, ...}.
    source: dict[str, Any]


class RunTickRequest(BaseModel):
    autopilot: bool = False
    approved: bool = False  # accepted but unused (tick is non-destructive)


# ─── management writes (audited, non-destructive) ──────────────────────
@audited(scope="sol.manage", destructive=False)
def _create_circle(*, name, contribution_cents, member_target, fee_bps):
    return engine.create_circle(name, contribution_cents, member_target, fee_bps).as_dict()


@audited(scope="sol.manage", destructive=False)
def _add_member(*, circle_id, name, email, dwolla_customer_id, funding_source_href):
    return engine.add_member(circle_id, name, email, dwolla_customer_id,
                             funding_source_href).as_dict()


@audited(scope="sol.manage", destructive=False)
def _activate(*, circle_id):
    return engine.activate_circle(circle_id)


@audited(scope="sol.manage", destructive=False)
def _advance(*, circle_id):
    return engine.advance_circle(circle_id)


@router.post("/circles")
def sol_create_circle(body: CreateCircleRequest):
    return _guard(_create_circle, name=body.name, contribution_cents=body.contribution_cents,
                  member_target=body.member_target, fee_bps=body.fee_bps)


@router.post("/circles/{circle_id}/members")
def sol_add_member(circle_id: int, body: AddMemberRequest):
    return _guard(_add_member, circle_id=circle_id, name=body.name, email=body.email,
                  dwolla_customer_id=body.dwolla_customer_id,
                  funding_source_href=body.funding_source_href)


@router.post("/circles/{circle_id}/activate")
def sol_activate(circle_id: int, body: ApprovedRequest):
    return _guard(_activate, circle_id=circle_id)


@router.post("/cycles/{cycle_id}/advance")
def sol_advance(cycle_id: int, body: ApprovedRequest):
    # cycle_id here identifies the circle to advance (any cycle of it); resolve.
    try:
        circle_id = st.get_cycle(cycle_id).circle_id
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no cycle {cycle_id}")
    return _guard(_advance, circle_id=circle_id)


# ─── Dwolla customer + funding-source provisioning ─────────────────────
# These call the already-@audited operations directly (scope dwolla.customer /
# dwolla.funding, non-destructive) — no second wrapper, so the audit log gets
# exactly one record per action.
@router.post("/customers")
def sol_create_customer(body: CreateCustomerRequest):
    from app.services.dwolla import operations
    return _guard(operations.create_customer, customer=body.customer)


@router.post("/customers/{customer_id}/funding-sources")
def sol_add_funding_source(customer_id: str, body: AddFundingSourceRequest):
    from app.services.dwolla import operations
    return _guard(operations.add_funding_source, customer_id=customer_id, source=body.source)


# ─── scheduler (status + manual tick) ──────────────────────────────────
@audited(scope="sol.manage", destructive=False)
def _run_tick(*, autopilot):
    from app.services.sol import scheduler
    return scheduler.run_sol_tick(autopilot=autopilot, notify=True)


@router.get("/scheduler")
def sol_scheduler_status() -> dict[str, Any]:
    from app.services.sol import scheduler
    return scheduler.status()


@router.post("/scheduler/run-now")
def sol_scheduler_run_now(body: RunTickRequest):
    return _guard(_run_tick, autopilot=body.autopilot)


# ─── money writes (audited, destructive → approved=True + sol.transfer) ─
def _debit_contribution(client, pool, c, cycle, *, attempt_key: str):
    """ATOMICALLY claim a contribution then fire ONE ACH debit. The claim
    (conditional UPDATE pending→processing) is the lock: only the winner
    transfers, so a double-click / concurrent collect can't debit twice. The
    Idempotency-Key collapses a retried HTTP call server-side at Dwolla. On a
    transfer error we revert the claim to 'pending' so it can be retried (the
    key makes that safe even if the debit actually went through)."""
    member = st.get_member(c.member_id)
    if not member.funding_source_href:
        return {"contribution_id": c.id, "skipped": "no funding source"}
    if not st.claim_contribution(c.id, expect=c.status):
        return {"contribution_id": c.id, "skipped": "already claimed"}
    try:
        res = client.create_transfer(
            member.funding_source_href, pool, _cents_to_str(c.amount_cents),
            metadata={"sol_kind": "contribution", "sol_contribution_id": str(c.id),
                      "sol_cycle": str(cycle.cycle_number)},
            idempotency_key=attempt_key)
        url = res.get("location")
        st.update_contribution(c.id, dwolla_transfer_url=url)  # stays 'processing'
        return {"contribution_id": c.id, "transfer_url": url}
    except DwollaError:
        st.update_contribution(c.id, status="pending")  # revert claim → retryable
        raise


@audited(scope="sol.transfer", destructive=True)
def _collect(*, cycle_id):
    """ACH-debit each still-pending contribution: member bank → Sol pool."""
    cycle = st.get_cycle(cycle_id)
    if cycle.status != "collecting":
        raise ValueError(f"cycle {cycle_id} is {cycle.status}, not collecting")
    client = DwollaClient()
    pool = client.balance_funding_source_href()
    results = []
    for c in st.list_contributions(cycle_id):
        if c.status != "pending":
            continue
        results.append(_debit_contribution(client, pool, c, cycle,
                                            attempt_key=f"sol-contrib-{c.id}"))
    return {"cycle_id": cycle_id, "initiated": len([r for r in results if r.get("transfer_url")]),
            "results": results}


@audited(scope="sol.transfer", destructive=True)
def _retry_failed(*, cycle_id):
    """Re-issue ACH debits for failed/returned contributions under the retry cap
    (operator-approved). After the cap the next failure marks the member
    delinquent. The idempotency key is keyed on the NEXT attempt number
    (retry_count+1) and retry_count only advances on a CONFIRMED transfer — so a
    lost-response re-attempt reuses the SAME key and Dwolla dedupes it (no double
    debit). On error we revert to the prior failed/returned status WITHOUT
    touching retry_count or the prior transfer URL (keeps it reconcilable)."""
    cycle = st.get_cycle(cycle_id)
    client = DwollaClient()
    pool = client.balance_funding_source_href()
    results = []
    for c in st.list_contributions(cycle_id):
        if c.status not in ("failed", "returned"):
            continue
        if c.retry_count >= engine.MAX_RETRIES:
            results.append({"contribution_id": c.id, "skipped": "retries exhausted"})
            continue
        member = st.get_member(c.member_id)
        if not member.funding_source_href:
            results.append({"contribution_id": c.id, "skipped": "no funding source"})
            continue
        prior_status = c.status
        attempt = c.retry_count + 1  # stable key per logical attempt
        if not st.claim_contribution(c.id, expect=prior_status):  # failed/returned → processing
            results.append({"contribution_id": c.id, "skipped": "already claimed"})
            continue
        try:
            res = client.create_transfer(
                member.funding_source_href, pool, _cents_to_str(c.amount_cents),
                metadata={"sol_kind": "contribution-retry", "sol_contribution_id": str(c.id),
                          "sol_retry": str(attempt)},
                idempotency_key=f"sol-contrib-{c.id}-retry-{attempt}")
            # Advance retry_count only now (confirmed) so the key stays stable.
            st.update_contribution(c.id, retry_count=attempt,
                                   dwolla_transfer_url=res.get("location"))
            results.append({"contribution_id": c.id, "retried": True,
                            "transfer_url": res.get("location")})
        except DwollaError:
            st.update_contribution(c.id, status=prior_status)  # revert; count untouched
            raise
    return {"cycle_id": cycle_id, "retried": len([r for r in results if r.get("retried")]),
            "results": results}


@audited(scope="sol.transfer", destructive=True)
def _payout(*, cycle_id):
    """Close collection (majority must have cleared) and pay the recipient:
    Sol pool → recipient bank. IDEMPOTENT — won't re-credit an already-staged
    payout (guards on the existing payout's status/transfer + an atomic claim)."""
    staged = engine.close_collection_and_create_payout(cycle_id)
    payout = staged.get("payout")
    if not payout:  # recipient delinquent — nothing to pay
        return staged
    # Idempotency guard: if a transfer is already in flight/done, don't re-issue.
    if payout.get("dwolla_transfer_url") or payout.get("status") != "pending":
        return {"cycle_id": cycle_id, "payout_id": payout["id"], "already_initiated": True,
                "transfer_url": payout.get("dwolla_transfer_url"),
                "amount_cents": payout["amount_cents"], "status": payout.get("status")}
    recipient = st.get_member(payout["recipient_member_id"])
    if not recipient.funding_source_href:
        raise ValueError(f"recipient {recipient.id} has no funding source")
    # Atomic claim pending→processing: only the winner credits the recipient.
    if not st.claim_payout(payout["id"]):
        cur = st.get_payout(payout["id"])
        return {"cycle_id": cycle_id, "payout_id": payout["id"], "already_initiated": True,
                "transfer_url": cur.dwolla_transfer_url, "amount_cents": cur.amount_cents}
    client = DwollaClient()
    pool = client.balance_funding_source_href()
    try:
        res = client.create_transfer(
            pool, recipient.funding_source_href, _cents_to_str(payout["amount_cents"]),
            metadata={"sol_kind": "payout", "sol_payout_id": str(payout["id"]),
                      "sol_cycle_id": str(cycle_id)},
            idempotency_key=f"sol-payout-{payout['id']}")
        url = res.get("location")
        st.update_payout(payout["id"], dwolla_transfer_url=url)  # stays 'processing'
        return {"cycle_id": cycle_id, "payout_id": payout["id"], "transfer_url": url,
                "amount_cents": payout["amount_cents"]}
    except DwollaError:
        st.update_payout(payout["id"], status="pending")  # revert claim → retryable
        raise


@router.post("/cycles/{cycle_id}/collect")
def sol_collect(cycle_id: int, body: ApprovedRequest):
    return _guard(_collect, cycle_id=cycle_id, approved=body.approved)


@router.post("/cycles/{cycle_id}/retry-failed")
def sol_retry_failed(cycle_id: int, body: ApprovedRequest):
    return _guard(_retry_failed, cycle_id=cycle_id, approved=body.approved)


@router.post("/cycles/{cycle_id}/payout")
def sol_payout(cycle_id: int, body: ApprovedRequest):
    return _guard(_payout, cycle_id=cycle_id, approved=body.approved)


# ─── Dwolla webhook (HMAC-verified, no admin auth) ─────────────────────
_SUCCESS_TOPICS = {"transfer_completed", "customer_transfer_completed"}
_FAILURE_TOPICS = {"transfer_failed", "transfer_returned", "transfer_cancelled",
                   "customer_transfer_failed", "customer_transfer_cancelled"}


@webhook_router.post("/webhook")
async def sol_webhook(request: Request) -> dict[str, Any]:
    raw = await request.body()
    sig = request.headers.get("X-Request-Signature-SHA-256")
    # Fail-closed: no secret configured or bad signature → reject. An unverified
    # webhook must NEVER drive a money state change.
    if not verify_webhook(raw, sig):
        raise HTTPException(status_code=401, detail="invalid or unverified webhook signature")
    try:
        event = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="bad JSON")

    topic = event.get("topic", "")
    href = ((event.get("_links", {}) or {}).get("resource", {}) or {}).get("href", "")
    if not href or topic not in (_SUCCESS_TOPICS | _FAILURE_TOPICS):
        return {"ok": True, "ignored": topic or "(none)"}

    success = topic in _SUCCESS_TOPICS
    contrib = st.find_contribution_by_transfer(href)
    if contrib:
        out = engine.mark_contribution_result(contrib.id, success)
        return {"ok": True, "kind": "contribution", "contribution_id": contrib.id,
                "member_delinquent": out["member_delinquent"]}
    payout = st.find_payout_by_transfer(href)
    if payout:
        engine.mark_payout_result(payout.id, success)
        return {"ok": True, "kind": "payout", "payout_id": payout.id}
    return {"ok": True, "ignored": "no matching transfer"}
