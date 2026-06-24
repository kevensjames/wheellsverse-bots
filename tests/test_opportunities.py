from core import opportunities


def _fake_get_json(url, timeout=8):
    if "algolia" in url:
        return {"hits": [
            {"title": "Show HN: I built a SaaS automation tool", "url": "https://x/1", "points": 120, "objectID": "1"},
            {"title": "A quiet poem about the sea", "url": "https://x/2", "points": 5, "objectID": "2"},
        ]}
    if "github" in url:
        return {"items": [
            {"name": "coolcrm", "description": "open-source CRM alternative", "html_url": "https://gh/cc", "stargazers_count": 900},
        ]}
    return {}


def test_scan_ranks_real_signal_and_drops_noise(monkeypatch):
    monkeypatch.setattr("core.opportunities._get_json", _fake_get_json)
    out = opportunities.scan(limit=10, now=1_700_000_000)
    titles = [o["title"] for o in out["opportunities"]]
    assert any("SaaS automation" in t for t in titles)   # high-signal surfaces
    assert not any("poem" in t for t in titles)          # 0-signal noise dropped
    assert out["feeds"]["hackernews"] is True and out["feeds"]["github"] is True
    assert out["feeds"]["reddit"] is False               # not connected, not faked
    assert out["opportunities"][0]["score"] >= out["opportunities"][-1]["score"]


def test_scan_feed_failure_is_honest(monkeypatch):
    def boom(url, timeout=8):
        raise RuntimeError("network down")
    monkeypatch.setattr("core.opportunities._get_json", boom)
    out = opportunities.scan(now=1_700_000_000)
    assert out["feeds"]["hackernews"] is False
    assert out["feeds"]["github"] is False
    assert out["opportunities"] == [] and out["connected_feeds"] == 0
