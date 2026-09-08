"""Checks for the containment attestation.

Runnable two ways so it works with or without the backend's pytest env:
    python3 ops/computer-ops/connector/test_attest.py     # standalone self-check
    pytest ops/computer-ops/connector/test_attest.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from attest import (  # noqa: E402
    NO_AUTONOMOUS_FANOUT,
    NO_INDEPENDENT_EGRESS,
    NO_UNTRUSTED_PLUGIN_LOADING,
    NOT_ON_THIS_PLATFORM,
    attest,
)

ALL_MUST_DISABLE = (
    NO_AUTONOMOUS_FANOUT + NO_INDEPENDENT_EGRESS
    + NO_UNTRUSTED_PLUGIN_LOADING + NOT_ON_THIS_PLATFORM
)


def _dump(*, sandbox_mode="read-only", approval="never", cloud_disabled=True,
          provider="kai-local", telemetry="DISABLED", omit=(), enable=()):
    """Build a synthetic composed-config dump."""
    rows = []
    for pid in ALL_MUST_DISABLE:
        if pid in omit:
            continue
        rows.append(f"- id: {pid}\n  name: '@deepseek-ai/dsh-{pid}'"
                    + ("" if pid in enable else "\n  disabled: true"))
    rows.append(f"- id: session-telemetry-otel\n  name: 'x'\n  config:\n    mode: {telemetry}")
    rows.append(f"- id: sandbox-policy\n  name: 'x'\n  config:\n    mode: {sandbox_mode}")
    rows.append(f"- id: approval\n  name: 'x'\n  config:\n    policy: {approval}")
    rows.append("- id: llm-deepseek\n  name: 'x'" + ("\n  disabled: true" if cloud_disabled else ""))
    rows.append(f"- id: agent-default-model\n  name: 'x'\n  config:\n    provider: {provider}")
    rows.append(f"- id: acp\n  name: 'x'\n  config:\n    provider: {provider}")
    return "\n".join(rows)


def test_clean_observe_local_passes():
    r = attest(_dump(), expect_sandbox_mode="read-only", expect_local_only=True,
               expect_approval_policy="never")
    assert r.ok, r.failures


def test_enabled_capability_fails():
    """A capability left mounted must fail, one case per containment group."""
    for pid in ("tool-ralph", "web-search-deepseek", "tool-skill"):
        r = attest(_dump(enable=(pid,)), expect_sandbox_mode="read-only",
                   expect_local_only=True, expect_approval_policy="never")
        assert not r.ok, f"{pid} left enabled but attestation passed"
        assert any(pid in f for f in r.failures)


def test_missing_id_fails_loudly():
    """An id absent from the tree is NOT treated as harmlessly-off.

    This is the upstream-rename guard: if DeepSeek renames `tool-ralph`, our overlay
    silently stops disabling anything, so absence must fail rather than pass.
    """
    r = attest(_dump(omit=("tool-ralph",)), expect_sandbox_mode="read-only",
               expect_local_only=True, expect_approval_policy="never")
    assert not r.ok
    assert any("tool-ralph" in f and "not present" in f for f in r.failures)


def test_telemetry_must_be_disabled():
    r = attest(_dump(telemetry="FEEDBACK_ONLY"), expect_sandbox_mode="read-only",
               expect_local_only=True, expect_approval_policy="never")
    assert not r.ok
    assert any("session-telemetry-otel" in f for f in r.failures)


def test_local_only_rejects_live_cloud_adapter():
    """LOCAL_ONLY must be structural: a mounted cloud adapter fails attestation."""
    r = attest(_dump(cloud_disabled=False), expect_sandbox_mode="read-only",
               expect_local_only=True, expect_approval_policy="never")
    assert not r.ok
    assert any("llm-deepseek" in f for f in r.failures)


def test_local_only_rejects_non_local_provider():
    r = attest(_dump(provider="deepseek-official"), expect_sandbox_mode="read-only",
               expect_local_only=True, expect_approval_policy="never")
    assert not r.ok
    assert any("agent-default-model" in f for f in r.failures)


def test_danger_full_access_never_accepted():
    """No KAI autonomy mode may run with the unrestricted file policy."""
    r = attest(_dump(sandbox_mode="danger-full-access"),
               expect_sandbox_mode="danger-full-access", expect_local_only=True,
               expect_approval_policy="never")
    assert not r.ok


def test_sandbox_mode_mismatch_fails():
    """Attestation binds to the mode the MISSION expects, not whatever composed."""
    r = attest(_dump(sandbox_mode="workspace-write"), expect_sandbox_mode="read-only",
               expect_local_only=True, expect_approval_policy="never")
    assert not r.ok
    assert any("sandbox-policy.mode" in f for f in r.failures)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\n{len(tests)}/{len(tests)} attestation checks passed")
