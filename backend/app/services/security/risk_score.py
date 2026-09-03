"""Security risk score (arch §26) — deterministic, versioned, explainable. NO LLM.

Pure integer arithmetic. Same inputs -> identical score, every time. Each factor may be:
  - an int count (or bool)   -> counted at its fixed weight, with an explaining component
  - a NOT_CONNECTED-style    -> contributes 0 AND appends an explicit caveat component so the
    string marker              score is never SILENTLY understated (arch §16/§49). The caveat
                               names the source, e.g. "aikido NOT_CONNECTED — criticals not counted".

The numeric score is NEVER invented by an LLM (§26): the Brain may narrate `components`,
but the number comes only from here.
"""
from __future__ import annotations

RISK_FORMULA_VERSION = "1.0.0"

# Fixed weights (points per unit). Versioned with RISK_FORMULA_VERSION — bump the version if these change.
# (key, weight, singular_label, source_name)  — source_name is used in the NOT_CONNECTED caveat.
_FACTORS = [
    ("criticals",        12, "critical vulnerability",     "aikido"),
    ("highs",             5, "high vulnerability",         "aikido"),
    ("internet_exposed",  8, "internet-exposed service",   "graph/config"),
    ("active_incidents", 10, "active incident",            "incident_engine"),
    ("auth_anomalies",    6, "auth anomaly",               "monitor/audit"),
    ("audit_gaps",        4, "audit gap",                  "monitor"),
    ("stale_findings",    2, "stale finding",              "aikido"),
]

_BANDS = (  # (upper_inclusive, band); first match wins
    (19, "LOW"),
    (49, "MODERATE"),
    (79, "HIGH"),
    (100, "CRITICAL"),
)


def _band(score: int) -> str:
    for upper, name in _BANDS:
        if score <= upper:
            return name
    return "CRITICAL"


def compute_risk(*, criticals=0, highs=0, internet_exposed=0, active_incidents=0,
                 auth_anomalies=0, audit_gaps=0, stale_findings=0) -> dict:
    """Deterministic 0-100 risk score + band + explaining components. Kwargs only.

    Each argument is either an int/bool count or a string marker (e.g. "NOT_CONNECTED",
    "UNAVAILABLE", "UNKNOWN") meaning the source is not connected — which contributes 0 and
    appends a caveat component. Numeric component points sum to the pre-clamp total; the score
    is that total clamped to [0, 100]."""
    values = {
        "criticals": criticals, "highs": highs, "internet_exposed": internet_exposed,
        "active_incidents": active_incidents, "auth_anomalies": auth_anomalies,
        "audit_gaps": audit_gaps, "stale_findings": stale_findings,
    }
    components: list[dict] = []
    total = 0
    for key, weight, label, source in _FACTORS:
        v = values[key]
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, int):
            if v < 0:
                v = 0  # a count is never negative; clamp defensively rather than trust caller
            if v > 0:
                pts = v * weight
                total += pts
                components.append({"reason": f"{v} × {label}", "points": pts})
        else:
            # non-int -> a NOT_CONNECTED/UNKNOWN/UNAVAILABLE source marker: count 0, but SAY SO.
            components.append({"reason": f"{source} {v} — {key} not counted", "points": 0})
    score = max(0, min(100, total))
    return {"score": score, "band": _band(score), "version": RISK_FORMULA_VERSION,
            "components": components}


def demo() -> None:
    # determinism: identical inputs -> byte-identical result
    kw = dict(criticals=1, highs=2, internet_exposed=1, active_incidents=0,
              auth_anomalies=1, audit_gaps=0, stale_findings=0)
    a = compute_risk(**kw)
    b = compute_risk(**kw)
    assert a == b, (a, b)
    # 1*12 + 2*5 + 1*8 + 1*6 = 36
    assert a["score"] == 36, a["score"]
    assert a["band"] == "MODERATE", a["band"]
    assert a["version"] == "1.0.0"
    # numeric component points sum to the (unclamped) total
    assert sum(c["points"] for c in a["components"]) == 36
    # NOT_CONNECTED input contributes 0 AND appends an explicit caveat naming the source
    nc = compute_risk(criticals="NOT_CONNECTED", highs=3)
    assert nc["score"] == 15, nc["score"]                 # only 3*5, criticals not counted
    caveats = [c for c in nc["components"] if c["points"] == 0 and "not counted" in c["reason"]]
    assert any("aikido NOT_CONNECTED" in c["reason"] and "criticals" in c["reason"] for c in caveats), nc
    # clamp: absurd input stays <= 100, band CRITICAL
    hi = compute_risk(criticals=50)
    assert hi["score"] == 100 and hi["band"] == "CRITICAL"
    # all-zero -> 0 / LOW, no components
    z = compute_risk()
    assert z["score"] == 0 and z["band"] == "LOW" and z["components"] == []
    print("risk_score.demo OK — deterministic, versioned, NOT_CONNECTED caveat, clamped, explainable")


if __name__ == "__main__":
    demo()
