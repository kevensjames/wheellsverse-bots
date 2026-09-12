"""KAI Capability Exchange — declarative capability CATALOG (Phase 1).

A *capability* is a governed mission type KAI can be granted (scaffold an Angular
app, run a browser mission, ...). This module is a **catalog only**: it holds
capability *manifests* (what a capability is — its risk class, isolation, egress
domains, approval policy, evidence types) and reports inventory. It has NO surface
that can make a capability run — no adapter binding, no execution, no scope/flag
evaluation. ``execution_supported`` is ``False``.

Being a catalog is a property of *construction*: there is simply no code path to
execution, so no in-process caller (not just no HTTP caller) can activate a
capability through it. (This corrects an earlier version that exposed
``bind_adapter`` + ``execute``, which — like the earlier HookRegistry — let an
in-process caller run a capability once an env scope flag was set.)

Executing a capability is the job of a FUTURE, separately-built broker/executor
that may exist ONLY after L3 (credential/network isolation), policy, approvals,
sandbox, and independent evidence verification are certified. When built, its kill
switch MUST default to BLOCKING; any activation is a separately named enable flag
— never a scope truthiness that turns execution on.

The Stage-1 seed is the Angular governed-frontend capability family from
``docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md`` — declared, catalog-only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RiskClass(str, Enum):
    READ = "READ"                # observes, no state change
    ANALYZE = "ANALYZE"          # derives artifacts from inputs, no external effect
    CREATE = "CREATE"            # produces new local artifacts (files, workspace)
    CONSEQUENTIAL = "CONSEQUENTIAL"  # externally visible / irreversible effect


class ExecutionMode(str, Enum):
    OBSERVE = "observe"                  # read-only
    DRAFT = "draft"                      # produces artifacts, never ships
    APPROVE_EXECUTE = "approve_execute"  # named + fresh bound single-use approval


# family.action.vN — lowercase, dot-separated, explicitly versioned.
_CAP_ID_RE = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+\.v\d+$")


def scope_env_var(scope: str) -> str:
    """Pure formatter: the env var an operator WOULD set to enable a scope —
    'frontend.scaffold' → 'KAI_SCOPE_FRONTEND_SCAFFOLD'. Documentation/mapping
    only; this module never reads it (a future broker would)."""
    return "KAI_SCOPE_" + scope.replace(".", "_").replace("-", "_").upper()


@dataclass(frozen=True)
class CapabilityManifest:
    """Declarative description of ONE governed capability. Frozen: a manifest is
    an identity, not mutable state."""

    capability_id: str
    risk_class: RiskClass
    execution_mode: ExecutionMode
    provider: str
    scope: str                          # the governance scope a future broker would require
    isolation: str = "sandbox"          # "sandbox" | "none"
    input_schema: str = ""
    output_schema: str = ""
    network_domains: tuple[str, ...] = ()   # deny-by-default egress allowlist (declarative)
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
        # catalog can never hold a dangerous capability that skipped approval.
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


class CapabilityError(Exception):
    pass


class CapabilityRegistry:
    """Catalog only. Holds and looks up capability manifests; never executes one
    and has no surface (binding, dispatch, scope evaluation) through which any
    caller could."""

    #: There is no execution path in this class, by construction.
    execution_supported: bool = False

    def __init__(self) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}

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

    def for_risk(self, risk_class: RiskClass) -> list[CapabilityManifest]:
        """Catalog filter — read-only inspection, arms/runs nothing."""
        return [m for m in self._manifests.values() if m.risk_class is risk_class]

    def summary(self) -> dict:
        by_risk: dict[str, int] = {}
        by_mode: dict[str, int] = {}
        for m in self._manifests.values():
            by_risk[m.risk_class.value] = by_risk.get(m.risk_class.value, 0) + 1
            by_mode[m.execution_mode.value] = by_mode.get(m.execution_mode.value, 0) + 1
        return {
            "total": len(self._manifests),
            "execution_supported": self.execution_supported,
            "by_risk": by_risk,
            "by_mode": by_mode,
        }


# ─── Stage-1 seed: the Angular governed-frontend capability family ──────────
# Source of truth: docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md. Declared here as
# a catalog. "<pinned>" providers stay literal — the CLI/dep versions are an
# admission event pinned at the later build stage, not now.

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
    """The Stage-1 catalog: the Angular capability family, declared. No execution
    surface exists (execution_supported=False) — this is the declarative contract
    only."""
    registry = CapabilityRegistry()
    for manifest in ANGULAR_CAPABILITIES:
        registry.register(manifest)
    return registry


if __name__ == "__main__":  # pragma: no cover - smoke check
    r = default_registry()
    assert r.summary()["execution_supported"] is False
    assert not hasattr(r, "execute") and not hasattr(r, "bind_adapter")
    print(f"capability exchange (catalog-only): {r.summary()}")
