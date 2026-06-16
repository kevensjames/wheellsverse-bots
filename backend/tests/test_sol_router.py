"""Sol admin router + Dwolla webhook — TestClient, mocked Dwolla, signed events.

Verifies the governance gates (admin token, sol.manage / sol.transfer scopes,
approved=True) and the fail-closed HMAC webhook, without moving real money.
"""
import hashlib
import hmac
import json

import pytest

from app.config import settings
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

    def create_transfer(self, src, dst, value, currency="USD", metadata=None):
        tag = (metadata or {}).get("sol_contribution_id") or (metadata or {}).get("sol_payout_id") or "x"
        return {"location": f"https://api-sandbox.dwolla.com/transfers/{tag}"}


def _make_active_circle(client, monkeypatch, n=3):
    monkeypatch.setenv("KAI_SCOPE_SOL", "1")  # wildcard → manage + transfer
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
