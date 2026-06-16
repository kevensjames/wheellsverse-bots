"""Phase 3 — pubmed_search tool: NCBI E-utilities esearch→esummary parsed into
citable results. Mocks urllib (no network)."""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools.base import ToolContext, ToolError
from app.services.tools.pubmed_search import PubMedSearchTool


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    url = getattr(req, "full_url", req)
    if "esearch" in url:
        return _Resp({"esearchresult": {"idlist": ["111", "222"]}})
    if "esummary" in url:
        return _Resp({"result": {
            "111": {"title": "BP control in stage II", "fulljournalname": "NEJM",
                    "pubdate": "2024 Jan 5",
                    "authors": [{"name": "Smith J"}, {"name": "Doe A"},
                                {"name": "Roe B"}, {"name": "Lee C"}]},
            "222": {"title": "Older study", "source": "Lancet", "pubdate": "2019",
                    "authors": []},
        }})
    return _Resp({})


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_returns_cited_articles(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    out = PubMedSearchTool().execute(_ctx(), query="hypertension")
    assert out["count"] == 2
    a = out["results"][0]
    assert a["pmid"] == "111"
    assert "pubmed.ncbi.nlm.nih.gov/111" in a["url"]
    assert a["journal"] == "NEJM" and a["year"] == "2024"
    assert "Smith J" in a["authors"] and "et al." in a["authors"]  # 4 authors → truncated
    assert "PMID" in out["note"]


def test_no_results(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"esearchresult": {"idlist": []}}))
    out = PubMedSearchTool().execute(_ctx(), query="zzznotathing")
    assert out["count"] == 0 and out["results"] == []


def test_blank_query_raises():
    with pytest.raises(ToolError):
        PubMedSearchTool().execute(_ctx(), query="   ")


def test_network_failure_is_tool_error(monkeypatch):
    def _boom(req, timeout=None):
        raise RuntimeError("network down")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(ToolError):
        PubMedSearchTool().execute(_ctx(), query="x")
