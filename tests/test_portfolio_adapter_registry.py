# tests/test_portfolio_adapter_registry.py
from core.portfolio import adapters, seed, loops, state
from core.portfolio.actions import ActionClass


def test_adapter_for_maps_known_verbs():
    step = loops.LoopStep("research_niche", "kai.research", ActionClass.GREEN, [])
    assert adapters.adapter_for(step).__class__.__name__ == "ResearchAdapter"
    unknown = loops.LoopStep("nope", "x", ActionClass.GREEN, [])
    assert adapters.adapter_for(unknown).run(_mk(unknown))["status"] == "noop"


def test_ctx_for_defaults_falsy():
    step = loops.LoopStep("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED,
                          ["warmup_complete"])
    assert adapters.ctx_for(step) == {}


def test_seed_writes_n8n_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    p = seed.seed_n8n_loop()
    assert p.exists()
    steps = loops.load_loop("n8n")
    verbs = [s.verb for s in steps]
    assert verbs[0] == "research_niche"
    assert "run_outreach_campaign" in verbs
    sends = next(s for s in steps if s.verb == "run_outreach_campaign")
    assert sends.action_class is ActionClass.AUTO_CAPPED


def _mk(step):
    from core.portfolio.actions import Action
    return Action(step.verb, step.agent, step.action_class, step.preconditions, "n8n", {})
