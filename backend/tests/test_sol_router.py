"""Sol admin router + Dwolla webhook — TestClient, mocked Dwolla, signed events.

Verifies the governance gates (admin token, sol.manage / sol.transfer scopes,
approved=True) and the fail-closed HMAC webhook, without moving real money.
"""
import hashlib
import hmac
import json

import pytest

from app.config import settings
from app.services.dwolla.client import DwollaError
from app.services.sol import storage as st
from app.services.sol import engine

ADMIN = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _temp_sol_db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SOL_DB_PATH", tmp_path / "sol.db")
    st.init_db()
    monkeypatch.setattr(engine, "MAX_RETRIES", 2)
    # scopes OFF by default — individual tests opt in
    for v in ("KAI_SCOPE_SOL", "KAI_SCOPE_SOL_MANAGE", "KAI_SCOPE_SOL_TRANSFER"):
        monkeypatch.delenv(v, raising=False)
    yield


class _FakeDwolla:
    env = "sandbox"

    def balance_funding_source_href(self):
        return "https://api-sandbox.dwolla.com/funding-sources/pool"

    def create_transfer(self, src, dst, value, currency="USD", metadata=None,
                        idempotency_key=None):
        tag = (metadata or {}).get("sol_contribution_id") or (metadata or {}).get("sol_payout_id") or "x"
        # vary by idempotency key so retries get a distinct (unique-indexed) url
        suffix = f"-{idempotency_key}" if idempotency_key else ""
        return {"location": f"https://api-sandbox.dwolla.com/transfers/{tag}{suffix}"}


def _make_active_circle(client, monkeypatch, n=3):
    monkeypatch.setenv("KAI_SCOPE_SOL", "1")  # wildcard → manage (non-destructive)
    monkeypatch.setenv("KAI_SCOPE_SOL_TRANSFER", "1")  # GOV-005: destructive transfer needs its exact flag
    r = client.post("/admin/sol/circles", headers=ADMIN,
                    json={"name": "C", "contribution_cents": 20000, "member_target": n})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    for i in range(n):
        rm = client.post(f"/admin/sol/circles/{cid}/members", headers=ADMIN,
                         json={"name": f"M{i}", "dwolla_customer_id": f"cust{i}",
                               "funding_source_href": f"https://api-sandbox.dwolla.com/funding-sources/fs{i}"})
        assert rm.status_code == 200, rm.text
    ra = client.post(f"/admin/sol/circles/{cid}/activate", headers=ADMIN, json={})
    assert ra.status_code == 200, ra.text
    return cid, ra.json()["cycle"]["id"]


# ─── auth + scope gates ────────────────────────────────────────────────
def test_stats_requires_admin(client):
    assert client.get("/admin/sol/stats").status_code == 403


def test_create_circle_needs_scope(client, monkeypatch):
    # admin token present, but sol.manage scope OFF → 403 ScopeDenied
    r = client.post("/admin/sol/circles", headers=ADMIN,
                    json={"name": "C", "contribution_cents": 20000, "member_target": 3})
    assert r.status_code == 403


def test_create_and_detail(client, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_SOL_MANAGE", "1")
    r = client.post("/admin/sol/circles", headers=ADMIN,
                    json={"name": "Block Party", "contribution_cents": 20000, "member_target": 3})
    assert r.status_code == 200
    cid = r.json()["id"]
    d = client.get(f"/admin/sol/circles/{cid}", headers=ADMIN).json()
    assert d["circle"]["name"] == "Block Party"
    assert d["payout_per_cycle_cents"] == 60000  # 200.00 × 3


# ─── money gates ───────────────────────────────────────────────────────
def test_collect_requires_transfer_scope(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch)
    # turn OFF transfer scope but keep manage so activate worked
    monkeypatch.delenv("KAI_SCOPE_SOL", raising=False)
    monkeypatch.delenv("KAI_SCOPE_SOL_TRANSFER", raising=False)  # helper set it; remove to test the gate
    monkeypatch.setenv("KAI_SCOPE_SOL_MANAGE", "1")
    r = client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    assert r.status_code == 403  # sol.transfer not enabled


def test_collect_requires_approval(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch)  # KAI_SCOPE_SOL on
    r = client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": False})
    assert r.status_code == 409  # PendingApproval


def test_collect_initiates_transfers(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch)
    monkeypatch.setattr("app.routers.sol.DwollaClient", _FakeDwolla)
    r = client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["initiated"] == 3
    # contributions now processing with transfer urls
    contribs = st.list_contributions(cycle_id)
    assert all(c.status == "processing" and c.dwolla_transfer_url for c in contribs)


# ─── webhook (fail-closed HMAC) ────────────────────────────────────────
def test_webhook_rejected_without_secret(client):
    # DWOLLA_WEBHOOK_SECRET unset → fail closed
    r = client.post("/sol/webhook", content=b"{}", headers={"X-Request-Signature-SHA-256": "x"})
    assert r.status_code == 401


def test_webhook_marks_contribution_completed(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch)
    monkeypatch.setattr("app.routers.sol.DwollaClient", _FakeDwolla)
    client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    contrib = st.list_contributions(cycle_id)[0]
    transfer_url = contrib.dwolla_transfer_url

    monkeypatch.setenv("DWOLLA_WEBHOOK_SECRET", "whsec")
    event = {"topic": "transfer_completed", "_links": {"resource": {"href": transfer_url}}}
    raw = json.dumps(event).encode()
    sig = hmac.new(b"whsec", raw, hashlib.sha256).hexdigest()
    r = client.post("/sol/webhook", content=raw,
                    headers={"X-Request-Signature-SHA-256": sig})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "contribution"
    assert st.get_contribution(contrib.id).status == "processed"


def test_webhook_bad_signature_rejected(client, monkeypatch):
    monkeypatch.setenv("DWOLLA_WEBHOOK_SECRET", "whsec")
    r = client.post("/sol/webhook", content=b'{"topic":"transfer_completed"}',
                    headers={"X-Request-Signature-SHA-256": "deadbeef"})
    assert r.status_code == 401


# ─── scheduler endpoints ───────────────────────────────────────────────
def test_scheduler_status_shape(client):
    r = client.get("/admin/sol/scheduler", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"enabled", "running", "hour_utc", "autopilot", "scope_on"}


def test_scheduler_run_now_needs_scope(client, monkeypatch):
    # run-now is @audited(sol.manage); scope OFF → 403
    r = client.post("/admin/sol/scheduler/run-now", headers=ADMIN, json={})
    assert r.status_code == 403


def test_scheduler_run_now_runs_with_scope(client, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_SOL_MANAGE", "1")
    r = client.post("/admin/sol/scheduler/run-now", headers=ADMIN, json={"autopilot": False})
    assert r.status_code == 200, r.text
    # no circles yet → no due actions, nothing notified
    assert r.json()["due_actions"] == []


# ─── customer / funding-source creation (audited dwolla.* scopes) ──────
class _FakeOps:
    """Stands in for DwollaClient inside dwolla.operations."""
    def create_customer(self, customer):
        return {"location": "https://api-sandbox.dwolla.com/customers/cust-new"}

    def create_funding_source(self, customer_id, source):
        return {"location": f"https://api-sandbox.dwolla.com/funding-sources/fs-new"}


def test_create_customer_needs_scope(client, monkeypatch):
    r = client.post("/admin/sol/customers", headers=ADMIN,
                    json={"customer": {"firstName": "Ada", "lastName": "L", "email": "a@x.com"}})
    assert r.status_code == 403  # dwolla.customer scope off


def test_create_customer_works(client, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_DWOLLA_CUSTOMER", "1")
    monkeypatch.setattr("app.services.dwolla.operations.DwollaClient", _FakeOps)
    r = client.post("/admin/sol/customers", headers=ADMIN,
                    json={"customer": {"firstName": "Ada", "lastName": "L", "email": "a@x.com"}})
    assert r.status_code == 200, r.text
    assert r.json()["location"].endswith("/customers/cust-new")


def test_add_funding_source_works(client, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_DWOLLA_FUNDING", "1")
    monkeypatch.setattr("app.services.dwolla.operations.DwollaClient", _FakeOps)
    r = client.post("/admin/sol/customers/cust-1/funding-sources", headers=ADMIN,
                    json={"source": {"plaidToken": "tok", "name": "Checking"}})
    assert r.status_code == 200, r.text
    assert "fs-new" in r.json()["location"]


# ─── idempotency / double-money guards (review FIX A/D) ────────────────
class _CountingDwolla:
    """Counts every ACH transfer issued, across instances (class-level)."""
    calls = []
    env = "sandbox"

    def balance_funding_source_href(self):
        return "https://api-sandbox.dwolla.com/funding-sources/pool"

    def create_transfer(self, src, dst, value, currency="USD", metadata=None, idempotency_key=None):
        _CountingDwolla.calls.append(idempotency_key)
        return {"location": f"https://api-sandbox.dwolla.com/transfers/{idempotency_key}"}


def test_collect_no_double_debit(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch, n=3)
    _CountingDwolla.calls = []
    monkeypatch.setattr("app.routers.sol.DwollaClient", _CountingDwolla)
    r1 = client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    assert r1.status_code == 200 and r1.json()["initiated"] == 3
    # second collect: every contribution is already 'processing' → zero new debits
    r2 = client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    assert r2.status_code == 200 and r2.json()["initiated"] == 0
    assert len(_CountingDwolla.calls) == 3  # NOT 6


def test_payout_no_double_credit(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch, n=3)
    contribs = st.list_contributions(cycle_id)
    engine.mark_contribution_result(contribs[0].id, True)
    engine.mark_contribution_result(contribs[1].id, True)  # majority met
    _CountingDwolla.calls = []
    monkeypatch.setattr("app.routers.sol.DwollaClient", _CountingDwolla)
    r1 = client.post(f"/admin/sol/cycles/{cycle_id}/payout", headers=ADMIN, json={"approved": True})
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"/admin/sol/cycles/{cycle_id}/payout", headers=ADMIN, json={"approved": True})
    assert r2.status_code == 200 and r2.json().get("already_initiated") is True
    assert len(_CountingDwolla.calls) == 1  # ONE credit, not two


def test_retry_failed_reissues_and_counts(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch, n=3)
    contribs = st.list_contributions(cycle_id)
    engine.mark_contribution_result(contribs[0].id, False)  # one fails
    assert st.get_contribution(contribs[0].id).status == "failed"
    _CountingDwolla.calls = []
    monkeypatch.setattr("app.routers.sol.DwollaClient", _CountingDwolla)
    r = client.post(f"/admin/sol/cycles/{cycle_id}/retry-failed", headers=ADMIN, json={"approved": True})
    assert r.status_code == 200, r.text
    assert r.json()["retried"] == 1
    again = st.get_contribution(contribs[0].id)
    assert again.status == "processing" and again.retry_count == 1
    assert len(_CountingDwolla.calls) == 1


def test_retry_ladder_to_delinquency_via_endpoint(client, monkeypatch):
    # Real production ladder: collect → fail → /retry-failed → fail → /retry-failed
    # → fail → delinquent (retry_count advances only on confirmed transfer).
    cid, cycle_id = _make_active_circle(client, monkeypatch, n=3)
    _CountingDwolla.calls = []
    monkeypatch.setattr("app.routers.sol.DwollaClient", _CountingDwolla)
    target = st.list_contributions(cycle_id)[0].id
    client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    engine.mark_contribution_result(target, False)            # fail #1 (rc 0)
    for expected_rc in (1, 2):
        r = client.post(f"/admin/sol/cycles/{cycle_id}/retry-failed", headers=ADMIN, json={"approved": True})
        assert r.status_code == 200 and r.json()["retried"] == 1
        assert st.get_contribution(target).retry_count == expected_rc
        out = engine.mark_contribution_result(target, False)  # webhook fails again
    assert out["member_delinquent"] is True                    # exhausted → delinquent
    assert st.get_member(st.get_contribution(target).member_id).status == "delinquent"
    # a further retry is refused (cap reached)
    r3 = client.post(f"/admin/sol/cycles/{cycle_id}/retry-failed", headers=ADMIN, json={"approved": True})
    assert any(x.get("skipped") == "retries exhausted" for x in r3.json()["results"])


def test_retry_requires_transfer_scope(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch, n=3)
    monkeypatch.delenv("KAI_SCOPE_SOL", raising=False)
    monkeypatch.delenv("KAI_SCOPE_SOL_TRANSFER", raising=False)  # helper set it; remove to test the gate
    monkeypatch.setenv("KAI_SCOPE_SOL_MANAGE", "1")  # manage on, transfer off
    r = client.post(f"/admin/sol/cycles/{cycle_id}/retry-failed", headers=ADMIN, json={"approved": True})
    assert r.status_code == 403


class _IdempotentDwolla:
    """Models REAL Dwolla idempotency: a repeated Idempotency-Key returns the
    SAME transfer resource (no new debit). `raise_keys` simulates a lost HTTP
    response AFTER the transfer was created (the dangerous case)."""
    seen = {}
    raise_keys = set()
    raised = set()
    env = "sandbox"

    def balance_funding_source_href(self):
        return "https://api-sandbox.dwolla.com/funding-sources/pool"

    def create_transfer(self, src, dst, value, currency="USD", metadata=None, idempotency_key=None):
        loc = _IdempotentDwolla.seen.setdefault(
            idempotency_key, f"https://api-sandbox.dwolla.com/transfers/{idempotency_key}")
        if idempotency_key in _IdempotentDwolla.raise_keys and idempotency_key not in _IdempotentDwolla.raised:
            _IdempotentDwolla.raised.add(idempotency_key)  # transfer WAS created, response lost
            raise DwollaError("simulated lost response")
        return {"location": loc}


def test_collect_lost_response_reconciles_via_idempotency_key(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch, n=3)
    contribs = st.list_contributions(cycle_id)
    key0 = f"sol-contrib-{contribs[0].id}"
    _IdempotentDwolla.seen = {}; _IdempotentDwolla.raised = set()
    _IdempotentDwolla.raise_keys = {key0}  # first contribution loses its response
    monkeypatch.setattr("app.routers.sol.DwollaClient", _IdempotentDwolla)
    # first collect → DwollaError on contrib[0] → 502; it reverts to 'pending'
    r1 = client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    assert r1.status_code == 502
    assert st.get_contribution(contribs[0].id).status == "pending"
    # re-collect → SAME idempotency key → Dwolla returns the SAME transfer
    r2 = client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    assert r2.status_code == 200
    # exactly ONE transfer resource ever existed for contrib[0] — no double debit
    assert sum(1 for k in _IdempotentDwolla.seen if k == key0) == 1
    assert st.get_contribution(contribs[0].id).status == "processing"


def test_webhook_duplicate_completed_is_noop(client, monkeypatch):
    cid, cycle_id = _make_active_circle(client, monkeypatch, n=3)
    monkeypatch.setattr("app.routers.sol.DwollaClient", _CountingDwolla)
    _CountingDwolla.calls = []
    client.post(f"/admin/sol/cycles/{cycle_id}/collect", headers=ADMIN, json={"approved": True})
    contrib = st.list_contributions(cycle_id)[0]
    url = contrib.dwolla_transfer_url
    monkeypatch.setenv("DWOLLA_WEBHOOK_SECRET", "whsec")
    event = json.dumps({"topic": "transfer_completed", "_links": {"resource": {"href": url}}}).encode()
    sig = hmac.new(b"whsec", event, hashlib.sha256).hexdigest()
    h = {"X-Request-Signature-SHA-256": sig}
    r1 = client.post("/sol/webhook", content=event, headers=h)
    r2 = client.post("/sol/webhook", content=event, headers=h)  # duplicate delivery
    assert r1.status_code == 200 and r2.status_code == 200
    assert st.get_contribution(contrib.id).status == "processed"  # not corrupted
