"""KAI Capability Exchange — inert Stage 1: the declarative capability layer.

A *capability* is a governed mission type KAI can be granted (scaffold an
Angular app, run a browser mission, ...). This module is the DECLARATIVE
registry: it holds capability *manifests* — what a capability is, its risk
class, isolation, egress domains, approval policy, evidence types — and reports
lifecycle status. It deliberately CANNOT execute anything: Stage 1 binds no
adapters, so every capability is INERT. Execution is a later, separately-gated
stage that must bind a real, sandboxed adapter.

Why inert-by-construction: the registry enforces "no adapter → no execution" in
code (``execute`` raises), not by docstring, so a manifest existing here can
never mean a capability silently runs. Same posture as governance scopes
(off-by-default) and the browser-ops flag (the capability, not a schema, is the
kill switch). The lifecycle also reuses the existing governance scope flags
(``is_scope_enabled``) rather than inventing a second on/off authority.

The Stage-1 seed is the Angular governed-frontend capability family from
``docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md`` — declared, inert, nothing
wired.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from app.services.governance import is_scope_enabled


class RiskClass(str, Enum):
    READ = "READ"                # observes, no state change
    ANALYZE = "ANALYZE"          # derives artifacts from inputs, no external effect
    CREATE = "CREATE"            # produces new local artifacts (files, workspace)
    CONSEQUENTIAL = "CONSEQUENTIAL"  # externally visible / irreversible effect


class ExecutionMode(str, Enum):
    OBSERVE = "observe"                  # read-only
    DRAFT = "draft"                      # produces artifacts, never ships
    APPROVE_EXECUTE = "approve_execute"  # named + fresh bound single-use approval


class Lifecycle(str, Enum):
    INERT = "INERT"        # declared, no adapter bound — cannot execute (Stage 1)
    DISABLED = "DISABLED"  # adapter bound but scope OFF
    ENABLED = "ENABLED"    # adapter bound AND scope ON


# family.action.vN — lowercase, dot-separated, explicitly versioned.
_CAP_ID_RE = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+\.v\d+$")


def scope_env_var(scope: str) -> str:
    """The env var an operator sets to enable a scope: 'frontend.scaffold' →
    'KAI_SCOPE_FRONTEND_SCAFFOLD' (matches governance.is_scope_enabled)."""
    return "KAI_SCOPE_" + scope.replace(".", "_").replace("-", "_").upper()


@dataclass(frozen=True)
class CapabilityManifest:
    """Declarative description of ONE governed capability. Frozen: a manifest is
    an identity, not mutable state — lifecycle is computed, never stored on it."""

    capability_id: str
    risk_class: RiskClass
    execution_mode: ExecutionMode
    provider: str
    scope: str                          # governance scope that must be ON to enable
    isolation: str = "sandbox"          # "sandbox" | "none"
    input_schema: str = ""
    output_schema: str = ""
    network_domains: tuple[str, ...] = ()   # deny-by-default egress allowlist
    approval_policy: str = "none"
    evidence_types: tuple[str, ...] = ()
    rollback_target: Optional[str] = None
    description: str = ""

    def __post_init__(self) -> None:
        if not _CAP_ID_RE.match(self.capability_id):
            raise ValueError(
                f"capability_id {self.capability_id!r} must look like "
                "'family.action.vN' (lowercase, dot-separated, versioned)"
            )
        # A capability that can cause an irreversible/external effect must carry
        # real governance: refuse to even DECLARE one with lax controls, so the
        # registry can never hold a dangerous capability that skipped approval.
        if self.risk_class is RiskClass.CONSEQUENTIAL:
            if self.execution_mode is not ExecutionMode.APPROVE_EXECUTE:
                raise ValueError(
                    f"{self.capability_id}: CONSEQUENTIAL must be approve_execute"
                )
            if self.approval_policy.strip().lower() in ("", "none"):
                raise ValueError(
                    f"{self.capability_id}: CONSEQUENTIAL needs an approval_policy"
                )
            if not self.rollback_target:
                raise ValueError(
                    f"{self.capability_id}: CONSEQUENTIAL needs a rollback_target"
                )


# The only thing that can perform a capability. Stage 1 binds none.
Adapter = Callable[..., object]


class CapabilityError(Exception):
    pass


class CapabilityRegistry:
    """Holds capability manifests and (later) their adapters. Inert by default:
    a manifest with no adapter can never execute, enforced in ``execute``."""

    def __init__(self) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}
        self._adapters: dict[str, Adapter] = {}

    def register(self, manifest: CapabilityManifest) -> None:
        if manifest.capability_id in self._manifests:
            raise CapabilityError(
                f"capability {manifest.capability_id!r} already registered"
            )
        self._manifests[manifest.capability_id] = manifest

    def get(self, capability_id: str) -> CapabilityManifest:
        if capability_id not in self._manifests:
            raise KeyError(f"unknown capability {capability_id!r}")
        return self._manifests[capability_id]

    def ids(self) -> list[str]:
        return sorted(self._manifests)

    def bind_adapter(self, capability_id: str, adapter: Adapter) -> None:
        """Bind the executor for a capability. NOT called in Stage 1 — kept so a
        later, separately-approved stage can wire a real sandboxed executor.
        Refuses to bind to an unknown capability."""
        if capability_id not in self._manifests:
            raise KeyError(
                f"cannot bind adapter to unknown capability {capability_id!r}"
            )
        self._adapters[capability_id] = adapter

    def lifecycle(self, capability_id: str) -> Lifecycle:
        manifest = self.get(capability_id)  # KeyError if unknown
        if capability_id not in self._adapters:
            return Lifecycle.INERT
        return (
            Lifecycle.ENABLED
            if is_scope_enabled(manifest.scope)
            else Lifecycle.DISABLED
        )

    def is_executable(self, capability_id: str) -> bool:
        return self.lifecycle(capability_id) is Lifecycle.ENABLED

    def execute(self, capability_id: str, *args, **kwargs):
        """Perform a capability — ONLY if an adapter is bound AND its scope is
        on. In Stage 1 this always raises (no adapters bound): inert by
        construction, not by policy."""
        lc = self.lifecycle(capability_id)
        if lc is Lifecycle.INERT:
            raise CapabilityError(
                f"{capability_id} is INERT: no adapter bound. The capability "
                "exchange is declarative-only at this stage — nothing executes."
            )
        if lc is Lifecycle.DISABLED:
            manifest = self.get(capability_id)
            raise CapabilityError(
                f"{capability_id} is DISABLED: scope {manifest.scope!r} is off "
                f"(set {scope_env_var(manifest.scope)}=1 to enable)."
            )
        return self._adapters[capability_id](*args, **kwargs)

    def summary(self) -> dict:
        by_status: dict[str, list[str]] = {}
        for cid in self.ids():
            by_status.setdefault(self.lifecycle(cid).value, []).append(cid)
        return {
            "total": len(self._manifests),
            "adapters_bound": len(self._adapters),
            "by_status": by_status,
        }


# ─── Stage-1 seed: the Angular governed-frontend capability family ──────────
# Source of truth: docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md. Declared here
# INERT (no adapters). "<pinned>" providers stay literal — the CLI/dep versions
# are an admission event pinned at the later build stage, not now.

ANGULAR_CAPABILITIES: tuple[CapabilityManifest, ...] = (
    CapabilityManifest(
        capability_id="kai.frontend.scaffold.v1",
        risk_class=RiskClass.CREATE,
        execution_mode=ExecutionMode.DRAFT,
        provider="angular-cli@<pinned>",
        scope="frontend.scaffold",
        input_schema="{app_name, style, routing, ssr:bool}",
        output_schema="{workspace_path, files[], lockfile_digest}",
        network_domains=("registry.npmjs.org",),
        approval_policy="none (draft)",
        evidence_types=("lockfile_digest", "tree"),
        description="ng new inside the sandbox, deny-by-default egress except the registry",
    ),
    CapabilityManifest(
        capability_id="kai.frontend.build.v1",
        risk_class=RiskClass.ANALYZE,
        execution_mode=ExecutionMode.DRAFT,
        provider="angular-cli@<pinned>",
        scope="frontend.build",
        evidence_types=("build_hash", "bundle_budget", "warnings"),
        description="production build; bundle-size budget is evidence, not prose",
    ),
    CapabilityManifest(
        capability_id="kai.frontend.test.v1",
        risk_class=RiskClass.ANALYZE,
        execution_mode=ExecutionMode.DRAFT,
        provider="angular-cli@<pinned> + governed-browser-runtime",
        scope="frontend.test",
        evidence_types=("unit_results", "e2e_results", "a11y", "lighthouse"),
        description="unit + e2e (e2e driven by the governed browser runtime) + a11y/Lighthouse",
    ),
    CapabilityManifest(
        capability_id="kai.frontend.preview.v1",
        risk_class=RiskClass.READ,
        execution_mode=ExecutionMode.OBSERVE,
        provider="governed-browser-runtime",
        scope="frontend.preview",
        isolation="sandbox",
        evidence_types=("screenshot", "console", "routes"),
        description="serve locally + drive under host-pin/route/WS/SW/WebRTC egress guards",
    ),
    CapabilityManifest(
        capability_id="kai.frontend.publish.v1",
        risk_class=RiskClass.CONSEQUENTIAL,
        execution_mode=ExecutionMode.APPROVE_EXECUTE,
        provider="governed-deploy",
        scope="frontend.publish",
        approval_policy="named approval + fresh bound single-use approval + evidence",
        evidence_types=("destination", "approval", "rollback_ref"),
        rollback_target="prev build",
        description="deploy ONLY behind named + fresh bound single-use approval; reversible",
    ),
)


def default_registry() -> CapabilityRegistry:
    """The Stage-1 registry: the Angular capability family, declared INERT. No
    adapters bound → ``is_executable`` is False for every capability and
    ``execute`` refuses. This is the declarative contract only."""
    registry = CapabilityRegistry()
    for manifest in ANGULAR_CAPABILITIES:
        registry.register(manifest)
    return registry


if __name__ == "__main__":  # pragma: no cover - smoke check
    r = default_registry()
    assert r.summary()["adapters_bound"] == 0
    assert all(not r.is_executable(cid) for cid in r.ids())
    print(f"capability exchange (inert): {r.summary()}")
