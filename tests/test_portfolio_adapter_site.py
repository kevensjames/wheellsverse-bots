from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.site import SiteAdapter
from core.portfolio.actions import Action, ActionClass


def test_site_serves_gtm_kit(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = SiteAdapter(generate=lambda p: (_ for _ in ()).throw(AssertionError("must not generate")))
    res = a.run(Action("publish_landing_page", "site_builder", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and res["bytes"] > 0
    assert res["source"] == "gtm_kit"
    assert res["verb"] == "publish_landing_page"


def test_site_falls_back_to_generation(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = SiteAdapter(generate=lambda p: "<html>DRAFT-CONTENT</html>")
    res = a.run(Action("publish_landing_page", "site_builder", ActionClass.AUTO_CAPPED, [], "__nokit__", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["source"] == "generated"
