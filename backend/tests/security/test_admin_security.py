import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ["KAI_SCOPE_SECURITY"] = "1"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KAI_SECURITY_DIR", str(tmp_path))
    from app.main import app  # imported after env is set
    return TestClient(app)


def _h():
    return {"X-Admin-Token": "test-admin-token"}


def test_summary_no_data_is_soft(client):
    r = client.get("/admin/security/summary", headers=_h())
    assert r.status_code == 200
    assert r.json().get("status") == "no-data"


def test_summary_requires_token(client):
    assert client.get("/admin/security/summary").status_code in (401, 403)


def test_scan_queues_marker_without_spawning(client, tmp_path):
    r = client.post("/admin/security/scan", headers=_h())
    assert r.status_code == 200 and r.json().get("queued") is True
    assert (tmp_path / ".request").exists()  # only a marker was written
