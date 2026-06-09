from unittest.mock import MagicMock

from app.config import settings
from app.models.asset import Asset


# Path X / credential rotation: settings.admin_token is the canonical
# property (prefers ADMIN_TOKEN, falls back to legacy JWT_SECRET_KEY).
# Hardcoding settings.JWT_SECRET_KEY here started failing once we blanked
# that env var as part of the leaked-credential rotation.
ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


def test_ingest_all_requires_admin_token(client):
    r = client.post("/admin/ingest/all")
    assert r.status_code == 403


def test_ingest_all_wrong_token(client):
    r = client.post("/admin/ingest/all", headers={"X-Admin-Token": "nope"})
    assert r.status_code == 403


def test_ingest_all_dispatches(client, monkeypatch):
    fake_task = MagicMock()
    fake_task.id = "task-abc"
    mock_delay = MagicMock(return_value=fake_task)
    monkeypatch.setattr(
        "app.routers.admin_data.ingest_all_assets.delay",
        mock_delay,
    )

    r = client.post("/admin/ingest/all", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body == {"task_id": "task-abc", "status": "queued"}
    mock_delay.assert_called_once_with()


def test_ingest_single_unknown_symbol(client, db_session, monkeypatch):
    # Seed a real asset so the symbol matcher has something to miss against.
    db_session.add(Asset(symbol="REAL", name="Real", asset_type="stock", is_active=True))
    db_session.commit()

    # Patch delay so a 500 in the task layer can't mask a routing bug.
    mock_delay = MagicMock()
    monkeypatch.setattr(
        "app.routers.admin_data.ingest_single_asset.delay",
        mock_delay,
    )

    r = client.post("/admin/ingest/NOTREAL", headers=ADMIN_HEADERS)
    assert r.status_code == 404
    mock_delay.assert_not_called()


# ─── operator dashboard endpoints ────────────────────────────────────


def test_recent_users_requires_admin_token(client):
    r = client.get("/admin/recent-users")
    assert r.status_code == 403


def test_recent_users_returns_shape(client, db_session):
    from app.models.profile import Profile
    from datetime import datetime, timedelta, timezone
    import uuid as _uuid
    # Explicit timestamps — Postgres NOW() is stable inside one transaction,
    # so two rows seeded back-to-back without explicit created_at would tie
    # and sort non-deterministically.
    now = datetime.now(timezone.utc)
    db_session.add(Profile(
        id=_uuid.uuid4(), email="older@kai.test", tier="free",
        created_at=now - timedelta(hours=2),
    ))
    db_session.add(Profile(
        id=_uuid.uuid4(), email="newer@kai.test", tier="pro",
        created_at=now,
    ))
    db_session.commit()

    r = client.get("/admin/recent-users?limit=5", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "users" in body
    # Newest comes first
    emails = [u["email"] for u in body["users"]]
    assert emails[0] == "newer@kai.test"
    # Required fields present on each row
    for u in body["users"]:
        assert set(u.keys()) >= {"id", "email", "tier", "created_at"}


def test_recent_users_limit_is_clamped(client):
    # limit=9999 should be silently capped to 100; verify no 5xx and the
    # response shape stays correct even with no rows.
    r = client.get("/admin/recent-users?limit=9999", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert "users" in r.json()


def test_spend_requires_admin_token(client):
    r = client.get("/admin/spend")
    assert r.status_code == 403


def test_spend_returns_shape(client):
    """Empty DB is fine — endpoint must still return all keys with zero/empty
    values so the dashboard can render without conditional logic."""
    r = client.get("/admin/spend", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    expected_keys = {
        "today", "last_7d",
        "today_total_usd", "last_7d_total_usd",
        "failures_24h",
    }
    assert set(body.keys()) == expected_keys
    assert isinstance(body["today"], list)
    assert isinstance(body["last_7d"], list)
    assert isinstance(body["today_total_usd"], (int, float))
    assert isinstance(body["last_7d_total_usd"], (int, float))


def test_spend_aggregates_by_adapter(client, db_session):
    """Seed llm_call_log rows and assert the rollup groups + sums correctly."""
    from sqlalchemy import text
    from app.models.profile import Profile
    import uuid as _uuid
    uid = _uuid.uuid4()
    # FK: llm_call_log.user_id references profiles.id
    db_session.add(Profile(id=uid, email=f"spend-{uid.hex[:8]}@kai.test", tier="pro"))
    db_session.commit()
    # Two openai calls, one cloudflare call — all in the last 7 days
    db_session.execute(
        text(
            """
            INSERT INTO llm_call_log
              (user_id, adapter, model, input_tokens, output_tokens,
               cost_usd, latency_ms, success, error_message, metadata, created_at)
            VALUES
              (:uid, 'openai',     'gpt-4o-mini', 100, 50,  0.05, 200, TRUE, NULL,
               CAST('{}' AS jsonb), NOW() - INTERVAL '1 hour'),
              (:uid, 'openai',     'gpt-4o-mini', 200, 80,  0.10, 250, TRUE, NULL,
               CAST('{}' AS jsonb), NOW() - INTERVAL '2 hours'),
              (:uid, 'cloudflare', '@cf/meta/llama-3.1-8b-instruct',
                                                 50,  20,  0.001, 80,  TRUE, NULL,
               CAST('{}' AS jsonb), NOW() - INTERVAL '3 hours')
            """
        ),
        {"uid": str(uid)},
    )
    db_session.commit()

    r = client.get("/admin/spend", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    by_adapter = {row["adapter"]: row for row in body["last_7d"]}
    assert "openai" in by_adapter
    assert "cloudflare" in by_adapter
    # openai: 2 calls totalling 0.15
    assert by_adapter["openai"]["calls"] == 2
    assert abs(by_adapter["openai"]["cost_usd"] - 0.15) < 1e-9
    # cloudflare: 1 call, 0.001
    assert by_adapter["cloudflare"]["calls"] == 1
    assert abs(by_adapter["cloudflare"]["cost_usd"] - 0.001) < 1e-9
    # Total = sum of both
    assert abs(body["last_7d_total_usd"] - 0.151) < 1e-9


def test_spend_counts_failures(client, db_session):
    from sqlalchemy import text
    from app.models.profile import Profile
    import uuid as _uuid
    uid = _uuid.uuid4()
    db_session.add(Profile(id=uid, email=f"fail-{uid.hex[:8]}@kai.test", tier="pro"))
    db_session.commit()
    db_session.execute(
        text(
            """
            INSERT INTO llm_call_log
              (user_id, adapter, model, input_tokens, output_tokens,
               cost_usd, latency_ms, success, error_message, metadata, created_at)
            VALUES
              (:uid, 'openai', 'gpt-4o-mini', 0, 0, 0.0, NULL,
               FALSE, 'rate limit', CAST('{}' AS jsonb),
               NOW() - INTERVAL '2 hours')
            """
        ),
        {"uid": str(uid)},
    )
    db_session.commit()
    r = client.get("/admin/spend", headers=ADMIN_HEADERS)
    assert r.json()["failures_24h"] >= 1
