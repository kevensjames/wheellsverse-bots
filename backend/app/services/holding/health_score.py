"""§57 HoldingHealthScore + §58 evidence-quality — deterministic, versioned, explainable. NO LLM.

CLONES the ``services/security/risk_score.py`` pattern: a versioned pure-integer formula whose number
is NEVER invented by an LLM (§0 #16-19, §79). The Brain may narrate ``components``; the number comes
only from here, and identical inputs -> byte-identical result.

Difference from risk_score (which SUMS penalty points, higher = worse): health is a WEIGHTED AVERAGE
over ONLY the dimensions that have a real source, higher = healthier. A dimension with no real source
does NOT silently score healthy — it is dropped from BOTH the numerator and the denominator and
recorded as INSUFFICIENT_DATA (§57). If fewer than ``_MIN_MEASURABLE`` dimensions are measurable the
overall is "NO SCORE / INSUFFICIENT_DATA", never a fabricated number.

ponytail: known ceiling — "omit the gap" means an absent BAD signal (e.g. security NOT_CONNECTED)
raises the score vs a present bad one, because the score is only ever over what is proven. That is the
honest reading (score what you can measure); the gap is made loud via ``insufficient_data`` +
``measured_dimensions`` so the dashboard shows "no data", not a green check. Upgrade path: a "neutral
contribution" mode if the operator prefers unknowns to drag the score toward the middle.

Dimensions (§57) and the REAL source each expects (shapes are injected — this module reads no DB/net,
exactly like its risk_score sibling; wiring live sources into an endpoint is the router step):
  availability      registry/digital_twin probes (holding.signals) -> {"healthy": int, "total": int}
  security          security evidence_bus / security.overview counts -> {"high": int, "critical": int}
                    or a marker str ("NOT_CONNECTED"/"UNAVAILABLE") -> INSUFFICIENT_DATA (a missing
                    feed is NEVER read as "secure")
  deployment_health holding_deployment.compute_drift()["state"] -> "IN_SYNC"/"STAGING_BEHIND"/...
  mission_blockers  count of blocking HoldingProblems (owner_required/CRITICAL) -> int
  data_freshness    digital_twin fact freshness tally -> {"fresh": int, "stale": int}
  customer_impact   twin report_value(customers) -> UNAVAILABLE today -> INSUFFICIENT_DATA
  financial_status  twin report_value(finance)   -> UNAVAILABLE today -> INSUFFICIENT_DATA
"""
from __future__ import annotations

HEALTH_FORMULA_VERSION = "1.0.0"

INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
NO_SCORE = "NO SCORE / INSUFFICIENT_DATA"

# Below this many MEASURED dimensions we refuse to emit a number (§57: never a fake healthy score from
# one or two signals). With 7 dimensions and customer/financial UNAVAILABLE today, up to 5 are real.
_MIN_MEASURABLE = 3

# Per-dimension "bad-unit" caps used by the count->ratio scorers below (versioned with the formula).
_BLOCKER_CAP = 5           # this many blocking problems -> 0 health on this dimension
_SECURITY_CAP = 6          # high = 1 bad-unit, critical = 3 bad-units; this many bad-units -> 0 health
_CRITICAL_UNITS = 3


# ── per-dimension scorers: each maps a REAL input to (healthy_units, total_units, detail), or None ──
# None ⇒ no real source ⇒ INSUFFICIENT_DATA (dropped from num+denom, never scored healthy).
def _availability_units(v):
    if not isinstance(v, dict):
        return None
    total = _int(v.get("total"))
    if total <= 0:
        return None
    healthy = max(0, min(_int(v.get("healthy")), total))
    return (healthy, total, f"{healthy}/{total} services healthy")


def _security_units(v):
    if not isinstance(v, dict):
        return None                     # "NOT_CONNECTED"/marker/None -> absence of a feed != secure
    if "high" not in v and "critical" not in v:
        return None                     # empty/partial dict is not a connected feed -> INSUFFICIENT_DATA, never "secure" (§0#18)
    high = max(0, _int(v.get("high")))
    crit = max(0, _int(v.get("critical")))
    bad = min(_SECURITY_CAP, high + crit * _CRITICAL_UNITS)
    return (_SECURITY_CAP - bad, _SECURITY_CAP, f"{crit} critical / {high} high finding(s)")


def _deploy_units(v):
    m = {"IN_SYNC": (3, 3), "STAGING_BEHIND": (2, 3), "PRODUCTION_BEHIND": (1, 3), "BOTH_BEHIND": (0, 3)}
    if not isinstance(v, str) or v not in m:
        return None                     # "UNKNOWN"/None -> INSUFFICIENT_DATA (never guess deploy health)
    h, t = m[v]
    return (h, t, f"drift={v}")


def _blocker_units(v):
    if isinstance(v, bool) or not isinstance(v, int):
        return None                     # marker/None -> INSUFFICIENT_DATA (unmeasured != zero blockers)
    v = max(0, v)
    return (max(0, _BLOCKER_CAP - v), _BLOCKER_CAP, f"{v} blocking problem(s)")


def _freshness_units(v):
    if not isinstance(v, dict):
        return None
    fresh = max(0, _int(v.get("fresh")))
    stale = max(0, _int(v.get("stale")))
    total = fresh + stale
    if total <= 0:
        return None                     # nothing datable -> INSUFFICIENT_DATA
    return (fresh, total, f"{fresh}/{total} facts fresh")


def _ratio_or_none(v):
    """customer_impact / financial_status: only a real {"healthy","total"} ratio scores. The twin
    returns UNAVAILABLE for money/customers today, so any marker/None -> INSUFFICIENT_DATA by
    construction — never a fabricated healthy money/customer signal (§45/§46, §0 #16)."""
    if not isinstance(v, dict):
        return None
    total = _int(v.get("total"))
    if total <= 0:
        return None
    healthy = max(0, min(_int(v.get("healthy")), total))
    return (healthy, total, f"{healthy}/{total}")


def _int(x) -> int:
    return x if isinstance(x, int) and not isinstance(x, bool) else 0


# (key, weight, source_name, scorer). weight = max health points a dimension may contribute when a real
# source is present — the deterministic importance of each dimension, versioned with the formula.
# Weights sum to 100 (availability + security carry the most).
_DIMENSIONS = [
    ("availability",      25, "registry/digital_twin probes",   _availability_units),
    ("security",          20, "security evidence_bus",           _security_units),
    ("deployment_health", 15, "holding_deployment drift",        _deploy_units),
    ("mission_blockers",  15, "mission/holding_problems",        _blocker_units),
    ("data_freshness",    10, "digital_twin fact freshness",     _freshness_units),
    ("customer_impact",    8, "twin report_value (customers)",   _ratio_or_none),
    ("financial_status",   7, "twin report_value (finance)",     _ratio_or_none),
]

_BANDS = ((24, "CRITICAL"), (49, "AT_RISK"), (74, "FAIR"), (89, "GOOD"), (100, "HEALTHY"))


def _band(score: int) -> str:
    for upper, name in _BANDS:
        if score <= upper:
            return name
    return "HEALTHY"


def compute_health(*, availability=None, security=None, deployment_health=None,
                   mission_blockers=None, data_freshness=None, customer_impact=None,
                   financial_status=None, min_measurable: int = _MIN_MEASURABLE) -> dict:
    """Deterministic 0-100 holding health + band + per-dimension components. Kwargs only.

    Each argument is either a real source input (see the scorer for its shape) or a marker/None meaning
    the source is not connected — which is recorded INSUFFICIENT_DATA and EXCLUDED from the average
    (never counted as healthy). score = earned_points * 100 // measured_weight (pure integer). If fewer
    than ``min_measurable`` dimensions are measurable, score is NO_SCORE (never a fabricated number)."""
    min_measurable = max(_MIN_MEASURABLE, int(min_measurable))  # a caller can never weaken the NO_SCORE floor
    values = {"availability": availability, "security": security,
              "deployment_health": deployment_health, "mission_blockers": mission_blockers,
              "data_freshness": data_freshness, "customer_impact": customer_impact,
              "financial_status": financial_status}
    components: list[dict] = []
    earned_total = 0
    measured_weight = 0
    measured = 0
    insufficient: list[str] = []
    for key, weight, source, scorer in _DIMENSIONS:
        units = scorer(values[key])
        if units is None:
            components.append({"dimension": key, "status": INSUFFICIENT_DATA, "points": 0,
                               "max_points": weight,
                               "detail": f"{source}: no real source — not scored healthy"})
            insufficient.append(key)
            continue
        h, t, detail = units
        pts = weight * h // t           # pure integer, floor, deterministic; pts in [0, weight]
        earned_total += pts
        measured_weight += weight
        measured += 1
        components.append({"dimension": key, "status": "MEASURED", "points": pts,
                           "max_points": weight, "detail": detail})

    base = {"version": HEALTH_FORMULA_VERSION, "measured_dimensions": measured,
            "required_dimensions": min_measurable, "insufficient_data": insufficient,
            "components": components}
    if measured < min_measurable or measured_weight == 0:
        return {"score": NO_SCORE, "band": INSUFFICIENT_DATA, **base}
    score = earned_total * 100 // measured_weight       # normalize over ONLY measured weight
    return {"score": score, "band": _band(score), **base}


# ── §58 evidence-quality confidence — HIGH/MEDIUM/LOW from EXPLICIT evidence, NOT token probability ──
_PLACEHOLDER = ("UNKNOWN", "UNAVAILABLE", "", None)   # tuple: membership must not crash on an unhashable value


def _source_of(item: dict):
    """The one real source an evidence item names, or None if it is a placeholder. Handles the shapes
    the holding streams emit: {"source"/"source_type"/"source_key"/"evidence_ref": ...}, a security
    audit record ({"event_id": ...}), and a drift dict ({"state": ...})."""
    for k in ("source", "source_type", "source_key", "evidence_ref"):
        v = item.get(k)
        if v not in _PLACEHOLDER:
            return str(v)
    if item.get("event_id") not in _PLACEHOLDER:
        return f"audit:{item.get('event_id')}"
    if item.get("state") not in _PLACEHOLDER:
        return f"drift:{item.get('state')}"
    return None


def evidence_quality(evidence) -> str:
    """§58 evidence-quality: HIGH / MEDIUM / LOW from source COUNT + FRESHNESS + PROVENANCE — a
    deterministic property of the evidence[] itself, NOT an LLM token probability. Usable on any
    HoldingProblem / opportunity / recommendation's ``evidence`` list.

      - no evidence, or every item is an explicit UNKNOWN/UNAVAILABLE placeholder -> LOW
      - >= 2 DISTINCT real sources, none stale                                     -> HIGH
      - otherwise (one real source, or 2+ but something stale)                     -> MEDIUM

    Rationale: one cite is corroboration-of-one (MEDIUM); staleness caps at MEDIUM; only multiple
    independent, non-stale sources earn HIGH. No source ⇒ we cannot claim confidence ⇒ LOW."""
    items = [e for e in (evidence or []) if isinstance(e, dict)]
    sources = {s for s in (_source_of(e) for e in items) if s}
    if not sources:
        return "LOW"
    stale = any(e.get("freshness") == "STALE" for e in items)
    # HIGH requires >=2 DISTINCT sources that carry a real recency signal (explicit FRESH, or a
    # timestamp/observed_at = dated) and none stale. An ENTIRELY unknown-age source (no freshness AND
    # no timestamp) does NOT count toward HIGH, so two unknown-age cites can't overclaim → MEDIUM.
    def _dated(e):
        return e.get("freshness") == "FRESH" or bool(e.get("timestamp")) or bool(e.get("observed_at"))
    dated_sources = {_source_of(e) for e in items
                     if _dated(e) and e.get("freshness") != "STALE" and _source_of(e)}
    if len(dated_sources) >= 2 and not stale:
        return "HIGH"
    return "MEDIUM"


def demo() -> None:
    # determinism: identical inputs -> byte-identical result, versioned
    kw = dict(availability={"healthy": 3, "total": 3}, security={"high": 0, "critical": 0},
              deployment_health="IN_SYNC", mission_blockers=0, data_freshness={"fresh": 4, "stale": 0})
    a = compute_health(**kw)
    b = compute_health(**kw)
    assert a == b, (a, b)
    assert a["version"] == "1.0.0"
    assert a["score"] == 100 and a["band"] == "HEALTHY", a               # 5 measured, all perfect
    assert a["insufficient_data"] == ["customer_impact", "financial_status"], a  # money UNAVAILABLE today

    # a dimension with no source -> INSUFFICIENT_DATA, 0 points, dropped from the average (not healthy)
    nc = compute_health(**{**kw, "security": "NOT_CONNECTED"})
    sec = next(c for c in nc["components"] if c["dimension"] == "security")
    assert sec["status"] == INSUFFICIENT_DATA and sec["points"] == 0, sec
    assert "security" in nc["insufficient_data"] and nc["measured_dimensions"] == 4, nc

    # too few measurable dimensions -> NO SCORE (never a fabricated number)
    thin = compute_health(availability={"healthy": 2, "total": 2})
    assert thin["score"] == NO_SCORE and thin["band"] == INSUFFICIENT_DATA, thin

    # §58 evidence_quality: rich (2+ real, fresh) -> HIGH ; thin (none/placeholder) -> LOW
    assert evidence_quality([{"source": "live health probe", "freshness": "FRESH"},
                             {"event_id": "e1", "timestamp": "t"}]) == "HIGH"
    assert evidence_quality([]) == "LOW" and evidence_quality([{"source": "UNKNOWN"}]) == "LOW"
    print("health_score.demo OK — deterministic, versioned, INSUFFICIENT_DATA not-healthy, "
          "NO_SCORE floor, evidence_quality HIGH/LOW")


if __name__ == "__main__":
    demo()
