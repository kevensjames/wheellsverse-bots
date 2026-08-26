"""KAI Capability Fabric — the single CapabilityRegistry (§15).

ONE registry over ALL capability types (MCP, skills, runtimes, adapters). There is no
separate MCP-registry / skill-registry / plugin-registry competing with it — adapters sit
*beneath* this registry, not beside it (§12). The registry is the catalog the Brain queries;
it does not itself activate anything (that is the lifecycle manager).

Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

from .manifest import (
    CapabilityManifest,
    CapabilityType,
    Availability,
    ActivationMode,
    Certification,
)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, CapabilityManifest] = {}
        self._disabled_prev: dict[str, ActivationMode] = {}   # remembers activation across disable/enable

    # ── registration ────────────────────────────────────────────────────────
    def register(self, manifest: CapabilityManifest) -> CapabilityManifest:
        if manifest.id in self._caps:
            raise ValueError(f"capability {manifest.id!r} already registered")
        self._caps[manifest.id] = manifest
        return manifest

    def register_all(self, manifests: list[CapabilityManifest]) -> None:
        for m in manifests:
            self.register(m)

    def unregister(self, cap_id: str) -> None:
        self._caps.pop(cap_id, None)
        self._disabled_prev.pop(cap_id, None)

    # ── lookup ──────────────────────────────────────────────────────────────
    def get(self, cap_id: str) -> CapabilityManifest:
        try:
            return self._caps[cap_id]
        except KeyError:
            raise KeyError(f"unknown capability {cap_id!r}")

    def has(self, cap_id: str) -> bool:
        return cap_id in self._caps

    def list(
        self,
        *,
        type: CapabilityType | None = None,
        availability: Availability | None = None,
        certification: Certification | None = None,
        selectable_only: bool = False,
    ) -> list[CapabilityManifest]:
        out = list(self._caps.values())
        if type is not None:
            out = [m for m in out if m.type == type]
        if availability is not None:
            out = [m for m in out if m.availability == availability]
        if certification is not None:
            out = [m for m in out if m.certification == certification]
        if selectable_only:
            out = [m for m in out if m.selectable()]
        return out

    # ── enable / disable / quarantine ─────────────────────────────────────────
    def disable(self, cap_id: str) -> None:
        m = self.get(cap_id)
        if m.activation != ActivationMode.DISABLED:
            self._disabled_prev[cap_id] = m.activation
        m.activation = ActivationMode.DISABLED

    def enable(self, cap_id: str) -> None:
        m = self.get(cap_id)
        # never re-enable a quarantined capability by this path — that requires clear_quarantine()
        if m.availability == Availability.QUARANTINED:
            raise ValueError(f"{cap_id!r} is QUARANTINED; clear quarantine before enabling")
        m.activation = self._disabled_prev.pop(cap_id, ActivationMode.ON_DEMAND)

    def quarantine(self, cap_id: str, reason: str = "") -> None:
        """Policy/health violation → block until explicitly cleared (§52). No auto-reactivation."""
        m = self.get(cap_id)
        m.availability = Availability.QUARANTINED
        if reason:
            m.notes = (m.notes + f" | QUARANTINED: {reason}").strip(" |")

    def clear_quarantine(self, cap_id: str, new_availability: Availability = Availability.AVAILABLE) -> None:
        m = self.get(cap_id)
        if m.availability != Availability.QUARANTINED:
            return
        m.availability = new_availability

    def is_quarantined(self, cap_id: str) -> bool:
        return self.get(cap_id).availability == Availability.QUARANTINED

    # ── relationships ─────────────────────────────────────────────────────────
    def dependencies(self, cap_id: str) -> list[str]:
        return list(self.get(cap_id).dependencies)

    def conflicts(self, cap_id: str) -> list[str]:
        return list(self.get(cap_id).conflicts)

    def version(self, cap_id: str) -> str:
        return self.get(cap_id).version

    def health(self, cap_id: str) -> dict:
        m = self.get(cap_id)
        return {"id": m.id, "availability": m.availability.value, "activation": m.activation.value,
                "certification": m.certification.value}

    def __len__(self) -> int:
        return len(self._caps)
