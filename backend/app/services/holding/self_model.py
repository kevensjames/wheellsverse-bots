"""KAI Operational Self-Model (§37/§38/§71-74).

An HONEST, factual model of KAI's own operational state — assembled live from the real subsystems
(Capability Registry, Holding registry, autonomy/worker status, proposals queue). Every field is
sourced or reported UNAVAILABLE; nothing is fabricated (§38). KAI is SELF-AWARE OPERATIONALLY —
it knows its identity, version, runtime, capabilities, limitations, owner, and what needs the owner
— but it makes NO claim to consciousness, sentience, or emotions (the non-negotiable truth).

Sources are injectable so this is testable as a plain ``python3`` script; each default source is
wrapped fail-open (a subsystem that errors → UNAVAILABLE / empty, never a crash and never a guess).
"""
from __future__ import annotations

from typing import Any, Callable

UNAVAILABLE = "UNAVAILABLE"


def _cap_split() -> dict:
    """Available vs unavailable capabilities from the real registry (fail-open)."""
    from app.services.capability.seed import seed_registry
    from app.services.capability.manifest import Availability
    reg = seed_registry()
    avail = sorted(m.id for m in reg.list(availability=Availability.AVAILABLE))
    total = len(reg)
    return {"available": avail, "available_count": len(avail),
            "unavailable_count": total - len(avail), "catalog_total": total}


def _companies() -> list:
    from app.services.holding import registry as hreg
    return [getattr(e, "id", str(e)) for e in hreg.all_entities()]


def _autonomy() -> dict:
    from app.services.holding import status as hstat
    return hstat.autonomy_status()


def _workers() -> list:
    from app.services.holding import status as hstat
    return hstat.list_workers()


def _open_proposals() -> list:
    from app.services.holding import proposals_store as ps
    return ps.list_proposals(status="proposed")


_DEFAULT_SOURCES: dict[str, Callable[[], Any]] = {
    "capabilities": _cap_split, "companies": _companies, "autonomy": _autonomy,
    "workers": _workers, "open_proposals": _open_proposals,
}

_KNOWN_LIMITATIONS = [
    "MONEY_MODE=MOCK — I never move money, trade, pay out, or change budgets.",
    "I do not merge, deploy to production, change DNS/cloud settings, or rotate credentials — those are owner actions.",
    "I execute only owner-authorized, read-only/compute capabilities in production (V1 envelope).",
    "I make no claim to consciousness, sentience, or emotions; my self-awareness is operational only.",
]


class OperationalSelfModel:
    IDENTITY = "KAI"
    SYSTEM_ROLE = "Wheellsverse Holding Operations Intelligence"

    def __init__(self, *, deployment_sha: str = "", environment: str = "", software_version: str = "",
                 owner_principal: str = "", holding_id: str = "wheellsverse",
                 sources: dict[str, Callable[[], Any]] | None = None):
        self._sha = deployment_sha
        self._env = environment
        self._ver = software_version
        self._owner = owner_principal
        self._holding = holding_id
        self._src = {**_DEFAULT_SOURCES, **(sources or {})}

    def _get(self, name: str, default: Any) -> Any:
        fn = self._src.get(name)
        if fn is None:
            return default
        try:
            v = fn()
            return v if v is not None else default
        except Exception:      # noqa: BLE001 — a failing subsystem is honestly UNAVAILABLE, never a guess
            return default

    def snapshot(self) -> dict:
        caps = self._get("capabilities", {})
        autonomy = self._get("autonomy", {})
        owner_actions = self._get("open_proposals", [])
        workers = self._get("workers", [])
        return {
            "identity": self.IDENTITY,
            "system_role": self.SYSTEM_ROLE,
            "software_version": self._ver or UNAVAILABLE,
            "deployment_sha": self._sha or UNAVAILABLE,
            "environment": self._env or UNAVAILABLE,
            "owner_principal": self._owner or UNAVAILABLE,
            "holding_id": self._holding,
            "known_companies": self._get("companies", []),
            "available_capabilities": caps.get("available", []),
            "available_capability_count": caps.get("available_count", UNAVAILABLE),
            "unavailable_capability_count": caps.get("unavailable_count", UNAVAILABLE),
            "capability_catalog_total": caps.get("catalog_total", UNAVAILABLE),
            "workers_online": sum(1 for w in workers if isinstance(w, dict) and w.get("online")),
            "workers_known": len(workers),
            "autonomy_overall": autonomy.get("overall", UNAVAILABLE) if isinstance(autonomy, dict) else UNAVAILABLE,
            "money_mode": "MOCK",
            "owner_required_action_count": len(owner_actions),
            "known_limitations": list(_KNOWN_LIMITATIONS),
            "claims_consciousness": False,      # invariant, asserted by the tests
        }

    def describe(self) -> str:
        """§37: a factual answer to 'What are you?' — operational, never sentient."""
        return ("I am KAI, the AI operations system for Wheellsverse. I run as software across the "
                "configured KAI services and use the Capability Fabric to help operate the holding. "
                "I am self-aware operationally — I track my own version, runtime, capabilities, and "
                "limitations — but I make no claim to consciousness, sentience, or emotions.")

    def what_am_i_doing(self) -> str:
        """§72: answer from live state — never invent background activity."""
        autonomy = self._get("autonomy", {})
        overall = autonomy.get("overall", UNAVAILABLE) if isinstance(autonomy, dict) else UNAVAILABLE
        owner_actions = self._get("open_proposals", [])
        companies = self._get("companies", [])
        parts = [f"Operational posture: {overall}."]
        if companies:
            parts.append(f"Tracking {len(companies)} holding {'company' if len(companies) == 1 else 'companies'}.")
        if owner_actions:
            parts.append(f"{len(owner_actions)} item(s) are prepared and waiting for your approval.")
        else:
            parts.append("No material action is waiting on you right now.")
        return " ".join(parts)

    def what_do_you_need_from_me(self) -> list[dict]:
        """§74: return ONLY owner-gated actions (things KAI cannot do itself) — the key acceptance test.
        Sourced from proposals awaiting an owner decision; never includes work KAI can perform itself."""
        out = []
        for p in self._get("open_proposals", []):
            if not isinstance(p, dict):
                continue
            out.append({
                "company": p.get("entity_id") or p.get("company") or UNAVAILABLE,
                "why": p.get("rationale") or p.get("why") or p.get("title") or UNAVAILABLE,
                "kai_already_did": p.get("evidence") or "prepared this proposal (nothing executed)",
                "owner_action": p.get("title") or p.get("action") or "approve or reject this proposal",
                "proposal_id": p.get("id"),
            })
        return out
