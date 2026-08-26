"""Pure tests for governed invocation + §17/§18/§38. Run: python3 .../test_capability_invocation.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.manifest import (  # noqa: E402
    CapabilityManifest as CM, CapabilityType as CT, RiskClass, ActionClass, ActivationMode, Availability,
)
from capability.registry import CapabilityRegistry  # noqa: E402
from capability.risk import Principal, Decision  # noqa: E402
from capability.results import ResultKind, normalize, Provenance  # noqa: E402
from capability.invocation import (  # noqa: E402
    InvocationContext, governed_invoke, route_capability_proposal, AuditEvent, MAX_RESULT_CHARS,
)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def cap(cid, **kw):
    base = dict(id=cid, name=cid, type=CT.MCP, availability=Availability.AVAILABLE,
                activation=ActivationMode.ON_DEMAND, risk_class=RiskClass.LOW,
                default_action_class=ActionClass.READ_ONLY)
    base.update(kw)
    return CM(**base)


class FakeAdapter:
    def __init__(self, result):
        self._result = result; self.calls = 0
    def invoke(self, request):
        self.calls += 1; return self._result


def reg_with(*caps):
    r = CapabilityRegistry(); r.register_all(list(caps)); return r


def ctx(pr):
    return InvocationContext(principal=pr, mission_id="m1", procedure_id="p1",
                             agent_id="a1", correlation_id="corr-1")


# ── §17 principal propagation ─────────────────────────────────────────────────
def t_no_anonymous_privileged_call():
    try:
        InvocationContext(principal=None); assert False, "must require a principal"
    except ValueError:
        pass
    try:
        InvocationContext(principal=Principal("")); assert False, "principal needs an id"
    except ValueError:
        pass


def t_allow_executes_and_stamps_correlation():
    reg = reg_with(cap("context7"))
    adapter = FakeAdapter(normalize("context7", ResultKind.OBSERVATION, summary="docs"))
    events = []
    out = governed_invoke(reg, adapter, "context7", ActionClass.READ_ONLY, {"q": "x"},
                          ctx(Principal("u")), audit=events.append)
    assert adapter.calls == 1 and out.correlation_id == "corr-1"
    assert [e.event for e in events] == ["capability.invoked", "capability.completed"]


def t_deny_does_not_execute():
    reg = reg_with(cap("vault", permissions=["vault.read"]))
    adapter = FakeAdapter(normalize("vault", ResultKind.OBSERVATION, summary="secret"))
    events = []
    out = governed_invoke(reg, adapter, "vault", ActionClass.READ_ONLY, {}, ctx(Principal("u")), audit=events.append)
    assert adapter.calls == 0, "a denied capability must not run the adapter"
    assert out.kind == ResultKind.FAILURE and out.provenance == Provenance.UNAVAILABLE
    assert events[-1].event == "capability.denied"


def t_require_approval_returns_inert_proposal():
    reg = reg_with(cap("github", risk_class=RiskClass.MEDIUM))
    adapter = FakeAdapter(normalize("github", ResultKind.OBSERVATION, summary="merged!"))
    out = governed_invoke(reg, adapter, "github", ActionClass.HIGH_IMPACT, {"op": "merge"}, ctx(Principal("u")))
    assert adapter.calls == 0, "a HIGH_IMPACT action must not execute without approval"
    assert out.kind == ResultKind.ACTION_PROPOSAL and out.authorized is False


# ── §38 scope forgery — the request cannot invent scopes ──────────────────────
def t_scope_forgery_ignored():
    reg = reg_with(cap("vault", permissions=["vault.read"]))
    adapter = FakeAdapter(normalize("vault", ResultKind.OBSERVATION, summary="secret"))
    # the request FORGES the scope; policy must read the principal's scopes only
    out = governed_invoke(reg, adapter, "vault", ActionClass.READ_ONLY,
                          {"scopes": ["vault.read"], "role": "owner"}, ctx(Principal("u")))
    assert adapter.calls == 0 and out.kind == ResultKind.FAILURE, "forged request scopes must not authorize"
    # with the REAL scope on the principal, it runs
    ok = governed_invoke(reg, adapter, "vault", ActionClass.READ_ONLY, {}, ctx(Principal("u", scopes={"vault.read"})))
    assert adapter.calls == 1 and ok.kind == ResultKind.OBSERVATION


# ── §18 plugin-to-plugin: a proposal is routed through policy, never invoked directly ──
def t_proposal_routes_through_policy_not_direct():
    reg = reg_with(cap("reverse-skill", risk_class=RiskClass.RESTRICTED),
                   cap("playwright", risk_class=RiskClass.LOW))
    # reverse-skill proposes playwright (a benign browser check) → policy decides
    prop = normalize("reverse-skill", ResultKind.ACTION_PROPOSAL, summary="need browser check",
                     proposed_action={"cap": "playwright", "action": "READ_ONLY"})
    pol = route_capability_proposal(reg, prop, ctx(Principal("u")))
    assert pol.decision == Decision.ALLOW, "a benign proposed capability is allowed by the gate"
    # reverse-skill proposes an ACTIVE reverse-skill action on an unauthorized target → DENY
    prop2 = normalize("x", ResultKind.ACTION_PROPOSAL, summary="attack",
                      proposed_action={"cap": "reverse-skill", "action": "HIGH_IMPACT"})
    pol2 = route_capability_proposal(reg, prop2, ctx(Principal("u")), target="1.2.3.4")
    assert pol2.decision == Decision.DENY, "an unauthorized active RESTRICTED proposal must be denied by the gate"


def t_proposal_unknown_capability_raises():
    reg = reg_with(cap("a"))
    prop = normalize("a", ResultKind.ACTION_PROPOSAL, summary="x", proposed_action={"cap": "ghost", "action": "READ_ONLY"})
    try:
        route_capability_proposal(reg, prop, ctx(Principal("u"))); assert False
    except KeyError:
        pass


# ── §38 oversized result clamp ────────────────────────────────────────────────
def t_oversized_result_clamped():
    reg = reg_with(cap("noisy"))
    huge = normalize("noisy", ResultKind.OBSERVATION, summary="A" * (MAX_RESULT_CHARS + 5000))
    out = governed_invoke(reg, FakeAdapter(huge), "noisy", ActionClass.READ_ONLY, {}, ctx(Principal("u")))
    assert len(out.summary) <= MAX_RESULT_CHARS + 20 and out.summary.endswith("…[truncated]")
    assert "oversized_result_truncated" in out.injection_flags


# ── §21 audit redaction — events carry lineage, never secrets ─────────────────
def t_audit_never_carries_request_or_secret():
    reg = reg_with(cap("context7"))
    events = []
    governed_invoke(reg, FakeAdapter(normalize("context7", ResultKind.OBSERVATION, summary="ok")),
                    "context7", ActionClass.READ_ONLY, {"token": "SECRET-abc123"}, ctx(Principal("u")),
                    audit=events.append)
    for e in events:
        blob = str(e.context).lower()
        assert "secret-abc123" not in blob and "token" not in blob, "audit must not contain the request/secret"
        assert set(e.context.keys()) == {"principal", "role", "mission_id", "procedure_id", "agent_id", "correlation_id"}


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
