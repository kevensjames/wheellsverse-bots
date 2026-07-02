from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.outreach_draft import OutreachDraftAdapter
from core.portfolio.actions import Action, ActionClass


def test_outreach_draft_serves_gtm_kit(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = OutreachDraftAdapter(generate=lambda p: (_ for _ in ()).throw(AssertionError("must not generate")))
    res = a.run(Action("draft_outreach", "cold_outreach", ActionClass.GREEN, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and res["bytes"] > 0
    assert res["source"] == "gtm_kit"
    assert res["verb"] == "draft_outreach"


def test_outreach_draft_falls_back_to_generation(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = OutreachDraftAdapter(generate=lambda p: "DRAFT-CONTENT")
    res = a.run(Action("draft_outreach", "cold_outreach", ActionClass.GREEN, [], "__nokit__", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["source"] == "generated"
