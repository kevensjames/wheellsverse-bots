"""Phase 6 — orchestrator sweep hardening: run_once ticks all 10, gates hold
(dormant by default, kill-switch halts), and one bad business never stalls the sweep."""
from core.portfolio import adapters, orchestrator, seed


def test_sweep_is_dormant_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("WMOS_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("WMOS_KILL", raising=False)
    seed.seed_all_loops()
    assert orchestrator.run_once(adapters.adapter_for, adapters.ctx_for)["status"] == "dormant"


def test_armed_sweep_ticks_all_ten(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    seed.seed_all_loops()
    res = orchestrator.run_once(adapters.adapter_for, adapters.ctx_for)
    assert res["status"] != "dormant"
    assert len(res["ticked"]) == 10  # every business got a tick this sweep


def test_kill_switch_halts_the_sweep(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.setenv("WMOS_KILL", "1")
    seed.seed_all_loops()
    assert orchestrator.run_once(adapters.adapter_for, adapters.ctx_for)["status"] == "killed"


def test_one_bad_business_does_not_stall_sweep(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    seed.seed_all_loops()

    def boom_adapter_for(step):
        if step.verb == "research_niche":
            class _Boom:
                def run(self, action):
                    raise RuntimeError("adapter blew up")
            return _Boom()
        return adapters.adapter_for(step)

    res = orchestrator.run_once(boom_adapter_for, adapters.ctx_for)
    assert len(res["ticked"]) == 10  # error isolated per business; sweep still covers all 10
