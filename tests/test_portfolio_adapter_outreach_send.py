from __future__ import annotations

from core.portfolio.adapters.outreach_send import OutreachSendAdapter
from core.portfolio.actions import Action, ActionClass


def test_outreach_send_is_gated_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    res = OutreachSendAdapter().run(
        Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {})
    )
    assert res["status"] == "would_send"
    assert "artifact" not in res
