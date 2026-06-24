from core.portfolio import adapters, preconditions, seed, state, loops
from core.portfolio.actions import Action, ActionClass


def _advance_to_outreach(slug="n8n"):
    seed.seed_n8n_loop()
    for v in ["research_niche", "build_workflow_pack", "generate_lead_list", "draft_outreach"]:
        state.mark_completed(slug, v)


def test_auto_fires_when_all_preconditions_met(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _advance_to_outreach()
    # satisfy run_outreach_campaign's [warmup_complete, campaign_approved_once, under_daily_cap]
    state.set_flag("n8n", "warmup_complete", True)
    aid = state.queue_approval(Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    state.resolve_approval(aid, "approved")               # campaign_approved_once -> True
    res = loops.tick("n8n", adapters.adapter_for, preconditions.make_ctx_for("n8n"))
    assert res.status == "executed"                       # auto-fired (inert would_send)
    assert res.output == {"status": "would_send",
                          "note": "gated send — wire cold_outreach.send_sequences(confirm=True, live=True) on approval",
                          "verb": "run_outreach_campaign"}


def test_queues_when_a_precondition_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _advance_to_outreach()
    # warmup flag NOT set -> still queues
    aid = state.queue_approval(Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    state.resolve_approval(aid, "approved")
    res = loops.tick("n8n", adapters.adapter_for, preconditions.make_ctx_for("n8n"))
    assert res.status == "queued"
