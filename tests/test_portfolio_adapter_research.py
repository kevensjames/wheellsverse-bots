from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.research import ResearchAdapter
from core.portfolio.actions import Action, ActionClass


def test_research_serves_gtm_kit(monkeypatch, tmp_path):
    # A business WITH a committed GTM kit is served from the kit (no generation).
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = ResearchAdapter(generate=lambda p: (_ for _ in ()).throw(AssertionError("must not generate")))
    res = a.run(Action("research_niche", "kai.research", ActionClass.GREEN, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and res["bytes"] > 0
    assert res["source"] == "gtm_kit"
    assert res["verb"] == "research_niche"


def test_research_falls_back_to_generation(monkeypatch, tmp_path):
    # A business WITHOUT a kit falls back to the injected generate callable.
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = ResearchAdapter(generate=lambda p: "DRAFT-CONTENT")
    res = a.run(Action("research_niche", "kai.research", ActionClass.GREEN, [], "__nokit__", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["source"] == "generated"
