"""Negative tests for the plugin allow-list.

The point of every test here is that something UNEXPECTED must stop the mission. A
deny-list passes when the world matches its assumptions; an allow-list has to prove it
rejects the world it did not anticipate.

    python3 ops/computer-ops/connector/test_allowlist.py
    pytest ops/computer-ops/connector/test_allowlist.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from allowlist import (ALLOWED_ENABLED, REQUIRED_DISABLED, REQUIRED_ENABLED,  # noqa: E402
                       composition_digest, parse_entries, redefined_ids, verify_composition)


def _dump(extra: str = "", drop: set[str] | None = None,
          enable: set[str] | None = None, rename: dict[str, str] | None = None) -> str:
    drop, enable, rename = drop or set(), enable or set(), rename or {}
    rows = []
    for pid, name in sorted(ALLOWED_ENABLED):
        if pid in drop:
            continue
        rows.append(f"- id: {pid}\n  name: '{rename.get(pid, name)}'")
    for pid in sorted(REQUIRED_DISABLED):
        if pid in drop:
            continue
        row = f"- id: {pid}\n  name: '@deepseek-ai/dsh-{pid}'"
        if pid not in enable:
            row += "\n  disabled: true"
        rows.append(row)
    return "\n".join(rows) + ("\n" + extra if extra else "")


def test_clean_composition_passes():
    rep = verify_composition(_dump())
    assert rep.ok, rep.violations
    assert len(rep.digest) == 64


def test_unknown_shell_plugin_rejected():
    """A fake shell plugin nobody anticipated must stop the mission."""
    rep = verify_composition(_dump(
        "- id: kai-evil-shell\n  name: '@evil/dsh-tool-shell'"))
    assert not rep.ok
    assert any("UNKNOWN plugin 'kai-evil-shell'" in v for v in rep.violations)


def test_unknown_network_plugin_rejected():
    rep = verify_composition(_dump(
        "- id: sneaky-fetch\n  name: '@deepseek-ai/dsh-web-fetch-http-v2'"))
    assert not rep.ok
    assert any("UNKNOWN plugin 'sneaky-fetch'" in v for v in rep.violations)


def test_package_substituted_under_permitted_id_rejected():
    """A permitted id must not be a free slot for any package.

    This is the attack a pure id-list misses: keep `tool-fs`, swap what it resolves to.
    """
    rep = verify_composition(_dump(rename={"tool-fs": "@evil/dsh-tool-fs"}))
    assert not rep.ok
    assert any("package substituted" in v for v in rep.violations)


def test_reenabled_shell_rejected():
    """tool-bash coming back must fail, whatever the reason."""
    rep = verify_composition(_dump(enable={"tool-bash"}))
    assert not rep.ok
    assert any("'tool-bash' MUST be disabled" in v for v in rep.violations)


def test_reenabled_web_tools_rejected():
    for pid in ("tool-web", "web-fetch-http", "web-search-deepseek"):
        rep = verify_composition(_dump(enable={pid}))
        assert not rep.ok, pid
        assert any(f"{pid!r} MUST be disabled" in v for v in rep.violations)


def test_missing_control_plugin_rejected():
    """Losing a control is more dangerous than gaining a tool, and easier to miss."""
    for pid in sorted(REQUIRED_ENABLED):
        rep = verify_composition(_dump(drop={pid}))
        assert not rep.ok, pid
        assert any(f"required plugin {pid!r} is absent" in v for v in rep.violations)


def test_vanished_denial_target_rejected():
    """If upstream renames tool-bash away, its denial can no longer be asserted."""
    rep = verify_composition(_dump(drop={"tool-bash"}))
    assert not rep.ok
    assert any("expected present-but-disabled is ABSENT" in v for v in rep.violations)


def test_id_redefined_to_another_package_rejected():
    """Layered config may re-state an id; it may not change what that id resolves to."""
    rep = verify_composition(_dump("- id: tool-fs\n  name: '@evil/dsh-tool-fs'"))
    assert not rep.ok
    assert any("redefined across layers" in v for v in rep.violations)


def test_id_restated_with_same_package_is_allowed():
    """Repetition is how layering works and must NOT be treated as a violation."""
    rep = verify_composition(_dump("- id: tool-fs\n  name: '@deepseek-ai/dsh-tool-fs'"))
    assert rep.ok, rep.violations


def test_digest_changes_when_composition_changes():
    base = composition_digest(parse_entries(_dump()))
    added = composition_digest(parse_entries(_dump("- id: x\n  name: 'y'")))
    assert base != added
    # and is stable for identical input
    assert base == composition_digest(parse_entries(_dump()))


def test_digest_ignores_per_mission_config_values():
    """Digest must be stable across missions or it is useless as a tripwire.

    Config values carry the volume mount and workspace path, which differ every run.
    """
    a = composition_digest(parse_entries(_dump() + "\n  config:\n    root: /Volumes/KAI-a/s"))
    b = composition_digest(parse_entries(_dump() + "\n  config:\n    root: /Volumes/KAI-b/s"))
    assert a == b


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, t in tests:
        t()
        print(f"  PASS  {name}")
    print(f"\n{len(tests)}/{len(tests)} allow-list negative checks passed")
