from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.outreach_draft import OutreachDraftAdapter
from core.portfolio.actions import Action, ActionClass


def test_outreach_draft_drafts_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = OutreachDraftAdapter(generate=lambda p: "DRAFT-CONTENT")
    res = a.run(Action("draft_outreach", "cold_outreach", ActionClass.GREEN, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["verb"] == "draft_outreach"
