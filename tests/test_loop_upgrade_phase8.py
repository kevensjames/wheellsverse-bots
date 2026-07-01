from core.portfolio import arm, state

_ARM_ENV = ("WMOS_BUSINESS_REGISTERED", "GOOGLE_PLACES_API_KEY", "HUNTER_API_KEY",
            "INSTANTLY_API_KEY", "SMTP_HOST", "SITEBOOST_OUTBOUND_DOMAIN")


def _clear(monkeypatch):
    for k in _ARM_ENV:
        monkeypatch.delenv(k, raising=False)


def test_arm_readiness_honest_when_unregistered(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _clear(monkeypatch)
    r = arm.arm_readiness("n8n")
    assert r["known"] and r["ready"] is False and not r["armed"]
    assert "business_registered" in r["blockers"]


def test_arm_refused_unless_ready_even_with_confirm(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _clear(monkeypatch)
    r = arm.arm_business("n8n", confirm=True)
    assert r["status"] == "blocked" and r["blockers"]


def test_full_arm_flow_when_all_gates_green(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_BUSINESS_REGISTERED", "1")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "x")
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    monkeypatch.setenv("INSTANTLY_API_KEY", "x")
    monkeypatch.setenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wv.com")
    state.set_flag("n8n", "warmup_complete", True)
    assert arm.arm_readiness("n8n")["ready"] is True
    assert arm.arm_business("n8n")["status"] == "needs_confirm"   # still needs explicit confirm
    assert arm.arm_business("n8n", confirm=True)["status"] == "armed"
    assert arm.is_armed("n8n") is True
    arm.disarm_business("n8n")
    assert arm.is_armed("n8n") is False


def test_arm_unknown_business(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert arm.arm_readiness("nope")["known"] is False
    assert arm.arm_business("nope")["status"] == "unknown_business"


def test_arm_endpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _clear(monkeypatch)
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    c = TestClient(app, raise_server_exceptions=False)
    h = {"X-API-Key": "test-key-123"}
    r = c.get("/api/narai/portfolio/arm/n8n", headers=h).json()
    assert r["ready"] is False and "business_registered" in r["blockers"]
    pr = c.post("/api/narai/portfolio/arm/n8n?confirm=true", headers=h).json()
    assert pr["status"] == "blocked"   # unregistered -> refused even via the API
    assert c.get("/api/narai/portfolio/arm/bogus", headers=h).status_code == 404
