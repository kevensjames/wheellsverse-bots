"""§55 cross-company shared-issue detector (extends §18) — CONSOLIDATION, not a new detector.

KAI already has ONE problem stream (holding_problems.detect_problems, the ProblemModel stage) and ONE
authoritative company model (holding.registry + holding.digital_twin). This module adds NO parallel
detector/ranker/queue/sender: it READS those and the capability registry and reports the *narrow* class
of issues that are SHARED across two-or-more holding companies — shared infrastructure failure, shared
vendor/cost, duplicate capabilities, a shared customer funnel, a common code defect, or a shared
credential outage.

Anti-false-correlation is the whole point (§55: "don't merge unrelated state"). Two companies merely
both having a problem is NEVER a shared issue. A shared issue requires a REAL shared SIGNAL — a concrete
token that literally appears in the registry data of 2+ companies (the same vendor name, the same infra
provider, the same repository, the same customer domain, the same duplicated capability). The failure
classes additionally require active per-company problems (from detect_problems) among exactly those
token-sharing companies. A false correlation is worse than none, so with no shared token there is no
issue, and the honest result is [].

Zero-fabrication (§0 #16-19): every field is a REAL source read, a DETERMINISTIC derivation of one, or
an explicit UNKNOWN. `possible_causes` is ALWAYS a plurality of candidate hypotheses — and for every
failure class it explicitly INCLUDES the "coincidental / not actually shared" hypothesis, so the card
never asserts a confirmed shared root cause. No LLM is consulted anywhere. Sources are injectable and
every producer is FAIL-OPEN (a broken source yields no issue, never a fabricated one). Bounded (§79):
pure functions over already-collected state — no loops-forever, no daemons, no network, no LLM.

Pure/injectable so the whole thing is a plain ``python3`` self-test (mirrors holding_problems.demo /
priorities.demo). Run the guard: ``python3 -m app.services.holding.test_cross_company``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

# reuse the digital_twin company taxonomy — a "company" is a startup-typed registry entity, never the
# holding parent or an internal-only project. (kept in sync with digital_twin.STARTUP_TYPES)
_STARTUP_TYPES = {"product", "company", "LLC", "startup"}

# curated infra PROVIDERS — a shared provider is a legitimate shared-fate signal (a provider incident
# would hit every company on it). Provider-level, not a fragile per-project-slug guess.
_INFRA_PROVIDERS = {"railway", "cloudflare", "vercel", "netlify", "heroku", "render", "fly",
                    "aws", "gcp", "azure", "digitalocean", "supabase", "fastly"}

# which ProblemModel categories evidence each failure class (§18 categories)
_INFRA_CATS = {"HEALTH", "DEPLOYMENT_DRIFT", "MONITORING", "INCIDENT"}
_CODE_CATS = {"CODE_DEFECT", "MISSION_FAILURE", "DOCUMENTATION"}
_CRED_HINT = ("credential", "auth", "token", "unauthorized", "401", "403", "api key", "apikey",
              "login", "expired key", "revoked")

# noise words that are never a vendor identity when they lead an integration label
_VENDOR_STOP = {"prod", "production", "internal", "observability", "monitor", "the", "a", "an"}

_ISSUE_META = {
    "SHARED_INFRA_FAILURE":     dict(
        impact="Two or more companies on the same infrastructure provider are failing at once — a single provider fault could be taking them all down.",
        causes=["a genuine shared-infrastructure / provider incident affecting every listed company",
                "coincidental independent failures on the same provider that are NOT actually related",
                "a shared network / DNS / region fault"],
        actions=["INVESTIGATE", "CREATE_MISSION", "EVIDENCE"], owner=True),
    "SHARED_VENDOR":            dict(
        impact="Multiple companies depend on the same external vendor — a concentration risk (shared cost, single point of failure, one contract).",
        causes=["intentional standardization on one vendor",
                "independent adoption that converged on the same vendor",
                "a consolidation / cost-negotiation opportunity"],
        actions=["INVESTIGATE", "DEFER", "EVIDENCE"], owner=False),
    "DUPLICATE_CAPABILITY":     dict(
        impact="The shared capability fabric carries more than one capability doing the same thing — redundant tooling the whole holding maintains twice.",
        causes=["two capabilities were added for overlapping needs",
                "a migration left the old capability in place",
                "a consolidation opportunity to retire the redundant one"],
        actions=["INVESTIGATE", "DEFER"], owner=False),
    "SHARED_FUNNEL":            dict(
        impact="Multiple companies share the same customer-facing domain / entry funnel — an outage or change there affects all of them.",
        causes=["companies intentionally share one apex / entry domain",
                "a shared front door (proxy / pages) fronts several products",
                "a routing or DNS change would fan out across all of them"],
        actions=["INVESTIGATE", "EVIDENCE"], owner=False),
    "COMMON_CODE_DEFECT":       dict(
        impact="Two or more companies live in the same repository and are failing at once — one code defect may be common to all of them.",
        causes=["a single shared-code defect affecting every listed company",
                "coincidental unrelated failures that merely share a monorepo",
                "a shared dependency or build/config problem in the repo"],
        actions=["INVESTIGATE", "PREPARE_FIX", "EVIDENCE"], owner=False),
    "SHARED_CREDENTIAL_OUTAGE": dict(
        impact="Companies sharing an external vendor are showing a credential / auth failure against it — one revoked or expired credential could be breaking all of them.",
        causes=["a single shared credential expired / was revoked / hit a quota",
                "coincidental independent auth failures that are NOT the same credential",
                "a vendor-side auth outage affecting every consumer"],
        actions=["INVESTIGATE", "CREATE_MISSION", "EVIDENCE"], owner=True),
}


@dataclass
class SharedIssue:
    """A §55 cross-company shared issue. Every field REAL / DERIVED / UNKNOWN — never fabricated."""
    issue_id: str
    issue_type: str
    companies: list                                   # >=2 real company ids that share the signal
    shared_resource: str                              # the concrete shared token (vendor / provider / repo / domain / capability)
    severity: str
    observed_facts: str
    evidence: list = field(default_factory=list)      # real source records (cited companies + tokens + problems)
    impact: str = "UNKNOWN"                           # DERIVED from issue_type (not a fabricated metric)
    confidence: str = "MEDIUM"                        # a cross-company correlation is DERIVED, never a directly-observed single fact
    possible_causes: list = field(default_factory=list)   # ALWAYS plural; failure classes include the "coincidence" hypothesis
    recommended_actions: list = field(default_factory=list)
    owner_required: bool = False
    root_signature: str = ""                          # deterministic dedup key: issue_type:shared_resource

    def as_dict(self) -> dict:
        return asdict(self)


# ── small adapters so a problem may be a HoldingProblem OR a plain dict, an entity a HoldingEntity OR a dict ──
def _pget(p, key, default=""):
    v = p.get(key) if isinstance(p, dict) else getattr(p, key, default)
    return v if v is not None else default


def _eget(e, key, default=""):
    v = e.get(key) if isinstance(e, dict) else getattr(e, key, default)
    return v if v is not None else default


def _worst(sevs: list[str]) -> str:
    return min(sevs, key=lambda s: _SEV_ORDER.get(s, 9)) if sevs else "LOW"


# ── token extraction (deterministic, no fabrication) ────────────────────────────────────────────
_SLUG_RE = re.compile(r"[a-z][a-z0-9]+(?:-[a-z0-9]+)+")            # e.g. wheellsverse-bots, kai-production
_DOMAIN_RE = re.compile(r"[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\.[a-z]{2,}")   # e.g. app.wheellsverse.com


def _repo_slugs(e) -> set[str]:
    return set(_SLUG_RE.findall(str(_eget(e, "repository", "")).lower()))


def _infra_providers(e) -> set[str]:
    txt = f"{_eget(e, 'deployment', '')} {_eget(e, 'operational_status', '')}".lower()
    toks = set(re.split(r"[^a-z0-9]+", txt))
    return {p for p in _INFRA_PROVIDERS if p in toks}


def _domain_roots(e) -> set[str]:
    hosts = set()
    for d in (_eget(e, "domains", []) or []):
        hosts.add(str(d).lower())
    txt = f"{_eget(e, 'deployment', '')} {_eget(e, 'operational_status', '')}".lower()
    hosts.update(_DOMAIN_RE.findall(txt))
    roots = set()
    for h in hosts:
        parts = [p for p in h.strip().split(".") if p]
        if len(parts) >= 2:
            roots.add(".".join(parts[-2:]))                       # registrable root: app.wheellsverse.com -> wheellsverse.com
    return roots


def _vendors(e) -> dict[str, str]:
    """{vendor_key: full_label} from the registry `integrations` field (a dedicated vendor list —
    the cleanest real source). Key is the leading meaningful word; noise/mode words are dropped."""
    out: dict[str, str] = {}
    for i in (_eget(e, "integrations", []) or []):
        label = str(i).split("(")[0].strip()
        first = re.split(r"[^a-z0-9]+", label.lower())[0] if label else ""
        if len(first) >= 3 and first not in _VENDOR_STOP:
            out[first] = label
    return out


def _invert(entities, extract) -> dict[str, list]:
    """token -> [company_id, ...] over the given extractor; only tokens shared by >=2 companies survive."""
    token_to: dict[str, list] = {}
    for e in entities:
        cid = _eget(e, "entity_id", "")
        if not cid:
            continue
        for tok in extract(e):
            token_to.setdefault(tok, [])
            if cid not in token_to[tok]:
                token_to[tok].append(cid)
    return {tok: cids for tok, cids in token_to.items() if len(cids) >= 2}


def _mk(*, issue_type, companies, shared_resource, severity, observed_facts, evidence,
        confidence, owner_extra=False) -> SharedIssue:
    meta = _ISSUE_META[issue_type]
    root = f"{issue_type}:{shared_resource}"
    return SharedIssue(
        issue_id=root, issue_type=issue_type, companies=sorted(companies),
        shared_resource=shared_resource, severity=severity,
        observed_facts=observed_facts, evidence=evidence or [{"source": "UNKNOWN"}],
        impact=meta["impact"], confidence=confidence, possible_causes=list(meta["causes"]),
        recommended_actions=list(meta["actions"]),
        owner_required=bool(meta["owner"] or owner_extra or severity == "CRITICAL"),
        root_signature=root)


# ── structural shared signals (a real shared token in the registry — no active problem required) ──
def _shared_vendors(entities, names) -> list:
    vend_of = {_eget(e, "entity_id", ""): _vendors(e) for e in entities}
    token_to: dict[str, list] = {}
    for cid, vmap in vend_of.items():
        for key in vmap:
            token_to.setdefault(key, [])
            if cid not in token_to[key]:
                token_to[key].append(cid)
    out = []
    for key, cids in token_to.items():
        if len(cids) < 2:
            continue
        labels = sorted({vend_of[c][key] for c in cids})
        out.append(_mk(
            issue_type="SHARED_VENDOR", companies=cids, shared_resource=key, severity="LOW",
            observed_facts=f"{len(cids)} companies depend on vendor '{labels[0]}' ({', '.join(sorted(cids))})",
            evidence=[{"company": c, "company_name": names.get(c, c), "integration": vend_of[c][key]} for c in sorted(cids)],
            confidence="MEDIUM"))                        # a cross-company dependency is a derived correlation
    return out


def _shared_funnels(entities, names) -> list:
    shared = _invert(entities, _domain_roots)
    out = []
    for root, cids in shared.items():
        out.append(_mk(
            issue_type="SHARED_FUNNEL", companies=cids, shared_resource=root, severity="INFO",
            observed_facts=f"{len(cids)} companies share the customer domain '{root}' ({', '.join(sorted(cids))})",
            evidence=[{"company": c, "company_name": names.get(c, c), "domain_root": root} for c in sorted(cids)],
            confidence="MEDIUM"))
    return out


def _duplicate_capabilities(capabilities) -> list:
    """From the capability REGISTRY: a capability token declared by >=2 AVAILABLE manifests is redundant
    tooling the whole holding maintains. Only AVAILABLE (selectable) manifests count — a DISCOVERED/
    dormant catalog entry is not a live duplicate. Fail-open on a bad manifest."""
    tok_to: dict[str, list] = {}
    for m in capabilities or []:
        try:
            avail = getattr(m, "availability", None)
            avail = getattr(avail, "value", avail)
            if str(avail).upper() != "AVAILABLE":
                continue
            mid = getattr(m, "id", "") or ""
            name = getattr(m, "name", mid) or mid
            for cap in (getattr(m, "capabilities", []) or []):
                key = str(cap).strip().lower()
                if not key:
                    continue
                tok_to.setdefault(key, [])
                if mid not in [x[0] for x in tok_to[key]]:
                    tok_to[key].append((mid, name))
        except Exception:
            continue
    out = []
    for cap, providers in tok_to.items():
        if len(providers) < 2:
            continue
        out.append(_mk(
            issue_type="DUPLICATE_CAPABILITY", companies=["holding"], shared_resource=cap, severity="LOW",
            observed_facts=f"capability '{cap}' is provided by {len(providers)} AVAILABLE capabilities: "
                           f"{', '.join(sorted(p[0] for p in providers))}",
            evidence=[{"capability_id": p[0], "name": p[1], "provides": cap} for p in sorted(providers)],
            confidence="MEDIUM"))
    return out


# ── failure shared signals (a real shared token AND active per-company problems among those companies) ──
def _by_company(problems) -> dict[str, list]:
    out: dict[str, list] = {}
    for p in problems or []:
        cid = _pget(p, "company", "")
        if cid and cid != "holding":
            out.setdefault(cid, []).append(p)
    return out


def _failure_over_token(*, issue_type, shared, probs_by_co, cats, names, portfolio, hint=None) -> list:
    """For each shared token, keep only the token-sharing companies that ALSO have a matching active
    problem. Requires >=2 such companies — otherwise it is not a shared failure (anti-false-correlation).
    portfolio_view (needs_attention/blocked) corroborates the health and drives owner escalation."""
    needs = set((portfolio or {}).get("needs_attention", []) or []) | set((portfolio or {}).get("blocked", []) or [])
    out = []
    for token, cids in shared.items():
        hit_co, ev, sevs = [], [], []
        for c in cids:
            for p in probs_by_co.get(c, []):
                cat = _pget(p, "category", "")
                if cat not in cats:
                    continue
                if hint is not None:
                    blob = f"{_pget(p, 'observed_facts', '')} {' '.join(map(str, _pget(p, 'possible_causes', []) or []))}".lower()
                    if not any(h in blob for h in hint):
                        continue
                if c not in hit_co:
                    hit_co.append(c)
                sevs.append(_pget(p, "severity", "MEDIUM"))
                ev.append({"company": c, "company_name": names.get(c, c), "category": cat,
                           "severity": _pget(p, "severity", "MEDIUM"),
                           "observed_facts": _pget(p, "observed_facts", ""),
                           "problem_id": _pget(p, "problem_id", ""),
                           "portfolio_health": "NEEDS_ATTENTION" if c in needs else "OK"})
        if len(hit_co) < 2:                              # <2 unhealthy sharers -> NOT a shared failure
            continue
        sev = _worst(sevs)
        out.append(_mk(
            issue_type=issue_type, companies=hit_co, shared_resource=token, severity=sev,
            observed_facts=f"{len(hit_co)} companies sharing '{token}' have active "
                           f"{'/'.join(sorted(cats))} problem(s): {', '.join(sorted(hit_co))}",
            evidence=ev, confidence="MEDIUM",           # the shared-ness is a correlation, not a directly-observed fact
            owner_extra=any(c in needs for c in hit_co)))
    return out


# ── fail-open default sources (each only runs when its arg is None) ──────────────────────────────
def _default_entities() -> list:
    try:
        from app.services.holding import registry as reg
        return reg.all_entities()
    except Exception:
        return []


def _default_problems() -> list:
    try:
        from app.services.holding.holding_problems import detect_problems
        return detect_problems()
    except Exception:
        return []


def _default_capabilities() -> list:
    try:
        from app.services.capability.seed import seed_registry
        from app.services.capability.manifest import Availability
        return seed_registry().list(availability=Availability.AVAILABLE)
    except Exception:
        return []


def _default_portfolio() -> dict:
    try:
        from app.services.holding.digital_twin import HoldingDigitalTwin
        return HoldingDigitalTwin().portfolio_view()
    except Exception:
        return {}


def detect_shared_issues(*, entities=None, problems=None, capabilities=None,
                         portfolio=None, now: str = "") -> list:
    """Detect the issues SHARED across 2+ holding companies from real state only.

    Sources (all injectable, each defaulting to a fail-open real read): registry.all_entities(),
    holding_problems.detect_problems() (the ProblemModel stage), the capability registry, and
    digital_twin.portfolio_view(). Every emitted issue requires a REAL shared token (a vendor /
    provider / repo / domain / capability that literally appears for 2+ companies); the failure
    classes additionally require 2+ of those companies to have a matching active problem. Companies
    that share no token are NEVER merged. Deduped by root_signature, most-severe first. Pure/bounded
    (§79): no LLM, no loop-forever, no write path."""
    ents = entities if entities is not None else _default_entities()
    companies = [e for e in ents if _eget(e, "entity_type", "") in _STARTUP_TYPES
                 and _eget(e, "entity_type", "") != "holding"]
    names = {_eget(e, "entity_id", ""): _eget(e, "brand_name", _eget(e, "entity_id", "")) for e in companies}

    probs = problems if problems is not None else _default_problems()
    caps = capabilities if capabilities is not None else _default_capabilities()
    port = portfolio if portfolio is not None else _default_portfolio()

    probs_by_co = _by_company(probs)
    shared_repos = _invert(companies, _repo_slugs)
    shared_infra = _invert(companies, _infra_providers)

    issues: list = []
    for producer in (
        lambda: _shared_vendors(companies, names),
        lambda: _shared_funnels(companies, names),
        lambda: _duplicate_capabilities(caps),
        lambda: _failure_over_token(issue_type="SHARED_INFRA_FAILURE", shared=shared_infra,
                                    probs_by_co=probs_by_co, cats=_INFRA_CATS, names=names, portfolio=port),
        lambda: _failure_over_token(issue_type="COMMON_CODE_DEFECT", shared=shared_repos,
                                    probs_by_co=probs_by_co, cats=_CODE_CATS, names=names, portfolio=port),
        lambda: _failure_over_token(issue_type="SHARED_CREDENTIAL_OUTAGE", shared={**shared_infra, **_vendor_shared(companies)},
                                    probs_by_co=probs_by_co, cats=_INFRA_CATS | {"SECURITY", "MISSION_FAILURE"},
                                    names=names, portfolio=port, hint=_CRED_HINT),
    ):
        try:
            issues.extend(producer())
        except Exception:
            continue                                     # fail-open per producer (§55): never fabricate

    # dedup by root_signature (issue_type:shared_resource) — higher severity kept, evidence merged
    by_root: dict = {}
    for it in issues:
        cur = by_root.get(it.root_signature)
        if cur is None:
            by_root[it.root_signature] = it
        elif _SEV_ORDER.get(it.severity, 9) < _SEV_ORDER.get(cur.severity, 9):
            it.evidence = cur.evidence + it.evidence
            by_root[it.root_signature] = it
        else:
            cur.evidence = cur.evidence + it.evidence
    return sorted(by_root.values(), key=lambda i: _SEV_ORDER.get(i.severity, 9))


def _vendor_shared(entities) -> dict[str, list]:
    """{vendor_key: [companies]} for vendors shared by >=2 companies — the token space for credential outages."""
    tok: dict[str, list] = {}
    for e in entities:
        cid = _eget(e, "entity_id", "")
        for key in _vendors(e):
            tok.setdefault(key, [])
            if cid not in tok[key]:
                tok[key].append(cid)
    return {k: v for k, v in tok.items() if len(v) >= 2}


def demo() -> None:
    """Pure self-check — no DB/network. Proves: a genuine shared signal (same vendor across 2 companies,
    a shared-infra failure with cited problems) is detected with cited companies+evidence; unrelated
    company state is NEVER merged; empty inputs return [] honestly; failure causes always include the
    'coincidence' hypothesis; dedup + ranking."""
    from app.services.holding.registry import HoldingEntity
    from app.services.holding.holding_problems import HoldingProblem

    # alpha & beta share Stripe (vendor), wheellsverse-bots (repo), Railway (infra), wheellsverse.com (funnel).
    # gamma shares NOTHING with them (Dwolla / its own repo / Fly.io / its own domain).
    alpha = HoldingEntity("alpha", "Alpha", entity_type="product",
                          integrations=["Stripe Checkout (Go Premium)"], repository="wheellsverse-bots (app)",
                          deployment="Railway: proj-alpha", domains=["app.wheellsverse.com"])
    beta = HoldingEntity("beta", "Beta", entity_type="product",
                         integrations=["Stripe"], repository="wheellsverse-bots (engine)",
                         deployment="Railway backend (beta-prod)", domains=["beta.wheellsverse.com"])
    gamma = HoldingEntity("gamma", "Gamma", entity_type="product",
                          integrations=["Dwolla (MOCK)"], repository="gamma-repo (standalone)",
                          deployment="Fly.io", domains=["gamma.io"])
    holdco = HoldingEntity("hold", "Holdings", entity_type="holding")   # parent — must be excluded
    ents = [alpha, beta, gamma, holdco]

    def prob(cid, cat, sev, facts, causes=None):
        return HoldingProblem(problem_id=f"{cid}:{cat}", company=cid, system=cid, severity=sev,
                              category=cat, observed_facts=facts, possible_causes=causes or ["x", "y"],
                              root_signature=f"{cid}:{cat}")

    # alpha+beta both failing on the shared Railway infra AND a shared-repo code defect; gamma also failing
    # (but shares no token) — gamma must NOT be merged into any shared issue.
    problems = [
        prob("alpha", "HEALTH", "CRITICAL", "alpha health probe not OK"),
        prob("beta", "HEALTH", "HIGH", "beta health probe not OK"),
        prob("gamma", "HEALTH", "CRITICAL", "gamma health probe not OK"),   # unrelated — no shared token
        prob("alpha", "CODE_DEFECT", "HIGH", "alpha certified suite failing"),
        prob("beta", "CODE_DEFECT", "MEDIUM", "beta certified suite failing"),
        prob("alpha", "SECURITY", "HIGH", "stripe auth token unauthorized (401)"),
        prob("beta", "SECURITY", "HIGH", "stripe credential unauthorized (401)"),
    ]

    class _Cap:
        def __init__(self, cid, name, avail, caps):
            self.id, self.name, self.availability, self.capabilities = cid, name, avail, caps
    caps = [_Cap("cap-a", "Cap A", "AVAILABLE", ["send_email", "implement"]),
            _Cap("cap-b", "Cap B", "AVAILABLE", ["send_email"]),          # duplicate of cap-a's send_email
            _Cap("cap-c", "Cap C", "DISCOVERED", ["send_email"])]          # dormant -> not a live duplicate

    port = {"needs_attention": ["alpha", "beta", "gamma"], "blocked": []}
    out = detect_shared_issues(entities=ents, problems=problems, capabilities=caps, portfolio=port)
    types = {i.issue_type for i in out}

    # 1) genuine shared signals detected, with cited companies + real evidence
    assert "SHARED_VENDOR" in types, types
    sv = next(i for i in out if i.issue_type == "SHARED_VENDOR" and i.shared_resource == "stripe")
    assert sorted(sv.companies) == ["alpha", "beta"], sv.companies
    assert sv.evidence and all(e.get("integration") for e in sv.evidence), sv.evidence
    assert "SHARED_INFRA_FAILURE" in types and "COMMON_CODE_DEFECT" in types, types
    infra = next(i for i in out if i.issue_type == "SHARED_INFRA_FAILURE")
    assert sorted(infra.companies) == ["alpha", "beta"] and infra.severity == "CRITICAL", infra
    assert infra.shared_resource == "railway" and infra.owner_required, infra
    assert "SHARED_FUNNEL" in types and "DUPLICATE_CAPABILITY" in types, types
    dup = next(i for i in out if i.issue_type == "DUPLICATE_CAPABILITY")
    assert dup.shared_resource == "send_email" and {"cap-a", "cap-b"} <= {e["capability_id"] for e in dup.evidence}, dup
    assert "SHARED_CREDENTIAL_OUTAGE" in types, types

    # 2) unrelated state is NEVER merged — gamma shares no token, so no issue lists gamma
    assert all("gamma" not in i.companies for i in out), [i.companies for i in out]
    # every failure class keeps the "coincidence / not actually shared" hypothesis (no confirmed shared root cause)
    for i in out:
        assert len(i.possible_causes) >= 2, i
        if i.issue_type in ("SHARED_INFRA_FAILURE", "COMMON_CODE_DEFECT", "SHARED_CREDENTIAL_OUTAGE"):
            assert any("coincident" in c.lower() or "not actually" in c.lower() for c in i.possible_causes), i

    # 3) ranked most-severe first
    sevs = [_SEV_ORDER.get(i.severity, 9) for i in out]
    assert sevs == sorted(sevs), sevs

    # 4) no shared token at all -> [] honestly (two companies both broken, but on different providers/repos/vendors)
    lone_a = HoldingEntity("lone_a", "LoneA", entity_type="product", integrations=["Stripe"],
                           repository="a-repo", deployment="Railway", domains=["a.com"])
    lone_b = HoldingEntity("lone_b", "LoneB", entity_type="product", integrations=["Dwolla"],
                           repository="b-repo", deployment="Fly.io", domains=["b.net"])
    none = detect_shared_issues(entities=[lone_a, lone_b],
                                problems=[prob("lone_a", "HEALTH", "CRITICAL", "a down"),
                                          prob("lone_b", "HEALTH", "CRITICAL", "b down")],
                                capabilities=[], portfolio={})
    assert none == [], [i.as_dict() for i in none]

    # 5) fully empty -> [] (never raises, never fabricates)
    assert detect_shared_issues(entities=[], problems=[], capabilities=[], portfolio={}) == []

    print(f"cross_company.demo OK — {len(out)} shared issues across {len(types)} types "
          f"({', '.join(sorted(types))}); unrelated 'gamma' never merged; no-shared-token -> []")


if __name__ == "__main__":
    demo()
