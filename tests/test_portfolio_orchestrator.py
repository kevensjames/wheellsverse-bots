import json
from core.portfolio import orchestrator, paths


class _OkAdapter:
    def run(self, action):
        return {"ran": action.verb}


def _seed_loop(tmp_path, slug, verb="research_niche"):
    d = tmp_path / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "loop.json").write_text(json.dumps(
        {"business": slug, "steps": [{"verb": verb, "agent": "kai", "class": "green"}]}))


def test_dormant_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("WMOS_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("WMOS_KILL", raising=False)
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {})
    assert res["status"] == "dormant"


def test_kill_switch_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.setenv("WMOS_KILL", "1")
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {})
    assert res["status"] == "killed"


def test_enabled_sweep_ticks_selected_business(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    _seed_loop(tmp_path, "n8n")
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {}, slugs=["n8n"])
    assert res["status"] == "ran"
    assert res["ticked"]["n8n"] == "executed"


def test_enabled_sweep_with_no_loop_returns_none_for_business(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {}, slugs=["ghost"])
    assert res["ticked"]["ghost"] is None      # no loop.json yet -> nothing ticked


def test_sweep_isolates_per_business_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    from core.portfolio.actions import DispatchResult

    def fake_tick(slug, adapter_for, ctx_for):
        if slug == "bad":
            raise RuntimeError("boom")
        return DispatchResult("executed", "ok")

    monkeypatch.setattr(orchestrator.loops, "tick", fake_tick)
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {}, slugs=["bad", "good"])
    assert res["status"] == "ran"
    assert res["ticked"]["bad"] == "error"      # the failing business is isolated
    assert res["ticked"]["good"] == "executed"  # the sweep continued to the next one


def test_persisted_arm_and_kill_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("WMOS_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("WMOS_KILL", raising=False)
    # dormant + not killed by default
    assert orchestrator.is_enabled() is False
    assert orchestrator.kill_engaged() is False
    # arm via persisted flag
    orchestrator.set_enabled(True)
    assert orchestrator.is_enabled() is True
    assert orchestrator.control_state() == {"enabled": True, "kill": False}
    # kill via persisted flag (checked first in run_once)
    orchestrator.engage_kill()
    assert orchestrator.kill_engaged() is True
    res = orchestrator.run_once(lambda s: None, lambda s: {}, slugs=["n8n"])
    assert res["status"] == "killed"
    # disengage kill, disarm
    orchestrator.disengage_kill()
    orchestrator.set_enabled(False)
    assert orchestrator.kill_engaged() is False
    assert orchestrator.is_enabled() is False


def test_env_still_overrides_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    # env arms even with no persisted flag
    assert orchestrator.is_enabled() is True
