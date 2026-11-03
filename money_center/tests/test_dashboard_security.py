"""Security checks for the Money Center dashboard (money_center/dashboard.py).

/start and /stop run shell commands from the asset registry, and /add and
/edit write them, so any request the app accepts can lead to running
commands on the host. These tests pin the defenses: loopback-only by
default, a token for anything else, same-origin state changes, a loopback
Host header, and escaped output.

Run with: python -m pytest money_center/tests/ -v
"""
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest

pytest.importorskip("flask")

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from money_center import dashboard  # noqa: E402
from money_center import registry as reg  # noqa: E402

XSS = '<script>alert("x")</script>'
TOKEN = "s3cret-test-token"
SAME_ORIGIN = {"Origin": "http://localhost"}


def _asset(**overrides) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    asset = {
        "id": "demo", "name": "Demo", "category": "service",
        "description": "", "revenue_model": "other",
        "monthly_estimate_usd": {"low": 0, "mid": 0, "high": 0},
        "status": "idle", "run_command": "echo start", "stop_command": "echo stop",
        "working_dir": "/tmp", "tags": [], "notes": "",
        "created_at": now, "updated_at": now,
    }
    asset.update(overrides)
    return asset


def _basic(password: str) -> dict:
    raw = base64.b64encode(f"anyone:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Test client over a temp registry. Commands never really run."""
    assets_file = tmp_path / "assets.json"
    assets_file.write_text(json.dumps([_asset()]))
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(reg, "ASSETS_FILE", assets_file)
    monkeypatch.setattr(reg, "BACKUP_FILE", tmp_path / "assets.backup.json")
    monkeypatch.setattr(reg, "check_ssd", lambda: True)
    monkeypatch.setattr(dashboard, "HERE", tmp_path)
    monkeypatch.delenv(dashboard.TOKEN_ENV, raising=False)
    fake = SimpleNamespace(Popen=MagicMock(), run=MagicMock())
    monkeypatch.setattr(dashboard, "subprocess", fake)
    c = dashboard.app.test_client()
    c.subprocess = fake
    return c


# ── Escaped output ──────────────────────────────────────────────────────────

def test_query_string_message_is_escaped(client):
    body = client.get("/", query_string={"msg": XSS, "cls": '"><script>x()</script>'}).get_data(as_text=True)
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_logs_url_segment_is_escaped(client):
    payload = "<img src=x onerror=alert(1)>"
    body = client.get("/logs/" + quote(payload, safe="")).get_data(as_text=True)
    assert payload not in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


def test_stored_fields_and_log_text_are_escaped(client, tmp_path):
    reg.save([_asset(name=XSS, run_command='"><script>y()</script>', notes="</textarea>" + XSS)])
    (tmp_path / "logs" / "demo.log").write_text(XSS)
    for path in ("/", "/asset/demo", "/edit/demo", "/logs/demo"):
        body = client.get(path).get_data(as_text=True)
        assert "<script>" not in body, path


# ── Same-origin state changes ───────────────────────────────────────────────

def test_cross_origin_post_is_refused_and_runs_nothing(client):
    resp = client.post("/start/demo", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403
    client.subprocess.Popen.assert_not_called()


def test_post_without_origin_or_referer_is_refused(client):
    assert client.post("/remove/demo").status_code == 403
    assert reg.get("demo") is not None


def test_same_origin_post_is_allowed(client):
    resp = client.post("/start/demo", headers=SAME_ORIGIN)
    assert resp.status_code == 302
    client.subprocess.Popen.assert_called_once()


def test_same_origin_referer_is_allowed(client):
    resp = client.post("/remove/demo", headers={"Referer": "http://localhost/asset/demo"})
    assert resp.status_code == 302
    assert reg.get("demo") is None


# ── Host header and token ───────────────────────────────────────────────────

def test_non_loopback_host_header_is_refused_without_token(client):
    # A DNS-rebinding page reaches the app under its own domain name.
    assert client.get("/", base_url="http://attacker.example:7777").status_code == 403


def test_token_requires_basic_auth(client, monkeypatch):
    monkeypatch.setenv(dashboard.TOKEN_ENV, TOKEN)
    resp = client.get("/")
    assert resp.status_code == 401
    assert "Basic" in resp.headers["WWW-Authenticate"]
    assert client.get("/", headers=_basic("wrong")).status_code == 401
    assert client.get("/", headers=_basic(TOKEN)).status_code == 200


def test_token_allows_lan_host_header(client, monkeypatch):
    monkeypatch.setenv(dashboard.TOKEN_ENV, TOKEN)
    resp = client.get("/", base_url="http://192.168.1.20:7777", headers=_basic(TOKEN))
    assert resp.status_code == 200


def test_token_still_requires_same_origin_posts(client, monkeypatch):
    # Browsers re-send cached Basic credentials on cross-site requests too.
    monkeypatch.setenv(dashboard.TOKEN_ENV, TOKEN)
    resp = client.post("/start/demo", headers={**_basic(TOKEN), "Origin": "http://evil.example"})
    assert resp.status_code == 403
    client.subprocess.Popen.assert_not_called()


# ── Startup guards in main() ────────────────────────────────────────────────

@pytest.fixture
def run_main(monkeypatch):
    app_run = MagicMock()
    monkeypatch.setattr(dashboard.app, "run", app_run)
    monkeypatch.setattr(reg, "check_ssd", lambda: True)
    monkeypatch.delenv(dashboard.TOKEN_ENV, raising=False)

    def _run(*argv):
        monkeypatch.setattr(sys, "argv", ["dashboard.py", *argv])
        dashboard.main()
        return app_run

    return _run


def test_main_defaults_to_loopback(run_main):
    assert run_main().call_args.kwargs["host"] == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::"])
def test_main_refuses_network_host_without_token(run_main, host):
    with pytest.raises(SystemExit) as exc:
        run_main("--host", host)
    assert exc.value.code == 2


def test_main_allows_network_host_with_token(run_main, monkeypatch):
    monkeypatch.setenv(dashboard.TOKEN_ENV, TOKEN)
    assert run_main("--host", "0.0.0.0").call_args.kwargs["host"] == "0.0.0.0"


def test_main_refuses_debug_off_loopback(run_main, monkeypatch):
    monkeypatch.setenv(dashboard.TOKEN_ENV, TOKEN)
    with pytest.raises(SystemExit) as exc:
        run_main("--host", "0.0.0.0", "--debug")
    assert exc.value.code == 2
