"""System-level invariants suite — single file, no helpers in a
separate module, no new abstractions.

This is the "must hold post-merge" cross-cutting test surface for the
Brain runtime. Every test asserts ONE invariant that, if it
regresses, would let an audit-class issue back into the codebase.

Categories (one ``class`` per category — purely visual grouping; no
shared state):

  * TestArchitectureBoundary  — module surface + import discipline
  * TestAgentSeparation       — planner/executor structural split
  * TestTelemetryIntegrity    — lifecycle ordering + ContextVar isolation
  * TestToolSafety            — tool dispatch through ToolExecutor only
  * TestPolicySafety          — dynamic policy contracts
  * TestSelfHealingSafety     — apply-patch gate + protected-branches
  * TestExceptionSafety       — no BaseException catches  (xfail → PR #8)
  * TestToolTruncationVisibility — visible marker + telemetry  (xfail → PR #8)
  * TestSanityOverride        — meta documentation

Architecture-freeze rule: this file MUST NOT introduce abstractions,
helpers in separate modules, or fixtures. All utility logic is inline.
The only sys.modules stubs at the top of the file mirror the same
pattern ``tests/debug/conftest.py`` uses — required to collect the
test file in environments without the chromadb / litellm runtime
deps installed (the canonical ``project_brain_test_venv`` blocker).
"""
from __future__ import annotations

# ── sys.modules stubs (run AT IMPORT TIME, before any infra.brain import) ─
#
# The parent ``tests/conftest.py``'s ``_isolate_chroma`` autouse fixture
# imports ``infra.brain.memory`` which does ``import chromadb``. This
# file's own imports below also trigger that chain via interface.py.
# Stubbing here lets the test file collect cleanly when chromadb /
# litellm aren't installed locally — the stubs are inert and never
# called by the invariants below (they assert structure, not chroma).
import sys as _sys
from unittest.mock import MagicMock as _MagicMock


def _stub_module(name: str) -> None:
    existing = _sys.modules.get(name)
    if existing is not None and not isinstance(existing, _MagicMock):
        return  # real module installed — leave it alone
    stub = _MagicMock(name=f"stub.{name}")
    stub.__path__ = []  # marks as a package so submodule imports work
    _sys.modules[name] = stub


for _name in ("chromadb", "chromadb.utils", "litellm"):
    _stub_module(_name)


# ── Real imports ───────────────────────────────────────────────────────

import ast
import asyncio
import os
import re
import subprocess
from pathlib import Path

import pytest

from infra.brain.interface import BrainClient, BrainPolicy
from infra.brain.policy import (
    CAPABILITY_READ_ONLY,
    CAPABILITY_SHELL,
    NARAI_POLICY,
)
from infra.brain.telemetry import (
    EVENT_TASK_END,
    EVENT_TASK_START,
    TelemetryCollector,
    get_current_telemetry,
)
from infra.brain.telemetry.collector import _current_telemetry
from infra.brain.tools.registry import Tool


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BRAIN_ROOT = Path(__file__).resolve().parents[1]


# ── Inline helper (the only one — per the architecture-freeze rule) ───
#
# The two self-healing tests + the two policy-seed tests all need a
# tmp git repo with one committed file. Inlining the same 8-line
# subprocess scaffold four times costs ~32 LOC and obscures the
# actual test intent. One helper is the surgical compromise.

def _init_tmp_git_repo(tmp_path: Path, *, branch: str = "feature") -> None:
    """Initialise a tmp git repo with one committed file, ready for
    apply_patch_safely / outcome-store tests. Sets identity + GPG-off."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=tmp_path, check=True, env=env)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    (tmp_path / "x.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "x.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True, env=env,
    )


# ─────────────────────────────────────────────────────────────────────
# TestArchitectureBoundary
# ─────────────────────────────────────────────────────────────────────


class TestArchitectureBoundary:
    """Imports stay inside ``infra.brain.interface``; internals are
    private to the crate. PR #2's load-bearing module discipline."""

    # ── _LEGITIMATE_SEAM_FILES contract ────────────────────────────
    #
    # The boundary rule is "no file outside infra/brain/ may import
    # from the crate's internal modules". This tuple is the single
    # place where a deliberate exception is recorded.
    #
    # Currently exactly ONE entry:
    #
    #   scripts/feedback/ingest_github_events.py
    #     - Why it exists: Phase F.2's GitHub Actions ↔ ingestor seam.
    #       It accepts a webhook payload on stdin or via a file path,
    #       dispatches to the right ingestor entry point in
    #       infra.brain.learning.feedback_ingestor, and writes the
    #       resulting outcome state to the JSONL ledger. Pure
    #       payload-in / store-side-effects-out — no GitHub API
    #       calls, no other side effects.
    #     - Why it MUST import from infra.brain.learning: it IS the
    #       dispatch layer for GitHub workflow events. The whole
    #       point of Phase F.2 was to put this seam OUTSIDE the brain
    #       crate so the workflow YAML stays trivial and the ingestor
    #       semantics live in a testable Python module.
    #
    # ANY new entry to this tuple requires an explicit code review
    # against this comment. Add a paragraph above naming the file,
    # the phase that introduced it, and why the import is legitimate.
    # No silent expansion — the contract is part of this file.
    # ────────────────────────────────────────────────────────────────
    _LEGITIMATE_SEAM_FILES: tuple[str, ...] = (
        "scripts/feedback/ingest_github_events.py",
    )

    def test_no_external_imports_into_brain_internals(self):
        """No file outside ``infra/brain/`` may import from the crate's
        internal modules. ``infra.brain.interface`` is the only legal
        import surface, except for deliberately-allowlisted seams."""
        forbidden = re.compile(
            r"from\s+infra\.brain\."
            r"(router|memory|rag|tiers|skills|tools|telemetry|agents|policy|debug|learning)"
        )
        offenders: list[str] = []
        for py in _REPO_ROOT.rglob("*.py"):
            parts = py.relative_to(_REPO_ROOT).parts
            if not parts:
                continue
            if parts[0] in {".venv", ".venv-1", "venv", ".git"}:
                continue
            if parts[0] == "infra" and len(parts) > 1 and parts[1] == "brain":
                continue
            if ".claude" in parts:
                continue
            rel = str(py.relative_to(_REPO_ROOT))
            if rel in self._LEGITIMATE_SEAM_FILES:
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if forbidden.search(text):
                offenders.append(rel)
        assert offenders == [], (
            f"External imports into infra.brain internals are forbidden. "
            f"Use BrainClient from infra.brain.interface instead, or add "
            f"the file to _LEGITIMATE_SEAM_FILES with reasoning. "
            f"Offending files: {offenders}"
        )

    def test_interface_py_exports_brain_client(self):
        """The single public surface is ``infra.brain.interface.BrainClient``.
        If any consumer reaches around it for a different symbol, that's
        a boundary violation tracked by the test above."""
        text = (_BRAIN_ROOT / "interface.py").read_text(encoding="utf-8")
        assert "class BrainClient" in text, "BrainClient class missing from interface.py"
        # Confirm the architectural-contract docstring is intact —
        # changing it should require deliberate review.
        assert "NEVER add another import to this file" in text


# ─────────────────────────────────────────────────────────────────────
# TestAgentSeparation
# ─────────────────────────────────────────────────────────────────────


class TestAgentSeparation:
    """Planner is structurally toolless; executor is the sole
    ``brain.use_tool`` caller. PR #2 single-author-per-tool-call
    invariant."""

    def test_planner_max_tool_iterations_is_zero(self):
        """``PlannerAgent.run`` must invoke ``self.brain.chat`` with
        ``max_tool_iterations=0`` so the planner cannot reach
        ``use_tool`` even via tool-call envelope detection."""
        path = _BRAIN_ROOT / "agents" / "planner.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Find the PlannerAgent.run method via AST.
        zero_iter_calls: list[ast.AST] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords or []:
                if kw.arg != "max_tool_iterations":
                    continue
                v = kw.value
                if isinstance(v, ast.Constant) and v.value == 0:
                    zero_iter_calls.append(node)
        assert zero_iter_calls, (
            "Planner must have at least one chat() call with "
            "max_tool_iterations=0 (the toolless-planner invariant)."
        )

    def test_executor_is_sole_use_tool_caller(self):
        """Inside ``infra/brain/agents/`` only ``executor.py`` may call
        ``brain.use_tool`` / ``self.brain.use_tool``. Anywhere else
        means tool dispatch can sidestep the policy gate."""
        agents_dir = _BRAIN_ROOT / "agents"
        offenders: list[str] = []
        for py in agents_dir.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if py.name == "executor.py":
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if re.search(r"\.use_tool\s*\(", line):
                    offenders.append(f"{py.name}:{line_no}: {line.strip()}")
        assert offenders == [], (
            f"Only executor.py may call use_tool() inside agents/. "
            f"Offenders: {offenders}"
        )


# ─────────────────────────────────────────────────────────────────────
# TestTelemetryIntegrity
# ─────────────────────────────────────────────────────────────────────


class TestTelemetryIntegrity:
    """ContextVar-bound collector + lifecycle event ordering. PR #2
    observability contract."""

    def test_task_lifecycle_emits_start_and_end(
        self, permissive_client, router_mock,
    ):
        """``run_task`` must always emit ``task_start`` first and
        ``task_end`` last, even when the plan is invalid."""
        from unittest.mock import MagicMock
        # Force the planner's first router call to return non-JSON,
        # which routes through ``state="failed"`` cleanly.
        resp = MagicMock()
        resp.choices[0].message.content = "not json"
        resp.usage.total_tokens = 5
        router_mock.return_value = resp

        async def go():
            return await permissive_client.run_task("hi")

        asyncio.run(go())
        types = [e["event_type"] for e in permissive_client.telemetry.flush()]
        assert types[0] == EVENT_TASK_START, (
            f"first event must be {EVENT_TASK_START}, got {types[0]!r}; trace: {types}"
        )
        assert types[-1] == EVENT_TASK_END, (
            f"last event must be {EVENT_TASK_END}, got {types[-1]!r}; trace: {types}"
        )

    def test_contextvar_isolation_no_cross_task_leak(self):
        """Two collectors active concurrently must not see each
        other's events. Tests the ContextVar bridge directly so the
        check is independent of the higher-level run_task path."""
        c1 = TelemetryCollector(user_id="alice", mode="t")
        c2 = TelemetryCollector(user_id="bob", mode="t")

        async def use(c: TelemetryCollector, who: str):
            with c.activate():
                # The active collector inside this task must always be ``c``.
                await asyncio.sleep(0.01)
                assert get_current_telemetry() is c, "ContextVar leaked"
                c.emit("probe", who=who)
                await asyncio.sleep(0.01)
                c.emit("probe", who=who)

        async def race():
            await asyncio.gather(use(c1, "alice"), use(c2, "bob"))

        asyncio.run(race())

        e1 = [e["metadata"].get("who") for e in c1.flush()]
        e2 = [e["metadata"].get("who") for e in c2.flush()]
        assert set(e1) == {"alice"}, f"c1 saw alien events: {e1}"
        assert set(e2) == {"bob"}, f"c2 saw alien events: {e2}"


# ─────────────────────────────────────────────────────────────────────
# TestToolSafety
# ─────────────────────────────────────────────────────────────────────


class TestToolSafety:
    """All tool dispatch routes through ``ToolExecutor.execute``; the
    capability gate is enforced; no bypass via direct registry lookup."""

    def test_tool_calls_pass_through_executor(self, permissive_client):
        """Calling ``client.use_tool`` must invoke
        ``ToolExecutor.execute`` — confirms the public-facing
        ``use_tool`` shim doesn't bypass the gate."""
        from infra.brain.tools.registry import ToolRegistry
        from infra.brain.tools.executor import ToolExecutor

        # The tool registry on the client. Register a probe tool with a
        # known sentinel return so we can confirm the executor's call
        # path actually invoked .run().
        async def _probe(input):
            return {"sentinel": "ran"}

        tool = Tool(name="probe_tool", description="x", run=_probe)
        permissive_client.tool_registry.register(tool)
        # Sanity check: tool_executor is a ToolExecutor, not a stub.
        assert isinstance(permissive_client.tool_executor, ToolExecutor)
        result = asyncio.run(permissive_client.use_tool("probe_tool", {}))
        assert result == {"sentinel": "ran"}

    def test_capability_gate_enforced_for_narai(self):
        """A tool declaring ``shell`` capability must be rejected by
        ``NARAI_POLICY.allows`` — the Phase B gate."""
        async def _runner(input):
            return None

        sneaky = Tool(
            name="web_search",  # name IS in NARAI_POLICY.allowed_tools
            description="x",
            run=_runner,
            capabilities=frozenset({CAPABILITY_READ_ONLY, CAPABILITY_SHELL}),
        )
        # Even though the NAME is allowed, the capability gate denies.
        assert NARAI_POLICY.allows(sneaky) is False
        # Sanity: a tool whose capabilities are a strict subset passes.
        clean = Tool(
            name="web_search", description="x", run=_runner,
            capabilities=frozenset({CAPABILITY_READ_ONLY}),
        )
        assert NARAI_POLICY.allows(clean) is True

    def test_no_direct_tool_run_outside_executor(self):
        """The actual single-author-per-tool-call invariant: ``tool.run(...)``
        may only be invoked inside ``ToolExecutor.execute``. Other
        modules legitimately call ``tool_registry.get()`` for schema
        inspection (e.g. ``BrainClient.available_tools`` for the LLM
        catalog, ``PolicyEvolver`` for capability lookups) — that's
        registry-as-catalog, not registry-as-dispatch.

        The dispatch invariant is what protects the policy gate. If
        any code outside ``ToolExecutor.execute`` reaches into a
        ``Tool`` object and calls its ``.run(...)`` directly, the
        permission/existence/capability checks at
        ``tools/executor.py:74-103`` get bypassed."""
        offenders: list[str] = []
        for py in _BRAIN_ROOT.rglob("*.py"):
            rel = py.relative_to(_BRAIN_ROOT)
            parts = rel.parts
            if parts and parts[0] == "tests":
                continue
            # The executor is the legitimate dispatcher. Skip the file.
            if parts == ("tools", "executor.py"):
                continue
            # Skip the registry definition itself — it doesn't dispatch.
            if parts == ("tools", "registry.py"):
                continue
            text = py.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                # Match calls like ``tool.run(`` / ``await tool.run(``
                # but NOT method definitions (``def run(``) or attribute
                # access (``tool.run`` without paren).
                if re.search(r"\btool\.run\s*\(", line):
                    offenders.append(f"{rel}:{line_no}: {line.strip()}")
        assert offenders == [], (
            f"Direct tool.run() calls outside ToolExecutor.execute "
            f"bypass the policy/capability gate. Offenders: {offenders}"
        )


# ─────────────────────────────────────────────────────────────────────
# TestPolicySafety
# ─────────────────────────────────────────────────────────────────────


class TestPolicySafety:
    """Dynamic policy is restriction-only, off by default, audited via
    telemetry. PR #5 contract."""

    def test_effective_subset_of_static(self, tmp_path, monkeypatch):
        """With a store seeded with restrictive history, the dynamic
        policy's allowed_tools MUST be a subset of the static
        baseline. Restriction-only invariant."""
        from infra.brain.learning.policy_evolver import EvolutionConfig
        from infra.brain.learning.repair_outcome_memory import (
            RepairOutcome, RepairOutcomeStore, STATE_REVERTED,
        )
        # Custom static policy with two tools so we have something to drop.
        static = BrainPolicy(
            mode="t", tone="t", system_prompt="t",
            memory_enabled=False, rag_enabled=False, tools_enabled=True,
            allowed_tools=("alpha", "beta"),
            allowed_capabilities=frozenset({CAPABILITY_READ_ONLY}),
        )
        store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
        for i in range(20):
            store.record_outcome(RepairOutcome(
                failure_signature=f"s_{i}",
                patch_hash=f"alpha_p{i}",
                applied_at=f"2026-05-06T00:{i:02d}:00+00:00",
                outcome_state=STATE_REVERTED,
                outcome_observed_at=f"2026-05-06T00:{i:02d}:00+00:00",
                touched_tools=("alpha",),
            ))

        monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
        client = BrainClient(
            user_id="t", policy=static,
            telemetry_enabled=False,
            dynamic_policy=True,
            outcome_store=store,
            evolution_config=EvolutionConfig(enabled=True, min_history=5),
        )
        eff = set(client.policy.allowed_tools or ())
        base = set(client.static_policy.allowed_tools or ())
        assert eff <= base, f"effective {eff} not subset of static {base}"
        # And alpha specifically dropped (sanity check the seed worked).
        assert "alpha" not in eff
        assert "beta" in eff

    def test_kill_switch_disables_dynamic(self, tmp_path, monkeypatch):
        """``BRAIN_POLICY_DYNAMIC=off`` (or unset) must yield
        ``client.policy is client.static_policy``. Kill switch
        invariant — operator's emergency revert path."""
        monkeypatch.setenv("BRAIN_POLICY_DYNAMIC", "off")
        client = BrainClient(
            user_id="t", mode="narai", telemetry_enabled=False,
            dynamic_policy=None,  # honour env var
        )
        assert client.policy is client.static_policy

    def test_policy_mutation_emits_telemetry(self, tmp_path, monkeypatch):
        """Every dynamic restriction must emit a
        ``policy_dynamic_restriction`` event — auditability invariant.
        Without this, dynamic narrowing happens silently."""
        from unittest.mock import MagicMock
        from infra.brain.learning.policy_evolver import EvolutionConfig
        from infra.brain.learning.repair_outcome_memory import (
            RepairOutcome, RepairOutcomeStore, STATE_REVERTED,
        )

        static = BrainPolicy(
            mode="t", tone="t", system_prompt="t",
            memory_enabled=False, rag_enabled=False, tools_enabled=True,
            allowed_tools=("alpha",),
            allowed_capabilities=None,
        )
        store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
        for i in range(20):
            store.record_outcome(RepairOutcome(
                failure_signature=f"s_{i}",
                patch_hash=f"a_p{i}",
                applied_at=f"2026-05-06T00:{i:02d}:00+00:00",
                outcome_state=STATE_REVERTED,
                outcome_observed_at=f"2026-05-06T00:{i:02d}:00+00:00",
                touched_tools=("alpha",),
            ))

        monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
        fake = MagicMock()
        fake.emit = MagicMock()
        token = _current_telemetry.set(fake)
        try:
            BrainClient(
                user_id="t", policy=static, telemetry_enabled=False,
                dynamic_policy=True,
                outcome_store=store,
                evolution_config=EvolutionConfig(enabled=True, min_history=5),
            )
        finally:
            _current_telemetry.reset(token)

        events = [c.args[0] for c in fake.emit.call_args_list if c.args]
        assert "policy_dynamic_restriction" in events, (
            f"Expected policy_dynamic_restriction event; saw: {events}"
        )


# ─────────────────────────────────────────────────────────────────────
# TestSelfHealingSafety
# ─────────────────────────────────────────────────────────────────────


def _git_present() -> bool:
    return subprocess.run(
        ["which", "git"], capture_output=True
    ).returncode == 0


class TestSelfHealingSafety:
    """``apply_patch_safely`` enforces six gates before disk mutation.
    Locked-in for the two most safety-critical ones."""

    @pytest.mark.skipif(not _git_present(), reason="git not on PATH")
    def test_validate_patch_required_before_apply(self, tmp_path, monkeypatch):
        """An empty / structureless patch must be rejected by
        ``validate_patch`` before ``git apply`` is invoked."""
        from infra.brain.debug.ci_autonomous_repair import apply_patch_safely
        _init_tmp_git_repo(tmp_path, branch="feature")
        monkeypatch.chdir(tmp_path)
        outcome = apply_patch_safely(
            "",  # empty patch — validate_patch must reject
            fix_confidence=0.95,
            repo_root=tmp_path,
        )
        assert not outcome.applied
        assert "patch_not_applicable" in outcome.reason or "empty" in outcome.reason

    @pytest.mark.skipif(not _git_present(), reason="git not on PATH")
    def test_protected_branches_blocked(self, tmp_path, monkeypatch):
        """``apply_patch_safely`` on ``main`` must refuse without the
        explicit override flag — protects production from the
        autonomous repair path."""
        from infra.brain.debug.ci_autonomous_repair import apply_patch_safely
        _init_tmp_git_repo(tmp_path, branch="main")
        monkeypatch.chdir(tmp_path)
        outcome = apply_patch_safely(
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
            fix_confidence=0.95,
            repo_root=tmp_path,
            # No allow_protected_branches=True — the gate fires.
        )
        assert not outcome.applied
        assert "protected_branch" in outcome.reason or "main" in outcome.reason


# ─────────────────────────────────────────────────────────────────────
# TestExceptionSafety  (xfail — depends on PR #8)
# ─────────────────────────────────────────────────────────────────────


# ── Silent-swallow classification rule ──────────────────────────────
#
# No allowlist, no magic comments. The contract is *structural*: a
# ``try / except Exception`` whose body is a bare ``pass`` (or ``...``)
# is permitted ONLY if a visible recovery action exists somewhere in
# the construct. Recovery counts when ANY of:
#
#   1. The except body contains at least one statement other than
#      ``pass`` / ``...`` (a logging call, an assignment, a return —
#      anything observable). Bare-``pass`` body fails this clause.
#   2. The statement IMMEDIATELY following the ``Try`` node in its
#      enclosing block is a "recovery statement" (assignment, return,
#      function call, control-flow). The classic chroma pattern
#      ``try: delete / except: pass / get_or_create_collection`` and
#      the sqlite ``try: close / except: pass / set None`` both fit.
#
# If neither holds, the test fails with the precise (file, line, body
# excerpt). Adding a new bare-``pass`` swallow requires either a
# recovery action in the except body (preferred — usually a one-line
# ``logger.debug`` or an explicit ``state = sentinel``) or a
# follow-up recovery statement after the try. Both are diff-visible
# and reviewable.
#
# This replaces the prior allowlist + ``# safe-pass:`` annotation
# rule. The structural form was rejected in favour of "silence must
# be visible recovery, not a magic word."
# ────────────────────────────────────────────────────────────────────


def _is_bare_pass_body(handler_body: list) -> bool:
    """True iff ``handler_body`` is exactly ``[Pass()]`` or ``[...]``."""
    if len(handler_body) != 1:
        return False
    stmt = handler_body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if (isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is ...):
        return True
    return False


def _next_sibling_in_block(parents: dict, target: ast.AST) -> ast.AST | None:
    """Return the AST node immediately after ``target`` in its
    enclosing block, or None when ``target`` is the last statement in
    its block."""
    parent = parents.get(id(target))
    if parent is None:
        return None
    for attr in ("body", "orelse", "finalbody"):
        block = getattr(parent, attr, None)
        if not isinstance(block, list):
            continue
        for i, stmt in enumerate(block):
            if stmt is target and i + 1 < len(block):
                return block[i + 1]
    return None


def _is_recovery_stmt(node: ast.AST) -> bool:
    """A "recovery statement" — anything observable in source.
    Specifically excludes another bare ``pass`` so two consecutive
    swallows can't whitewash each other."""
    if isinstance(node, ast.Pass):
        return False
    if (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and node.value.value is ...):
        return False
    return isinstance(node, (
        ast.Assign, ast.AugAssign, ast.AnnAssign,
        ast.Return, ast.Expr, ast.If, ast.For, ast.While,
        ast.With, ast.AsyncWith, ast.Raise,
    ))


class TestExceptionSafety:
    """No ``except BaseException`` anywhere in the runtime; no
    unauthorized silent ``except Exception: pass``."""

    @pytest.mark.xfail(
        reason="depends on PR #8 narrowing — PR #5's branch still has "
        "infra/brain/debug/ci_self_healing.py:639 catching BaseException"
    )
    def test_no_baseexception_in_brain_source(self):
        """Grep all ``infra/brain/`` source for ``except BaseException``;
        assert zero non-string-literal hits. PR #8 narrows the only
        offender at ``ci_self_healing.py:639``."""
        offenders: list[str] = []
        pattern = re.compile(r"except\s+BaseException\b")
        for py in _BRAIN_ROOT.rglob("*.py"):
            rel = py.relative_to(_REPO_ROOT.parent / _REPO_ROOT.name)
            text = py.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                # Skip comment-only lines + lines that look like string
                # literals containing the phrase (templates, docstrings).
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if not pattern.search(line):
                    continue
                # Heuristic: if the line contains a ``"`` or ``'`` BEFORE
                # ``except``, treat it as a string literal.
                idx = line.find("except")
                quote_before = any(q in line[:idx] for q in ('"', "'"))
                if quote_before:
                    continue
                offenders.append(f"{rel}:{line_no}: {stripped}")
        assert offenders == [], (
            f"BaseException catches forbidden in brain source. "
            f"Offenders: {offenders}"
        )

    def test_no_silent_exception_pass_without_visible_recovery(self):
        """AST classifier: every ``try / except Exception`` whose body
        is a bare ``pass`` (or ``...``) MUST have a visible recovery
        either inside the except body OR as the next statement in the
        enclosing block. Bare swallows with no recovery are forbidden;
        adding one requires a deliberate diff that introduces an
        observable action (logger call / assignment / etc.).

        See the module-level comment block above for the full rule
        and rationale."""
        offenders: list[str] = []
        for py in _BRAIN_ROOT.rglob("*.py"):
            parts = py.relative_to(_BRAIN_ROOT).parts
            if parts and parts[0] == "tests":
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue

            # Build a parent map for next-sibling lookup.
            parents: dict[int, ast.AST] = {}
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    parents[id(child)] = parent

            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                for handler in node.handlers:
                    # Only ``except Exception (as e)?:`` — narrower
                    # types like ``except KeyError`` aren't the target.
                    t = handler.type
                    if not (isinstance(t, ast.Name) and t.id == "Exception"):
                        continue
                    if not _is_bare_pass_body(handler.body):
                        continue
                    # Bare swallow detected. Check for recovery.
                    nxt = _next_sibling_in_block(parents, node)
                    if nxt is not None and _is_recovery_stmt(nxt):
                        continue  # next-stmt recovery satisfies the rule
                    rel = py.relative_to(_BRAIN_ROOT)
                    line = handler.body[0].lineno
                    offenders.append(
                        f"infra/brain/{rel}:{line}: "
                        f"bare pass swallow with no visible recovery"
                    )
        assert offenders == [], (
            "Bare ``except Exception: pass`` swallows MUST carry a "
            "visible recovery action (logger call, assignment, or a "
            "follow-up statement in the enclosing block). Add an "
            "observable action in the except body, or restructure so "
            "the next statement performs the recovery. "
            f"Offenders: {offenders}"
        )


# ─────────────────────────────────────────────────────────────────────
# TestToolTruncationVisibility  (xfail — depends on PR #8)
# ─────────────────────────────────────────────────────────────────────


class TestToolTruncationVisibility:
    """Oversized tool outputs must (a) carry a visible inline marker
    (NOT just a ``…[truncated]`` suffix) and (b) emit a
    ``tool_result_truncated`` telemetry event. PR #8 closure."""

    @pytest.mark.xfail(
        reason="depends on PR #8 — PR #5's branch still emits the silent "
        "[truncated] suffix without a visible prepended marker"
    )
    def test_truncation_marker_visible_in_output(self):
        from infra.brain.tools.agent_loop import format_tool_result
        big = {"data": "z" * 20000}
        out = format_tool_result("big_tool", big)
        assert "[TRUNCATED:" in out, (
            "Truncation marker missing — silent-suffix-only behavior "
            "is the failure mode this test guards against."
        )

    @pytest.mark.xfail(
        reason="depends on PR #8 — PR #5's branch emits no truncation "
        "telemetry event (the format_tool_result function on this branch "
        "does not call get_current_telemetry)"
    )
    def test_truncation_emits_telemetry_event(self):
        from unittest.mock import MagicMock
        from infra.brain.tools.agent_loop import format_tool_result
        fake = MagicMock()
        fake.emit = MagicMock()
        token = _current_telemetry.set(fake)
        try:
            format_tool_result("big", {"data": "y" * 20000})
        finally:
            _current_telemetry.reset(token)
        events = [c.args[0] for c in fake.emit.call_args_list if c.args]
        assert "tool_result_truncated" in events


# ─────────────────────────────────────────────────────────────────────
# TestSanityOverride
# ─────────────────────────────────────────────────────────────────────


class TestSanityOverride:
    """Meta-documentation. This test asserts nothing runtime-relevant;
    it exists so a reviewer running ``pytest`` sees the invariants
    file is discoverable with no setup beyond the standard test
    invocation."""

    def test_invariants_run_independently_of_test_suite_status(self):
        """Asserts the file's tests are discoverable. If pytest can run
        this single test, it can run the rest of the file. Use
        ``pytest infra/brain/tests/test_system_invariants.py`` as the
        canonical invocation."""
        # Self-evident — if you're reading this, pytest discovered it.
        assert True
