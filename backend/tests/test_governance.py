"""KAI governance — audit log + action decorator tests.

Each test points the audit log at a per-test tmp file so they don't
pollute the real data/governance/audit.jsonl.
"""
from __future__ import annotations

import json

import pytest

from app.services import governance
from app.services.governance import (
    PendingApproval,
    ScopeDenied,
    audited,
    audit_log as al,
    is_scope_enabled,
)


@pytest.fixture(autouse=True)
def _isolated_audit_log(tmp_path, monkeypatch):
    """Every test gets its own audit log file. Auto-applied because every
    governance call writes — no test should leak into another."""
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(al, "AUDIT_LOG_PATH", p)
    yield p


# ─── scope checks ────────────────────────────────────────────────────


def test_scope_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_TEST_THING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_TEST", raising=False)
    assert is_scope_enabled("test.thing") is False


def test_scope_enabled_specific(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_TEST_THING", "1")
    assert is_scope_enabled("test.thing") is True


def test_scope_enabled_via_wildcard_parent(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_TEST_THING", raising=False)
    monkeypatch.setenv("KAI_SCOPE_TEST", "1")
    # Parent KAI_SCOPE_TEST authorizes all test.* scopes
    assert is_scope_enabled("test.thing") is True
    assert is_scope_enabled("test.other") is True


def test_wildcard_does_not_reach_destructive_scopes(monkeypatch):
    """A module wildcard must never transitively authorize an irreversible
    action. KAI_SCOPE_SOL=1 is required by the Sol reminder scheduler; it must
    NOT also satisfy the gate for sol.transfer (live ACH)."""
    monkeypatch.delenv("KAI_SCOPE_SOL_TRANSFER", raising=False)
    monkeypatch.setenv("KAI_SCOPE_SOL", "1")
    # non-destructive still inherits the wildcard (no regression)
    assert is_scope_enabled("sol.manage") is True
    # destructive callers opt out of the wildcard
    assert is_scope_enabled("sol.transfer", allow_wildcard=False) is False

    calls = []

    @audited(scope="sol.transfer", destructive=True)
    def _transfer():
        calls.append(1)
        return "moved"

    with pytest.raises(ScopeDenied):
        _transfer(approved=True)
    assert calls == []          # the wildcard did not authorize live money

    # naming the scope exactly is the only way in
    monkeypatch.setenv("KAI_SCOPE_SOL_TRANSFER", "1")
    assert _transfer(approved=True) == "moved"


def test_scope_truthy_variants(monkeypatch):
    for v in ("1", "true", "yes", "ON", "True"):
        monkeypatch.setenv("KAI_SCOPE_X", v)
        assert is_scope_enabled("x") is True, f"failed for {v!r}"


def test_scope_falsy_variants(monkeypatch):
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("KAI_SCOPE_X", v)
        assert is_scope_enabled("x") is False, f"failed for {v!r}"


# ─── decorator: scope gate ───────────────────────────────────────────


def test_scope_denied_raises_and_audits(monkeypatch, _isolated_audit_log):
    monkeypatch.delenv("KAI_SCOPE_TEST_BLOCKED", raising=False)
    monkeypatch.delenv("KAI_SCOPE_TEST", raising=False)

    @audited(scope="test.blocked")
    def f():
        return "ran"

    with pytest.raises(ScopeDenied):
        f()
    rows = governance.list_actions()
    assert len(rows) == 1
    assert rows[0]["success"] is False
    assert "not enabled" in rows[0]["error"]


# ─── decorator: destructive approval ─────────────────────────────────


def test_destructive_without_approval_pending(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_DESTROY", "1")

    @audited(scope="test.destroy", destructive=True)
    def nuke():
        return "boom"

    with pytest.raises(PendingApproval):
        nuke()
    rows = governance.list_actions()
    assert rows[0]["destructive"] is True
    assert rows[0]["approved"] is False
    assert rows[0]["success"] is False


def test_destructive_with_approval_runs(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_DESTROY", "1")

    @audited(scope="test.destroy", destructive=True)
    def nuke():
        return {"deleted": 1}

    result = nuke(approved=True)
    assert result == {"deleted": 1}
    rows = governance.list_actions()
    assert rows[0]["success"] is True
    assert rows[0]["approved"] is True


def test_non_destructive_skips_approval(monkeypatch, _isolated_audit_log):
    """Read-only actions don't need approval — that's the whole point of
    the destructive flag."""
    monkeypatch.setenv("KAI_SCOPE_TEST_READ", "1")

    @audited(scope="test.read", destructive=False)
    def look():
        return "view"

    assert look() == "view"
    rows = governance.list_actions()
    assert rows[0]["success"] is True


# ─── decorator: exception path still audits ─────────────────────────


def test_exception_in_wrapped_function_is_audited(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_X", "1")

    @audited(scope="test.x")
    def boom():
        raise RuntimeError("intentional")

    with pytest.raises(RuntimeError):
        boom()
    rows = governance.list_actions()
    assert rows[0]["success"] is False
    assert "intentional" in rows[0]["error"]
    assert rows[0]["duration_ms"] is not None


# ─── audit log content ───────────────────────────────────────────────


def test_audit_log_has_id_and_timestamp(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_OK", "1")

    @audited(scope="test.ok")
    def ok():
        return "fine"

    ok()
    rows = governance.list_actions()
    assert rows[0]["id"]
    assert rows[0]["ts"]
    assert rows[0]["scope"] == "test.ok"
    assert rows[0]["actor"] == "operator"
    assert rows[0]["duration_ms"] is not None


def test_actor_can_be_overridden(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_AS", "1")

    @audited(scope="test.as")
    def f():
        return None

    f(actor="cron")
    rows = governance.list_actions()
    assert rows[0]["actor"] == "cron"


def test_secret_keys_redacted_in_inputs(monkeypatch, _isolated_audit_log):
    """Defense-in-depth: even if a caller passes a password/token via
    inputs, the audit log must redact it."""
    monkeypatch.setenv("KAI_SCOPE_TEST_R", "1")

    @audited(scope="test.r")
    def f(payload):
        return None

    f({"username": "alice", "password": "supersecret", "api_token": "abc123"})
    rows = governance.list_actions()
    # _args is a list of arg tuples — find the dict
    args = rows[0]["inputs"]["_args"]
    payload = args[0]
    assert payload["username"] == "alice"
    assert payload["password"] == "<redacted>"
    assert payload["api_token"] == "<redacted>"


def test_long_values_truncated_in_log(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_L", "1")

    @audited(scope="test.l")
    def f(big):
        return None

    f("x" * 2000)
    rows = governance.list_actions()
    val = rows[0]["inputs"]["_args"][0]
    assert len(val) < 600  # truncated to ~500 + suffix
    assert "(2000 chars)" in val


# ─── list_actions filtering + ordering ──────────────────────────────


def test_list_actions_newest_first(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_SEQ", "1")

    @audited(scope="test.seq")
    def f(i):
        return i

    for i in range(5):
        f(i)
    rows = governance.list_actions()
    # _args[0] is the i value of each call
    first_logged_i = rows[0]["inputs"]["_args"][0]
    assert first_logged_i == 4  # most recent first


def test_list_actions_filter_by_scope(monkeypatch, _isolated_audit_log):
    monkeypatch.setenv("KAI_SCOPE_TEST_A", "1")
    monkeypatch.setenv("KAI_SCOPE_TEST_B", "1")

    @audited(scope="test.a")
    def fa(): return None

    @audited(scope="test.b")
    def fb(): return None

    fa(); fb(); fa()
    only_a = governance.list_actions(scope="test.a")
    assert len(only_a) == 2
    assert all(r["scope"] == "test.a" for r in only_a)


def test_list_actions_empty_when_log_missing(tmp_path, monkeypatch):
    """Brand-new install — no audit.jsonl yet — must return [] not raise."""
    monkeypatch.setattr(al, "AUDIT_LOG_PATH", tmp_path / "never-created.jsonl")
    assert governance.list_actions() == []


# ─── action metadata ────────────────────────────────────────────────


def test_decorator_attaches_metadata():
    @audited(scope="test.meta", destructive=True)
    def f():
        return None

    assert f.__kai_action__["scope"] == "test.meta"
    assert f.__kai_action__["destructive"] is True
    assert f.__kai_action__["name"] == "f"


# ─── audit-log resilience ───────────────────────────────────────────


def test_audit_write_failure_does_not_break_action(monkeypatch, _isolated_audit_log):
    """If the audit log path becomes unwritable mid-flight, the action
    itself must still succeed — silent metrics > broken product."""
    monkeypatch.setenv("KAI_SCOPE_TEST_R", "1")
    # Point at a directory that can't be opened for append (/proc-style)
    monkeypatch.setattr(al, "AUDIT_LOG_PATH",
                        type("BadPath", (), {"open": lambda self, m: (_ for _ in ()).throw(OSError("nope")),
                                              "parent": _isolated_audit_log.parent,
                                              "exists": lambda self: False})())
    # The lambda above raises OSError; record_action catches & logs only.

    @audited(scope="test.r")
    def f():
        return "still works"

    # No raise — the action succeeds even though audit write fails
    assert f() == "still works"


# ─── destructive-scope invariant (central policy) ────────────────────
#
# THE INVARIANT: a module wildcard grants NON-destructive operations only.
# Every destructive scope must be named EXACTLY. Without this,
# KAI_SCOPE_SOL=1 — which the Sol reminder scheduler requires — also
# authorized sol.transfer (live ACH). 23 destructive scopes were reachable
# that way, including stripe.refund, dwolla.transfer and browser.execute.


def _discover_destructive_scopes() -> set[str]:
    """Read the source for `audited(scope="x", destructive=True)`.

    Static discovery (not a hand-maintained registry) so the inventory cannot
    drift: a new destructive scope is covered the moment it is written.
    """
    import pathlib
    import re

    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    pat = re.compile(r'audited\(\s*scope\s*=\s*"([a-z_.]+)"\s*,\s*destructive\s*=\s*True')
    found: set[str] = set()
    for py in app_dir.rglob("*.py"):
        found.update(pat.findall(py.read_text(encoding="utf-8", errors="replace")))
    return found


def test_destructive_scope_inventory_is_non_empty():
    """Guards the guard — if discovery silently returned nothing, the
    invariant test below would vacuously pass."""
    scopes = _discover_destructive_scopes()
    assert len(scopes) >= 15, f"suspiciously few destructive scopes found: {scopes}"
    assert "sol.transfer" in scopes


def test_no_destructive_scope_is_granted_by_a_module_wildcard(monkeypatch):
    """The core PR #43 regression, applied to EVERY destructive scope."""
    for scope in sorted(_discover_destructive_scopes()):
        norm = scope.replace(".", "_").replace("-", "_").upper()
        parent = norm.split("_")[0]
        monkeypatch.delenv(f"KAI_SCOPE_{norm}", raising=False)
        monkeypatch.setenv(f"KAI_SCOPE_{parent}", "1")      # module wildcard ON
        assert is_scope_enabled(scope, allow_wildcard=False) is False, (
            f"{scope} was granted by the KAI_SCOPE_{parent} wildcard"
        )
        monkeypatch.delenv(f"KAI_SCOPE_{parent}", raising=False)


@pytest.mark.parametrize("scope", ["sol.transfer", "stripe.refund", "dwolla.transfer",
                                   "planning.execute", "browser.execute"])
def test_destructive_scope_matrix(scope, monkeypatch):
    """wildcard-only → denied; exact → allowed; both → allowed;
    unrelated / missing → denied; approval remains independent."""
    norm = scope.replace(".", "_").upper()
    parent = norm.split("_")[0]

    def clear():
        for v in (f"KAI_SCOPE_{norm}", f"KAI_SCOPE_{parent}", "KAI_SCOPE_UNRELATED_THING"):
            monkeypatch.delenv(v, raising=False)

    calls = []

    @audited(scope=scope, destructive=True)
    def act():
        calls.append(1)
        return "done"

    clear()                                                   # 1. missing → denied
    with pytest.raises(ScopeDenied):
        act(approved=True)

    clear()                                                   # 2. wildcard only → denied
    monkeypatch.setenv(f"KAI_SCOPE_{parent}", "1")
    with pytest.raises(ScopeDenied):
        act(approved=True)

    clear()                                                   # 3. unrelated scope → denied
    monkeypatch.setenv("KAI_SCOPE_UNRELATED_THING", "1")
    with pytest.raises(ScopeDenied):
        act(approved=True)

    assert calls == [], "no side effect may run under any denied configuration"

    clear()                                                   # 4. exact only → allowed
    monkeypatch.setenv(f"KAI_SCOPE_{norm}", "1")
    assert act(approved=True) == "done"

    clear()                                                   # 5. wildcard + exact → allowed
    monkeypatch.setenv(f"KAI_SCOPE_{parent}", "1")
    monkeypatch.setenv(f"KAI_SCOPE_{norm}", "1")
    assert act(approved=True) == "done"

    clear()                                                   # 6. exact but unapproved → blocked
    monkeypatch.setenv(f"KAI_SCOPE_{norm}", "1")
    with pytest.raises(PendingApproval):
        act()


def test_non_destructive_still_inherits_wildcard(monkeypatch):
    """The fix must not over-tighten: convenience wildcards still work for
    non-destructive operations (sol.manage under KAI_SCOPE_SOL)."""
    monkeypatch.delenv("KAI_SCOPE_SOL_MANAGE", raising=False)
    monkeypatch.setenv("KAI_SCOPE_SOL", "1")
    assert is_scope_enabled("sol.manage") is True
