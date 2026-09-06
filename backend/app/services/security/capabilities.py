"""Cyber Operations — security capability manifests (arch §5/§32, spec §0/§1/§32/§33).

Registers the LOGICAL security capabilities as normalized ``CapabilityManifest``s using
the EXISTING capability fabric (``capability.manifest`` / ``capability.registry``). These
describe what the read endpoints do — they are NON-EXECUTABLE read surfaces; they grant the
Brain no new power. This satisfies §1 "register new capabilities as non-executable" while
keeping the certified global registry's privileged/restricted-executable counts at 0.

Three classes (spec §32):
  READ_ONLY  → AVAILABLE this sprint — pure read surfaces (default_action_class READ_ONLY,
               permissions ["security.read"]). selectable() == True.
  STANDARD   → DISABLED (deployed dark, Phase C/D) — analysis producers, still no mutation.
  PRIVILEGED → DISABLED and NEVER AVAILABLE (§0/§1) — contain/block/revoke/rollback:
               DESTRUCTIVE/HIGH_IMPACT, risk_class RESTRICTED, automatic_activation_allowed
               False, operator_approval_required True. selectable() == False, always.

Isolation (§59): this module registers into an ISOLATED registry only. It never mutates the
certified ``seed_registry()`` — importing it cannot increase the global selectable-executable
count. Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

from app.services.capability.manifest import (
    CapabilityManifest as CM, CapabilityType as CT, RiskClass as RK, ActionClass as AC,
    ActivationMode as AM, Availability as AV, Certification as CE,
)
from app.services.capability.registry import CapabilityRegistry
from app.services.security.models import SourceState

# The three capability classes (spec §32), by id — also the class-of-record for the view.
READ_CAP_IDS = (
    "SECURITY_OVERVIEW", "SECURITY_EVENTS_READ", "SECURITY_INCIDENTS_READ",
    "SECURITY_ATTACK_GRAPH", "SECURITY_ASSET_GRAPH", "SECURITY_AIKIDO_STATUS",
    "SECURITY_AIKIDO_FINDINGS", "SECURITY_AUTH_ANALYSIS", "SECURITY_DEPLOYMENT_RISK",
    "SECURITY_AUDIT_ANALYSIS",
)
STANDARD_CAP_IDS = (
    "SECURITY_GENERATE_REPORT", "SECURITY_PREPARE_REMEDIATION", "SECURITY_BEHAVIOR_ANALYSIS",
)
PRIVILEGED_CAP_IDS = (
    "SECURITY_CONTAIN", "SECURITY_BLOCK_RESOURCE", "SECURITY_REVOKE_SESSION",
    "SECURITY_ROLLBACK_DEPLOYMENT",
)


def _read(cap_id: str, name: str, capabilities: list[str], note: str) -> CM:
    """A non-executable READ surface: AVAILABLE, READ_ONLY, security.read, tier-0 (§5)."""
    return CM(
        id=cap_id, name=name, type=CT.NATIVE_KAI_TOOL, version="phase-a",
        availability=AV.AVAILABLE, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
        risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
        permissions=["security.read"], capabilities=capabilities, triggers=[],
        notes=note,
    )


def _standard(cap_id: str, name: str, capabilities: list[str], note: str) -> CM:
    """A STANDARD analysis capability: deployed DARK (DISABLED), no mutation, Phase C/D (§5)."""
    return CM(
        id=cap_id, name=name, type=CT.NATIVE_KAI_TOOL, version="phase-c-pending",
        availability=AV.DISABLED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
        risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0,
        automatic_activation_allowed=False, permissions=["security.read"],
        capabilities=capabilities, triggers=[], notes=note,
    )


def _privileged(cap_id: str, name: str, action_class: AC, capabilities: list[str], note: str) -> CM:
    """A PRIVILEGED response capability: DISABLED, NEVER selectable, full approval envelope (§0/§1/§33).

    RESTRICTED + DESTRUCTIVE/HIGH_IMPACT + automatic_activation_allowed=False +
    operator_approval_required + sandbox + target-allowlist. Not registered AVAILABLE, ever.
    """
    return CM(
        id=cap_id, name=name, type=CT.NATIVE_KAI_TOOL, version="not-implemented",
        availability=AV.DISABLED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
        risk_class=RK.RESTRICTED, default_action_class=action_class, security_tier=3,
        automatic_activation_allowed=False, operator_approval_required=True,
        sandbox_required=True, target_allowlist_required=True, authorized_context_required=True,
        permissions=["security.respond"], capabilities=capabilities, triggers=[], notes=note,
    )


def security_capability_manifests() -> list[CM]:
    """Build the security capability manifests fresh (no shared mutable state).

    17 total: 10 READ_ONLY (AVAILABLE), 3 STANDARD (DISABLED), 4 PRIVILEGED (DISABLED).
    """
    return [
        # ── READ_ONLY → AVAILABLE this sprint (non-executable read surfaces, §5) ──
        _read("SECURITY_OVERVIEW", "Security Overview",
              ["read_posture_summary", "read_counts"],
              "§4/§36 home card: state + counts. Reads holding/audit/capability/posture in-process."),
        _read("SECURITY_EVENTS_READ", "Security Events (read)",
              ["read_security_events"],
              "§10 governance.list_actions() normalized to SecurityEvent. correlation_id/ip UNKNOWN (audit schema gap)."),
        _read("SECURITY_INCIDENTS_READ", "Security Incidents (read)",
              ["read_incidents"],
              "§14 returns [] + PHASE_C_PENDING — no correlation/triage engine in Phase A. Never fabricates an incident (§55)."),
        _read("SECURITY_ATTACK_GRAPH", "Attack Graph (read)",
              ["read_attack_paths"],
              "§7 config-evidence attack path steps; unknown where no evidence — never proven by attacking prod (§0)."),
        _read("SECURITY_ASSET_GRAPH", "Asset Graph (read)",
              ["read_asset_graph"],
              "§6 holding all_entities() + entity_status overlay; config-only edges. No fabricated topology (§4)."),
        _read("SECURITY_AIKIDO_STATUS", "Aikido Status (read)",
              ["read_aikido_health"],
              "§16 AikidoReadAdapter health; NOT_CONNECTED until AIKIDO_* secrets provisioned — never a fake zero."),
        _read("SECURITY_AIKIDO_FINDINGS", "Aikido Findings (read)",
              ["read_aikido_findings"],
              "§16/§17 whitelisted Aikido issue fields, redacted; NOT_CONNECTED payload until credentials exist."),
        _read("SECURITY_AUTH_ANALYSIS", "Auth Analysis (read)",
              ["read_auth_posture"],
              "§22/§23 api_key_auth live probe + claimed controls (headers/audit/https) recorded as claimed, not attested."),
        _read("SECURITY_DEPLOYMENT_RISK", "Deployment Risk (read)",
              ["read_deployment_risk"],
              "§26 deterministic versioned risk score (risk_score.compute_risk v1.0.0). No LLM; NOT_CONNECTED inputs caveated."),
        _read("SECURITY_AUDIT_ANALYSIS", "Audit Analysis (read)",
              ["read_audit_analysis"],
              "§10 read-only analysis over governance audit records. A logged action is a recorded fact, not an inference."),

        # ── STANDARD → DISABLED (deployed dark, Phase C/D; analysis, no mutation, §5) ──
        _standard("SECURITY_GENERATE_REPORT", "Generate Security Report",
                  ["compose_report"],
                  "Phase C/D: composes a report from read surfaces. Ships DISABLED (non-selectable) this sprint."),
        _standard("SECURITY_PREPARE_REMEDIATION", "Prepare Remediation Plan",
                  ["propose_remediation_plan"],
                  "Phase C/D: PREPARES a plan only — proposes, never executes. Ships DISABLED this sprint."),
        _standard("SECURITY_BEHAVIOR_ANALYSIS", "Behavior Analysis",
                  ["analyze_behavior"],
                  "§11/§12 Phase C behavior/anomaly analysis engine. Ships DISABLED (non-selectable) this sprint."),

        # ── PRIVILEGED → DISABLED, NEVER AVAILABLE (§0/§1 defensive-only; no offensive/mutation) ──
        _privileged("SECURITY_CONTAIN", "Contain System", AC.DESTRUCTIVE,
                    ["isolate_system"],
                    "§0/§1 privileged response — DISABLED, never selectable. Requires full envelope (mission+target+approval+sandbox)."),
        _privileged("SECURITY_BLOCK_RESOURCE", "Block Resource", AC.DESTRUCTIVE,
                    ["block_resource"],
                    "§0/§1 privileged response — DISABLED, never selectable. Not built this sprint; approval-gated by design."),
        _privileged("SECURITY_REVOKE_SESSION", "Revoke Session", AC.HIGH_IMPACT,
                    ["revoke_session"],
                    "§0/§1 privileged response — DISABLED, never selectable. Owner-approval + authorized target required."),
        _privileged("SECURITY_ROLLBACK_DEPLOYMENT", "Rollback Deployment", AC.DESTRUCTIVE,
                    ["rollback_deployment"],
                    "§0/§1 privileged response — DISABLED, never selectable. Never touches MONEY_MODE/deploy (§59)."),
    ]


def register(reg: CapabilityRegistry | None = None) -> CapabilityRegistry:
    """Register the security manifests into an ISOLATED registry and return it.

    Defaults to a FRESH registry so the certified global ``seed_registry()`` is never mutated
    (§1). A caller may pass an existing registry to merge into, but Phase A never does.
    """
    reg = reg if reg is not None else CapabilityRegistry()
    reg.register_all(security_capability_manifests())
    return reg


def list_security_capabilities() -> list[CM]:
    """Return the security capability manifests (the certified global registry is untouched)."""
    return security_capability_manifests()


def _cap_class(cap_id: str) -> str:
    if cap_id in READ_CAP_IDS:
        return "READ_ONLY"
    if cap_id in STANDARD_CAP_IDS:
        return "STANDARD"
    if cap_id in PRIVILEGED_CAP_IDS:
        return "PRIVILEGED"
    return "UNKNOWN"


def capability_view() -> dict:
    """Manifests + registry health + selectable gate for GET /admin/cyber/capabilities (§32/§35).

    Every entry carries its class, availability, action/risk class, the approval flags, the
    ``selectable()`` gate (so a read-only display never implies executability), and the
    registry ``health(id)``. Built over an isolated registry — no global mutation.
    """
    reg = register()
    caps = []
    for m in reg.list():
        caps.append({
            "id": m.id,
            "name": m.name,
            "class": _cap_class(m.id),
            "availability": m.availability.value,
            "default_action_class": m.default_action_class.value,
            "risk_class": m.risk_class.value,
            "permissions": list(m.permissions),
            "automatic_activation_allowed": m.automatic_activation_allowed,
            "operator_approval_required": m.operator_approval_required,
            "selectable": m.selectable(),
            "health": reg.health(m.id),
        })
    selectable = [c for c in caps if c["selectable"]]
    privileged_selectable = [c for c in caps if c["class"] == "PRIVILEGED" and c["selectable"]]
    summary = {
        "total": len(caps),
        "read_only_available": sum(1 for c in caps if c["class"] == "READ_ONLY" and c["availability"] == "AVAILABLE"),
        "standard_disabled": sum(1 for c in caps if c["class"] == "STANDARD" and c["availability"] == "DISABLED"),
        "privileged_disabled": sum(1 for c in caps if c["class"] == "PRIVILEGED" and c["availability"] == "DISABLED"),
        "selectable": len(selectable),
        "privileged_selectable": len(privileged_selectable),   # must be 0 (§1)
    }
    return {"capabilities": caps, "summary": summary, "state": SourceState.WORKING.value}


def demo() -> None:
    from app.services.capability.seed import seed_registry
    from app.services.capability.manifest import ActionClass, RiskClass, Availability

    res = []
    def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    mans = security_capability_manifests()
    by_id = {m.id: m for m in mans}
    ck("17 security manifests (10 read + 3 standard + 4 privileged)", len(mans) == 17)

    # READ_ONLY caps: AVAILABLE, selectable, READ_ONLY, security.read
    reads = [by_id[i] for i in READ_CAP_IDS]
    ck("10 read caps AVAILABLE", all(m.availability == Availability.AVAILABLE for m in reads) and len(reads) == 10)
    ck("read caps selectable()==True", all(m.selectable() for m in reads))
    ck("read caps default_action_class READ_ONLY", all(m.default_action_class == ActionClass.READ_ONLY for m in reads))
    ck("read caps permissions == ['security.read']", all(m.permissions == ["security.read"] for m in reads))

    # STANDARD caps: DISABLED, not selectable
    stds = [by_id[i] for i in STANDARD_CAP_IDS]
    ck("3 standard caps DISABLED + not selectable",
       len(stds) == 3 and all(m.availability == Availability.DISABLED and not m.selectable() for m in stds))

    # PRIVILEGED caps: the load-bearing §0/§1 invariants
    privs = [by_id[i] for i in PRIVILEGED_CAP_IDS]
    ck("4 privileged caps availability DISABLED", len(privs) == 4 and all(m.availability == Availability.DISABLED for m in privs))
    ck("privileged automatic_activation_allowed == False", all(m.automatic_activation_allowed is False for m in privs))
    ck("privileged selectable() == False", all(m.selectable() is False for m in privs))
    ck("privileged risk_class RESTRICTED", all(m.risk_class == RiskClass.RESTRICTED for m in privs))
    ck("privileged DESTRUCTIVE/HIGH_IMPACT", all(m.default_action_class in (ActionClass.DESTRUCTIVE, ActionClass.HIGH_IMPACT) for m in privs))
    ck("privileged operator_approval_required == True", all(m.operator_approval_required is True for m in privs))

    # Isolated register(): exactly 10 selectable, 0 privileged/restricted selectable-executable
    reg = register()
    ck("register() isolated registry holds 17", len(reg) == 17)
    sel = reg.list(selectable_only=True)
    ck("isolated selectable == 10", len(sel) == 10)
    ck("isolated privileged/restricted selectable-executable == 0",
       not any(m.risk_class == RiskClass.RESTRICTED or m.default_action_class in
               (ActionClass.DESTRUCTIVE, ActionClass.HIGH_IMPACT, ActionClass.FINANCIAL) for m in sel))

    # §1 THE invariant: importing/using this module does NOT touch the certified global registry
    g = seed_registry()
    gsel = g.list(selectable_only=True)
    g_priv = [m for m in gsel if m.risk_class == RiskClass.RESTRICTED or m.default_action_class in
              (ActionClass.DESTRUCTIVE, ActionClass.HIGH_IMPACT, ActionClass.FINANCIAL)]
    ck("global registry unchanged: 126 total", len(g) == 126)
    ck("global registry unchanged: 7 selectable", len(gsel) == 7)
    ck("global registry unchanged: 0 privileged/restricted selectable-executable", len(g_priv) == 0)

    # capability_view() shape
    view = capability_view()
    ck("capability_view summary.read_only_available == 10", view["summary"]["read_only_available"] == 10)
    ck("capability_view summary.privileged_selectable == 0", view["summary"]["privileged_selectable"] == 0)
    ck("capability_view carries health per cap", all("health" in c and "selectable" in c for c in view["capabilities"]))

    n, ok = len(res), sum(res)
    print(f"\nSECURITY CAPABILITIES TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    raise SystemExit(0 if ok == n else 1)


if __name__ == "__main__":
    demo()
