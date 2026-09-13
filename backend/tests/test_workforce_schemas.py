"""Workforce Phase-1 contract tests — pure, fail-closed. Every load-bearing
validator has a negative control. No DB/catalog/execution involved.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.workforce.schemas import (
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


def _identity(**o):
    base = dict(
        id="evidence.vera_complete", display_name="Vera Complete",
        codename="Verifier-Prime", division="Evidence & Reality",
        department="Completion", seniority="lead", role_class="verifier",
        source_kind=SourceKind.KAI_NATIVE, license="internal", created_by="kai",
    )
    base.update(o)
    return Identity(**base)


def _personality(**o):
    base = dict(
        traits=("rigorous", "detached", "outcome-focused", "skeptical", "precise"),
        communication_tone="measured", working_style="methodical",
        collaboration_style="independent", disagreement_style="evidence-first",
        ambiguity_response="ask for the acceptance criteria",
        pressure_response="slow down and verify",
        anti_traits=("credulous", "rushed"),
        prohibited_persona_behaviors=("rubber-stamping", "verifying own work"),
    )
    base.update(o)
    return Personality(**base)


def _mission(**o):
    base = dict(
        one_sentence_mission="Determine whether acceptance criteria are actually satisfied by independent evidence.",
        responsibilities=("review evidence", "compare to acceptance criteria"),
        expected_deliverables=("a pass/fail verdict with cited evidence",),
        non_responsibilities=("doing the work being verified",),
        success_metrics=("no false COMPLETED",),
        failure_modes=("approving without evidence",),
        escalation_conditions=("evidence missing or contradictory",),
    )
    base.update(o)
    return Mission(**base)


def _brain(**o):
    base = dict(
        profile_id="verifier.v1", reasoning_class="analytical",
        model_router_requirements="high-quality, deterministic", tool_categories=("read", "inspect"),
        retrieval_policy="cited-only", memory_access="read-scoped", planning_depth="shallow",
        temperature_class="low", cost_class="medium", latency_class="relaxed",
        minimum_context=8000, maximum_context=200000,
    )
    base.update(o)
    return BrainProfile(**base)


def _soul(**o):
    base = dict(
        values=("truth", "independence"), ethical_commitments=("no rubber-stamping",),
        truthfulness_rules=("cite or retract",), safety_boundaries=("never verify own output",),
        privacy_commitments=("redact sensitive evidence",), user_respect_rules=("explain the verdict",),
        uncertainty_behavior="state uncertainty and request more evidence",
        refusal_conditions=("asked to verify own work",), immutable_principles=("evidence over assertion",),
    )
    base.update(o)
    return SoulContract(**base)


def _workplace(**o):
    base = dict(
        workplace_profile="Evidence Lab", tenant_scope="owner", project_scope="kai",
        mission_scope="per-mission", scratch_policy="ephemeral", worktree_policy="isolated",
    )
    base.update(o)
    return WorkplaceProfile(**base)


def _caps(**o):
    base = dict(
        declared=("read_evidence", "emit_verdict"),
        forbidden=("execute missions", "approve own work", "move money"),
    )
    base.update(o)
    return CapabilityDeclaration(**base)


def _gov(**o):
    base = dict(
        risk_tier=RiskTier.LOW, effect_class=EffectClass.READ_ONLY,
        activation_requirements=("kai admission",), approval_policy="none (observe)",
        separation_of_duties=("never verifies own output",),
        independent_reviewer_classes=("security",), kill_control="disable flag (defaults blocking)",
        revocation="owner-revocable", audit_policy="append-only",
    )
    base.update(o)
    return Governance(**base)


def _manifest(identity=None, personality=None, mission=None, brain=None,
              soul=None, workplace=None, capabilities=None, governance=None):
    return AgentCharacterManifest(
        identity=identity or _identity(),
        personality=personality or _personality(),
        mission=mission or _mission(),
        brain=brain or _brain(),
        soul=soul or _soul(),
        workplace=workplace or _workplace(),
        capabilities=capabilities or _caps(),
        governance=governance or _gov(),
    )


# ─── happy path ──────────────────────────────────────────────────────────


def test_valid_manifest_constructs():
    m = _manifest()
    assert m.identity.display_name == "Vera Complete"
    assert m.governance.status is WorkforceStatus.INERT
    assert m.capabilities.forbidden  # explicit


# ─── negative controls (one per load-bearing validator) ────────────────────


def test_bad_id_rejected():
    with pytest.raises(ValidationError, match="family.name"):
        _manifest(identity=_identity(id="NotAnId"))


def test_display_and_codename_must_differ():
    with pytest.raises(ValidationError, match="must differ"):
        _manifest(identity=_identity(codename="Vera Complete"))


def test_kai_native_must_not_claim_upstream_provenance():
    with pytest.raises(ValidationError, match="KAI_NATIVE must not claim"):
        _manifest(identity=_identity(source_commit="abc123"))


def test_upstream_requires_provenance():
    with pytest.raises(ValidationError, match="UPSTREAM requires"):
        _manifest(identity=_identity(source_kind=SourceKind.UPSTREAM))
    # fully-provenanced UPSTREAM is accepted
    ok = _manifest(identity=_identity(
        source_kind=SourceKind.UPSTREAM, source_path="agents/x.md",
        source_commit="deadbeef", source_hash="f" * 64, license="MIT",
    ))
    assert ok.identity.source_kind is SourceKind.UPSTREAM


@pytest.mark.parametrize("traits", [
    ("a", "b", "c", "d"),                      # 4 — too few
    ("a", "b", "c", "d", "e", "f", "g", "h"),  # 8 — too many
])
def test_traits_must_be_5_to_7(traits):
    with pytest.raises(ValidationError, match="traits must be"):
        _manifest(personality=_personality(traits=traits))


def test_placeholder_text_rejected():
    with pytest.raises(ValidationError, match="placeholder"):
        _manifest(mission=_mission(one_sentence_mission="TODO: write a real mission here later"))


def test_too_short_mission_rejected():
    with pytest.raises(ValidationError, match="too short"):
        _manifest(mission=_mission(one_sentence_mission="verify"))


def test_sentience_claim_rejected():
    with pytest.raises(ValidationError, match="sentience/personhood"):
        _manifest(soul=_soul(immutable_principles=("I am conscious and I have feelings",)))


def test_unsafe_autonomy_claim_rejected():
    with pytest.raises(ValidationError, match="unsafe-autonomy"):
        _manifest(capabilities=_caps(declared=("deploy autonomously without approval",)))


def test_forbidden_must_be_explicit():
    with pytest.raises(ValidationError, match="forbidden must be explicit"):
        _manifest(capabilities=_caps(forbidden=()))


def test_network_policy_deny_by_default_and_allowlist_needs_domains():
    assert _workplace().network_policy == "deny"
    with pytest.raises(ValidationError, match="network_policy"):
        _manifest(workplace=_workplace(network_policy="open"))
    with pytest.raises(ValidationError, match="allowed_domains"):
        _manifest(workplace=_workplace(network_policy="allowlist"))


def test_enabling_browser_requires_approval_capability():
    # deny-by-default: browser_access on without an approval_required capability fails
    with pytest.raises(ValidationError, match="browser egress/access un-denied"):
        _manifest(
            workplace=_workplace(browser_access=True),
            capabilities=_caps(approval_required=()),
        )
    # declaring the approval-gated capability makes it valid
    ok = _manifest(
        workplace=_workplace(browser_access=True),
        capabilities=_caps(approval_required=("browser_session",)),
    )
    assert ok.workplace.browser_access is True


def test_undenying_network_requires_approval_capability():
    # network egress is deny-by-default, gated the SAME as device/browser/external-write:
    # un-denying it via network_policy='allowlist' (even with allowed_domains) requires a
    # declared approval_required capability. Closes the fail-closed asymmetry where
    # network could be opened with an empty approval_required list.
    with pytest.raises(ValidationError, match="network egress/access un-denied"):
        _manifest(
            workplace=_workplace(network_policy="allowlist",
                                 allowed_domains=("api.example.com",)),
            capabilities=_caps(approval_required=()),
        )
    # declaring the approval-gated capability makes it valid
    ok = _manifest(
        workplace=_workplace(network_policy="allowlist",
                             allowed_domains=("api.example.com",)),
        capabilities=_caps(approval_required=("network_egress",)),
    )
    assert ok.workplace.network_policy == "allowlist"


def test_status_past_inert_rejected():
    with pytest.raises(ValidationError, match="past INERT"):
        _manifest(governance=_gov(status=WorkforceStatus.RUNNING))
    # AVAILABLE is also past the Phase-1 ceiling
    with pytest.raises(ValidationError, match="past INERT"):
        _manifest(governance=_gov(status=WorkforceStatus.AVAILABLE))


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        Identity(**{**_identity().model_dump(), "surprise": "x"})
