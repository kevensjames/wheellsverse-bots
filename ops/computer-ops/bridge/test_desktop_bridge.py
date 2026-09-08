"""Checks for the desktop bridge permission gate.

These run anywhere: every test drives `evaluate()` with the host probes stubbed, so the
policy logic is verified independently of whether THIS machine has TCC grants. The
separate live probe (probe_desktop.py) reports the real host state.

    python3 ops/computer-ops/bridge/test_desktop_bridge.py
    pytest ops/computer-ops/bridge/test_desktop_bridge.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import desktop_bridge as db  # noqa: E402
from desktop_bridge import BridgePolicy, Decision, Availability, evaluate  # noqa: E402


#: Real probes, captured once so each test can restore them. Reloading the module
#: instead would rebind the Decision/Availability enums and break `is` comparisons.
_REAL_PROBES = (db.has_interactive_desktop, db.probe_screen_recording,
                db.probe_accessibility, db.assert_tcc_identity)


def _restore_probes():
    (db.has_interactive_desktop, db.probe_screen_recording,
     db.probe_accessibility, db.assert_tcc_identity) = _REAL_PROBES


def _grant_everything():
    """Stub the host probes AND the TCC identity check.

    Identity is stubbed here so the policy tests can reach the gate steps that follow it;
    the identity rule itself is tested separately, unstubbed, below.
    """
    db.has_interactive_desktop = lambda: True
    db.probe_screen_recording = lambda: True
    db.probe_accessibility = lambda: True
    db.assert_tcc_identity = lambda: None


def _policy(**kw):
    base = dict(mode="EXECUTE_SCOPED", allowed_apps=frozenset({"Safari", "1Password"}),
                stopped=False, screen_capture_opt_in=True)
    base.update(kw)
    return BridgePolicy(**base)


def test_stop_outranks_everything():
    """STOP must deny even a verb that is otherwise fully permitted and granted."""
    _grant_everything()
    r = evaluate("list_windows", _policy(stopped=True), target_app="Safari")
    assert r.decision is Decision.DENY and "STOP" in r.reason


def test_unknown_verb_refused():
    _grant_everything()
    r = evaluate("run_shell_command", _policy())
    assert r.decision is Decision.DENY and "unknown verb" in r.reason


def test_mode_restricts_verbs():
    """OBSERVE cannot capture the screen even with capture opted in and TCC granted."""
    _grant_everything()
    r = evaluate("capture_screen", _policy(mode="OBSERVE"), target_app="Safari")
    assert r.decision is Decision.DENY and "autonomy mode" in r.reason


def test_unknown_mode_grants_nothing():
    _grant_everything()
    r = evaluate("list_windows", _policy(mode="TOTALLY_NEW_MODE"), target_app="Safari")
    assert r.decision is Decision.DENY


def test_credential_paths_denied_regardless_of_allowlist():
    _grant_everything()
    for path in ("/Users/x/.ssh/id_rsa", "/Users/x/.aws/credentials",
                 "/Users/x/Library/Keychains/login.keychain-db", "/Users/x/site.pem",
                 "/Users/x/Library/App/Cookies/Cookies.binarycookies"):
        r = evaluate("capture_window", _policy(), target_app="Safari", target_path=path)
        assert r.decision is Decision.DENY, path
        assert "forbidden credential pattern" in r.reason


def test_sensitive_app_capture_blocked_not_masked():
    """A password manager is on the allowlist here; capture must STILL be refused."""
    _grant_everything()
    r = evaluate("capture_window", _policy(), target_app="1Password")
    assert r.decision is Decision.DENY
    assert "blocked, not masked" in r.reason


def test_target_allowlist_is_default_deny():
    _grant_everything()
    r = evaluate("capture_window", _policy(allowed_apps=frozenset()), target_app="Safari")
    assert r.decision is Decision.DENY and "approved targets" in r.reason


def test_screen_capture_requires_opt_in():
    _grant_everything()
    r = evaluate("capture_window", _policy(screen_capture_opt_in=False), target_app="Safari")
    assert r.decision is Decision.DENY and "not opted in" in r.reason


def test_no_desktop_reports_truthfully():
    """A headless host must say DESKTOP_UNAVAILABLE, not pretend or crash later."""
    db.assert_tcc_identity = lambda: None
    db.has_interactive_desktop = lambda: False
    r = evaluate("list_windows", _policy(), target_app="Safari")
    assert r.decision is Decision.DENY
    assert r.availability is Availability.DESKTOP_UNAVAILABLE


def test_missing_tcc_reports_permission_not_granted():
    db.assert_tcc_identity = lambda: None   # identity is tested separately; reach the grant path
    db.has_interactive_desktop = lambda: True
    db.probe_accessibility = lambda: False
    r = evaluate("list_windows", _policy(), target_app="Safari")
    assert r.decision is Decision.DENY
    assert r.availability is Availability.PERMISSION_NOT_GRANTED
    assert "System Settings" in r.reason


def test_mutating_verb_requires_fresh_approval():
    """launch_app is consequential: the bridge never self-approves it."""
    _grant_everything()
    r = evaluate("launch_app", _policy(), target_app="Safari")
    assert r.decision is Decision.REQUIRE_APPROVAL


def test_read_only_verb_allowed_when_everything_satisfied():
    _grant_everything()
    r = evaluate("list_windows", _policy(), target_app="Safari")
    assert r.decision is Decision.ALLOW and r.availability is Availability.AVAILABLE


def test_policy_denial_precedes_os_probe():
    """A denied request must never touch the OS (and never trigger a TCC dialog)."""
    db.has_interactive_desktop = lambda: (_ for _ in ()).throw(
        AssertionError("probed the OS for an already-denied request"))
    r = evaluate("capture_screen", _policy(mode="OBSERVE"), target_app="Safari")
    assert r.decision is Decision.DENY


def test_generic_interpreter_is_not_a_valid_tcc_identity():
    """Granting TCC to python3/node/Terminal would grant it to everything they run."""
    ident = db.executable_identity()
    check_generic = ident["is_generic_interpreter"] or ident["bundle_id"] is None
    assert check_generic, ident
    assert not ident["acceptable"], ident
    try:
        db.assert_tcc_identity()
        raise AssertionError("a generic interpreter identity was accepted")
    except PermissionError as exc:
        assert "not a valid TCC identity" in str(exc)


def test_tcc_verbs_denied_under_interpreter_identity():
    """A verb needing a TCC grant must refuse before probing the OS."""
    _grant_everything()
    db.assert_tcc_identity = _REAL_PROBES[3]   # unstub: this test IS the identity rule
    for verb in ("list_windows", "capture_window"):
        r = evaluate(verb, _policy(), target_app="Safari")
        assert r.decision is Decision.DENY, verb
        assert r.availability is Availability.PERMISSION_NOT_GRANTED, verb
        assert "TCC identity" in r.reason, r.reason


def test_non_tcc_verb_unaffected_by_identity():
    """launch_app needs no TCC grant, so identity must not block it spuriously."""
    _grant_everything()
    r = evaluate("launch_app", _policy(), target_app="Safari")
    assert r.decision is Decision.REQUIRE_APPROVAL, r.reason


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, t in tests:
        _restore_probes()
        t()
        print(f"  PASS  {name}")
    _restore_probes()
    print(f"\n{len(tests)}/{len(tests)} desktop-bridge gate checks passed")
