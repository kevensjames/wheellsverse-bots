"""Tests for :mod:`infra.brain.debug.repair_generator`.

Coverage targets:
  * No emitted patch ever contains a ``<placeholder>`` string.
  * Each transform produces structurally-valid unified diffs.
  * The generator returns ``None`` (declines) cleanly when there is
    nothing to do, when the file content has no candidate site, or when
    the supplied analysis routes to no transform.
  * ``validate_patch`` accepts every non-empty diff against the
    pre-image content (verified by setting up a real tmp git repo).
  * The :func:`suggest_fix` integration is fully backwards compatible:
    contextless callers see identical output to the pre-generator
    behavior, and ``context``-aware callers fall back to the template
    path the moment the generator declines.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from infra.brain.debug import ci_auto_fix
from infra.brain.debug.ci_auto_fix import suggest_fix
from infra.brain.debug.ci_autonomous_repair import validate_patch
from infra.brain.debug.repair_generator import (
    FIX_TYPE_EXECUTOR,
    FIX_TYPE_PARSER,
    FIX_TYPE_SAFETY,
    FailureContext,
    MAX_PATCHED_LINES,
    MIN_GENERATOR_CONFIDENCE,
    RepairGenerator,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_./\- ]+>")


def _has_placeholders(patch: str) -> bool:
    """Same regex as ``ci_autonomous_repair._PLACEHOLDER_RE``."""
    if not patch:
        return False
    return bool(PLACEHOLDER_RE.search(patch))


def _make_git_repo(root: Path) -> None:
    """Initialise a real git repo at ``root`` so ``validate_patch`` works."""
    subprocess.run(
        ["git", "init", "-q"], cwd=root, check=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    subprocess.run(
        ["git", "config", "user.email", "ci@example.com"],
        cwd=root, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "ci"], cwd=root, check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=root, check=True,
    )


def _commit_file(root: Path, relpath: str, content: str) -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", relpath], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", f"add {relpath}"], cwd=root, check=True,
    )


# ── Sample sources used by multiple tests ──────────────────────────────────


_BASEEXC_SOURCE = textwrap.dedent('''\
    """sample module — has a BaseException catch we should narrow."""

    class Worker:
        def run(self, task):
            try:
                return task.execute()
            except BaseException as e:
                return {"error": str(e)}

        def other(self):
            return None
''')


_PARSER_SOURCE = textwrap.dedent('''\
    """sample module — assigns from a parse_* call without a None guard."""

    def handle(payload):
        plan = parse_plan(payload)
        steps = plan.get("steps", [])
        return steps


    def parse_plan(text):
        return None
''')


_CLAMP_SOURCE = textwrap.dedent('''\
    """sample module — accepts an unbounded max_steps integer."""

    HARD_MAX_STEPS = 10


    def configure(max_steps):
        max_steps = int(max_steps)
        return max_steps


    def configure_iter(value):
        max_iterations = int(value)
        return max_iterations
''')


# ── No-placeholder invariant ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "stage,reason,filename,source",
    [
        ("executor", "unhandled_RuntimeError",
         "infra/brain/agents/executor.py", _BASEEXC_SOURCE),
        ("router", "invalid_plan_from_llm",
         "infra/brain/agents/planner.py", _PARSER_SOURCE),
        ("executor", "executor_max_steps_overflow",
         "infra/brain/interface.py", _CLAMP_SOURCE),
    ],
)
def test_no_placeholders_in_any_emitted_patch(stage, reason, filename, source):
    ctx = FailureContext(
        test_name="t",
        traceback=f'File "{filename}", line 5, in run',
        files={filename: source},
        analysis={"stage": stage, "reason": reason},
    )
    fix = RepairGenerator().generate_patch(ctx)
    assert fix is not None, f"transform unexpectedly declined for ({stage}, {reason})"
    assert fix["patch"], "transform returned an empty patch"
    assert not _has_placeholders(fix["patch"]), (
        f"placeholder leaked into patch:\n{fix['patch']}"
    )


# ── Decline cases ──────────────────────────────────────────────────────────


def test_returns_none_when_files_empty():
    ctx = FailureContext(
        test_name="t",
        analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
    )
    assert RepairGenerator().generate_patch(ctx) is None


def test_returns_none_for_unrouted_reason():
    ctx = FailureContext(
        test_name="t",
        files={"foo.py": "x = 1\n"},
        analysis={"stage": "tool", "reason": "tool_permission_denied"},
    )
    # tool_permission_denied has no surgical transform — generator declines.
    assert RepairGenerator().generate_patch(ctx) is None


def test_returns_none_when_no_baseexception_in_file():
    ctx = FailureContext(
        test_name="t",
        traceback='File "x.py", line 1, in run',
        files={"x.py": "def run():\n    return 1\n"},
        analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
    )
    assert RepairGenerator().generate_patch(ctx) is None


def test_returns_none_when_file_has_syntax_error():
    ctx = FailureContext(
        test_name="t",
        traceback='File "x.py", line 1',
        files={"x.py": "def broken(:\n    pass\n"},
        analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
    )
    # AST parse fails → BaseException transform skips → no other transforms
    # match → generator returns None.
    assert RepairGenerator().generate_patch(ctx) is None


def test_returns_none_for_non_failurecontext_input():
    assert RepairGenerator().generate_patch({"not": "a context"}) is None  # type: ignore[arg-type]


# ── Per-transform structural checks ────────────────────────────────────────


def test_baseexception_transform_replaces_inside_target_function():
    ctx = FailureContext(
        test_name="t",
        traceback='File "infra/brain/agents/executor.py", line 6, in run',
        files={"infra/brain/agents/executor.py": _BASEEXC_SOURCE},
        analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
    )
    fix = RepairGenerator().generate_patch(ctx)
    assert fix is not None
    assert fix["fix_type"] == FIX_TYPE_SAFETY
    # Patch removes BaseException and adds Exception in its place,
    # preserving the `as e:` bind. Indentation in `_BASEEXC_SOURCE` is
    # 8 spaces (try inside def run inside class).
    assert "-        except BaseException as e:" in fix["patch"]
    assert "+        except Exception as e:" in fix["patch"]
    # Bounded changes.
    assert fix["lines_changed"] <= MAX_PATCHED_LINES
    assert fix["confidence"] >= MIN_GENERATOR_CONFIDENCE


def test_null_guard_transform_inserts_after_parse_call():
    ctx = FailureContext(
        test_name="t",
        traceback='File "infra/brain/agents/planner.py", line 4, in handle',
        files={"infra/brain/agents/planner.py": _PARSER_SOURCE},
        analysis={"stage": "router", "reason": "invalid_plan_from_llm"},
    )
    fix = RepairGenerator().generate_patch(ctx)
    assert fix is not None
    assert fix["fix_type"] == FIX_TYPE_PARSER
    assert "+    if plan is None:" in fix["patch"]
    assert "+        raise ValueError(" in fix["patch"]


def test_null_guard_skips_when_guard_already_present():
    src = textwrap.dedent('''\
        def handle(payload):
            plan = parse_plan(payload)
            if plan is None:
                raise ValueError("nope")
            return plan
    ''')
    ctx = FailureContext(
        test_name="t",
        files={"x.py": src},
        analysis={"stage": "router", "reason": "invalid_plan_from_llm"},
    )
    assert RepairGenerator().generate_patch(ctx) is None


def test_clamp_transform_wraps_int_assignment():
    ctx = FailureContext(
        test_name="t",
        files={"infra/brain/interface.py": _CLAMP_SOURCE},
        analysis={"stage": "executor", "reason": "executor_max_steps_overflow"},
    )
    fix = RepairGenerator().generate_patch(ctx)
    assert fix is not None
    assert fix["fix_type"] == FIX_TYPE_EXECUTOR
    # Both ``max_steps`` and ``max_iterations`` qualify; both should clamp.
    assert "min(10, max(1, int(max_steps)))" in fix["patch"]
    assert "min(10, max(1, int(value)))" in fix["patch"]


def test_clamp_transform_skips_already_clamped_lines():
    src = textwrap.dedent('''\
        def configure(n):
            max_steps = min(10, max(1, int(n)))
            return max_steps
    ''')
    ctx = FailureContext(
        test_name="t",
        files={"x.py": src},
        analysis={"stage": "executor", "reason": "executor_max_steps_overflow"},
    )
    assert RepairGenerator().generate_patch(ctx) is None


# ── Structural diff validity ───────────────────────────────────────────────


def test_emitted_diff_has_well_formed_headers_and_hunks():
    ctx = FailureContext(
        test_name="t",
        files={"x.py": _CLAMP_SOURCE},
        analysis={"stage": "executor", "reason": "executor_max_steps_overflow"},
    )
    fix = RepairGenerator().generate_patch(ctx)
    assert fix is not None
    patch = fix["patch"]
    assert patch.startswith("--- a/x.py\n"), patch[:60]
    assert "+++ b/x.py\n" in patch
    # At least one valid hunk header.
    assert re.search(r"^@@ -\d+(,\d+)? \+\d+(,\d+)? @@", patch, re.MULTILINE)
    assert patch.endswith("\n")


# ── End-to-end: validate_patch (real git repo) ─────────────────────────────


def _git_present() -> bool:
    return shutil.which("git") is not None


@pytest.mark.skipif(not _git_present(), reason="git not on PATH")
@pytest.mark.parametrize(
    "stage,reason,relpath,source",
    [
        ("executor", "unhandled_RuntimeError",
         "agents/executor.py", _BASEEXC_SOURCE),
        ("router", "invalid_plan_from_llm",
         "agents/planner.py", _PARSER_SOURCE),
        ("executor", "executor_max_steps_overflow",
         "interface.py", _CLAMP_SOURCE),
    ],
)
def test_validate_patch_accepts_generated_diff(
    tmp_path, stage, reason, relpath, source,
):
    _make_git_repo(tmp_path)
    _commit_file(tmp_path, relpath, source)

    ctx = FailureContext(
        test_name="t",
        traceback=f'File "{relpath}", line 5, in run',
        files={relpath: source},
        analysis={"stage": stage, "reason": reason},
    )
    fix = RepairGenerator().generate_patch(ctx)
    assert fix is not None

    result = validate_patch(fix["patch"], repo_root=tmp_path)
    assert result.applicable, (
        f"validate_patch rejected the diff: reason={result.reason} "
        f"output={result.git_check_output!r}\n--- patch ---\n{fix['patch']}"
    )
    assert not result.has_placeholders
    assert tuple(result.files_referenced) == (relpath,)


# ── Confidence handling ───────────────────────────────────────────────────


def test_recent_history_failures_lower_confidence():
    base_ctx = FailureContext(
        test_name="t",
        traceback='File "x.py", line 6, in run',
        files={"x.py": _BASEEXC_SOURCE},
        analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
    )
    # No history → base confidence.
    fresh = RepairGenerator().generate_patch(base_ctx)
    assert fresh is not None
    base = fresh["confidence"]

    # 2 prior failures of the same fix-type → confidence drops by ~0.20.
    history = [
        {"fix_type": FIX_TYPE_SAFETY, "result": "failed"},
        {"fix_type": FIX_TYPE_SAFETY, "result": "failed"},
    ]
    penalised_ctx = FailureContext(
        test_name="t",
        traceback='File "x.py", line 6, in run',
        files={"x.py": _BASEEXC_SOURCE},
        analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
        recent_history=history,
    )
    penalised = RepairGenerator().generate_patch(penalised_ctx)
    if penalised is None:
        # Confidence may have dropped below MIN_GENERATOR_CONFIDENCE — that
        # is a legitimate decline path. The contract is "lower than base or
        # decline", both of which prove the penalty applied.
        return
    assert penalised["confidence"] < base


# ── Integration: suggest_fix backwards compatibility ──────────────────────


def test_suggest_fix_without_context_returns_template_shape():
    """No ``context`` kwarg → identical behavior to pre-generator."""
    out = suggest_fix({"stage": "planner", "reason": "no_plan"})
    # Template-path types remain the historical small set.
    assert out["stage"] == "planner"
    assert out["fix_type"] in {
        ci_auto_fix.FIX_TYPE_SCHEMA,
        ci_auto_fix.FIX_TYPE_LOGIC,
        ci_auto_fix.FIX_TYPE_ORDERING,
        ci_auto_fix.FIX_TYPE_MISSING_EVENT,
        ci_auto_fix.FIX_TYPE_CRASH,
        ci_auto_fix.FIX_TYPE_CONFIG,
    }
    # Generator-only key NOT present in template path.
    assert "source" not in out


def test_suggest_fix_with_context_uses_generator():
    ctx = FailureContext(
        test_name="t",
        traceback='File "x.py", line 6, in run',
        files={"x.py": _BASEEXC_SOURCE},
        analysis={"stage": "executor", "reason": "unhandled_RuntimeError"},
    )
    out = suggest_fix(
        {"stage": "executor", "reason": "unhandled_RuntimeError"},
        context=ctx,
    )
    assert out.get("source") == "generator"
    assert out["fix_type"] == FIX_TYPE_SAFETY
    assert out["files_modified"] == ["x.py"]
    assert not _has_placeholders(out["patch"])


def test_suggest_fix_with_dict_context_is_normalised():
    """Passing a plain dict (instead of FailureContext) must work too."""
    out = suggest_fix(
        {"stage": "executor", "reason": "unhandled_RuntimeError"},
        context={
            "test_name": "t",
            "traceback": 'File "x.py", line 6, in run',
            "files": {"x.py": _BASEEXC_SOURCE},
        },
    )
    assert out.get("source") == "generator"


def test_suggest_fix_falls_back_when_generator_declines():
    """Context is supplied but the generator can't produce a clean fix —
    suggest_fix must return the template-path output, NOT a None."""
    ctx = FailureContext(
        test_name="t",
        # tool_permission_denied has no surgical transform.
        files={"x.py": "x = 1\n"},
        analysis={"stage": "tool", "reason": "tool_permission_denied"},
    )
    out = suggest_fix(
        {"stage": "tool", "reason": "tool_permission_denied"},
        context=ctx,
    )
    # Generator declined → template path → no "source" key.
    assert "source" not in out
    assert out["stage"] == "tool"
    # Template path produces a non-empty patch for this exact reason.
    assert isinstance(out.get("patch"), str)


def test_suggest_fix_generator_crash_falls_back_silently(monkeypatch):
    """If the generator raises, suggest_fix must still return a dict."""
    from infra.brain.debug import repair_generator as rg

    def _boom(self, ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(rg.RepairGenerator, "generate_patch", _boom)
    out = suggest_fix(
        {"stage": "executor", "reason": "unhandled_RuntimeError"},
        context=FailureContext(test_name="t", files={"x.py": _BASEEXC_SOURCE}),
    )
    assert isinstance(out, dict)
    # Falls through to template path.
    assert "source" not in out
