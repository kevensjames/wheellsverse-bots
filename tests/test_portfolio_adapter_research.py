from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.research import ResearchAdapter
from core.portfolio.actions import Action, ActionClass


def test_research_drafts_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = ResearchAdapter(generate=lambda p: "DRAFT-CONTENT")
    res = a.run(Action("research_niche", "kai.research", ActionClass.GREEN, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["verb"] == "research_niche"
