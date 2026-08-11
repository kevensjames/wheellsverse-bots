"""AgentRuntime — KAI-owned seam for software-engineering execution.

One implementation today (SandboxCommandRuntime) runs a bounded command in the
disposable sandbox and returns the produced patch/artifacts. The OpenHands
autonomous agent (which plans + edits code) plugs in behind this interface as a
later increment, running its steps through the SAME sandbox envelope + human
approval before any patch touches a real branch. Nothing here auto-merges or
auto-deploys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.swe_runtime.config import SandboxPolicy, default_policy
from app.services.swe_runtime.sandbox import SandboxResult, get_backend


@dataclass(slots=True)
class SweTask:
    task_id: str
    source_dir: str
    command: str  # the bounded command to run in the sandbox
    policy: SandboxPolicy = field(default_factory=default_policy)


@runtime_checkable
class AgentRuntime(Protocol):
    def run_task(self, task: SweTask) -> SandboxResult: ...


class SandboxCommandRuntime:
    """Runs the task's command in the disposable sandbox. No autonomous planning
    yet — the operator supplies the command; the value is the secured envelope."""

    def run_task(self, task: SweTask) -> SandboxResult:
        return get_backend().run(
            source_dir=task.source_dir, command=task.command, policy=task.policy)
