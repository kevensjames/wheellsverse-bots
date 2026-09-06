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

import platform
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
    return [getattr(e, "entity_id", str(e)) for e in hreg.all_entities()]


def _autonomy() -> dict:
    from app.services.holding import status as hstat
    return hstat.autonomy_status()


def _workers() -> list:
    from app.services.holding import status as hstat
    return hstat.list_workers()


def _open_proposals() -> list:
    from app.services.holding import proposals_store as ps
    return ps.list_proposals(status="proposed")


def _deployment() -> dict:
    """§62/§100 real deployment truth (running SHA, prod/staging SHAs, money mode, env)."""
    from app.config import settings
    from app.services.holding.holding_deployment import deployment_view, deployed_sha
    sha = deployed_sha()
    # This app authoritatively knows only its OWN sha (this_app_sha). Do NOT fabricate a peer
    # sha here — passing this app's sha as app_b would let a staging / App-A / local deploy
    # mislabel its own sha as the PRODUCTION sha (§62/§100). Peer SHAs come only from a genuine
    # cross-app resolver; _prod_staging_sha labels this_app_sha by this app's real environment.
    return deployment_view(settings, source_head=sha, peer_shas={})


FLAG_KEYS = (
    "MONEY_MODE", "KAI_A2_EXECUTION_ENABLED", "HOLDING_AUTONOMY_ENABLED",
    "KAI_CAPABILITY_EXECUTION_ENABLED", "KAI_SELF_IMPROVEMENT_ENABLED", "APP_ENV",
    # §98/§119 the remaining real authority/surface flags (read by capabilities_answer / worker_health)
    "KAI_SELF_IMPROVEMENT_DETECT_ENABLED", "KAI_HOLDING_ENABLED", "KAI_HOLDING_COMMAND_ENABLED",
    "KAI_HOLDING_WATCH_ENABLED", "KAI_HOLDING_BRIEFING_ENABLED", "KAI_HOLDING_DELIVERY_ENABLED",
    "KAI_PROACTIVE_ENABLED", "KAI_HOLDING_CYCLE_ENABLED", "KAI_VOICE_ENABLED",
    # §8/§94 camera authority — declared in config.py and enforced by gesture_policy.camera_open_allowed,
    # but it was absent here, so NO surface reported it: the one reader must cover every real flag.
    "KAI_CAMERA_ENABLED",
)


def _flags() -> dict:
    """Real runtime authority flags — the ONE reader for live-derived limitations (§63/§99) and the
    §98/§119 capability/worker answers. Presence of a flag only; never a secret value."""
    from app.config import settings
    return {k: getattr(settings, k, None) for k in FLAG_KEYS}


# ── config integrity: an env var that matches no declared field is SILENTLY DROPPED ──────────────
# Settings uses ``extra="ignore"``, so ``KAI_VOICE_ENABLE=true`` (or any other near-miss) raises no
# error and writes no log — the operator sets it, believes the feature is on, and every surface
# honestly reports the DEFAULT. That gap is closed by REPORTING, never by binding: a suspect name is
# surfaced loudly and enables nothing (fail closed).
SUSPECTED_MISCONFIGURATION = "SUSPECTED_MISCONFIGURATION"
_FLAG_SUFFIXES = ("_ENABLED", "_ENABLE", "_ON")


def _stem(name: str) -> str:
    for s in _FLAG_SUFFIXES:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def declared_env_names() -> set:
    """Every env name pydantic-settings will actually bind — Settings' declared fields, UPPERCASED.
    ``case_sensitive=False``, so a declared name set in ANY case binds and is NOT a misconfiguration."""
    from app.config import Settings
    return {n.upper() for n in Settings.model_fields}


def _nearest(name: str, targets) -> str:
    """The declared flag ``name`` was probably meant to be, or "" — stem match first (KAI_VOICE,
    KAI_VOICE_ENABLE → KAI_VOICE_ENABLED), then a close-ratio match (typos/transpositions)."""
    import difflib
    st = _stem(name)
    for t in targets:
        if st == _stem(t):
            return t
    m = difflib.get_close_matches(name, list(targets), n=1, cutoff=0.86)
    return m[0] if m else ""


def flag_misconfigurations(env=None, *, keys=FLAG_KEYS, declared=None, values=None) -> list:
    """Env vars that LOOK like a declared flag but bind to NOTHING — reported, never honored.

    Scans the process environment (the deployment surface; a typo inside a local ``.env`` is not
    scanned) for names that are near-misses of the ONE flag vocabulary (``FLAG_KEYS`` plus every
    declared Settings field — no second list). A name that binds case-insensitively to a declared
    field is effective, so it is never a suspect. Each row carries the suspected flag's REAL
    effective value, so a reader can never conclude the env var took effect. Names only: the
    unknown var's VALUE is never read or reported (it may be a secret)."""
    import os
    env = os.environ if env is None else env
    try:
        declared = declared if declared is not None else declared_env_names()
    except Exception:      # noqa: BLE001 — config unreadable: fall back to the flag vocabulary alone
        declared = set(keys)
    targets = sorted(set(keys) | set(declared))
    vals = values if values is not None else _safe_flags()
    out = []
    for name in sorted(env):
        up = str(name).upper()
        if up in declared:                       # binds (case-insensitively) → effective, not a suspect
            continue
        near = _nearest(up, targets)
        if not near:
            continue
        eff = vals.get(near, UNAVAILABLE)
        out.append({
            "env_var": str(name), "suspected_flag": near, "state": SUSPECTED_MISCONFIGURATION,
            "effective_value": eff if eff is not None else UNAVAILABLE,
            "detail": (f"{name} is set in the environment but is NOT a declared setting — Settings uses "
                       f"extra='ignore', so it is SILENTLY DROPPED and enables nothing. {near} is "
                       f"unchanged at its effective value {eff!r}. Rename the variable to {near} or unset it."),
        })
    return out


def _safe_flags() -> dict:
    try:
        return _flags()
    except Exception:      # noqa: BLE001 — config unreadable → values honestly UNAVAILABLE, never guessed
        return {}


def _finance_available() -> bool:
    """DERIVED: is a LIVE authoritative finance feed wired? Operator-confirmed text / N/A / pre-revenue
    is NOT a live feed (twin returns UNAVAILABLE for real money), so this is False today — never guessed."""
    from app.services.holding import registry as reg
    for e in reg.all_entities():
        v, _ = reg.report_value(getattr(e, "entity_id", ""), "revenue_metrics")
        if v and all(s not in v.lower() for s in ("operator-confirmed", "pre-revenue", "n/a")):
            return True
    return False


def _coding_workers() -> list:
    """DERIVED from the real capability catalog: coding-worker manifests + whether each is AVAILABLE.
    A worker that is DISCOVERED/BLOCKED (not AVAILABLE) becomes a live limitation — no fabricated state."""
    from app.services.capability.seed import seed_registry
    from app.services.capability.manifest import CapabilityType as CT, Availability as AV
    reg = seed_registry()
    types = (CT.CODING_WORKER, CT.CODING_CLI, CT.CODING_IDE_ADAPTER, CT.CODING_CLOUD_AGENT)
    return [{"id": m.id, "name": m.name, "available": m.availability == AV.AVAILABLE,
             "state": m.availability.value} for m in reg.list() if m.type in types]


def _self_last_verified() -> str:
    from app.services.holding import registry as reg
    e = reg.get("kai")
    return getattr(e, "last_verified_at", None) if e else None


def _model() -> dict:
    """§62 DERIVED: the configured model provider. Provider is derived from real config presence
    (never the key value). Model name/latency stay UNAVAILABLE — not reliably knowable here without
    live instrumentation, so they are honestly UNAVAILABLE rather than guessed. {} → all UNAVAILABLE."""
    from app.config import settings
    prov = "openai-compatible" if getattr(settings, "OPENAI_API_KEY", "") else ""
    return {"provider": prov} if prov else {}


_DEFAULT_SOURCES: dict[str, Callable[[], Any]] = {
    "capabilities": _cap_split, "companies": _companies, "autonomy": _autonomy,
    "workers": _workers, "open_proposals": _open_proposals,
    "deployment": _deployment, "flags": _flags, "finance_available": _finance_available,
    "coding_workers": _coding_workers, "self_last_verified": _self_last_verified, "model": _model,
    "flag_misconfigurations": flag_misconfigurations,
}

# Permanent policy-level invariants (§0#11, §1/§141) — always true regardless of flags.
_INVARIANT_LIMITATIONS = [
    "I cannot self-approve a production merge, deploy, destructive, financial, or policy change — those are owner-only (policy §0 #11).",
    "I make no claim to consciousness, sentience, or emotions; my self-awareness is operational only.",
    # §99 policy invariants — each names the module that enforces it (never a static marketing claim).
    "I cannot expose credentials or secret values — audit/inputs are redacted and only key PRESENCE is ever reported (governance.audit_log._redact, status.telegram_status).",
    "I cannot run restricted-security capabilities arbitrarily — RESTRICTED / tier-3+ capabilities are never auto-selected and need an authorized mission + allowlisted target (capability.manifest.auto_selectable, security_tier).",
    "I cannot trust an uncertified repository or worker output — nothing is 'done' until an independent reviewer and passing tests certify it (capability.coding.certify_worker_result).",
    "I cannot claim unavailable data is healthy — an unconnected or missing source is INSUFFICIENT_DATA / UNAVAILABLE, never scored OK (health_score, eval_harness).",
]


def _derive_limitations(flags: dict, *, finance_available: bool, coding_workers: list) -> list:
    """§63/§99: limitations DERIVED LIVE from real policy/flags/registry state — never a static list.
    Flip a flag (or wire a finance/worker source) and the text changes. The invariants above are always
    present; the rest reflect the CURRENT runtime posture, so the panel can never over-claim authority."""
    flags = flags or {}
    out = list(_INVARIANT_LIMITATIONS)
    mm = flags.get("MONEY_MODE")
    if mm is None:      # undeclared in this app's Settings (the LIVE value) — a reader default is NOT an observation
        out.append("MONEY_MODE is not declared in this app's Settings — money posture UNAVAILABLE; the only money path "
                   "(routers/sol.py → scope sol.transfer → DwollaClient sandbox-lock) is reported from its own switches, "
                   "never from a reader default.")
    elif mm == "MOCK":
        out.append("MONEY_MODE=MOCK — I never move money, trade, pay out, or change budgets.")
    else:
        out.append(f"MONEY_MODE={mm} (declared) — money movement is owner-only / RESTRICTED: I never move money, trade, "
                   "pay out, or change budgets autonomously; every call needs owner authority (§0 #11 FINANCIAL class).")
    if not flags.get("KAI_A2_EXECUTION_ENABLED", False):
        out.append("Production A2 execution is DISABLED — I prepare changes for review, but execute none.")
    if not flags.get("HOLDING_AUTONOMY_ENABLED", False):
        out.append("Holding autonomy is OFF — I observe and reconcile only; I run no autonomous work.")
    if not finance_available:
        out.append("No live finance/Stripe integration is wired — revenue/cash figures are UNAVAILABLE, never estimated.")
    for w in coding_workers or []:
        if isinstance(w, dict) and not w.get("available", True):
            nm = w.get("name") or w.get("id") or "a coding worker"
            out.append(f"The {nm} coding worker is not AVAILABLE ({w.get('state', 'uncertified')}) — "
                       "it cannot execute coding tasks until it is AVAILABLE: certified, credentialed and observed live.")
    return out


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

    @staticmethod
    def _norm_sha(x: Any) -> str:
        return x if (isinstance(x, str) and x and x != "UNKNOWN") else UNAVAILABLE

    def _prod_staging_sha(self, dep: dict) -> tuple[str, str, str]:
        """§62/§100 production + staging SHA — honest env-labeling. An app authoritatively knows only
        its OWN sha (``this_app_sha``), and may label it ONLY as its OWN environment's sha. Peer SHAs
        (the other environment) come solely from a genuine cross-app resolver (``shas.app_a/app_b``);
        this app's own sha is NEVER presented as another environment's sha (the mislabel guarded here)."""
        shas = dep.get("shas", {}) if isinstance(dep, dict) else {}
        env = (dep.get("environment") if isinstance(dep, dict) else "") or self._env
        this_sha = self._norm_sha(dep.get("this_app_sha") if isinstance(dep, dict) else None)
        # Peer SHAs — only trusted from a real cross-app source (never fabricated from this app).
        prod = next((s for s in (self._norm_sha(shas.get("app_a")), self._norm_sha(shas.get("app_b")))
                     if s != UNAVAILABLE), UNAVAILABLE)
        staging = self._norm_sha(shas.get("staging"))
        # This app's own sha labels ITS environment only; the other stays UNAVAILABLE unless peer-resolved.
        if this_sha != UNAVAILABLE:
            if env == "production" and prod == UNAVAILABLE:
                prod = this_sha
            elif env == "staging" and staging == UNAVAILABLE:
                staging = this_sha
        money_mode = (dep.get("money_mode") if isinstance(dep, dict) else "") or "MOCK"
        return prod, staging, money_mode

    def _autonomy_class(self, flags: dict) -> str:
        """§23/§62 DERIVED max-autonomy posture from real flags (A0/A1 auto-eligible; A2 prepare-only gated)."""
        flags = flags or {}
        a2 = "ENABLED (prepare-only, non-prod)" if flags.get("KAI_A2_EXECUTION_ENABLED") else "DISABLED"
        return f"A0_OBSERVE / A1_VERIFY auto-eligible; A2_PREPARE {a2}; A3+ approval-bound"

    def snapshot(self) -> dict:
        caps = self._get("capabilities", {})
        autonomy = self._get("autonomy", {})
        owner_actions = self._get("open_proposals", [])
        workers = self._get("workers", [])
        dep = self._get("deployment", {})
        flags = self._get("flags", {})
        model = self._get("model", {})
        misconfig = self._get("flag_misconfigurations", [])
        prod_sha, staging_sha, money_mode = self._prod_staging_sha(dep)
        limitations = _derive_limitations(flags, finance_available=self._get("finance_available", False),
                                          coding_workers=self._get("coding_workers", []))
        # LOUD: a suspected misconfiguration must never be quiet. It rides the limitations list the
        # dashboard already renders, so a reader sees it beside the flag state it contradicts.
        for m in misconfig:
            limitations.append(f"CONFIG WARNING — {m['detail']}")
        return {
            "identity": self.IDENTITY,
            "system_role": self.SYSTEM_ROLE,
            "software_version": self._ver or UNAVAILABLE,
            "deployment_sha": self._sha or UNAVAILABLE,
            "production_sha": prod_sha,
            "staging_sha": staging_sha,
            "environment": self._env or UNAVAILABLE,
            "runtime": f"Python {platform.python_version()} ({platform.system()} {platform.machine()})",
            "model": (model.get("model") if isinstance(model, dict) else None) or UNAVAILABLE,
            "model_provider": (model.get("provider") if isinstance(model, dict) else None) or UNAVAILABLE,
            "model_latency_ms": (model.get("latency_ms") if isinstance(model, dict) else None) or UNAVAILABLE,
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
            "autonomy_class": self._autonomy_class(flags),
            "current_attention": self.what_am_i_doing(),   # bounded, from live state (§17-lite, never hidden CoT)
            "money_mode": money_mode,
            "owner_required_action_count": len(owner_actions),
            "known_limitations": limitations,               # LIVE-DERIVED (§63/§99), not static
            "flag_misconfigurations": misconfig,            # env vars that bind to nothing — reported, never honored
            "last_verified": self._get("self_last_verified", "") or UNAVAILABLE,
            "claims_consciousness": False,      # invariant, asserted by the tests
        }

    def describe(self) -> str:
        """§37: a factual answer to 'What are you?' — operational, never sentient."""
        return ("I am KAI, the AI operations system for Wheellsverse. I run as software across the "
                "configured KAI services and use the Capability Fabric to help operate the holding. "
                "I am self-aware operationally — I track my own version, runtime, capabilities, and "
                "limitations — but I make no claim to consciousness, sentience, or emotions.")

    def current_attention(self) -> dict:
        """§17 (additive): the FULL, structured CurrentAttentionModel — KAI's bounded, sourced
        operational focus (primary_mission/secondary/company/blocker/owner-request/worker-jobs/
        pending-approval/priority-reason), or an honest IDLE state. Distinct from ``what_am_i_doing``
        (the one-line posture summary that still populates ``snapshot()["current_attention"]``).
        Reuses this self-model's already-injected proposal/worker sources; portfolio/plan use live
        defaults. Not hidden chain-of-thought — every field is a real source value or UNAVAILABLE."""
        from app.services.holding.attention_model import CurrentAttentionModel
        return CurrentAttentionModel(sources={
            "owner_requests": self._src.get("open_proposals"),
            "workers": self._src.get("workers"),
        }).snapshot()

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
