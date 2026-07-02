# tests/test_factory_runner_parse.py
from factory import runner


def test_parse_success_envelope():
    out = '{"type":"result","subtype":"success","is_error":false,' \
          '"total_cost_usd":0.0123,"result":"done","session_id":"s1"}'
    ok, cost, text = runner.parse_result(out)
    assert ok is True and abs(cost - 0.0123) < 1e-9 and text == "done"


def test_parse_error_envelope_is_not_ok():
    out = '{"is_error":true,"total_cost_usd":0.5,"result":"boom"}'
    ok, cost, text = runner.parse_result(out)
    assert ok is False and abs(cost - 0.5) < 1e-9


def test_parse_unparseable_fails_closed():
    ok, cost, text = runner.parse_result("not json at all")
    assert ok is False and cost == 0.0 and text == ""


def test_parse_non_object_fails_closed():
    ok, cost, text = runner.parse_result('["a","list"]')
    assert ok is False and cost == 0.0 and text == ""


def test_parse_missing_keys_defaults_safely():
    ok, cost, text = runner.parse_result('{"session_id":"s1"}')
    # no is_error -> treated as not-error (ok True), no cost -> 0.0, no result -> ""
    assert ok is True and cost == 0.0 and text == ""
