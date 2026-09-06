"""§80 goals-vs-reality improvement cycle — ONE BOUNDED PASS, event-driven, never a loop.

Assembles the pieces that already exist: §81/§82 ``goal_registry.analyze_all`` (owner-set goals vs the
live twin, deterministic + cited) and the §34 ``eval_harness`` snapshot (+ optional ``compare`` against a
previous snapshot) → ranked, evidence-backed improvement candidates in the SAME item shape the §22
``priorities`` ladder ranks (severity / rung / title / source / evidence), sorted by the ONE
``priorities.rank_key``. Evidence quality is ``health_score.evidence_quality`` (§58).

Zero-fabrication (§0 #16-19): a goal whose gap is UNAVAILABLE yields only a "wire the source / set the
target" candidate carrying that blocker's citation; an UNAVAILABLE eval metric yields NO candidate (it is
listed under ``unmeasured``). No LLM, no invented number. §79: ``run_pass`` is called by an event (a
cycle tick / owner request) and returns — it arms nothing and repeats nothing. §0 #11/§165: the
output is a ranked proposal set for KAI-the-coordinator and the owner; nothing here executes.
Pure over injected inputs; ``run_live_pass`` is the only storage touch. Testable as a plain ``python3``
script (mirrors test_registry.py).
"""
from __future__ import annotations

from app.services.holding.eval_harness import compare, UNAVAILABLE
from app.services.holding.health_score import evidence_quality
from app.services.holding.priorities import rank_key

IMPROVEMENT_CYCLE_VERSION = "1.0.0"
# Versioned metric → (ladder rung, severity) for a current-value alarm; only these two metrics carry a
# "> 0 is a problem" semantic on their own (the rest are judged by IMPROVED/REGRESSED trend).
_METRIC_ALARM = {"security_violations": ("safety_security", "CRITICAL"), "regressions": ("reliability", "HIGH")}
_REGRESSION_RUNG = ("reliability", "MEDIUM")
_GAP_RUNG = {"GAP": ("roadmap", "MEDIUM"), UNAVAILABLE: ("speculative", "LOW")}


def _candidate(*, rung, severity, title, source, evidence, actions, kind, entity=None, detail=None) -> dict:
    ev = [e for e in (evidence or []) if isinstance(e, dict)]
    c = {"kind": kind, "rung": rung, "severity": severity, "title": title, "source": source,
         "evidence": ev, "evidence_quality": evidence_quality(ev),
         "recommended_actions": list(actions or []), "executes": False}
    if entity:
        c["entity"] = entity
    if detail is not None:
        c["detail"] = detail
    return c


def candidates_from_gaps(gaps: list) -> list:
    out = []
    for g in gaps or []:
        if not isinstance(g, dict) or g.get("verdict") not in _GAP_RUNG:
            continue                                   # MET → nothing to improve; never invent work
        rung, sev = _GAP_RUNG[g["verdict"]]
        gap = g.get("gap") or {}
        if g["verdict"] == "GAP":       # numbers as recorded on the gap; :g is goal_registry's own rendering
            title = (f"{g.get('metric')} on {g.get('company')}: {gap.get('current'):g} vs target "
                     f"{gap.get('target'):g} ({gap.get('remaining_to_target'):g} to go)")
        else:
            title = (f"{g.get('metric')} on {g.get('company')} cannot be evaluated — "
                     f"{gap.get('reason', 'target or current UNAVAILABLE')}")
        out.append(_candidate(rung=rung, severity=sev, title=title, kind="goal_gap",
                              source=f"goal_registry.analyze_gap:goal:{g.get('goal_id')}",
                              evidence=(g.get("evidence") or []) + (g.get("blockers") or []),
                              actions=g.get("recommended_actions"), entity=g.get("company"),
                              detail={"verdict": g["verdict"], "gap": gap}))
    return out


def candidates_from_eval(eval_now: dict, eval_prev: dict | None = None) -> tuple[list, list, dict]:
    """(candidates, unmeasured metric keys, comparison). Only MEASURED metrics can produce a candidate."""
    out, unmeasured = [], []
    metrics = {m["metric"]: m for m in (eval_now or {}).get("metrics", []) if isinstance(m, dict)}
    as_of = (eval_now or {}).get("as_of", UNAVAILABLE)
    for key, m in metrics.items():
        if m.get("status") == UNAVAILABLE or m.get("value") is None:
            unmeasured.append(key); continue
        if key in _METRIC_ALARM and m["value"] > 0:
            rung, sev = _METRIC_ALARM[key]
            out.append(_candidate(rung=rung, severity=sev, kind="eval_alarm",
                                  title=f"{key} = {m['value']} ({m.get('detail')})",
                                  source=f"eval_harness:{key} as_of {as_of}",
                                  evidence=[{"claim": key, "value": m["value"], "source": f"eval_harness.{m.get('source')}",
                                             "n": m.get("n")}],
                                  actions=[{"action": f"investigate the {m.get('n')} record(s) behind {key}",
                                            "source": f"eval_harness:{key}"}]))
    comparison = compare(eval_prev, eval_now) if eval_prev is not None else {"comparable": False, "reason": "no previous snapshot"}
    if comparison.get("comparable"):
        for d in comparison.get("deltas", []):
            if d.get("verdict") == "REGRESSED":
                rung, sev = _REGRESSION_RUNG
                out.append(_candidate(rung=rung, severity=sev, kind="eval_regression",
                                      title=f"{d['metric']} regressed {d['prev']} → {d['cur']}",
                                      source=f"eval_harness.compare:{d['metric']}",
                                      evidence=[{"claim": f"{d['metric']} prev", "value": d["prev"], "source": f"eval snapshot {comparison.get('from')}"},
                                                {"claim": f"{d['metric']} cur", "value": d["cur"], "source": f"eval snapshot {comparison.get('to')}"}],
                                      actions=[{"action": f"find what changed between {comparison.get('from')} and {comparison.get('to')} for {d['metric']}",
                                                "source": "eval_harness.compare"}]))
    return out, sorted(unmeasured), comparison


def run_pass(*, gaps, eval_now, eval_prev=None, source_failures=None) -> dict:
    """ONE bounded §80 pass: goals-vs-reality + eval → ranked candidates. Returns; never loops or re-arms.
    ``source_failures`` = [{source, error}] the caller could not read; they are reported and no_change is
    NOT claimed over them (an unread store has not proven "nothing to improve")."""
    failures = [f for f in (source_failures or []) if isinstance(f, dict)]
    cands = candidates_from_gaps(gaps)
    ev, unmeasured, comparison = candidates_from_eval(eval_now, eval_prev)
    cands += ev
    # §0 #16-19: a candidate with no REAL cited source (§58 evidence_quality LOW) is dropped, not ranked.
    dropped = [c["title"] for c in cands if c["evidence_quality"] == "LOW"]
    cands = [c for c in cands if c["evidence_quality"] != "LOW"]
    cands.sort(key=rank_key)                                    # THE §22 ladder — no second ranker
    ranked = [dict(rank=i + 1, **c) for i, c in enumerate(cands)]
    return {"version": IMPROVEMENT_CYCLE_VERSION, "bounded": True, "passes": 1, "loop": False,
            "goals_reviewed": len([g for g in (gaps or []) if isinstance(g, dict)]),
            "eval_as_of": (eval_now or {}).get("as_of", UNAVAILABLE),
            "eval_version": (eval_now or {}).get("version", UNAVAILABLE),
            "comparison": comparison, "unmeasured": unmeasured,
            "candidates": ranked, "dropped_no_evidence": dropped, "source_failures": failures,
            "no_change": not ranked and not failures,
            "ranker": "priorities.rank_key", "executes": False,
            "final_decision_by": "KAI coordinator + owner (§0 #11/§165) — candidates are proposals, not actions"}


def run_live_pass(*, eval_prev=None, limit: int = 500) -> dict:
    """The live pass: goal_registry.analyze_all() + eval_harness.evaluate(**collect_sources()). One call
    each (bounded). A store that cannot be read is REPORTED under source_failures (and no_change is not
    claimed) — never erased into an empty goal list / an all-UNAVAILABLE snapshot that looks like calm."""
    from app.services.holding.goal_registry import analyze_all
    from app.services.holding.eval_harness import evaluate, collect_sources
    failures = []
    try:
        gaps = analyze_all()
    except Exception as e:   # noqa: BLE001
        gaps = []
        failures.append({"source": "goal_registry.analyze_all", "error": f"{type(e).__name__}: {e}"[:300]})
    try:
        feeds = collect_sources(limit)
    except Exception as e:   # noqa: BLE001
        feeds = {}
        failures.append({"source": "eval_harness.collect_sources", "error": f"{type(e).__name__}: {e}"[:300]})
    snap = evaluate(**feeds)
    down = sorted(k for k, v in (snap.get("sources") or {}).items() if v == "NOT_CONNECTED")
    if down:
        failures.append({"source": "eval_harness.collect_sources", "error": f"NOT_CONNECTED: {', '.join(down)}"})
    return run_pass(gaps=gaps, eval_now=snap, eval_prev=eval_prev, source_failures=failures)


if __name__ == "__main__":
    from app.services.holding.test_improvement_cycle import run
    raise SystemExit(0 if run() else 1)
