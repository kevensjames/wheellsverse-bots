"""§80 goals-vs-reality improvement cycle — ONE bounded pass guard. Zero-framework (mirrors test_registry.py).
Gaps come from the REAL goal_registry.analyze_all (injected goals + current source); eval snapshots from the REAL
eval_harness.evaluate. Run (from backend/):  python3 -m app.services.holding.test_improvement_cycle
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import improvement_cycle as ic                      # noqa: E402
from app.services.holding.improvement_cycle import run_pass, candidates_from_gaps, candidates_from_eval, IMPROVEMENT_CYCLE_VERSION  # noqa: E402
from app.services.holding import goal_registry, eval_harness                  # noqa: E402
from app.services.holding.goal_registry import analyze_all                    # noqa: E402
from app.services.holding.eval_harness import evaluate, compare, METRIC_KEYS, UNAVAILABLE   # noqa: E402
from app.services.holding.priorities import rank_key, LADDER                  # noqa: E402
from app.services.holding.explain import explain                              # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────────
GOALS = [
    {"id": "g-cust", "company": "sol", "metric": "customers", "direction": "increase", "target": 100, "target_source": "owner:2026-08-01"},
    {"id": "g-mrr", "company": "sol", "metric": "mrr", "direction": "increase"},                       # no owner target
    {"id": "g-lat", "company": "kai", "metric": "latency_ms", "direction": "decrease", "target": 500, "target_source": "owner:2026-08-01"},
]
_CUR = {("sol", "customers"): (40, "registry:sol.customers (operator-confirmed)"),
        ("kai", "latency_ms"): (300, "monitor:kai.latency")}


def cur(company, metric):
    return _CUR.get((company, metric), (None, "registry: REQUIRES_OPERATOR_CONFIRMATION"))


GAPS = analyze_all(goals=GOALS, current_source=cur)                            # the REAL §82 output shape
AUDIT = [   # governance.audit_log shape
    {"ts": "2026-09-01T10:02:00+00:00", "action": "merge", "actor": "worker-x", "destructive": True, "approved": False,
     "success": False, "duration_ms": None},
    {"ts": "2026-09-01T10:03:00+00:00", "action": "read", "actor": "kai", "destructive": False, "approved": True,
     "success": True, "duration_ms": 80},
]
CYCLES = [{"cycle_id": "cy-1", "completed_at": "2026-09-01T09:00:00+00:00", "auto_actions_failed": 2, "duration_ms": 1200}]
NOW = evaluate(audit=AUDIT, cycles=CYCLES)                                    # jobs/missions/proposals NOT connected
PREV = evaluate(audit=[AUDIT[1]], cycles=[{**CYCLES[0], "auto_actions_failed": 0, "completed_at": "2026-08-31T09:00:00+00:00"}])
CLEAN = evaluate(audit=[AUDIT[1]], cycles=[{**CYCLES[0], "auto_actions_failed": 0}])


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    out = run_pass(gaps=GAPS, eval_now=NOW, eval_prev=PREV)
    cands = out["candidates"]
    by_kind = {k: [c for c in cands if c["kind"] == k] for k in ("goal_gap", "eval_alarm", "eval_regression")}

    # ── ONE bounded pass: deterministic, versioned, never a loop, never executes ──────────────────
    ck("same inputs -> byte-identical pass, versioned", run_pass(gaps=GAPS, eval_now=NOW, eval_prev=PREV) == out
       and out["version"] == IMPROVEMENT_CYCLE_VERSION == "1.0.0")
    ck("bounded=True, passes=1, loop=False, executes=False; the final decision is named as KAI coordinator + owner (§0 #11/§165)",
       out["bounded"] is True and out["passes"] == 1 and out["loop"] is False and out["executes"] is False
       and "owner" in out["final_decision_by"] and "coordinator" in out["final_decision_by"]
       and all(c["executes"] is False for c in cands))
    src = Path(ic.__file__).read_text()
    ck("run_pass never re-invokes itself: defined once, called once (by run_live_pass) — no sleep / while / thread / scheduler",
       src.count("run_pass(") == 2 and src.count("run_live_pass(") == 1
       and all(t not in src for t in ("sleep", "while ", "threading", "asyncio", "schedule", "Timer", "cron")))
    calls = {"gaps": 0, "eval": 0, "analyze_all": 0, "evaluate": 0}
    _g, _e = ic.candidates_from_gaps, ic.candidates_from_eval
    _aa, _ev = goal_registry.analyze_all, eval_harness.evaluate
    try:
        ic.candidates_from_gaps = lambda gaps: calls.__setitem__("gaps", calls["gaps"] + 1) or _g(gaps)
        ic.candidates_from_eval = lambda now, prev=None: calls.__setitem__("eval", calls["eval"] + 1) or _e(now, prev)
        run_pass(gaps=GAPS, eval_now=NOW, eval_prev=PREV)
        one_pass = dict(calls)
        goal_registry.analyze_all = lambda *a, **k: calls.__setitem__("analyze_all", calls["analyze_all"] + 1) or GAPS
        eval_harness.evaluate = lambda **k: calls.__setitem__("evaluate", calls["evaluate"] + 1) or NOW
        live = ic.run_live_pass(eval_prev=PREV)      # its ONE run_pass adds exactly one more sweep of each
    finally:
        ic.candidates_from_gaps, ic.candidates_from_eval = _g, _e
        goal_registry.analyze_all, eval_harness.evaluate = _aa, _ev
    ck("one pass = exactly one gap sweep + one eval sweep; run_live_pass = exactly one analyze_all + one evaluate",
       one_pass == {"gaps": 1, "eval": 1, "analyze_all": 0, "evaluate": 0}
       and calls == {"gaps": 2, "eval": 2, "analyze_all": 1, "evaluate": 1} and live["candidates"] == cands)

    # ── gaps -> candidates: only from real numbers/blockers, never invented work ──────────────────
    gg = {c["source"]: c for c in by_kind["goal_gap"]}
    ck("MET goal (latency 300 <= 500) yields NO candidate — nothing to improve is never busy-work",
       not any("g-lat" in s for s in gg) and out["goals_reviewed"] == 3)
    open_c = gg["goal_registry.analyze_gap:goal:g-cust"]
    ck("OPEN gap -> roadmap/MEDIUM candidate carrying the recorded numbers (40 vs 100, 60 to go) and the gap's own evidence + actions",
       open_c["rung"] == "roadmap" and open_c["severity"] == "MEDIUM" and "40 vs target 100" in open_c["title"] and "60" in open_c["title"]
       and open_c["evidence"] == GAPS[0]["evidence"] + GAPS[0]["blockers"]
       and open_c["recommended_actions"] == GAPS[0]["recommended_actions"] and open_c["entity"] == "sol"
       and open_c["detail"]["verdict"] == "GAP")
    un_c = gg["goal_registry.analyze_gap:goal:g-mrr"]
    ck("UNAVAILABLE gap -> speculative/LOW 'cannot be evaluated' candidate citing the blocker (wire the source / set the target)",
       un_c["rung"] == "speculative" and un_c["severity"] == "LOW" and "cannot be evaluated" in un_c["title"]
       and "no owner-set target" in un_c["title"]
       and any(e.get("blocker", "").startswith("no owner-set target") for e in un_c["evidence"])
       and any("define a target" in a["action"] for a in un_c["recommended_actions"]))
    ck("no candidate number is invented: every numeric in a gap title is on the gap record",
       all(f"{x:g}" in open_c["title"] for x in (GAPS[0]["gap"]["current"], GAPS[0]["gap"]["target"], GAPS[0]["gap"]["remaining_to_target"]))
       and candidates_from_gaps([{"verdict": "MET"}, {"verdict": "nonsense"}, None, "x"]) == [])

    # ── eval -> candidates: only MEASURED metrics; UNAVAILABLE -> unmeasured, no candidate ───────
    al = {c["source"].split(":")[1].split(" ")[0]: c for c in by_kind["eval_alarm"]}
    ck("security_violations=1 -> CRITICAL safety_security alarm; regressions=1 -> HIGH reliability alarm; evidence = the metric value + n",
       al["security_violations"]["rung"] == "safety_security" and al["security_violations"]["severity"] == "CRITICAL"
       and al["regressions"]["rung"] == "reliability" and al["regressions"]["severity"] == "HIGH"
       and al["security_violations"]["evidence"][0]["value"] == 1 and al["security_violations"]["evidence"][0]["n"] == 2)
    ck("metrics with no connected source are listed as unmeasured and yield NO candidate",
       set(out["unmeasured"]) == {m for m in METRIC_KEYS if m not in ("latency", "reliability", "regressions", "security_violations")}
       and not any(c["source"].startswith("eval_harness:cost") for c in cands))
    nothing = run_pass(gaps=[], eval_now=evaluate())
    ck("nothing connected -> all 11 unmeasured, zero candidates, no_change=True, eval_as_of UNAVAILABLE",
       set(nothing["unmeasured"]) == set(METRIC_KEYS) and nothing["candidates"] == [] and nothing["no_change"] is True
       and nothing["eval_as_of"] == UNAVAILABLE)
    ck("a clean eval + only MET goals -> no candidates (no busy-work)",
       run_pass(gaps=[GAPS[2]], eval_now=CLEAN)["no_change"] is True)

    # ── comparison: eval_harness.compare is the ONE delta; only REGRESSED yields a candidate ───────
    cmp_ = compare(PREV, NOW)
    regressed = [d["metric"] for d in cmp_["deltas"] if d["verdict"] == "REGRESSED"]
    ck("comparison == eval_harness.compare(prev, now); one reliability/MEDIUM candidate per REGRESSED metric, citing both snapshots",
       out["comparison"] == cmp_ and cmp_["comparable"] is True and regressed
       and sorted(c["source"].split(":")[1] for c in by_kind["eval_regression"]) == sorted(regressed)
       and all(c["rung"] == "reliability" and c["severity"] == "MEDIUM" and len(c["evidence"]) == 2 for c in by_kind["eval_regression"]))
    ck("no previous snapshot -> not comparable, no regression candidates; version mismatch -> NOT_COMPARABLE (never fake progress)",
       run_pass(gaps=[], eval_now=NOW)["comparison"] == {"comparable": False, "reason": "no previous snapshot"}
       and not [c for c in run_pass(gaps=[], eval_now=NOW)["candidates"] if c["kind"] == "eval_regression"]
       and "NOT_COMPARABLE" in run_pass(gaps=[], eval_now=NOW, eval_prev={**PREV, "version": "0.9.0"})["comparison"]["reason"])

    # ── ranked by THE §22 ladder; evidence-backed only ───────────────────────────────────────────
    ck("candidates are sorted by priorities.rank_key (safety_security first), ranks 1..n, ranker named",
       [rank_key(c) for c in cands] == sorted(rank_key(c) for c in cands) and [c["rank"] for c in cands] == list(range(1, len(cands) + 1))
       and cands[0]["rung"] == "safety_security" and out["ranker"] == "priorities.rank_key"
       and all(c["rung"] in LADDER for c in cands))
    ck("every ranked candidate is evidence-backed (>= 1 real cited source; §58 quality MEDIUM/HIGH) — none dropped here",
       all(c["evidence_quality"] in ("MEDIUM", "HIGH") and any(e.get("source") for e in c["evidence"]) for c in cands)
       and out["dropped_no_evidence"] == [])
    bare = {"goal_id": "g-x", "company": "x", "metric": "m", "verdict": "GAP", "gap": {"current": 1, "target": 2, "remaining_to_target": 1},
            "evidence": [], "blockers": [], "recommended_actions": []}
    ph = {**bare, "goal_id": "g-y", "evidence": [{"source": "UNKNOWN"}, {"claim": "c", "value": UNAVAILABLE}]}
    dropped = run_pass(gaps=[bare, ph, GAPS[0]], eval_now=evaluate())
    ck("a candidate without evidence, or with placeholder-only evidence, is DROPPED (reported, never ranked)",
       [c["source"] for c in dropped["candidates"]] == ["goal_registry.analyze_gap:goal:g-cust"]
       and len(dropped["dropped_no_evidence"]) == 2 and all("m on x" in t for t in dropped["dropped_no_evidence"]))

    # ── §87 composition: every candidate explains from its observable inputs with the same rank ──
    ck("explain(candidate).priority.rank_key == rank_key(candidate) for every candidate (one ladder end-to-end)",
       all(explain(c)["priority"]["rank_key"] == list(rank_key(c)) and explain(c)["hidden_reasoning_exposed"] is False for c in cands))

    # ── live pass over the real readers (DB-less here: every source fails soft) ──────────────────
    lv = ic.run_live_pass()
    ck("run_live_pass(): one bounded pass over the real goal store + real feeds, honest when nothing is connected",
       lv["bounded"] is True and lv["passes"] == 1 and lv["executes"] is False and isinstance(lv["candidates"], list))

    # ── consolidation + purity ────────────────────────────────────────────────────────────────────
    ck("composes goal_registry.analyze_all, eval_harness.evaluate/compare/collect_sources, priorities.rank_key, health_score.evidence_quality",
       all(s in src for s in ("from app.services.holding.goal_registry import analyze_all",
                              "from app.services.holding.eval_harness import evaluate, collect_sources",
                              "from app.services.holding.eval_harness import compare",
                              "from app.services.holding.priorities import rank_key",
                              "from app.services.holding.health_score import evidence_quality")))
    ck("no LLM / network / clock — a pure function of the pass inputs",
       all(t not in src for t in ("datetime.now", "time.time", "openai", "ollama", "httpx", "requests", "subprocess",
                                  "capability.brain", "nai_brain")))

    n = len(res); ok = sum(res)
    print(f"\nIMPROVEMENT CYCLE (§80) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
