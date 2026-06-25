from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.site import SiteAdapter
from core.portfolio.actions import Action, ActionClass


def test_site_drafts_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = SiteAdapter(generate=lambda p: "<html>DRAFT-CONTENT</html>")
    res = a.run(Action("publish_landing_page", "site_builder", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["verb"] == "publish_landing_page"
