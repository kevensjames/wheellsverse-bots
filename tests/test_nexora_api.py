import pytest
import core.api as api
from core import nexora_db, nexora_auth, nexora_users
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db


class FakeReq:
    """Minimal stand-in for FastAPI Request: only .headers.get is used by the deps."""
    def __init__(self, token=None):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def test_require_user_valid_and_bad(db):
    reg = nexora_auth.register_creator("u@x.com", "hunter2", "Yoo")
    user = api._nx_require_user(FakeReq(reg["token"]))
    assert user["email"] == "u@x.com" and user["role"] == "creator"
    with pytest.raises(HTTPException) as e:
        api._nx_require_user(FakeReq("badtoken"))
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e2:
        api._nx_require_user(FakeReq(None))
    assert e2.value.status_code == 401


def test_require_admin(db):
    reg_a = nexora_auth.register_creator("admin@x.com", "hunter2", "Boss")
    nexora_users.set_role("admin@x.com", "admin")
    admin = api._nx_require_admin(FakeReq(reg_a["token"]))
    assert admin["role"] == "admin"
    reg_c = nexora_auth.register_creator("creator@x.com", "hunter2", "Cee")
    with pytest.raises(HTTPException) as e:
        api._nx_require_admin(FakeReq(reg_c["token"]))
    assert e.value.status_code == 403


def test_auth_me_route_via_testclient(db):
    reg = nexora_auth.register_creator("r@x.com", "hunter2", "Arr")
    client = TestClient(api.app)
    ok = client.get("/api/nx/auth/me", headers={"Authorization": f"Bearer {reg['token']}"})
    assert ok.status_code == 200
    assert ok.json()["email"] == "r@x.com" and ok.json()["role"] == "creator"
    bad = client.get("/api/nx/auth/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
