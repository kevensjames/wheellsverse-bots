"""Cyber Operations data models (arch §2) — pure dataclasses + enums, NO I/O.

Mirrors holding/registry.py's HoldingEntity.as_dict() pattern: asdict() then coerce
each enum field to its .value so a serialized model is plain JSON-able primitives.
Nested dataclasses (evidence refs) are recursed by asdict and carry no enums.

Honesty (arch §49): default values are typed markers — UNKNOWN / UNAVAILABLE /
PHASE_C_PENDING / NOT_STARTED — never a fabricated zero or a made-up finding. The
bus fills real values; anything it cannot source stays a marker.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Union


# ── Enums ──────────────────────────────────────────────────────────────────────
class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Confidence(str, Enum):          # spec §55 — never "ATTACK DETECTED" without evidence
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CONFIRMED = "CONFIRMED"


class TriageStatus(str, Enum):        # spec §13
    NEW = "NEW"
    CORRELATING = "CORRELATING"
    INVESTIGATING = "INVESTIGATING"
    CONFIRMED = "CONFIRMED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    MITIGATED = "MITIGATED"
    VERIFYING = "VERIFYING"
    CLOSED = "CLOSED"


class SourceState(str, Enum):         # arch §4 honesty matrix
    WORKING = "WORKING"                       # real value read
    DISABLED_WITH_REASON = "DISABLED_WITH_REASON"  # control present but not enforced/enabled
    NOT_CONNECTED = "NOT_CONNECTED"           # external source unprovisioned
    UNAVAILABLE = "UNAVAILABLE"               # provisioned path but no data this call
    UNKNOWN = "UNKNOWN"                        # no probe / no evidence
    PHASE_C_PENDING = "PHASE_C_PENDING"       # engine not built this sprint


# ── Dataclasses ────────────────────────────────────────────────────────────────
@dataclass
class EvidenceReference:              # spec §54 — every conclusion points at real evidence
    source_type: str                 # "audit"|"capability_registry"|"holding_registry"|"aikido"|"scanner"|"app_a_status"|"monitor"|"config"
    source_id: str                   # underlying id (audit id / cap id / entity_id / file sha256 / signal name)
    timestamp: str = "UNKNOWN"       # record's own ts; UNKNOWN if the source has none
    digest: str = ""                 # sha256 of the raw record (scanner gives a real file sha256)
    system: str = "UNKNOWN"          # entity/system the evidence is about
    retrieval_time: str = "UNKNOWN"  # stamped by the bus at read time (no clock in pure modules)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SecurityEvent:                  # spec §10 — normalized from governance.list_actions() audit records
    event_id: str                    # audit id (stable dedup key)
    timestamp: str
    source: str
    company: str
    system: str
    environment: str
    category: str
    severity: Severity
    actor: str
    resource: str
    action: str
    result: str
    correlation_id: str = "UNKNOWN"  # audit schema has none
    ip: str = "UNKNOWN"              # audit schema has none
    evidence_refs: list = field(default_factory=list)   # list[EvidenceReference]
    confidence: Confidence = Confidence.CONFIRMED        # a logged action is a recorded fact

    def as_dict(self) -> dict:
        d = asdict(self)             # recurses evidence_refs into plain dicts (no enums inside)
        d["severity"] = self.severity.value
        d["confidence"] = self.confidence.value
        return d


@dataclass
class Node:                          # spec §6 — holding all_entities() + entity_status overlay
    node_id: str
    system: str
    company: str = "UNKNOWN"
    asset_type: str = "UNKNOWN"
    environment: str = "UNKNOWN"
    trust_zone: str = "UNKNOWN"
    health: str = "UNKNOWN"
    security_state: str = "UNKNOWN"
    exposure: str = "UNKNOWN"
    findings_count: Union[int, str] = "UNAVAILABLE"      # aikido NOT_CONNECTED -> UNAVAILABLE
    incident_count: Union[int, str] = "PHASE_C_PENDING"  # no incident engine in Phase A
    last_seen: str = "UNKNOWN"

    def as_dict(self) -> dict:
        return asdict(self)          # no enums


@dataclass
class Edge:                          # spec §6 — config-evidence only; if no evidence, the edge is not drawn
    source: str
    target: str
    relationship: str
    protocol: str = "UNKNOWN"
    trust_boundary: bool = False
    authorization: str = "UNKNOWN"
    exposure: str = "UNKNOWN"
    evidence: Optional[EvidenceReference] = None

    def as_dict(self) -> dict:
        return asdict(self)          # recurses evidence into a dict (or None); no enums


@dataclass
class Incident:                     # spec §14 — NOT populated in Phase A (correlation/triage = Phase C)
    incident_id: str
    title: str
    severity: Severity
    status: TriageStatus
    affected_systems: list = field(default_factory=list)
    affected_companies: list = field(default_factory=list)
    first_seen: str = "UNKNOWN"
    last_seen: str = "UNKNOWN"
    detection_sources: list = field(default_factory=list)
    evidence: list = field(default_factory=list)          # list[EvidenceReference]
    likely_root_cause: str = "UNKNOWN"
    confidence: Confidence = Confidence.LOW
    attack_techniques: list = field(default_factory=list)
    recommended_actions: list = field(default_factory=list)
    approval_required: bool = True
    remediation_state: str = "NOT_STARTED"
    verification_state: str = "NOT_STARTED"

    def as_dict(self) -> dict:
        d = asdict(self)             # recurses evidence into plain dicts
        d["severity"] = self.severity.value
        d["status"] = self.status.value
        d["confidence"] = self.confidence.value
        return d


def demo() -> None:
    ev = EvidenceReference(source_type="audit", source_id="abc123", system="app_b")
    se = SecurityEvent(
        event_id="abc123", timestamp="2026-09-03T00:00:00Z", source="governance.audit_log",
        company="sol", system="app_b", environment="staging", category="authz_denial",
        severity=Severity.HIGH, actor="operator", resource="sol.transfer", action="transfer",
        result="failure", evidence_refs=[ev],
    )
    d = se.as_dict()
    # enums coerced to plain strings, not Enum instances (verify contract)
    assert d["severity"] == "HIGH" and type(d["severity"]) is str, d["severity"]
    assert d["confidence"] == "CONFIRMED" and type(d["confidence"]) is str
    assert d["correlation_id"] == "UNKNOWN" and d["ip"] == "UNKNOWN"     # audit schema gaps
    assert d["evidence_refs"][0]["source_id"] == "abc123"               # nested recursed to dict
    # honest markers on a bare Node
    n = Node(node_id="solcircle", system="SOLCIRCLE")
    nd = n.as_dict()
    assert nd["health"] == "UNKNOWN" and nd["findings_count"] == "UNAVAILABLE"
    assert nd["incident_count"] == "PHASE_C_PENDING"
    # Edge with no evidence still serializes; Incident coerces its three enums
    assert Edge(source="app_a", target="app_b", relationship="bridge").as_dict()["evidence"] is None
    inc = Incident(incident_id="i1", title="t", severity=Severity.CRITICAL, status=TriageStatus.NEW)
    idc = inc.as_dict()
    assert idc["severity"] == "CRITICAL" and idc["status"] == "NEW" and idc["confidence"] == "LOW"
    assert idc["approval_required"] is True and idc["remediation_state"] == "NOT_STARTED"
    print("models.demo OK — enums->str via as_dict; nested evidence recursed; honest markers intact")


if __name__ == "__main__":
    demo()
