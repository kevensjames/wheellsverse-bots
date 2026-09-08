"""Composition attestation for KAI Computer Operations.

The pinned DeepSeek Harness is a REPLACEABLE execution provider, and upstream
SAFETY.md states it is not a security boundary. KAI therefore never trusts that a
policy overlay "was applied" -- before every dispatch it dumps the composed plugin
tree (`dsh --dump-config`) and asserts the containment invariants against what the
harness will ACTUALLY run.

Two properties make this worth doing rather than trusting configuration:

  * An upstream rename or removal of a plugin id would otherwise silently leave a
    capability mounted. A MISSING id is a hard failure here, not a skipped check.
  * The resulting attestation is recorded as mission evidence, so "this session could
    not reach the network" is a verifiable claim rather than an assertion.

This module performs NO I/O of its own beyond running the dump command it is given;
policy lives here, in KAI, outside the harness and outside any model prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# --- containment invariants -------------------------------------------------
# Plugin ids read from `dsh --profile acp --dump-default-config` at pinned commit
# c389f96bf3a9b6807cb71ed6bdad5849be0df6d8. Grouped by WHY they must be neutralised,
# because the reason is what a future maintainer needs when upstream moves.

#: Harness-side agent spawning, loops and background jobs. KAI owns mission
#: decomposition, budgets and evidence; work KAI never authorised cannot be accounted for.
NO_AUTONOMOUS_FANOUT = (
    "tool-ralph",
    "tool-subagent",
    "tool-subagent-fork",
    "tool-subagent-control",
    "tool-subagent-list-agents",
    "subagent-spawn-in-process",
    "subagent-fork-in-process",
    "tool-workflow",
    "workflow-worker-thread",
    "tool-jobs",
)

#: Harness-side network egress. Every external fetch must be a KAI capability with its
#: own policy and audit; a harness-side fetch is both an unlogged egress path and an
#: unmediated prompt-injection intake.
NO_INDEPENDENT_EGRESS = ("tool-web", "web-fetch-http", "web-search-deepseek")

#: On-disk skills are untrusted input, never permission grants. KAI never auto-installs
#: or auto-enables third-party plugins.
NO_UNTRUSTED_PLUGIN_LOADING = ("skill-filesystem", "tool-skill")

#: Irrelevant on macOS; removed so the mounted surface matches the platform.
NOT_ON_THIS_PLATFORM = ("tool-pwsh", "pwsh-sandbox")

#: Sandbox modes. 'danger-full-access' is never used by any KAI autonomy mode.
ALLOWED_SANDBOX_MODES = ("read-only", "workspace-write")


@dataclass
class AttestationResult:
    ok: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        passed = sum(1 for _, ok, _ in self.checks if ok)
        return f"{passed}/{len(self.checks)} containment checks passed"


def _blocks(dump: str) -> dict[str, str]:
    """Split a composed-config dump into `id -> last block text`.

    The dump lists an entry once per layer that touched it; the LAST occurrence is
    the effective one, which is why later layers win and why we keep the last block.
    """
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for line in dump.splitlines():
        m = re.match(r"^- id: (\S+)\s*$", line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur, buf = m.group(1), [line]
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


def _require_disabled(blocks: dict[str, str], ids: Iterable[str], reason: str,
                      res: AttestationResult) -> None:
    for pid in ids:
        block = blocks.get(pid)
        if block is None:
            # Not "absent so harmless": an id we cannot find is an id we cannot prove
            # is off. Upstream renames must fail loudly.
            res.checks.append((pid, False, f"id absent from composed tree ({reason})"))
            res.failures.append(f"{pid}: not present in composed tree - upstream rename?")
            continue
        ok = "disabled: true" in block
        res.checks.append((pid, ok, reason))
        if not ok:
            res.failures.append(f"{pid}: still enabled ({reason})")


def attest(dump: str, *, expect_sandbox_mode: str, expect_local_only: bool,
           expect_approval_policy: str) -> AttestationResult:
    """Assert containment invariants against a composed-config dump."""
    res = AttestationResult(ok=True)
    blocks = _blocks(dump)

    _require_disabled(blocks, NO_AUTONOMOUS_FANOUT, "no autonomous fan-out", res)
    _require_disabled(blocks, NO_INDEPENDENT_EGRESS, "no independent egress", res)
    _require_disabled(blocks, NO_UNTRUSTED_PLUGIN_LOADING, "no untrusted plugin loading", res)
    _require_disabled(blocks, NOT_ON_THIS_PLATFORM, "not applicable on macOS", res)

    # Telemetry: the plugin stays mounted but must be pinned to DISABLED.
    tel = blocks.get("session-telemetry-otel")
    ok = tel is not None and "mode: DISABLED" in tel
    res.checks.append(("session-telemetry-otel", ok, "telemetry egress disabled"))
    if not ok:
        res.failures.append("session-telemetry-otel: mode is not DISABLED")

    # File sandbox mode.
    sb = blocks.get("sandbox-policy") or ""
    m = re.search(r"^\s*mode: (\S+)", sb, re.M)
    mode = m.group(1) if m else None
    ok = mode == expect_sandbox_mode and mode in ALLOWED_SANDBOX_MODES
    res.checks.append(("sandbox-policy.mode", ok, f"expected {expect_sandbox_mode}, got {mode}"))
    if not ok:
        res.failures.append(f"sandbox-policy.mode is {mode!r}, expected {expect_sandbox_mode!r}")

    # Approval policy. 'ask' routes each request to the KAI connector over ACP and
    # fails closed with no answerer; 'never' is a deterministic deny.
    ap = blocks.get("approval") or ""
    m = re.search(r"^\s*policy: (\S+)", ap, re.M)
    policy = m.group(1) if m else None
    ok = policy == expect_approval_policy
    res.checks.append(("approval.policy", ok, f"expected {expect_approval_policy}, got {policy}"))
    if not ok:
        res.failures.append(f"approval.policy is {policy!r}, expected {expect_approval_policy!r}")

    if expect_local_only:
        # Structural no-fallback: with the cloud adapter disabled there is no cloud
        # route left for a fallback to reach, so LOCAL_ONLY cannot silently degrade.
        ds = blocks.get("llm-deepseek")
        ok = ds is not None and "disabled: true" in ds
        res.checks.append(("llm-deepseek", ok, "cloud adapter disabled (LOCAL_ONLY)"))
        if not ok:
            res.failures.append("llm-deepseek: cloud adapter not disabled under LOCAL_ONLY")

        for pid in ("agent-default-model", "acp"):
            block = blocks.get(pid) or ""
            ok = "provider: kai-local" in block
            res.checks.append((f"{pid}.provider", ok, "routed to local provider"))
            if not ok:
                res.failures.append(f"{pid}: provider is not kai-local under LOCAL_ONLY")

    res.ok = not res.failures
    return res
