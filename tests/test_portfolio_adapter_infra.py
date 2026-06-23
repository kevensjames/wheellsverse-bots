from __future__ import annotations

from pathlib import Path

from core.portfolio.adapters.infra import InfraAdapter
from core.portfolio.actions import Action, ActionClass


def test_infra_drafts_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    res = InfraAdapter().run(Action("deploy_demo_instance", "infra", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    assert res["status"] == "draft"
    p = Path(res["artifact"])
    assert p.exists() and "TBD" in p.read_text()
