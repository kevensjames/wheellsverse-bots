"""KAI ⇄ TARS adapter: structured contracts, runtime-truth status, fail-closed execution.

This is the ONLY seam between KAI's governed brain and an (isolated, separate) TARS
execution worker. It does NOT install, embed, or run TARS. Until a certified worker is
registered and online AND every runtime-truth condition holds, the capability is
UNAVAILABLE and execute() refuses — no false READY, no execution.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

from app.services.tars.provenance import PINNED, is_pinned
from app.services.tars import policy as pol


class WorkerStatus(str, Enum):
    READY = "READY"                # every runtime-truth condition holds (see derive_status)
    EXPERIMENTAL = "EXPERIMENTAL"  # online + healthy but not fully certified
    DEGRADED = "DEGRADED"          # online but a required channel (e.g. cancel/audit) failed
    UNAVAILABLE = "UNAVAILABLE"    # no worker online / auth fails / version mismatch
    DISABLED = "DISABLED"          # explicitly turned off (kill switch / operator)


@dataclass
class TarsTask:
    task_id: str
    user_id: str
    worker_id: str
    session_id: str
    objective: str
    allowed_domains: list = field(default_factory=list)
    allowed_applications: list = field(default_factory=list)
    allowed_actions: list = field(default_factory=list)
    prohibited_actions: list = field(default_factory=lambda: sorted(pol.PROHIBITED))
    maximum_steps: int = 20
    maximum_runtime_seconds: int = 180
    maximum_download_bytes: int = 0          # 0 = downloads off by default
    approval_scope: str = ""
    approval_expires_at: float = 0.0
    credential_policy: str = "none"          # no credential entry by default
    data_classification: str = "public"
    created_at: float = field(default_factory=time.time)
    correlation_id: str = ""


@dataclass
class TarsResult:
    task_id: str
    status: str
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    actions_attempted: int = 0
    actions_completed: int = 0
    final_url: str = ""
    artifacts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    policy_denials: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    cleanup_status: str = "n/a"
    audit_event_ids: list = field(default_factory=list)
    def as_dict(self): return asdict(self)


@dataclass
class WorkerEvidence:
    """Runtime attestations gathered from a candidate worker. ALL must hold for READY."""
    worker_online: bool = False
    authenticated: bool = False
    upstream_version: str = ""        # must match PINNED.package_version
    health_ok: bool = False
    execution_probe_ok: bool = False  # a harmless probe actually ran
    policy_engine_ok: bool = False
    audit_sink_ok: bool = False
    cancel_channel_ok: bool = False
    isolation_attested: bool = False  # container/network/fs isolation attested
    last_verified_at: float = 0.0


def derive_status(ev: Optional[WorkerEvidence]) -> WorkerStatus:
    """Runtime truth — status is DERIVED, never declared. READY needs every condition."""
    if ev is None or not ev.worker_online:
        return WorkerStatus.UNAVAILABLE
    if not (ev.authenticated and is_pinned(ev.upstream_version)):
        return WorkerStatus.UNAVAILABLE
    # online + auth + pinned, but a required safety channel failed → DEGRADED (never usable)
    if not (ev.policy_engine_ok and ev.audit_sink_ok and ev.cancel_channel_ok and ev.isolation_attested):
        return WorkerStatus.DEGRADED
    if not (ev.health_ok and ev.execution_probe_ok):
        return WorkerStatus.EXPERIMENTAL
    return WorkerStatus.READY


class WorkerRegistry:
    """Tracks registered/online workers. Empty by default → capability UNAVAILABLE.
    A real worker registers with a signed worker_id + reports live evidence; nothing is
    assumed from mere configuration."""
    def __init__(self):
        self._workers: dict[str, WorkerEvidence] = {}
    def register_evidence(self, worker_id: str, ev: WorkerEvidence):
        self._workers[worker_id] = ev
    def revoke(self, worker_id: str):
        self._workers.pop(worker_id, None)
    def evidence(self, worker_id: str) -> Optional[WorkerEvidence]:
        return self._workers.get(worker_id)
    def best_status(self) -> WorkerStatus:
        if not self._workers:
            return WorkerStatus.UNAVAILABLE
        return max((derive_status(e) for e in self._workers.values()),
                   key=lambda s: ["UNAVAILABLE", "DISABLED", "DEGRADED", "EXPERIMENTAL", "READY"].index(s.value))


class TarsAdapter:
    """Fail-closed adapter. With no certified online worker, health→UNAVAILABLE and
    execute→denied. Executing real actions is added in the (separately gated) worker phase;
    even then, every action passes policy.permit() + a bound approval first."""
    def __init__(self, registry: Optional[WorkerRegistry] = None, kill_switch=lambda: False):
        self.registry = registry or WorkerRegistry()
        self._kill_switch = kill_switch    # returns True when the KAI emergency stop is engaged

    def health(self) -> WorkerStatus:
        if self._kill_switch():
            return WorkerStatus.DISABLED
        return self.registry.best_status()

    def execute(self, task: TarsTask, *, isolated_preapproved_env: bool = False,
                approval: Optional[pol.Approval] = None) -> TarsResult:
        # 1) kill switch / not-ready → refuse, audited as a denial, NO execution
        st = self.health()
        if st != WorkerStatus.READY:
            return TarsResult(task_id=task.task_id, status="denied",
                              policy_denials=[f"worker not READY (status={st.value})"],
                              errors=["execution refused: no certified READY worker"])
        # 2) even READY: this build does not yet run actions — worker execution is a
        #    separately gated phase. Fail closed rather than pretend.
        return TarsResult(task_id=task.task_id, status="denied",
                          policy_denials=["worker-execution phase not yet certified"],
                          errors=["execution not enabled in this build (governance foundation only)"])
