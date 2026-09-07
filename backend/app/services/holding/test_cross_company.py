"""No-fabrication guard for §55 cross-company shared-issue detection. Run (from backend/):
    python3 -m app.services.holding.test_cross_company

Mirrors test_registry.py / test_holding_problems.py: a flat ck() ledger. Proves the detector reports
ONLY issues backed by a REAL shared token across 2+ companies (never a false correlation of unrelated
state), cites the companies + real evidence, and returns [] honestly when there is no shared issue.
"""
from app.services.holding.cross_company import detect_shared_issues, SharedIssue, _SEV_ORDER
from app.services.holding.registry import HoldingEntity
from app.services.holding.holding_problems import HoldingProblem

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def prob(cid, cat, sev, facts, causes=None):
    return HoldingProblem(problem_id=f"{cid}:{cat}", company=cid, system=cid, severity=sev, category=cat,
                          observed_facts=facts, possible_causes=causes or ["hyp-a", "hyp-b"],
                          root_signature=f"{cid}:{cat}")


class _Cap:
    def __init__(self, cid, name, avail, caps):
        self.id, self.name, self.availability, self.capabilities = cid, name, avail, caps


# ── inputs: alpha & beta genuinely share (Stripe vendor / wheellsverse-bots repo / Railway infra /
#    wheellsverse.com funnel). gamma shares NOTHING. holdco is the parent (must be excluded). ────────────
alpha = HoldingEntity("alpha", "Alpha", entity_type="product", integrations=["Stripe Checkout (Go Premium)"],
                      repository="wheellsverse-bots (app)", deployment="Railway: proj-alpha",
                      domains=["app.wheellsverse.com"])
beta = HoldingEntity("beta", "Beta", entity_type="product", integrations=["Stripe"],
                     repository="wheellsverse-bots (engine)", deployment="Railway backend (beta-prod)",
                     domains=["beta.wheellsverse.com"])
gamma = HoldingEntity("gamma", "Gamma", entity_type="product", integrations=["Dwolla (MOCK)"],
                      repository="gamma-repo (standalone)", deployment="Fly.io", domains=["gamma.io"])
holdco = HoldingEntity("hold", "Holdings", entity_type="holding")
ents = [alpha, beta, gamma, holdco]

problems = [
    prob("alpha", "HEALTH", "CRITICAL", "alpha health probe not OK"),
    prob("beta", "HEALTH", "HIGH", "beta health probe not OK"),
    prob("gamma", "HEALTH", "CRITICAL", "gamma health probe not OK"),     # unrelated — shares no token
    prob("alpha", "CODE_DEFECT", "HIGH", "alpha certified suite failing"),
    prob("beta", "CODE_DEFECT", "MEDIUM", "beta certified suite failing"),
    prob("alpha", "SECURITY", "HIGH", "stripe auth token unauthorized (401)"),
    prob("beta", "SECURITY", "HIGH", "stripe credential unauthorized (401)"),
]
caps = [_Cap("cap-a", "Cap A", "AVAILABLE", ["send_email", "implement"]),
        _Cap("cap-b", "Cap B", "AVAILABLE", ["send_email"]),
        _Cap("cap-c", "Cap C", "DISCOVERED", ["send_email"])]            # dormant -> not a live duplicate
port = {"needs_attention": ["alpha", "beta", "gamma"], "blocked": []}

out = detect_shared_issues(entities=ents, problems=problems, capabilities=caps, portfolio=port)
types = {i.issue_type for i in out}

# a genuine shared signal is detected for EACH class, with cited companies + real evidence
ck("shared vendor (Stripe) detected across the two companies that name it",
   any(i.issue_type == "SHARED_VENDOR" and sorted(i.companies) == ["alpha", "beta"]
       and i.shared_resource == "stripe" for i in out))
ck("shared vendor issue cites the real integration evidence per company",
   all(e.get("integration") for i in out if i.issue_type == "SHARED_VENDOR" for e in i.evidence))
ck("shared infrastructure failure detected (same provider + active problems on 2+ sharers)",
   any(i.issue_type == "SHARED_INFRA_FAILURE" and i.shared_resource == "railway"
       and sorted(i.companies) == ["alpha", "beta"] for i in out))
ck("common code defect detected (shared repo + active code problems on 2+ sharers)",
   any(i.issue_type == "COMMON_CODE_DEFECT" and sorted(i.companies) == ["alpha", "beta"] for i in out))
ck("shared customer funnel detected (shared domain root)",
   any(i.issue_type == "SHARED_FUNNEL" and i.shared_resource == "wheellsverse.com" for i in out))
ck("duplicate capability detected from the capability registry (2 AVAILABLE providers of one token)",
   any(i.issue_type == "DUPLICATE_CAPABILITY" and i.shared_resource == "send_email"
       and {"cap-a", "cap-b"} <= {e["capability_id"] for e in i.evidence} for i in out))
ck("dormant (DISCOVERED) capability is NOT counted as a live duplicate",
   all("cap-c" not in {e.get("capability_id") for e in i.evidence}
       for i in out if i.issue_type == "DUPLICATE_CAPABILITY"))
ck("shared credential outage detected (shared vendor + auth/credential problem on 2+ sharers)",
   any(i.issue_type == "SHARED_CREDENTIAL_OUTAGE" for i in out))

# THE core §55 guard: unrelated company state is NEVER merged
ck("unrelated company (gamma) with its own problems is NEVER merged into any shared issue",
   all("gamma" not in i.companies for i in out))
ck("the holding parent entity is excluded (not treated as a company)",
   all("hold" not in i.companies for i in out))

# zero-fabrication honesty
ck("every shared issue cites >=2 companies (or the holding scope for a fabric-wide duplicate)",
   all(len(i.companies) >= 2 or i.companies == ["holding"] for i in out))
ck("possible_causes is ALWAYS >=2 hypotheses (never one confirmed shared root cause)",
   all(len(i.possible_causes) >= 2 for i in out))
ck("failure classes explicitly keep the 'coincidental / not actually shared' hypothesis",
   all(any("coincident" in c.lower() or "not actually" in c.lower() for c in i.possible_causes)
       for i in out if i.issue_type in ("SHARED_INFRA_FAILURE", "COMMON_CODE_DEFECT", "SHARED_CREDENTIAL_OUTAGE")))
ck("every issue carries a real evidence[] (never empty)", all(i.evidence for i in out))
ck("prod-severity infra failure is owner_required", any(i.issue_type == "SHARED_INFRA_FAILURE"
   and i.owner_required for i in out))

# ranking + dedup
ck("ranked most-severe first", [_SEV_ORDER.get(i.severity, 9) for i in out] ==
   sorted(_SEV_ORDER.get(i.severity, 9) for i in out))
ck("one issue per (type, shared_resource) — deduped by root_signature",
   len({i.root_signature for i in out}) == len(out))

# no shared token at all -> [] honestly (both broken, but different provider/repo/vendor/domain)
lone_a = HoldingEntity("lone_a", "LoneA", entity_type="product", integrations=["Stripe"],
                       repository="a-repo", deployment="Railway", domains=["a.com"])
lone_b = HoldingEntity("lone_b", "LoneB", entity_type="product", integrations=["Dwolla"],
                       repository="b-repo", deployment="Fly.io", domains=["b.net"])
ck("two companies both broken but sharing NO token -> [] (no false correlation)",
   detect_shared_issues(entities=[lone_a, lone_b],
                        problems=[prob("lone_a", "HEALTH", "CRITICAL", "a down"),
                                  prob("lone_b", "HEALTH", "CRITICAL", "b down")],
                        capabilities=[], portfolio={}) == [])
# a shared token but only ONE company actually failing -> not a shared failure
ck("shared repo but only ONE company failing -> no shared code defect",
   not any(i.issue_type == "COMMON_CODE_DEFECT"
           for i in detect_shared_issues(entities=[alpha, beta], capabilities=[], portfolio={},
                                         problems=[prob("alpha", "CODE_DEFECT", "HIGH", "only alpha")])))
# fully empty -> [] (never raises, never fabricates)
ck("fully empty inputs -> [] (no fabricated shared issues)",
   detect_shared_issues(entities=[], problems=[], capabilities=[], portfolio={}) == [])

# as_dict round-trips to the full §55 field set
d = out[0].as_dict()
FIELDS = {"issue_id", "issue_type", "companies", "shared_resource", "severity", "observed_facts",
          "evidence", "impact", "confidence", "possible_causes", "recommended_actions",
          "owner_required", "root_signature"}
ck("as_dict() carries the full §55 field set", FIELDS <= set(d) and isinstance(d["companies"], list))

# real-registry default run: does not raise, and any issue it finds is over real shared registry tokens
real = detect_shared_issues()
ck("real-registry default run does not raise and is bounded (list)", isinstance(real, list))
ck("real default run merges nothing without a real shared token (>=2 companies or holding scope each)",
   all(len(i.companies) >= 2 or i.companies == ["holding"] for i in real))

n = len(res); ok = sum(res)
print(f"\nCROSS-COMPANY SHARED-ISSUE TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
