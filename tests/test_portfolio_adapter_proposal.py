from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.proposal import ProposalAdapter
from core.portfolio.actions import Action, ActionClass


def test_proposal_drafts_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = ProposalAdapter(generate=lambda p: "DRAFT-CONTENT")
    res = a.run(Action("draft_proposal", "kai.research", ActionClass.GREEN, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["verb"] == "draft_proposal"
