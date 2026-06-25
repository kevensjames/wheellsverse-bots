from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.workflow import WorkflowPackAdapter
from core.portfolio.actions import Action, ActionClass


def test_workflow_drafts_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    a = WorkflowPackAdapter(generate=lambda p: "DRAFT-CONTENT")
    res = a.run(Action("build_workflow_pack", "kai.planning", ActionClass.GREEN, [], "n8n", {}))
    p = Path(res["artifact"])
    assert p.exists() and "DRAFT-CONTENT" in p.read_text()
    assert res["verb"] == "build_workflow_pack"
