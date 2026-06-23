from core.portfolio.actions import (
    Action, ActionClass, DispatchResult, check_preconditions, dispatch,
)


class _RecordingAdapter:
    def __init__(self):
        self.ran = []

    def run(self, action):
        self.ran.append(action.verb)
        return {"ok": True, "verb": action.verb}


def _mk(action_class, preconditions=None, verb="do_thing"):
    return Action(verb=verb, agent="kai", action_class=action_class,
                  preconditions=preconditions or [], business="n8n", payload={})


def _harness():
    queued, audited = [], []
    return queued, audited, (lambda a: queued.append(a)), (lambda r: audited.append(r))


def test_green_runs_immediately():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    res = dispatch(_mk(ActionClass.GREEN), adapter, {}, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "executed"
    assert adapter.ran == ["do_thing"]
    assert q == []
    assert a and a[0]["status"] == "executed"


def test_red_never_dispatches():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    res = dispatch(_mk(ActionClass.RED), adapter, {}, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "refused"
    assert adapter.ran == []          # adapter NEVER touched
    assert q == []                    # not even queued
    assert a and a[0]["status"] == "refused"


def test_amber_always_queues_never_runs():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    res = dispatch(_mk(ActionClass.AMBER), adapter, {}, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "queued"
    assert adapter.ran == []
    assert len(q) == 1


def test_auto_capped_runs_when_all_preconditions_truthy():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    action = _mk(ActionClass.AUTO_CAPPED, ["warmup_complete", "under_daily_cap"])
    ctx = {"warmup_complete": True, "under_daily_cap": True}
    res = dispatch(action, adapter, ctx, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "executed"
    assert adapter.ran == ["do_thing"]


def test_auto_capped_queues_when_a_precondition_fails():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    action = _mk(ActionClass.AUTO_CAPPED, ["warmup_complete", "under_daily_cap"])
    ctx = {"warmup_complete": True, "under_daily_cap": False}
    res = dispatch(action, adapter, ctx, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "queued"
    assert adapter.ran == []
    assert res.failed_preconditions == ["under_daily_cap"]
    assert len(q) == 1


def test_check_preconditions_reports_all_failures():
    action = _mk(ActionClass.AUTO_CAPPED, ["a", "b", "c"])
    ok, failed = check_preconditions(action, {"a": True, "b": False, "c": 0})
    assert ok is False
    assert failed == ["b", "c"]
