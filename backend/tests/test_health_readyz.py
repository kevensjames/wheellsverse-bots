"""/health is liveness (always 200); /readyz is readiness (503 when DB is down)."""
from sqlalchemy import text


def test_health_is_always_ok(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_readyz_ok_when_db_up(client):
    r = client.get("/readyz")
    # test env has a live Postgres; the DB check must pass (Redis may be absent).
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready" and body["checks"]["database"] == "ok"


def test_readyz_503_when_db_down(client, monkeypatch):
    import app.main as main

    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("app.database.engine", _BrokenEngine())
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"
    assert "error" in r.json()["checks"]["database"]
    # liveness must still be green — the process is up
    assert client.get("/health").status_code == 200
