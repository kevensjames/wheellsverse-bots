"""§20 OpportunityEngine — surface evidence-backed OPPORTUNITIES from real holding state.

CONSOLIDATION, not a new detector. This adds NO parallel detector/ranker/queue/sender: it READS three
already-certified streams and reports the *opportunity* facet each one implies —
  • §82 goal-gap analysis (goal_registry.analyze_all)         → GROWTH opportunities (a measured gap to close)
  • §55 cross-company shared issues (cross_company)           → CONSOLIDATION opportunities (dup tooling / shared vendor)
  • §18 problem stream (holding_problems.detect_problems)     → RELIABILITY opportunities (a fixable problem)

It reuses the self_improvement_detect Candidate/evidence+confidence shape: every HoldingOpportunity has a
stable ``signature`` (root dedup key), a real ``evidence[]`` list, and an evidence-quality ``confidence``.

Zero-fabrication (§0 #16-19): every field is a REAL source read or a DETERMINISTIC derivation of one. An
opportunity whose evidence is empty or UNKNOWN-only is DROPPED — no generic ideas. No LLM is consulted
anywhere; ``effort``/``risk`` are coarse deterministic category heuristics (like proposals._template's
``effort``), never fabricated metrics. Sources are injectable and every producer is FAIL-OPEN (a broken
source yields no opportunity, never a fabricated one). Bounded (§79): pure functions over already-collected
state — no loop, no daemon, no network, no write path.

Pure/injectable so the whole thing is a plain ``python3`` self-test (mirrors holding_problems.demo /
cross_company.demo). Run: ``python3 -m app.services.holding.test_opportunity_engine``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

_CONF_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}

# cross_company issue types that are genuine CONSOLIDATION opportunities (the failure classes are
# PROBLEMS, not opportunities — they flow through detect_problems, never here).
_CONSOLIDATION_TYPES = {"DUPLICATE_CAPABILITY", "SHARED_VENDOR"}

# a fixable problem is one whose §106 action set includes PREPARE_FIX (KAI can prepare a fix for review).
_FIXABLE_ACTION = "PREPARE_FIX"

# coarse deterministic effort/risk per category. ponytail: T-shirt heuristic, not a fabricated metric —
# real effort is genuinely unknown for a business opportunity; these are honest coarse defaults.
_SEV_EFFORT = {"CRITICAL": "L", "HIGH": "M", "MEDIUM": "S", "LOW": "S", "INFO": "S"}


@dataclass
class HoldingOpportunity:
    """§20 opportunity. Every field is REAL / DERIVED / UNKNOWN — never fabricated."""
    title: str
    company: str
    why_now: str
    evidence: list = field(default_factory=list)          # real source records (cited)
    expected_benefit: str = "UNKNOWN"                     # DERIVED from the cited evidence, never generic
    confidence: str = "MEDIUM"                            # evidence quality (HIGH direct / MEDIUM derived / LOW best-effort)
    effort: str = "UNKNOWN"                               # coarse deterministic heuristic (S/M/L)
    risk: str = "low"
    dependencies: list = field(default_factory=list)
    owner_impact: bool = False                            # True if the owner must act (target/decision)
    recommended_next_step: str = "UNKNOWN"
    signature: str = ""                                   # stable dedup key (one per root opportunity)
    status: str = "PROPOSED"
    category: str = "GROWTH"                              # GROWTH | CONSOLIDATION | RELIABILITY

    def as_dict(self) -> dict:
        return asdict(self)


# ── adapters (an item may be a dataclass OR a plain dict) ──────────────────────────────────────────
def _get(o, key, default=""):
    v = o.get(key) if isinstance(o, dict) else getattr(o, key, default)
    return v if v is not None else default


def _is_real_evidence_item(e) -> bool:
    """An evidence item is real unless it is empty or the explicit UNKNOWN sentinel ({"source":"UNKNOWN"})."""
    if isinstance(e, dict):
        if not e:
            return False
        return any(str(v).strip().upper() not in ("", "UNKNOWN", "NONE") for v in e.values())
    return bool(e)


def _has_real_evidence(ev) -> bool:
    return any(_is_real_evidence_item(e) for e in (ev or []))


# ── source 1 (§82) : goal-gap analysis → GROWTH opportunities ──────────────────────────────────────
def _from_goal_gaps(gaps) -> list:
    """A goal whose gap verdict is GAP (target set, current known, not yet met) is a GROWTH opportunity
    to close a MEASURED gap. UNAVAILABLE/MET verdicts are NOT opportunities (no actionable gap / already
    met). Evidence = the analysis's cited {claim,value,source} rows."""
    out = []
    for g in gaps or []:
        d = g if isinstance(g, dict) else dict(g)
        if d.get("verdict") != "GAP":
            continue
        gap = d.get("gap") or {}
        company, metric = d.get("company", "?"), d.get("metric", "?")
        cur, tgt = gap.get("current"), gap.get("target")
        remaining = gap.get("remaining_to_target")
        actions = d.get("recommended_actions") or []
        nxt = (actions[0].get("action") if actions and isinstance(actions[0], dict) else "UNKNOWN")
        out.append(HoldingOpportunity(
            title=f"Close the {metric} gap on {company}",
            company=company,
            why_now=f"Measured gap: current {cur} vs target {tgt} (remaining {remaining}).",
            evidence=list(d.get("evidence") or []),
            expected_benefit=f"Move {metric} from {cur} toward target {tgt} (remaining {remaining}).",
            confidence="HIGH",                            # computed from real, cited numbers
            effort="M", risk="low",
            dependencies=[b.get("blocker") for b in (d.get("blockers") or []) if isinstance(b, dict)],
            owner_impact=False,
            recommended_next_step=nxt,
            signature=f"opp:goal:{d.get('goal_id','?')}:{metric}",
            category="GROWTH"))
    return out


# ── source 2 (§55) : cross-company shared issues → CONSOLIDATION opportunities ──────────────────────
def _from_shared_issues(issues) -> list:
    out = []
    for it in issues or []:
        itype = _get(it, "issue_type")
        if itype not in _CONSOLIDATION_TYPES:
            continue                                      # failure classes are problems, not opportunities
        companies = _get(it, "companies", []) or []
        resource = _get(it, "shared_resource")
        actions = _get(it, "recommended_actions", []) or []
        nxt = f"{actions[0]}: {resource}" if actions else "UNKNOWN"
        if itype == "DUPLICATE_CAPABILITY":
            title = f"Retire redundant tooling for '{resource}'"
            benefit = f"Retire redundant tooling: multiple AVAILABLE capabilities provide '{resource}'."
        else:  # SHARED_VENDOR
            title = f"Consolidate spend on vendor '{resource}'"
            benefit = f"Consolidate {len(companies)} companies' dependence on vendor '{resource}' (cost/negotiation leverage)."
        out.append(HoldingOpportunity(
            title=title,
            company=companies[0] if companies else "holding",
            why_now=_get(it, "observed_facts") or benefit,
            evidence=list(_get(it, "evidence", []) or []),
            expected_benefit=benefit,
            confidence=_get(it, "confidence", "MEDIUM") or "MEDIUM",
            effort="M", risk="low",
            dependencies=sorted(companies),
            owner_impact=bool(_get(it, "owner_required", False)),
            recommended_next_step=nxt,
            signature=f"opp:{_get(it, 'root_signature') or itype + ':' + resource}",
            category="CONSOLIDATION"))
    return out


# ── source 3 (§18) : fixable problems → RELIABILITY opportunities ───────────────────────────────────
def _from_problems(problems) -> list:
    """A problem KAI can PREPARE_FIX for is a RELIABILITY opportunity. Evidence = the problem's real
    evidence[]; a problem carrying only UNKNOWN evidence is dropped by the caller's evidence filter."""
    out = []
    for p in problems or []:
        actions = _get(p, "recommended_actions", []) or []
        if _FIXABLE_ACTION not in actions:
            continue
        facts = _get(p, "observed_facts")
        sev = _get(p, "severity", "MEDIUM") or "MEDIUM"
        out.append(HoldingOpportunity(
            title=f"Prepare a fix: {facts[:70]}",
            company=_get(p, "company", "holding") or "holding",
            why_now=facts,
            evidence=list(_get(p, "evidence", []) or []),
            expected_benefit=f"Resolve the {(_get(p, 'category') or '').lower()} problem: {facts}",
            confidence=_get(p, "confidence", "MEDIUM") or "MEDIUM",
            effort=_SEV_EFFORT.get(sev, "S"), risk="low",
            dependencies=[],
            owner_impact=bool(_get(p, "owner_required", False)),
            recommended_next_step=f"{_FIXABLE_ACTION}: {facts}",
            signature=f"opp:{_get(p, 'root_signature') or _get(p, 'problem_id')}",
            category="RELIABILITY"))
    return out


# ── fail-open default sources (each only runs when its arg is None) ─────────────────────────────────
def _default_goal_gaps() -> list:
    try:
        from app.services.holding.goal_registry import analyze_all
        return analyze_all(status="active")
    except Exception:
        return []


def _default_shared_issues() -> list:
    try:
        from app.services.holding.cross_company import detect_shared_issues
        return detect_shared_issues()
    except Exception:
        return []


def _default_problems() -> list:
    try:
        from app.services.holding.holding_problems import detect_problems
        return detect_problems()
    except Exception:
        return []


def detect_opportunities(*, goal_gaps=None, shared_issues=None, problems=None) -> list:
    """Surface evidence-backed opportunities from real state only.

    Sources (all injectable, each defaulting to a fail-open real read): goal_registry.analyze_all() (§82),
    cross_company.detect_shared_issues() (§55), holding_problems.detect_problems() (§18). Every emitted
    opportunity carries a stable signature + a REAL evidence[] + an evidence-quality confidence (the
    self_improvement_detect Candidate shape). An opportunity with empty/UNKNOWN-only evidence is DROPPED
    (no generic ideas). Deduped by signature, ranked by confidence then signature. Pure/bounded (§79):
    no LLM, no loop, no write path."""
    gaps = goal_gaps if goal_gaps is not None else _default_goal_gaps()
    issues = shared_issues if shared_issues is not None else _default_shared_issues()
    probs = problems if problems is not None else _default_problems()

    raw: list = []
    for producer in (lambda: _from_goal_gaps(gaps),
                     lambda: _from_shared_issues(issues),
                     lambda: _from_problems(probs)):
        try:
            raw.extend(producer())
        except Exception:
            continue                                      # fail-open per source: never fabricate

    # DROP any candidate whose evidence is empty/UNKNOWN-only (§0 #16-19: no generic ideas).
    real = [o for o in raw if _has_real_evidence(o.evidence)]

    # dedup by signature (keep the higher-confidence one), then rank by confidence, then signature.
    by_sig: dict = {}
    for o in real:
        cur = by_sig.get(o.signature)
        if cur is None or _CONF_ORDER.get(o.confidence, 3) < _CONF_ORDER.get(cur.confidence, 3):
            by_sig[o.signature] = o
    return sorted(by_sig.values(), key=lambda o: (_CONF_ORDER.get(o.confidence, 3), o.signature))


def demo() -> None:
    """Pure self-check — no DB/network. Proves: each source becomes the right opportunity category with
    cited evidence; a no-evidence / UNKNOWN-only candidate is DROPPED (no generic ideas); dedup by
    signature; ranked by confidence."""
    # §82 goal gap (verdict GAP) → GROWTH; a verdict UNAVAILABLE goal must NOT become an opportunity
    gaps = [
        {"goal_id": 1, "company": "sol", "metric": "customers", "verdict": "GAP",
         "gap": {"current": 40, "target": 100, "remaining_to_target": 60},
         "evidence": [{"claim": "current customers", "value": 40, "source": "registry:sol.customers (operator-confirmed)"}],
         "recommended_actions": [{"action": "Increase customers on sol by 60", "source": "computed"}],
         "blockers": []},
        {"goal_id": 2, "company": "kai", "metric": "revenue", "verdict": "UNAVAILABLE",
         "gap": {"status": "UNAVAILABLE", "reason": "no owner-set target"},
         "evidence": [{"claim": "target for revenue", "value": "UNAVAILABLE", "source": "no target on record"}],
         "recommended_actions": [], "blockers": [{"blocker": "no owner-set target", "source": "goal:2"}]},
    ]
    # §55 shared issues: a DUPLICATE_CAPABILITY (consolidation opp) + a SHARED_INFRA_FAILURE (a problem, NOT an opp)
    issues = [
        {"issue_type": "DUPLICATE_CAPABILITY", "companies": ["holding"], "shared_resource": "send_email",
         "recommended_actions": ["INVESTIGATE", "DEFER"], "confidence": "MEDIUM", "owner_required": False,
         "observed_facts": "capability 'send_email' provided by 2 AVAILABLE capabilities",
         "evidence": [{"capability_id": "cap-a", "provides": "send_email"}], "root_signature": "DUPLICATE_CAPABILITY:send_email"},
        {"issue_type": "SHARED_INFRA_FAILURE", "companies": ["a", "b"], "shared_resource": "railway",
         "recommended_actions": ["INVESTIGATE"], "confidence": "MEDIUM", "owner_required": True,
         "observed_facts": "2 companies failing on railway", "evidence": [{"company": "a"}],
         "root_signature": "SHARED_INFRA_FAILURE:railway"},
    ]
    # §18 problems: a fixable CODE_DEFECT (opp) + a HEALTH problem w/ only UNKNOWN evidence (dropped)
    problems = [
        {"problem_id": "p1", "company": "kai", "category": "CODE_DEFECT", "severity": "HIGH",
         "observed_facts": "certified suite 'x' failing", "confidence": "HIGH",
         "recommended_actions": ["INVESTIGATE", "PREPARE_FIX", "EVIDENCE"], "owner_required": False,
         "evidence": [{"suite_id": "x", "failed": 1}], "root_signature": "failing_suite:x"},
        {"problem_id": "p2", "company": "kai", "category": "DOCUMENTATION", "severity": "LOW",
         "observed_facts": "maybe stale doc", "confidence": "LOW",
         "recommended_actions": ["INVESTIGATE", "PREPARE_FIX"], "owner_required": False,
         "evidence": [{"source": "UNKNOWN"}], "root_signature": "doc:README.md"},     # UNKNOWN-only → dropped
    ]

    opps = detect_opportunities(goal_gaps=gaps, shared_issues=issues, problems=problems)
    cats = {o.category for o in opps}
    sigs = {o.signature for o in opps}

    # the three real opportunities are present; each cites real evidence
    assert cats == {"GROWTH", "CONSOLIDATION", "RELIABILITY"}, cats
    assert all(o.evidence and o.why_now and o.recommended_next_step for o in opps), opps

    # a UNAVAILABLE-verdict goal is NOT an opportunity (no measured gap)
    assert not any(o.signature == "opp:goal:2:revenue" for o in opps), "UNAVAILABLE goal must not surface"
    # a failure-class shared issue is a PROBLEM, never a consolidation opportunity
    assert not any("SHARED_INFRA_FAILURE" in o.signature for o in opps), "failure class is not an opportunity"
    # the UNKNOWN-only-evidence problem is DROPPED (no generic idea)
    assert "opp:doc:README.md" not in sigs, "UNKNOWN-only evidence must be dropped"

    growth = next(o for o in opps if o.category == "GROWTH")
    assert growth.confidence == "HIGH" and "60" in growth.why_now, growth
    cons = next(o for o in opps if o.category == "CONSOLIDATION")
    assert cons.signature == "opp:DUPLICATE_CAPABILITY:send_email", cons

    # ranked by confidence (HIGH before MEDIUM)
    confs = [_CONF_ORDER.get(o.confidence, 3) for o in opps]
    assert confs == sorted(confs), confs

    # dedup by signature: the same goal gap twice → one opportunity
    dup = detect_opportunities(goal_gaps=gaps + [gaps[0]], shared_issues=[], problems=[])
    assert len([o for o in dup if o.signature == "opp:goal:1:customers"]) == 1, dup

    # fully empty → [] (never raises, never fabricates)
    assert detect_opportunities(goal_gaps=[], shared_issues=[], problems=[]) == []

    print(f"opportunity_engine.demo OK — {len(opps)} opportunities across {len(cats)} categories "
          f"({', '.join(sorted(cats))}); UNAVAILABLE goal + failure-class + UNKNOWN-evidence all dropped; dedup verified")


if __name__ == "__main__":
    demo()
