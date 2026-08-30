"""Holding Registry — KAI's authoritative operational model of the holding.

Hard rule: KAI must NEVER fabricate revenue, balances, customers, compliance status,
ownership, or funding. Any datum not sourced from a trusted, cited source is marked
UNVERIFIED / UNKNOWN / REQUIRES_OPERATOR_CONFIRMATION and returns None for its value.
Only facts verifiable from this repo or this engagement's live checks are seeded; every
financial / customer / legal / compliance field defaults to operator confirmation.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Confidence(str, Enum):
    VERIFIED = "VERIFIED"                              # cited, checked this engagement / in-repo
    UNVERIFIED = "UNVERIFIED"                          # plausible but not re-checked
    UNKNOWN = "UNKNOWN"
    REQUIRES_OPERATOR_CONFIRMATION = "REQUIRES_OPERATOR_CONFIRMATION"

# Value classes that KAI may never invent — always operator-confirmed unless source-cited.
_MUST_CONFIRM = "REQUIRES_OPERATOR_CONFIRMATION"


@dataclass
class HoldingEntity:
    entity_id: str
    brand_name: str
    entity_type: str = "UNKNOWN"                       # product | company | project | LLC …
    legal_name: Optional[str] = None                   # REQUIRES confirmation unless cited
    ownership: str = _MUST_CONFIRM
    operational_status: str = "UNKNOWN"
    stage: str = "UNKNOWN"
    repository: Optional[str] = None
    deployment: Optional[str] = None
    domains: list = field(default_factory=list)
    products: list = field(default_factory=list)
    # financials / customers — NEVER fabricated: None value + confirm marker
    revenue_metrics: str = _MUST_CONFIRM
    expense_metrics: str = _MUST_CONFIRM
    customers: str = _MUST_CONFIRM
    banking_provider_reference: str = _MUST_CONFIRM
    payment_provider_reference: str = _MUST_CONFIRM
    kpis: list = field(default_factory=list)
    projects: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    incidents: list = field(default_factory=list)
    compliance_items: str = _MUST_CONFIRM
    integrations: list = field(default_factory=list)
    last_verified_at: Optional[str] = None
    data_source: str = ""                              # citation for VERIFIED facts
    confidence: Confidence = Confidence.UNVERIFIED

    def as_dict(self) -> dict:
        d = asdict(self); d["confidence"] = self.confidence.value; return d


# Seed set. Only repo/deployment/status verifiable from THIS engagement or the repo is set;
# all money/customer/legal fields keep the confirm-marker (no fabrication).
_ENTITIES: list[HoldingEntity] = [
    HoldingEntity("wheellsverse_holdings", "Wheellsverse Holdings", entity_type="holding",
                  operational_status="ACTIVE", stage="operating",
                  data_source="operator-stated (mission)", confidence=Confidence.REQUIRES_OPERATOR_CONFIRMATION),
    HoldingEntity("solcircle", "SOLCIRCLE Technologies LLC", entity_type="LLC",
                  legal_name=None, data_source="operator-stated (mission)",
                  confidence=Confidence.REQUIRES_OPERATOR_CONFIRMATION),
    HoldingEntity("sol", "SOL", entity_type="product", operational_status="DEPLOYED",
                  stage="live (MONEY MODE MOCK — no real payments)",
                  repository="wheellsverse-sol (standalone) + wheellsverse-bots (frontend/engine)",
                  deployment="Railway (grateful-flexibility-production)",
                  data_source="verified this engagement (Sol deploy reality, staging env)",
                  confidence=Confidence.VERIFIED),
    HoldingEntity("kai", "KAI", entity_type="product", operational_status="LIVE",
                  stage="governed prod (App A app.wheellsverse.com ⇄ App B kai-prod, bridge ON)",
                  repository="wheellsverse-bots (core/api.py + backend/app)",
                  deployment="Railway: grateful-flexibility (App A) + kai-production (App B)",
                  domains=["app.wheellsverse.com"],
                  data_source="verified this engagement (Phase 0–4, operational-truth cert)",
                  confidence=Confidence.VERIFIED),
    HoldingEntity("nurtelle", "Nurtelle", entity_type="product", operational_status="UNVERIFIED",
                  repository="kevensjames/chenara (private; renamed Nurtelle publicly)",
                  data_source="prior memory (point-in-time) — re-confirm", confidence=Confidence.UNVERIFIED),
    HoldingEntity("narai", "NarAI", entity_type="product", operational_status="UNVERIFIED",
                  repository="wheellsverse-bots (NarAI-v2 chat + /api/narai)",
                  data_source="in-repo (NarAI_Genesis_Master_Plan.md) + core/api", confidence=Confidence.UNVERIFIED),
    HoldingEntity("nexora", "Nexora", entity_type="product", operational_status="UNVERIFIED",
                  data_source="prior SaaS audit (point-in-time) — re-confirm", confidence=Confidence.UNVERIFIED),
    HoldingEntity("siteboost", "SiteBoost", entity_type="product", operational_status="UNVERIFIED",
                  repository="wheellsverse-bots (frontend/siteboost)",
                  data_source="in-repo (SITEBOOST_LAUNCH.md, data/launches/siteboost)", confidence=Confidence.UNVERIFIED),
    HoldingEntity("wmos", "W-MOS", entity_type="project", operational_status="UNKNOWN",
                  data_source="operator-stated — re-confirm scope", confidence=Confidence.UNKNOWN),
    HoldingEntity("suprema", "Suprema", entity_type="project", operational_status="UNKNOWN",
                  repository="wheellsverse-bots (backend admin_supreme)",
                  data_source="in-repo router only — scope unknown", confidence=Confidence.UNKNOWN),
    HoldingEntity("wheellsverse_bots", "Wheellsverse Bots", entity_type="project", operational_status="ACTIVE",
                  stage="monorepo (this repo)", repository="kevensjames/wheellsverse-bots",
                  data_source="verified this engagement", confidence=Confidence.VERIFIED),
]
_BY_ID = {e.entity_id: e for e in _ENTITIES}


def all_entities() -> list[HoldingEntity]:
    return list(_ENTITIES)

def get(entity_id: str) -> Optional[HoldingEntity]:
    return _BY_ID.get(entity_id)

def needs_confirmation() -> list[str]:
    """Fields KAI must NOT report without operator confirmation, per entity."""
    out = []
    for e in _ENTITIES:
        for fld in ("revenue_metrics", "expense_metrics", "customers", "banking_provider_reference",
                    "payment_provider_reference", "compliance_items", "ownership"):
            if getattr(e, fld) == _MUST_CONFIRM:
                out.append(f"{e.entity_id}.{fld}")
    return out

def report_value(entity_id: str, field_name: str) -> tuple[Optional[str], str]:
    """The ONLY way KAI reads a holding datum. Returns (value_or_None, provenance).
    A field still marked REQUIRES_OPERATOR_CONFIRMATION returns None — KAI must disclaim, not invent."""
    e = _BY_ID.get(entity_id)
    if e is None:
        return None, "unknown entity"
    v = getattr(e, field_name, None)
    if v == _MUST_CONFIRM or v is None:
        return None, f"{field_name} not source-backed — REQUIRES_OPERATOR_CONFIRMATION"
    return v, f"source: {e.data_source} · confidence={e.confidence.value}"
