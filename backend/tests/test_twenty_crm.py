"""twenty_crm — talks to a Twenty CRM over REST. Mocks urllib (no network);
payloads mirror Twenty's {"data": {...}} envelope. Asserts config-gating,
list/get/create, defensive extraction, and fail-soft error handling."""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools.base import ToolContext, ToolError
from app.services.tools.twenty_crm import TwentyCrmTool


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def _configured(monkeypatch):
    monkeypatch.setenv("TWENTY_API_URL", "https://crm.example.com")
    monkeypatch.setenv("TWENTY_API_KEY", "tok_test")


def test_missing_config_raises(monkeypatch):
    monkeypatch.delenv("TWENTY_API_URL", raising=False)
    monkeypatch.delenv("TWENTY_API_KEY", raising=False)
    with pytest.raises(ToolError):
        TwentyCrmTool().execute(_ctx(), action="list", object="people")


def test_list_people(monkeypatch):
    _configured(monkeypatch)
    payload = {"data": {"people": [
        {"id": "1", "name": {"firstName": "Ada", "lastName": "Lovelace"}},
        {"id": "2", "name": {"firstName": "Alan", "lastName": "Turing"}},
    ]}}
    captured = {}

    def _open(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        return _Resp(payload)
    monkeypatch.setattr("urllib.request.urlopen", _open)
    out = TwentyCrmTool().execute(_ctx(), action="list", object="people", limit=10, search="ada")
    assert out["count"] == 2 and out["results"][0]["id"] == "1"
    assert "limit=10" in captured["url"] and "search=ada" in captured["url"]
    assert captured["auth"] == "Bearer tok_test"


def test_get_company(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"data": {"company": {"id": "c1", "name": "Acme"}}}))
    out = TwentyCrmTool().execute(_ctx(), action="get", object="companies", record_id="c1")
    assert out["record"]["name"] == "Acme"


def test_get_requires_record_id(monkeypatch):
    _configured(monkeypatch)
    with pytest.raises(ToolError):
        TwentyCrmTool().execute(_ctx(), action="get", object="people")


def test_create_person(monkeypatch):
    _configured(monkeypatch)
    seen = {}

    def _open(req, timeout=None):
        seen["method"] = req.method
        seen["body"] = json.loads(req.data)
        return _Resp({"data": {"person": {"id": "new1"}}})
    monkeypatch.setattr("urllib.request.urlopen", _open)
    out = TwentyCrmTool().execute(
        _ctx(), action="create", object="people",
        data={"name": {"firstName": "Grace", "lastName": "Hopper"}},
    )
    assert seen["method"] == "POST"
    assert seen["body"]["name"]["firstName"] == "Grace"
    assert out["record"]["id"] == "new1"


def test_create_requires_data(monkeypatch):
    _configured(monkeypatch)
    with pytest.raises(ToolError):
        TwentyCrmTool().execute(_ctx(), action="create", object="people")


def test_bad_action_and_object_raise(monkeypatch):
    _configured(monkeypatch)
    with pytest.raises(ToolError):
        TwentyCrmTool().execute(_ctx(), action="delete", object="people")
    with pytest.raises(ToolError):
        TwentyCrmTool().execute(_ctx(), action="list", object="invoices")


def test_http_error_failsoft(monkeypatch):
    _configured(monkeypatch)
    import urllib.error

    def _boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(ToolError):
        TwentyCrmTool().execute(_ctx(), action="list", object="people")


def test_registered_only_when_configured(monkeypatch):
    from app.services.tools import build_default_registry
    monkeypatch.delenv("TWENTY_API_URL", raising=False)
    monkeypatch.delenv("TWENTY_API_KEY", raising=False)
    reg_off = build_default_registry(include_composio=False, include_mcp=False)
    assert "twenty_crm" not in reg_off.names()
    _configured(monkeypatch)
    reg_on = build_default_registry(include_composio=False, include_mcp=False)
    assert "twenty_crm" in reg_on.names()
