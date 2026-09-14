"""
tests/test_decision_engine.py — unit tests for core/decision_engine.py

Covers the pure decision logic: the Rule primitive (cooldown, evaluation,
serialization), the default rule factory, build_system_state (with lightweight
fakes standing in for the orchestrator / health registry), and the
DecisionEngine analyze / execute_action / run_cycle flow.
"""
from datetime import datetime

import pytest

from core import decision_engine
from core.decision_engine import (
    DecisionEngine,
    Rule,
    _build_default_rules,
    build_system_state,
)


# ─── Fakes ────────────────────────────────────────────────────────────────────

class FakeBot:
    def __init__(self, status="idle", last_run=None):
        self._status = {"status": status}
        if last_run is not None:
            self._status["last_run"] = last_run

    def get_status(self):
        return self._status


class FakeHealthRecord:
    def __init__(self, consecutive_failures):
        self.consecutive_failures = consecutive_failures


class FakeHealthRegistry:
    def __init__(self, avg=100, failed=None, records=None):
        self._avg = avg
        self._failed = failed or []
        self._records = records or {}

    def get_summary(self):
        return {"avg_health_score": self._avg}

    def get_failed_bots(self):
        return self._failed


class FakeOrchestrator:
    def __init__(self, bots=None, run_history=None):
        self.bots = bots or {}
        self.run_history = run_history or []
        self.calls = []

    def list_bots(self):
        return list(self.bots.keys())

    def run_bot(self, name):
        self.calls.append(("run_bot", name))

    def run_category(self, cat, parallel=False):
        self.calls.append(("run_category", cat, parallel))


class FakePipeline:
    def __init__(self):
        self.calls = []

    def run_pipeline(self, name):
        self.calls.append(name)
        return {"succeeded": 3, "total_bots": 4}


# ─── Rule ─────────────────────────────────────────────────────────────────────

def test_rule_can_trigger_initially():
    r = Rule("r", "d", lambda s: True, {"type": "noop"})
    assert r.can_trigger() is True


def test_rule_disabled_never_triggers():
    r = Rule("r", "d", lambda s: True, {"type": "noop"}, enabled=False)
    assert r.can_trigger() is False
    assert r.evaluate({}) is False


def test_rule_cooldown_blocks_retrigger():
    r = Rule("r", "d", lambda s: True, {"type": "noop"}, cooldown_minutes=60)
    r.mark_triggered()
    assert r.trigger_count == 1
    assert r.can_trigger() is False   # still within cooldown


def test_rule_cooldown_elapsed_allows_retrigger():
    r = Rule("r", "d", lambda s: True, {"type": "noop"}, cooldown_minutes=1)
    r.mark_triggered()
    r.last_triggered -= 120  # pretend 2 minutes passed
    assert r.can_trigger() is True


def test_rule_evaluate_true_and_false():
    assert Rule("r", "d", lambda s: s.get("go"), {}).evaluate({"go": True}) is True
    assert Rule("r", "d", lambda s: s.get("go"), {}).evaluate({"go": False}) is False


def test_rule_evaluate_swallows_condition_errors():
    def boom(_state):
        raise RuntimeError("bad condition")
    r = Rule("r", "d", boom, {})
    assert r.evaluate({}) is False


def test_rule_to_dict_serialization():
    r = Rule("morning", "desc", lambda s: True, {"type": "run_pipeline"},
             priority=1, cooldown_minutes=30)
    d = r.to_dict()
    assert d["name"] == "morning"
    assert d["priority"] == 1
    assert d["last_triggered"] is None
    r.mark_triggered()
    assert isinstance(r.to_dict()["last_triggered"], str)


# ─── default rules ────────────────────────────────────────────────────────────

def test_build_default_rules_shape():
    rules = _build_default_rules()
    assert len(rules) == 11
    names = {r.name for r in rules}
    assert "morning_blast" in names
    assert "retry_failed_bots" in names
    assert all(isinstance(r, Rule) for r in rules)
    assert all(1 <= r.priority <= 10 for r in rules)


def test_retry_failed_bots_rule_condition():
    rule = next(r for r in _build_default_rules() if r.name == "retry_failed_bots")
    assert rule.evaluate({"consecutive_failures": ["botA"]}) is True
    assert rule.evaluate({"consecutive_failures": []}) is False


def test_mass_failure_rule_threshold():
    rule = next(r for r in _build_default_rules() if r.name == "mass_failure_alert")
    assert rule.evaluate({"total_failed": 5}) is True
    assert rule.evaluate({"total_failed": 4}) is False


# ─── build_system_state ───────────────────────────────────────────────────────

def test_build_system_state_aggregates_metrics():
    orch = FakeOrchestrator(
        bots={
            "botA": FakeBot(status="error"),
            "botB": FakeBot(status="idle", last_run="2020-01-01T00:00:00"),
        },
        run_history=[
            {"bot": "blog_writer", "timestamp": datetime.now().strftime("%Y-%m-%d") + "T09:00"},
        ],
    )
    health = FakeHealthRegistry(
        avg=88,
        failed=["botA"],
        records={"botA": FakeHealthRecord(consecutive_failures=3)},
    )
    state = build_system_state(orch, health)
    assert state["total_bots"] == 2
    assert state["total_failed"] == 1
    assert state["failed_bots"] == ["botA"]
    assert state["consecutive_failures"] == ["botA"]
    assert state["avg_health_score"] == 88
    # today's run history contained "blog" -> content flag true
    assert state["content_ran_today"] is True
    assert state["hours_since_last_run"] > 0


def test_build_system_state_no_runs_defaults_high_idle():
    orch = FakeOrchestrator(bots={"botA": FakeBot()})
    health = FakeHealthRegistry()
    state = build_system_state(orch, health)
    assert state["hours_since_last_run"] == 999.0
    assert state["content_ran_today"] is False


# ─── DecisionEngine analyze / execute ─────────────────────────────────────────

@pytest.fixture
def eng():
    return DecisionEngine(FakeOrchestrator(), FakePipeline(), FakeHealthRegistry())


def test_analyze_triggers_matching_rules_by_priority(eng):
    eng.rules = [
        Rule("low", "d", lambda s: True, {"type": "noop"}, priority=5),
        Rule("high", "d", lambda s: True, {"type": "noop"}, priority=1),
        Rule("never", "d", lambda s: False, {"type": "noop"}, priority=2),
    ]
    triggered = eng.analyze({})
    assert [t["rule"] for t in triggered] == ["high", "low"]
    # both matching rules recorded a trigger
    assert all(r.trigger_count == (1 if r.name != "never" else 0) for r in eng.rules)


def test_analyze_respects_cooldown(eng):
    rule = Rule("once", "d", lambda s: True, {"type": "noop"}, cooldown_minutes=60)
    eng.rules = [rule]
    assert len(eng.analyze({})) == 1
    assert len(eng.analyze({})) == 0  # cooldown blocks second trigger


def test_execute_action_run_bot(eng):
    res = eng.execute_action({"type": "run_bot", "bot": "marketing/x"})
    assert res["status"] == "success"
    assert ("run_bot", "marketing/x") in eng.orchestrator.calls


def test_execute_action_run_pipeline(eng):
    res = eng.execute_action({"type": "run_pipeline", "pipeline": "morning_blast"})
    assert res["status"] == "success"
    assert "morning_blast" in eng.pipeline_engine.calls
    assert "3/4" in res["output"]


def test_execute_action_run_category(eng):
    res = eng.execute_action({"type": "run_category", "category": "sales"})
    assert res["status"] == "success"
    assert ("run_category", "sales", True) in eng.orchestrator.calls


def test_execute_action_noop(eng):
    assert eng.execute_action({"type": "noop"})["status"] == "success"


def test_execute_action_handles_errors(eng):
    def explode(_name):
        raise RuntimeError("boom")
    eng.orchestrator.run_bot = explode
    res = eng.execute_action({"type": "run_bot", "bot": "x"})
    assert res["status"] == "error"
    assert "boom" in res["output"]


def test_run_cycle_executes_and_logs(eng):
    eng.rules = [Rule("noop_rule", "d", lambda s: True, {"type": "noop"})]
    results = eng.run_cycle()
    assert len(results) == 1
    assert results[0]["rule"] == "noop_rule"
    assert results[0]["result"] == "success"
    assert len(eng.decision_log) == 1


# ─── get_decision_engine factory ──────────────────────────────────────────────

def test_get_decision_engine_requires_deps_first_call(monkeypatch):
    monkeypatch.setattr(decision_engine, "_engine", None)
    with pytest.raises(ValueError):
        decision_engine.get_decision_engine()


def test_get_decision_engine_is_singleton(monkeypatch):
    monkeypatch.setattr(decision_engine, "_engine", None)
    e1 = decision_engine.get_decision_engine(
        FakeOrchestrator(), FakePipeline(), FakeHealthRegistry())
    e2 = decision_engine.get_decision_engine()
    assert e1 is e2
