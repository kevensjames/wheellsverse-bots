from unittest.mock import MagicMock

from app.config import settings
from app.models.asset import Asset


ADMIN_HEADERS = {"X-Admin-Token": settings.JWT_SECRET_KEY}


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
