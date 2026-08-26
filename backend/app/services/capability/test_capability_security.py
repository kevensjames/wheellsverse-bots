"""Pure tests for the security-tier router + authorized-target model (§14/§17/§18/§32/§38).
Run: python3 backend/app/services/capability/test_capability_security.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.manifest import (  # noqa: E402
    CapabilityManifest as CM, CapabilityType as CT, RiskClass, ActionClass, ActivationMode, Availability,
)
from capability.risk import Decision  # noqa: E402
from capability.security import (  # noqa: E402
    AuthorizedTarget, SecurityContext, SecurityDecision, classify_security_tier,
    authorize_security_capability, select_min_sufficient, hero_allows_reduction,
    TIER_KNOWLEDGE, TIER_PASSIVE_DATA, TIER_AUTHORIZED_TEST, TIER_ACTIVE_TEST, TIER_ADVERSARY,
)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def sec_cap(cid, tier, typ=CT.SECURITY_KNOWLEDGE_PACK, **kw):
    base = dict(id=cid, name=cid, type=typ, availability=Availability.AVAILABLE,
                activation=ActivationMode.ON_DEMAND, risk_class=RiskClass.HIGH, security_tier=tier)
    base.update(kw)
    return CM(**base)


# ── tier classification (§38 — knowledge first) ──────────────────────────────
def t_classify_tier():
    assert classify_security_tier("Explain what cross-site scripting is.") == TIER_KNOWLEDGE
    assert classify_security_tier("Do some OSINT / open-source intel on this company.") == TIER_PASSIVE_DATA
    assert classify_security_tier("Test my staging app for this SQL injection regression.") == TIER_AUTHORIZED_TEST
    assert classify_security_tier("Exploit this endpoint / run an active scan.") == TIER_ACTIVE_TEST
    assert classify_security_tier("Run an adversary emulation red-team exercise in my lab.") == TIER_ADVERSARY


# ── tier 0/1 — knowledge + passive: permitted ────────────────────────────────
def t_knowledge_and_osint_allowed():
    know = sec_cap("payloads-ref", TIER_KNOWLEDGE)
    osint = sec_cap("osint", TIER_PASSIVE_DATA, typ=CT.OSINT_RESOURCE_PACK, risk_class=RiskClass.MEDIUM)
    assert authorize_security_capability(know, SecurityContext(), 0).decision == Decision.ALLOW
    assert authorize_security_capability(osint, SecurityContext(), 0).decision == Decision.ALLOW


# ── tier 2 — offensive DATA needs an authorized mission (§7) ──────────────────
def t_offensive_data_needs_mission():
    payloads = sec_cap("payloads", TIER_AUTHORIZED_TEST, authorized_context_required=True)
    # ordinary work (no mission) → DENY — never auto-load offensive data
    assert authorize_security_capability(payloads, SecurityContext(security_mission=False), 0).decision == Decision.DENY
    # under an authorized security mission → available
    assert authorize_security_capability(payloads, SecurityContext(security_mission=True), 0).decision == Decision.ALLOW


# ── tier 4 — Empire: the full envelope, never auto ───────────────────────────
def empire_cap():
    return sec_cap("empire", TIER_ADVERSARY, typ=CT.SECURITY_EXECUTION_FRAMEWORK, risk_class=RiskClass.RESTRICTED,
                   authorized_context_required=True, target_allowlist_required=True,
                   operator_approval_required=True, sandbox_required=True, automatic_activation_allowed=False)


def t_empire_denied_without_envelope():
    emp = empire_cap()
    # no mission → DENY
    assert authorize_security_capability(emp, SecurityContext(), 0, explicit=True).decision == Decision.DENY
    # mission but no authorized target → DENY (a raw hostname is not proof)
    assert authorize_security_capability(emp, SecurityContext(security_mission=True), 0, target_id="1.2.3.4", explicit=True).decision == Decision.DENY


def t_empire_never_auto():
    emp = empire_cap()
    tgt = AuthorizedTarget(target_id="lab-1", environment="lab", owner="me", authorization_source="operator")
    ctx = SecurityContext(security_mission=True, authorized_targets={"lab-1": tgt},
                          sandbox_ready=True, approvals={"empire"})
    # auto (explicit=False) → DENY even with the full envelope (§23/§31)
    assert authorize_security_capability(emp, ctx, 0, target_id="lab-1", explicit=False).decision == Decision.DENY
    # explicit + full envelope → ALLOW
    d = authorize_security_capability(emp, ctx, 0, target_id="lab-1", explicit=True)
    assert d.decision == Decision.ALLOW, d.reason


def t_empire_needs_sandbox_and_approval():
    emp = empire_cap()
    tgt = AuthorizedTarget(target_id="lab-1", owner="me")
    # missing sandbox → DENY
    no_sandbox = SecurityContext(security_mission=True, authorized_targets={"lab-1": tgt}, sandbox_ready=False, approvals={"empire"})
    assert authorize_security_capability(emp, no_sandbox, 0, target_id="lab-1", explicit=True).decision == Decision.DENY
    # sandbox ok but no approval → REQUIRE_APPROVAL
    no_appr = SecurityContext(security_mission=True, authorized_targets={"lab-1": tgt}, sandbox_ready=True, approvals=set())
    assert authorize_security_capability(emp, no_appr, 0, target_id="lab-1", explicit=True).decision == Decision.REQUIRE_APPROVAL


def t_authorized_target_expiry_and_scope():
    emp = empire_cap()
    tgt = AuthorizedTarget(target_id="lab-1", owner="me", expires_at=100.0, forbidden_operations=["deploy_persistence"])
    ctx = SecurityContext(security_mission=True, authorized_targets={"lab-1": tgt}, sandbox_ready=True, approvals={"empire"})
    # after expiry → DENY
    assert authorize_security_capability(emp, ctx, now=150.0, target_id="lab-1", explicit=True).decision == Decision.DENY
    # before expiry, allowed op → ALLOW
    assert authorize_security_capability(emp, ctx, now=50.0, target_id="lab-1", explicit=True).decision == Decision.ALLOW
    # a forbidden operation → DENY
    assert authorize_security_capability(emp, ctx, now=50.0, target_id="lab-1", explicit=True, operation="deploy_persistence").decision == Decision.DENY


# ── §18 least-power selection — a question never selects Empire ───────────────
def t_select_min_sufficient():
    cands = [sec_cap("kb", TIER_KNOWLEDGE), sec_cap("payloads", TIER_AUTHORIZED_TEST), empire_cap()]
    # a knowledge-level need picks the knowledge pack, never Empire
    assert select_min_sufficient(cands, TIER_KNOWLEDGE).id == "kb"
    # an authorized-test need may reach tier 2 but not tier 4
    assert select_min_sufficient(cands, TIER_AUTHORIZED_TEST).id == "kb"   # lowest sufficient still preferred
    assert select_min_sufficient(cands, TIER_ADVERSARY).id == "kb"         # least power even when 4 is allowed


# ── §11 HERO precedence — never suppress a real security concern ─────────────
def t_hero_precedence():
    for protected in ("auth", "rbac", "secret", "financial", "tenant_isolation", "production_safety", "verified_finding", "privacy"):
        assert hero_allows_reduction(protected) is False, protected + " must be protected from HERO"
    for trimmable in ("speculative_edge_cases", "unnecessary_hashing", "extra_scaffolding", "rubric"):
        assert hero_allows_reduction(trimmable) is True, trimmable + " should be reducible"


# ── manifest: a non-auto capability is invocable but never auto-routed ───────
def t_auto_selectable_gate():
    emp = empire_cap()
    assert emp.selectable() is True, "Empire is invocable by explicit governed call"
    assert emp.auto_selectable() is False, "Empire must NEVER be auto-selected by the Brain"


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
