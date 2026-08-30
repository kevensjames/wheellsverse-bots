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


# Seed set. Enriched 2026-08-30 with everything verifiable from THIS engagement + the repo
# (infra, status, ownership-as-operator-stated, products). Money/customer/banking/legal-name
# fields keep the confirm-marker — never fabricated, even under an operator "use what you found".
_OWNER = "Sole founder/CEO: Jhon Wheeler (operator-stated)"   # per operator across this engagement
_HOLDCO = "Wheellsverse Holdings (operator-stated parent)"

_ENTITIES: list[HoldingEntity] = [
    HoldingEntity("wheellsverse_holdings", "Wheellsverse Holdings", entity_type="holding",
                  operational_status="ACTIVE", stage="operating",
                  ownership=_OWNER,
                  products=["KAI", "SOL", "Nurtelle", "NarAI", "Nexora", "SiteBoost"],
                  last_verified_at="2026-08-30",
                  data_source="operator-stated (engagement)", confidence=Confidence.UNVERIFIED),
    HoldingEntity("solcircle", "SOLCIRCLE Technologies LLC", entity_type="LLC",
                  legal_name=None,                              # registered legal name NOT verified — disclaim
                  ownership=_HOLDCO, operational_status="ACTIVE", stage="operating entity for SOL",
                  repository="wheellsverse-sol (standalone) + wheellsverse-bots (frontend/engine)",
                  products=["SOL"],
                  data_source="operator-stated (engagement); SOL infra verified this engagement",
                  confidence=Confidence.UNVERIFIED),
    HoldingEntity("sol", "SOL", entity_type="product", operational_status="DEPLOYED",
                  stage="live (MONEY MODE MOCK — no real payments)",
                  ownership="SOLCIRCLE Technologies LLC / " + _HOLDCO,
                  repository="wheellsverse-sol (standalone backend) + wheellsverse-bots (frontend/engine)",
                  deployment="Railway backend (grateful-flexibility-production) + Cloudflare Pages frontend",
                  products=["SOL member app", "Circle Catalog (participation plan)"],
                  integrations=["Dwolla (MOCK — no real money movement)", "Stripe Checkout (Go Premium)"],
                  # Verified context in NON-protected fields (payment RAILS are code-facts, not the
                  # operator's merchant/account reference — that stays disclaimed below):
                  kpis=["Pricing: Premium $14.99, Participation plan $9.99 (plan_id 999)",
                        "Payment rails: Stripe Checkout (Go Premium) + Dwolla (MOCK — no real transfers)",
                        "Money mode: MOCK (no real Dwolla transfers)"],
                  # OPERATOR-CONFIRMED 2026-08-30 (pre-revenue / mock stage):
                  revenue_metrics="Pre-revenue — MONEY MODE MOCK; no real revenue collected yet (operator-confirmed 2026-08-30)",
                  customers="Pre-revenue / mock stage — no paying customers yet (operator-confirmed 2026-08-30)",
                  last_verified_at="2026-08-30",
                  data_source="verified this engagement (Sol deploy reality, staging env, Phase-3 build) + repo pricing; revenue/customers operator-confirmed 2026-08-30",
                  confidence=Confidence.VERIFIED),
                  # STILL disclaimed (no source; operator to confirm): expense_metrics, banking_provider_reference,
                  # payment_provider_reference (merchant/account ref), compliance_items, legal_name.
    HoldingEntity("kai", "KAI", entity_type="product", operational_status="LIVE",
                  stage="governed prod (App A app.wheellsverse.com ⇄ App B kai-prod, bridge ON)",
                  ownership=_HOLDCO,
                  repository="wheellsverse-bots (core/api.py + backend/app)",
                  deployment="Railway: grateful-flexibility (App A) + kai-production (App B)",
                  domains=["app.wheellsverse.com", "kai.wheellsverse.com"],
                  products=["KAI Command Center", "KAI governance runtime", "Holding Operations OS (dormant)"],
                  integrations=["OpenAI (prod)", "prod observability monitor (Railway cron, */5)"],
                  # KAI is the internal, owner-only operator control plane — not a sold product. These are
                  # verified code/engagement facts, kept in NON-protected fields (kpis), so the money/
                  # customer fields below still hard-disclaim (operator confirms the business model):
                  kpis=["LIVE governed prod; A⇄B bridge ON", "Prod observability monitor active (Railway cron */5)",
                        "Owner-only access (kai.ultra) enforced at every reachable entry point",
                        "Internal control plane — processes no payments (no Stripe/Dwolla in its codebase)"],
                  # OPERATOR-CONFIRMED 2026-08-30: KAI is the internal operator platform, not a sold product:
                  revenue_metrics="N/A — internal operator platform, not a revenue product (operator-confirmed 2026-08-30)",
                  customers="N/A — internal owner-only platform, no external customers (operator-confirmed 2026-08-30)",
                  last_verified_at="2026-08-30",
                  data_source="verified this engagement (Phase 0–4, operational-truth cert, owner-only RBAC); revenue/customers operator-confirmed 2026-08-30",
                  confidence=Confidence.VERIFIED),
                  # STILL disclaimed (operator to confirm): expense_metrics (hosting spend), banking, compliance, legal_name.
    HoldingEntity("nurtelle", "Nurtelle", entity_type="product", operational_status="ACTIVE (development)",
                  stage="Phase 2 (PR #11 open, 248 tests) — point-in-time",
                  ownership=_HOLDCO,
                  repository="kevensjames/chenara (private; renamed Nurtelle publicly)",
                  products=["Pregnancy companion app"],
                  data_source="prior memory (point-in-time) — re-confirm", confidence=Confidence.UNVERIFIED),
    HoldingEntity("narai", "NarAI", entity_type="product", operational_status="IN-REPO component",
                  stage="chat assistant integrated in core/api",
                  ownership=_HOLDCO,
                  repository="wheellsverse-bots (NarAI-v2 chat + /api/narai)",
                  data_source="in-repo verified (NarAI_Genesis_Master_Plan.md + core/api.py)",
                  confidence=Confidence.VERIFIED),
    HoldingEntity("nexora", "Nexora", entity_type="product", operational_status="UNVERIFIED",
                  ownership=_HOLDCO,
                  risks=["2026-07 SaaS audit found a money-theft vuln (fixed in PR #31) — re-confirm current state"],
                  data_source="prior SaaS audit (point-in-time) — re-confirm", confidence=Confidence.UNVERIFIED),
    HoldingEntity("siteboost", "SiteBoost", entity_type="product", operational_status="UNVERIFIED",
                  ownership=_HOLDCO,
                  repository="wheellsverse-bots (SITEBOOST_LAUNCH.md, data/launches/siteboost)",
                  data_source="in-repo verified (SITEBOOST_LAUNCH.md, data/launches/siteboost)",
                  confidence=Confidence.UNVERIFIED),
    HoldingEntity("wmos", "W-MOS", entity_type="project", operational_status="UNKNOWN",
                  ownership=_HOLDCO,
                  data_source="operator-stated — re-confirm scope", confidence=Confidence.UNKNOWN),
    HoldingEntity("suprema", "Suprema", entity_type="project", operational_status="UNKNOWN",
                  ownership=_HOLDCO,
                  repository="wheellsverse-bots (backend/app/routers/admin_supreme.py)",
                  data_source="in-repo router only — scope unknown", confidence=Confidence.UNKNOWN),
    HoldingEntity("wheellsverse_bots", "Wheellsverse Bots", entity_type="project", operational_status="ACTIVE",
                  stage="monorepo (this repo)", repository="kevensjames/wheellsverse-bots",
                  ownership=_HOLDCO, last_verified_at="2026-08-30",
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
