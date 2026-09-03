"""KAI Holding Digital Twin (§3-7, §15) — the canonical NORMALIZED operational state of the holding.

This is NOT a second database of everything. It is a normalized state/index assembled LIVE over the
already-authoritative sources (holding.registry, holding.status, holding.priorities, proposals_store,
CapabilityRegistry). Every operational fact carries provenance (value/source/observed_at/freshness/
status) and unknown is honestly UNAVAILABLE — never fabricated (§58 preserves REAL/DERIVED/DEMO/
UNAVAILABLE). Companies are DISCOVERED dynamically from the registry (§5): add an entity to the
registry and the twin includes it with no code change here.

Sources are injectable (like OperationalSelfModel) so this is a plain ``python3`` self-test with no DB.
Each default source is wrapped fail-open: a subsystem that errors → empty/UNAVAILABLE, never a crash.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable

UNAVAILABLE = "UNAVAILABLE"

# Status taxonomy carried on every Fact (§58) — never collapse these into a bare value.
REAL, DERIVED, DEMO = "REAL", "DERIVED", "DEMO"

# Which registry entity_types are "startups" for the companies[] view (§5). Anything else
# (the holding parent, internal projects) is holding-level context, not a company card.
STARTUP_TYPES = {"product", "company", "LLC", "startup"}


# ── §6 SOURCE-OF-TRUTH MAP ─────────────────────────────────────────────────────────────────────
# For every fact type: canonical source, fallback, and a freshness window (days). Conflicts are
# NOT reconciled by guessing (§6) — the canonical source wins and provenance records which was used.
SOURCE_MAP: dict[str, dict] = {
    "company_identity":  {"canonical": "holding.registry",            "fallback": None,               "freshness_days": 30},
    "repository_state":  {"canonical": "configured git source",       "fallback": "holding.registry", "freshness_days": 1},
    "deployment":        {"canonical": "railway/deploy provider",     "fallback": "holding.registry", "freshness_days": 1},
    "service_health":    {"canonical": "holding.signals/observer",    "fallback": None,               "freshness_days": 1},
    "worker_state":      {"canonical": "holding.status.list_workers", "fallback": None,               "freshness_days": 1},
    "capability_health": {"canonical": "capability registry runtime", "fallback": None,               "freshness_days": 1},
    "owner_actions":     {"canonical": "holding.proposals_store",     "fallback": None,               "freshness_days": 7},
    "priorities":        {"canonical": "holding.priorities",          "fallback": None,               "freshness_days": 1},
    "money":             {"canonical": "approved accounting source",  "fallback": None,               "freshness_days": 30},
    "customers":         {"canonical": "approved CRM/billing source", "fallback": None,               "freshness_days": 30},
    "analytics":         {"canonical": "configured analytics provider", "fallback": None,             "freshness_days": 1},
    "mission":           {"canonical": "KAI holding database",        "fallback": None,               "freshness_days": 1},
}


# ── §7 PROVENANCE ──────────────────────────────────────────────────────────────────────────────
def _freshness(observed_at: str, window_days: int, today: str) -> str:
    """FRESH | STALE | UNKNOWN from a YYYY-MM-DD(...) observed_at vs today. Date-only, deterministic.
    No basis (missing/garbage date) → UNKNOWN; never guesses a freshness it can't compute (§7)."""
    if not observed_at or observed_at == UNAVAILABLE or not today:
        return "UNKNOWN"
    try:
        from datetime import date
        o = date.fromisoformat(observed_at[:10])
        t = date.fromisoformat(today[:10])
        return "FRESH" if (t - o).days <= window_days else "STALE"
    except Exception:
        return "UNKNOWN"


def fact(value: Any, source: str, *, observed_at: str = UNAVAILABLE, fact_type: str = "",
         today: str = "", status: str = REAL, confidence: str | None = None,
         evidence_ref: str | None = None) -> dict:
    """One operational datum with provenance. value None/UNAVAILABLE ⇒ status UNAVAILABLE (§58).

    §16 knowledge-freshness: a Fact may ALSO carry ``confidence`` (from registry.Confidence / data
    provenance) and ``evidence_ref`` (a pointer at the source record, e.g. ``holding.registry:sol.revenue``).
    Both are ADDITIVE and only appear when supplied — a call with neither returns the original 5-key shape,
    so every existing caller/consumer is unchanged (backward-compatible)."""
    if value is None or value == UNAVAILABLE:
        d = {"value": UNAVAILABLE, "source": source, "observed_at": observed_at,
             "freshness": "UNKNOWN", "status": UNAVAILABLE}
    else:
        window = SOURCE_MAP.get(fact_type, {}).get("freshness_days", 30)
        d = {"value": value, "source": source, "observed_at": observed_at,
             "freshness": _freshness(observed_at, window, today), "status": status}
    if confidence is not None:
        d["confidence"] = confidence
    if evidence_ref is not None:
        d["evidence_ref"] = evidence_ref
    return d


def _confidence_from_prov(prov: str) -> str:
    """Pull the registry Confidence marker out of a report_value provenance string (§16 confidence).
    ``"... · confidence=VERIFIED"`` → ``"VERIFIED"``; no marker → ``"UNVERIFIED"`` (never guessed higher)."""
    if isinstance(prov, str) and "confidence=" in prov:
        return prov.split("confidence=", 1)[1].split()[0].strip()
    return "UNVERIFIED"


# ── §4 STARTUP STATE MODEL ─────────────────────────────────────────────────────────────────────
@dataclass
class StartupState:
    company_id: str
    name: str
    slug: str
    entity_type: str = UNAVAILABLE
    mission: str = UNAVAILABLE
    stage: str = UNAVAILABLE
    status: str = UNAVAILABLE
    products: list = field(default_factory=list)
    repositories: list = field(default_factory=list)
    deployments: list = field(default_factory=list)
    domains: list = field(default_factory=list)
    integrations: list = field(default_factory=list)
    # money/customers are provenance Facts — value UNAVAILABLE unless source-backed (never fabricated).
    revenue_summary: dict = field(default_factory=dict)
    expense_summary: dict = field(default_factory=dict)
    customers_summary: dict = field(default_factory=dict)
    compliance_summary: dict = field(default_factory=dict)
    # summaries with no wired source yet — honestly UNAVAILABLE, not invented.
    analytics_summary: str = UNAVAILABLE
    marketing_summary: str = UNAVAILABLE
    sales_summary: str = UNAVAILABLE
    support_summary: str = UNAVAILABLE
    engineering_summary: str = UNAVAILABLE
    security_summary: str = UNAVAILABLE
    active_incidents: list = field(default_factory=list)
    current_goal: str = UNAVAILABLE
    # plan horizons — populated by the planner in a later wave; UNAVAILABLE until then.
    today_plan: Any = UNAVAILABLE
    seven_day_plan: Any = UNAVAILABLE
    thirty_day_plan: Any = UNAVAILABLE
    ninety_day_plan: Any = UNAVAILABLE
    active_missions: list = field(default_factory=list)
    queued_missions: list = field(default_factory=list)
    completed_recently: list = field(default_factory=list)
    kai_actions_available: list = field(default_factory=list)
    owner_actions_required: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    opportunities: list = field(default_factory=list)
    recent_material_changes: list = field(default_factory=list)
    source_freshness: str = UNAVAILABLE
    last_analyzed_at: str = UNAVAILABLE
    last_reconciled_at: str = UNAVAILABLE

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def health(self) -> str:
        """Coarse health for the portfolio view: BLOCKED > INCIDENT > OK, from real state only."""
        if self.blockers or self.owner_actions_required:
            return "NEEDS_OWNER"
        if self.active_incidents:
            return "INCIDENT"
        return "OK"


# ── default live sources (fail-open) ───────────────────────────────────────────────────────────
def _entities() -> list:
    from app.services.holding import registry as reg
    return reg.all_entities()


def _report_value(entity_id: str, field_name: str):
    from app.services.holding import registry as reg
    return reg.report_value(entity_id, field_name)


def _priorities() -> list:
    from app.services.holding.priorities import derive_priorities
    return derive_priorities()


def _open_proposals() -> list:
    from app.services.holding import proposals_store as ps
    return ps.list_proposals(status="proposed")


def _autonomy() -> dict:
    from app.services.holding import status as hstat
    return hstat.autonomy_status()


def _workers() -> list:
    from app.services.holding import status as hstat
    return hstat.list_workers()


def _cap_split() -> dict:
    from app.services.capability.seed import seed_registry
    from app.services.capability.manifest import Availability
    reg = seed_registry()
    avail = sorted(m.id for m in reg.list(availability=Availability.AVAILABLE))
    return {"available": avail, "available_count": len(avail), "catalog_total": len(reg)}


def _hierarchy() -> list:
    from app.services.holding import registry as reg
    return reg.hierarchy_edges()


_DEFAULT_SOURCES: dict[str, Callable] = {
    "entities": _entities, "report_value": _report_value, "priorities": _priorities,
    "open_proposals": _open_proposals, "autonomy": _autonomy, "workers": _workers,
    "capabilities": _cap_split, "hierarchy": _hierarchy,
}


class HoldingDigitalTwin:
    HOLDING_ID = "wheellsverse"

    def __init__(self, *, observed_at: str = UNAVAILABLE, today: str = "",
                 sources: dict[str, Callable] | None = None):
        self._observed_at = observed_at
        self._today = today or (observed_at[:10] if observed_at and observed_at != UNAVAILABLE else "")
        self._src = {**_DEFAULT_SOURCES, **(sources or {})}

    def _get(self, name: str, default: Any) -> Any:
        fn = self._src.get(name)
        if fn is None:
            return default
        try:
            v = fn()
            return v if v is not None else default
        except Exception:      # a failing subsystem is honestly empty/UNAVAILABLE, never a guess
            return default

    def _money_fact(self, entity_id: str, field_name: str, fact_type: str) -> dict:
        """report_value is the ONLY money/customer read path — None ⇒ UNAVAILABLE (never invented).
        §16: carries confidence (parsed from the registry provenance) + evidence_ref (the source record)."""
        rv = self._src.get("report_value")
        try:
            value, prov = rv(entity_id, field_name) if rv else (None, "no source")
        except Exception:
            value, prov = None, "source error"
        # confidence: UNAVAILABLE for an un-sourced value; else the registry's own confidence marker if present.
        confidence = UNAVAILABLE if value is None else _confidence_from_prov(prov)
        evidence_ref = f"holding.registry:{entity_id}.{field_name}"
        return fact(value, prov, fact_type=fact_type, today=self._today,
                    confidence=confidence, evidence_ref=evidence_ref)

    def _proposals_for(self, entity_id: str, proposals: list) -> list:
        return [{"proposal_id": p.get("id"), "title": p.get("title"), "severity": p.get("severity"),
                 "source_key": p.get("source_key")} for p in proposals
                if isinstance(p, dict) and (p.get("entity") == entity_id)]

    def _startup_state(self, e: Any, proposals: list) -> StartupState:
        eid = getattr(e, "entity_id", "")
        owner_actions = self._proposals_for(eid, proposals)
        lv = getattr(e, "last_verified_at", None) or UNAVAILABLE
        repo = getattr(e, "repository", None)
        dep = getattr(e, "deployment", None)
        return StartupState(
            company_id=eid, name=getattr(e, "brand_name", eid), slug=eid,
            entity_type=getattr(e, "entity_type", UNAVAILABLE),
            stage=getattr(e, "stage", UNAVAILABLE) or UNAVAILABLE,
            status=getattr(e, "operational_status", UNAVAILABLE) or UNAVAILABLE,
            products=list(getattr(e, "products", []) or []),
            repositories=[repo] if repo else [],
            deployments=[dep] if dep else [],
            domains=list(getattr(e, "domains", []) or []),
            integrations=list(getattr(e, "integrations", []) or []),
            revenue_summary=self._money_fact(eid, "revenue_metrics", "money"),
            expense_summary=self._money_fact(eid, "expense_metrics", "money"),
            customers_summary=self._money_fact(eid, "customers", "customers"),
            compliance_summary=self._money_fact(eid, "compliance_items", "mission"),
            active_incidents=list(getattr(e, "incidents", []) or []),
            risks=list(getattr(e, "risks", []) or []),
            owner_actions_required=owner_actions,
            source_freshness=_freshness(lv, SOURCE_MAP["company_identity"]["freshness_days"], self._today),
            last_analyzed_at=self._observed_at,
        )

    def companies(self) -> list[StartupState]:
        """DISCOVERED dynamically from the registry (§5): every startup-typed entity, no hard-coding."""
        proposals = self._get("open_proposals", [])
        out = []
        for e in self._get("entities", []):
            if getattr(e, "entity_type", "") in STARTUP_TYPES:
                out.append(self._startup_state(e, proposals))
        return out

    def snapshot(self) -> dict:
        """The normalized twin (§3): holding + companies[] + shared_resources + priorities + risks +
        owner_actions + active_missions + last_reconciled_at. Assembled live, provenance-carrying."""
        proposals = self._get("open_proposals", [])
        companies = self.companies()
        caps = self._get("capabilities", {})
        workers = self._get("workers", [])
        autonomy = self._get("autonomy", {})
        try:                                  # single source of truth, not a stale hardcode (§0#18)
            from app.config import settings as _s
            money_mode = getattr(_s, "MONEY_MODE", "MOCK") or "MOCK"
        except Exception:                     # noqa: BLE001 — config unavailable → honest default
            money_mode = "MOCK"
        return {
            "holding": self.HOLDING_ID,
            "observed_at": self._observed_at,
            # §14 EXPLICIT parent→child hierarchy (edges), not just each company's implicit products[].
            "hierarchy": self._get("hierarchy", []),
            "companies": [c.as_dict() for c in companies],
            "company_count": len(companies),
            "shared_resources": {
                "capabilities_available": caps.get("available_count", UNAVAILABLE),
                "capability_catalog_total": caps.get("catalog_total", UNAVAILABLE),
                "workers_online": sum(1 for w in workers if isinstance(w, dict) and w.get("online")),
                "workers_known": len(workers),
            },
            "holding_priorities": self._get("priorities", []),
            "holding_risks": [{"company": c.company_id, "risk": r} for c in companies for r in c.risks],
            "owner_actions": [{"company": p.get("entity"), "proposal_id": p.get("id"),
                               "title": p.get("title"), "severity": p.get("severity")}
                              for p in proposals if isinstance(p, dict)],
            "active_missions": self._get("active_missions", []),
            "autonomy_overall": autonomy.get("overall", UNAVAILABLE) if isinstance(autonomy, dict) else UNAVAILABLE,
            "money_mode": money_mode,
            "last_reconciled_at": self._observed_at,
        }

    # ── §15 PORTFOLIO VIEW ──────────────────────────────────────────────────────────────────────
    def portfolio_view(self) -> dict:
        """Answers the §15 questions from real state only: who needs attention, who's healthy/blocked,
        what KAI vs the owner must do. No opaque scoring — coarse health from concrete signals."""
        companies = self.companies()
        needs = [c for c in companies if c.health != "OK"]
        healthy = [c for c in companies if c.health == "OK"]
        blocked = [c for c in companies if c.owner_actions_required or c.blockers]
        return {
            "needs_attention": [c.company_id for c in needs],
            "healthy": [c.company_id for c in healthy],
            "blocked": [c.company_id for c in blocked],
            "owner_work_count": sum(len(c.owner_actions_required) for c in companies),
            "kai_work_count": sum(len(c.active_missions) for c in companies),
        }


if __name__ == "__main__":
    from app.services.holding.test_digital_twin import run
    run()
