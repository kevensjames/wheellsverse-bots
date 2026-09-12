"""KAI Governed Workforce — Phase 1 (pure contracts, inert).

Declarative schemas for workforce *characters* that work FOR KAI. This package is
contracts only: no catalog execution, no upstream import, no handler/adapter/router,
nothing runs. See docs/workforce/KAI_GOVERNED_WORKFORCE_MASTER_PLAN.md and its
hash-linked companions (AGENT_CHARACTER_CONTRACT.md is the field contract).
"""
from app.services.workforce.schemas import (
    PHASE1_MAX_STATES,
    AgentCharacterManifest,
    BrainProfile,
    CapabilityDeclaration,
    EffectClass,
    Governance,
    Identity,
    Mission,
    Personality,
    RiskTier,
    SoulContract,
    SourceKind,
    WorkforceStatus,
    WorkplaceProfile,
)

__all__ = [
    "PHASE1_MAX_STATES",
    "AgentCharacterManifest",
    "BrainProfile",
    "CapabilityDeclaration",
    "EffectClass",
    "Governance",
    "Identity",
    "Mission",
    "Personality",
    "RiskTier",
    "SoulContract",
    "SourceKind",
    "WorkforceStatus",
    "WorkplaceProfile",
]
