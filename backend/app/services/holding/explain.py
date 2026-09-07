"""§87 self-explanation — explain a recommendation / priority / problem / proposal / goal-gap from its
OBSERVABLE inputs only: facts + policy applied + priority calculation (the ONE §22 ladder via
``priorities.rank_key``) + evidence refs + alternatives + uncertainty.

NO hidden chain-of-thought (§87/§0 #16-19): every line of an explanation is a real field of the item
being explained, a named policy rule that observably fired on that field, or the deterministic
``rank_key`` arithmetic. Nothing is narrated by an LLM, no number is invented, and any hidden-reasoning
key that arrives on the input (the §61 ``timeline.is_cot_key`` token rule) is STRIPPED before explanation
and reported as stripped — the output never carries it. Unknown → UNKNOWN/UNAVAILABLE, never guessed.

CONSOLIDATION: composes ``priorities.rank_key``/``LADDER`` (§22), ``health_score.evidence_quality``
(§58) and ``timeline.is_cot_key``/``_contains_cot`` (§61) — no second ranker, scorer, or CoT filter.
Pure/deterministic; testable as a plain ``python3`` script (mirrors test_registry.py).
"""
from __future__ import annotations

from app.services.holding.priorities import LADDER, rank_key
from app.services.holding.health_score import evidence_quality
from app.services.holding.timeline import is_cot_key, _contains_cot

EXPLAIN_VERSION = "1.0.0"
UNKNOWN, UNAVAILABLE = "UNKNOWN", "UNAVAILABLE"
_PLACEHOLDER = (UNKNOWN, UNAVAILABLE, "", None)     # tuple: membership must not crash on an unhashable value
# Evidence keys that name a real reference (the shapes the holding streams emit — mirrors health_score._source_of).
_REF_KEYS = ("source", "source_type", "source_key", "evidence_ref", "event_id", "audit_id",
             "correlation_id", "mission_id", "job_id")
# Fallback rung map used by rank_key when an item carries no explicit rung (kept in sync by the test).
_SEVERITY_RUNG_NOTE = "rung derived from severity by priorities.rank_key (no explicit rung on the item)"


def _strip_cot(obj):
    """Return a copy of ``obj`` with every hidden-reasoning key removed (recursively) + the keys found.
    Fail-closed: lists and nested dicts are walked fully; the key rule is timeline.is_cot_key (tokens)."""
    found: list[str] = []
    def walk(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if is_cot_key(k):
                    found.append(str(k)); continue
                out[k] = walk(v)
            return out
        if isinstance(o, (list, tuple)):
            return [walk(x) for x in o]
        return o
    return walk(obj), sorted(set(found))


def _kind(item: dict) -> str:
    """Deterministic subject kind from the item's OBSERVABLE shape (no guessing beyond field presence)."""
    if "gap" in item and "verdict" in item:
        return "goal_gap"
    if "problem_id" in item or ("root_signature" in item and "observed_facts" in item):
        return "problem"
    if "source_key" in item or ("status" in item and isinstance(item.get("action"), dict)):
        return "proposal"
    # priorities.derive_priorities emits {severity, rung, title, source, [entity], [detail]} (+ rank once
    # ranked); a severity-only owner action carries none of the ladder/signal keys → recommendation.
    if "rung" in item or "rank" in item or "detail" in item:
        return "priority"
    return "recommendation"


def _ref_of(e) -> str | None:
    if not isinstance(e, dict):
        return str(e) if e not in _PLACEHOLDER else None
    for k in _REF_KEYS:
        v = e.get(k)
        if v not in _PLACEHOLDER:
            return f"{k}:{v}" if k != "source" else str(v)
    return None


def _facts(item: dict, kind: str) -> list[dict]:
    """Observable inputs only: each fact is (claim, value, source) read straight off the item."""
    src = item.get("source") or item.get("source_key") or item.get("data_source") or UNKNOWN
    facts = []
    for key in ("title", "observed_facts", "objective", "metric", "severity", "category", "entity",
                "company", "status", "verdict", "confidence", "first_seen", "last_seen", "owner_required",
                "detail", "impact"):
        if key in item and item[key] not in (None, ""):
            facts.append({"claim": key, "value": item[key], "source": src if key not in ("impact",) else
                          "DERIVED from category (holding_problems._CATEGORY_META)"})
    if kind == "goal_gap":
        for e in item.get("evidence") or []:
            if isinstance(e, dict):
                facts.append({"claim": e.get("claim", "evidence"), "value": e.get("value", UNAVAILABLE),
                              "source": e.get("source", UNKNOWN)})
        gap = item.get("gap") or {}
        if isinstance(gap, dict):        # the recorded gap, verbatim — never projected or recomputed
            facts.append({"claim": "gap", "value": gap, "source": gap.get("source", UNKNOWN)})
    return facts


def _policies(item: dict, kind: str, prio: dict, facts: list[dict]) -> list[dict]:
    """The named rules that OBSERVABLY fired on this item — each cites the module that holds the rule."""
    out = [{"policy": "§22 single prioritization ladder", "ref": "priorities.rank_key / LADDER",
            "applied_because": f"placed on rung '{prio['rung']}' ({prio['rung_position']}), "
                               f"severity {prio['severity']} → rank_key {prio['rank_key']}"}]
    if item.get("owner_required") is True:
        out.append({"policy": "§18 owner-required escalation", "ref": "holding_problems._CATEGORY_META / CRITICAL",
                    "applied_because": "the item's category baseline or CRITICAL severity requires an owner decision"})
    if kind == "proposal":
        out.append({"policy": "§0 #11 owner-only decision", "ref": "proposals_store.decide",
                    "applied_because": f"proposal status '{item.get('status', UNKNOWN)}' — the owner approves/rejects; KAI never self-approves"})
    if kind == "goal_gap":
        tgt = next((e for e in item.get("evidence") or [] if isinstance(e, dict) and str(e.get("claim", "")).startswith("target")), None)
        if tgt is not None and tgt.get("value") == UNAVAILABLE:
            out.append({"policy": "§81 / §0 #19 no invented target", "ref": "goal_registry.normalize_target",
                        "applied_because": "no owner-set, sourced target → the gap is UNAVAILABLE, not estimated"})
        if item.get("verdict") == UNAVAILABLE:
            out.append({"policy": "§82 deterministic gap only from real numbers", "ref": "goal_registry.analyze_gap",
                        "applied_because": (item.get("gap") or {}).get("reason", "target or current not numeric/available")})
    if any(f["value"] in (UNKNOWN, UNAVAILABLE) for f in facts) or item.get("confidence") in (UNKNOWN, "LOW"):
        out.append({"policy": "§0 #16-19 zero-fabrication", "ref": "registry.report_value / digital_twin.fact",
                    "applied_because": "at least one input is UNKNOWN/UNAVAILABLE — it is reported as such, never filled in"})
    if kind == "problem" and item.get("possible_causes"):
        out.append({"policy": "§18 causes are plural hypotheses", "ref": "holding_problems._mk",
                    "applied_because": f"{len(item['possible_causes'])} candidate cause(s) listed — no single confirmed root cause"})
    return out


def _priority(item: dict) -> dict:
    """The §22 calculation, shown: rank_key tuple + ladder rung/position + how the rung was obtained."""
    rk = rank_key(item)
    rung = LADDER[rk[0]]
    explicit = item.get("rung") in LADDER
    return {"rank_key": list(rk), "rung": rung, "rung_position": f"{rk[0] + 1} of {len(LADDER)}",
            "severity": item.get("severity") or item.get("priority_name") or "LOW",
            "derivation": "explicit rung on the item" if explicit else _SEVERITY_RUNG_NOTE,
            "ladder": list(LADDER), "ranker": "priorities.rank_key"}


def _alternatives(item: dict, kind: str) -> list[dict]:
    """Alternatives RECORDED on the item (hypotheses, other actions, blockers) — none are invented."""
    out = []
    for c in item.get("possible_causes") or []:
        out.append({"type": "alternative_hypothesis", "text": str(c), "source": "holding_problems.possible_causes"})
    acts = item.get("recommended_actions") or []
    for i, a in enumerate(acts):
        text = a.get("action") if isinstance(a, dict) else str(a)
        out.append({"type": "recommended" if i == 0 else "alternative_action", "text": text,
                    "source": (a.get("source") if isinstance(a, dict) else None) or "item.recommended_actions"})
    for b in item.get("blockers") or []:
        out.append({"type": "blocker", "text": b.get("blocker") if isinstance(b, dict) else str(b),
                    "source": (b.get("source") if isinstance(b, dict) else None) or "item.blockers"})
    if kind == "proposal" and item.get("status") == "proposed":
        out.append({"type": "alternative_action", "text": "reject this proposal (owner decision)", "source": "proposals_store.decide"})
    return out


def explain(item) -> dict:
    """§87: explain ONE holding item from its observable inputs. Deterministic; same item → same output.
    Accepts a dict or an object with ``as_dict()`` (HoldingProblem, Goal, …)."""
    raw = item.as_dict() if hasattr(item, "as_dict") else dict(item or {})
    clean, stripped = _strip_cot(raw)
    kind = _kind(clean)
    facts = _facts(clean, kind)
    prio = _priority(clean)
    evidence = [e for e in (clean.get("evidence") or []) if isinstance(e, dict)]
    refs = [r for r in (_ref_of(e) for e in evidence) if r]
    top = clean.get("source") or clean.get("source_key")
    if top and top not in _PLACEHOLDER and top not in refs:
        refs.insert(0, str(top))
    unknown_fields = sorted(k for k, v in clean.items() if v in (UNKNOWN, UNAVAILABLE))
    quality = evidence_quality(evidence) if evidence else ("MEDIUM" if refs else "LOW")
    result = {
        "version": EXPLAIN_VERSION,
        "subject": {"kind": kind,
                    "id": clean.get("problem_id") or clean.get("id") or clean.get("goal_id")
                          or clean.get("mission_id") or clean.get("source_key") or UNKNOWN,
                    "title": clean.get("title") or clean.get("observed_facts") or clean.get("objective")
                             or clean.get("metric") or UNKNOWN},
        "facts": facts,
        "policy_applied": _policies(clean, kind, prio, facts),
        "priority": prio,
        "evidence_refs": refs or [UNAVAILABLE],
        "alternatives": _alternatives(clean, kind),
        "uncertainty": {"confidence": clean.get("confidence") or UNKNOWN,
                        "evidence_quality": quality,
                        "unknown_fields": unknown_fields,
                        "caveat": ("no evidence references on record — treat as unverified" if not refs
                                   else "explanation covers observable inputs only; nothing beyond them is claimed")},
        "stripped_hidden_fields": stripped,
    }
    result["hidden_reasoning_exposed"] = _contains_cot(result)     # the attestation IS the scan, not a constant
    if result["hidden_reasoning_exposed"]:
        raise ValueError("§87 invariant violated: the explanation carries a hidden-reasoning key")   # fail closed
    return result


if __name__ == "__main__":
    from app.services.holding.test_explain import run
    raise SystemExit(0 if run() else 1)
