"""sec_edgar_search + courtlistener_search — parse official-API responses into
citable results, fail-soft. Mocks urllib (no network); payloads mirror the real
EDGAR FTS + CourtListener v4 shapes."""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools.base import ToolContext, ToolError
from app.services.tools.courtlistener_search import CourtListenerSearchTool
from app.services.tools.sec_edgar_search import SecEdgarSearchTool


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


# ─── SEC EDGAR ───────────────────────────────────────────────────────

_EDGAR = {"hits": {"hits": [
    {"_id": "0000035527-22-000119:fitb10k.pdf",
     "_source": {"ciks": ["0000035527"],
                 "display_names": ["FIFTH THIRD BANCORP (FITB) (CIK 0000035527)"],
                 "form": "10-K", "file_date": "2022-02-25", "adsh": "0000035527-22-000119"}},
]}}


def test_edgar_parses_filing(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp(_EDGAR))
    out = SecEdgarSearchTool().execute(_ctx(), query="climate risk", forms="10-K")
    assert out["count"] == 1
    r = out["results"][0]
    assert "FIFTH THIRD" in r["company"] and r["form"] == "10-K" and r["date"] == "2022-02-25"
    assert r["accession"] == "0000035527-22-000119"
    # cik leading zeros stripped; accession dashes removed in the doc URL
    assert "/edgar/data/35527/000003552722000119/fitb10k.pdf" in r["url"]
    assert "SEC:" in out["note"]


def test_edgar_blank_query_raises():
    with pytest.raises(ToolError):
        SecEdgarSearchTool().execute(_ctx(), query="  ")


def test_edgar_network_failure(monkeypatch):
    def _boom(req, timeout=None):
        raise RuntimeError("edgar down")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(ToolError):
        SecEdgarSearchTool().execute(_ctx(), query="x")


# ─── CourtListener ───────────────────────────────────────────────────

_CL = {"results": [
    {"caseName": "Miranda v. Arizona", "court": "Supreme Court",
     "dateFiled": "1966-06-13", "citation": ["384 U.S. 436"], "docketNumber": "759",
     "absolute_url": "/opinion/107252/miranda-v-arizona/"},
]}


def test_courtlistener_parses_case(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp(_CL))
    out = CourtListenerSearchTool().execute(_ctx(), query="custodial interrogation")
    assert out["count"] == 1
    r = out["results"][0]
    assert r["case"] == "Miranda v. Arizona" and r["citation"] == "384 U.S. 436"
    assert r["url"] == "https://www.courtlistener.com/opinion/107252/miranda-v-arizona/"
    assert "not legal advice" in out["note"]


def test_courtlistener_blank_query_raises():
    with pytest.raises(ToolError):
        CourtListenerSearchTool().execute(_ctx(), query="")


def test_courtlistener_no_results(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp({"results": []}))
    out = CourtListenerSearchTool().execute(_ctx(), query="zzz")
    assert out["count"] == 0 and out["results"] == []


# ─── WHO GHO ─────────────────────────────────────────────────────────

from app.services.tools.who_search import WhoSearchTool  # noqa: E402

_WHO = {"value": [
    {"IndicatorCode": "NCD_HYP_PREVALENCE_A",
     "IndicatorName": "Hypertension among adults 30-79, prevalence, age-standardized"},
    {"IndicatorCode": "NCD_HYP_CONTROL_C", "IndicatorName": "Hypertension: effective treatment coverage"},
]}


def test_who_parses_indicators(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp(_WHO))
    out = WhoSearchTool().execute(_ctx(), query="hypertension")
    assert out["count"] == 2
    r = out["results"][0]
    assert r["code"] == "NCD_HYP_PREVALENCE_A" and "Hypertension" in r["name"]
    assert "ghoapi.azureedge.net/api/NCD_HYP_PREVALENCE_A" in r["url"]
    assert "WHO GHO" in out["note"]


def test_who_blank_query_raises():
    with pytest.raises(ToolError):
        WhoSearchTool().execute(_ctx(), query="  ")
