"""
tests/test_trending.py — unit tests for core/trending.py

Focuses on the pure-logic surface: TrendItem serialization, niche/count
helpers, and the query/summary/persistence methods of TrendingEngine. The
network fetch methods (_fetch_news, _fetch_reddit, ...) and GPT angle
generation are not exercised — the engine's _trends list is populated
directly so tests stay hermetic.
"""
import pytest

from core import trending
from core.trending import (
    TrendingEngine,
    TrendItem,
    _count_by,
    _query_to_niche,
    _sub_to_niche,
)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(trending, "DATA_FILE", tmp_path / "trending.json")
    return TrendingEngine()


def _item(topic, source="news", score=50.0, niche="general", angle=""):
    t = TrendItem(topic, source, score, headline=topic, niche=niche)
    t.angle = angle
    return t


# ── TrendItem ─────────────────────────────────────────────────────────────────

def test_trend_item_roundtrip():
    t = TrendItem("Bitcoin surging", "crypto", 88.0, headline="Bitcoin surging",
                  url="http://x", niche="crypto")
    t.angle = "buy the dip"
    restored = TrendItem.from_dict(t.to_dict())
    assert restored.topic == "Bitcoin surging"
    assert restored.source == "crypto"
    assert restored.score == 88.0
    assert restored.niche == "crypto"
    assert restored.angle == "buy the dip"


def test_trend_item_from_dict_defaults():
    t = TrendItem.from_dict({"topic": "x", "source": "news", "score": 10.0})
    assert t.niche == "general"
    assert t.angle == ""
    assert t.headline == ""


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sub,expected", [
    ("CryptoCurrency", "crypto"),
    ("Bitcoin", "crypto"),
    ("investing", "investing"),
    ("personalfinance", "investing"),
    ("passive_income", "passive_income"),
    ("Entrepreneur", "general"),
    ("artificial", "ai_tools"),
    ("SomethingElse", "general"),
])
def test_sub_to_niche(sub, expected):
    assert _sub_to_niche(sub) == expected


@pytest.mark.parametrize("query,expected", [
    ("#crypto", "crypto"),
    ("bitcoin news", "crypto"),
    ("#AI", "ai_tools"),
    ("#passiveincome", "passive_income"),
    ("random topic", "general"),
])
def test_query_to_niche(query, expected):
    assert _query_to_niche(query) == expected


def test_count_by():
    items = [_item("a", source="news"), _item("b", source="news"),
             _item("c", source="reddit")]
    assert _count_by(items, "source") == {"news": 2, "reddit": 1}
    assert _count_by([], "source") == {}


# ── query methods ─────────────────────────────────────────────────────────────

def test_get_top_sorts_and_limits(engine):
    engine._trends = [_item("low", score=10.0), _item("high", score=90.0),
                      _item("mid", score=50.0)]
    top = engine.get_top(limit=2)
    assert [t["topic"] for t in top] == ["high", "mid"]


def test_get_top_filters_by_niche(engine):
    engine._trends = [_item("c", niche="crypto", score=80.0),
                      _item("a", niche="ai_tools", score=90.0)]
    res = engine.get_top(niche="crypto")
    assert [t["topic"] for t in res] == ["c"]


def test_get_top_general_niche_returns_all(engine):
    engine._trends = [_item("c", niche="crypto"), _item("a", niche="ai_tools")]
    assert len(engine.get_top(niche="general")) == 2


def test_get_best_for_content_prefers_angled(engine):
    engine._trends = [_item("no angle", score=99.0),
                      _item("has angle", score=50.0, angle="angle!")]
    best = engine.get_best_for_content()
    assert best["topic"] == "has angle"


def test_get_best_for_content_falls_back_when_no_angles(engine):
    engine._trends = [_item("a", score=10.0), _item("b", score=80.0)]
    assert engine.get_best_for_content()["topic"] == "b"


def test_get_best_for_content_none_when_empty(engine):
    engine._trends = []
    assert engine.get_best_for_content() is None


def test_get_best_for_content_niche_preference(engine):
    engine._trends = [
        _item("crypto item", score=60.0, niche="crypto", angle="a"),
        _item("ai item", score=99.0, niche="ai_tools", angle="a"),
    ]
    assert engine.get_best_for_content(niche="crypto")["topic"] == "crypto item"


def test_get_viral_opportunities_threshold(engine):
    engine._trends = [_item("hot", score=75.0), _item("cold", score=40.0)]
    viral = engine.get_viral_opportunities()
    assert [t["topic"] for t in viral] == ["hot"]


# ── summary ───────────────────────────────────────────────────────────────────

def test_summary_empty(engine):
    s = engine.summary()
    assert s["total_trends"] == 0
    assert s["last_refresh"] == "never"
    assert s["top_topic"] is None


def test_summary_with_trends(engine):
    engine._trends = [_item("top", source="news", score=90.0, niche="crypto"),
                      _item("other", source="reddit", score=75.0, niche="crypto")]
    s = engine.summary()
    assert s["total_trends"] == 2
    assert s["by_source"] == {"news": 1, "reddit": 1}
    assert s["by_niche"] == {"crypto": 2}
    assert s["viral_opportunities"] == 2
    assert s["top_topic"] == "top"


# ── persistence ───────────────────────────────────────────────────────────────

def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "trending.json"
    monkeypatch.setattr(trending, "DATA_FILE", path)
    e1 = TrendingEngine()
    e1._trends = [_item("Bitcoin surging", source="crypto", score=88.0, niche="crypto")]
    e1._save()
    assert path.exists()
    e2 = TrendingEngine()
    assert len(e2._trends) == 1
    assert e2._trends[0].topic == "Bitcoin surging"


def test_load_survives_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "trending.json"
    path.write_text("{{ not json")
    monkeypatch.setattr(trending, "DATA_FILE", path)
    e = TrendingEngine()  # should not raise
    assert e._trends == []


# ── module wrappers ───────────────────────────────────────────────────────────

def test_module_wrappers(tmp_path, monkeypatch):
    monkeypatch.setattr(trending, "DATA_FILE", tmp_path / "trending.json")
    monkeypatch.setattr(TrendingEngine, "_instance", None)
    TrendingEngine.get()._trends = [_item("x", score=80.0, angle="a")]
    assert trending.get_top(limit=1)[0]["topic"] == "x"
    assert trending.get_best_topic()["topic"] == "x"
