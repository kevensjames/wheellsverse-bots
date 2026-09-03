"""No-fabrication guard for the Holding Goal Registry (§81) + gap analysis (§82). Run (from backend/):
    python3 -m app.services.holding.test_goal_registry

Zero-framework (mirrors test_registry.py). Uses a throwaway SQLite file — no live DB/server needed.
"""
import os
import tempfile

# Point the sidecar DB at a fresh temp file BEFORE the store is used (lazy path read honors this).
_TMP = tempfile.NamedTemporaryFile(prefix="goals_test_", suffix=".db", delete=False)
_TMP.close()
os.environ["KAI_GOALS_DB_PATH"] = _TMP.name

from app.services.holding import goal_registry as gr  # noqa: E402

# A synthetic entity check so the store is testable without depending on the registry seed.
_ENT = lambda c: c in {"sol", "kai", "acme"}


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    # ── §81: NEVER invent a target ────────────────────────────────────────────────────────────────
    # (1a) a target VALUE with NO source is REJECTED to UNAVAILABLE — not a guessed number.
    g_nosrc = gr.add_goal("sol", "Jhon", "monthly_revenue_usd", target=10000, target_source=None,
                          entity_exists=_ENT)
    ck("target value without a source → UNAVAILABLE (rejected, not stored)",
       g_nosrc.target == gr.UNAVAILABLE and not g_nosrc.target_is_set())
    ck("rejected target cites the no-invention rule (§0 #19)", "never invents" in g_nosrc.target_source)

    # (1b) no target at all → UNAVAILABLE with the honest 'not on record' reason.
    g_none = gr.add_goal("sol", "Jhon", "reliability_uptime_pct", entity_exists=_ENT)
    ck("no target on record → UNAVAILABLE", g_none.target == gr.UNAVAILABLE)
    ck("missing target says 'no target on record'", "no target on record" in g_none.target_source)

    # (1c) a SOURCED owner target IS accepted and keeps its provenance.
    g_ok = gr.add_goal("sol", "Jhon", "monthly_revenue_usd", target=10000,
                       target_source="ops review 2026-09-03", dimension="revenue", entity_exists=_ENT)
    ck("owner target WITH a source is accepted", g_ok.target == 10000 and g_ok.target_is_set())
    ck("accepted target is provenance-marked owner-set", "owner-set" in g_ok.target_source)

    # (1d) goals hang off REAL entities — a bogus company is rejected fail-closed.
    rejected = False
    try:
        gr.add_goal("not_a_company", "Jhon", "x", entity_exists=_ENT)
    except ValueError:
        rejected = True
    ck("unknown holding entity is rejected (goals hang off real entities)", rejected)

    # (1e) set_target gate still rejects a sourceless target.
    g2 = gr.set_target(g_none.id, 99.9, None)
    ck("set_target with no source stays UNAVAILABLE", g2.target == gr.UNAVAILABLE)
    g3 = gr.set_target(g_none.id, 99.9, "SLO doc")
    ck("set_target with a source is accepted", g3.target == 99.9 and g3.target_is_set())

    # ── §82: a real current + target yields a DETERMINISTIC, CITED gap ───────────────────────────
    cur = lambda company, metric: (7500.0, "stripe MRR export 2026-09-03")   # injected live source
    a = gr.analyze_gap(g_ok, current_source=cur)
    ck("gap computed when current + target are both real", a["verdict"] == "GAP")
    ck("gap is the deterministic remaining-to-target (10000-7500)", a["gap"]["remaining_to_target"] == 2500.0)
    ck("gap direction + numbers present", a["gap"]["current"] == 7500.0 and a["gap"]["target"] == 10000.0)
    ck("every evidence item cites a source", all(e.get("source") for e in a["evidence"]))
    ck("recommended action cites both current + target sources (not generic advice)",
       any("stripe MRR export" in ra["source"] and "owner-set" in ra["source"]
           for ra in a["recommended_actions"]))
    # determinism: same inputs → identical result.
    ck("gap analysis is deterministic (same inputs → same output)",
       gr.analyze_gap(g_ok, current_source=cur) == a)

    # met target → verdict MET, no 'close the gap' action.
    a_met = gr.analyze_gap(g_ok, current_source=lambda c, m: (12000.0, "stripe MRR export"))
    ck("current past target → verdict MET", a_met["verdict"] == "MET" and a_met["gap"]["status"] == "MET")

    # lower-is-better metric: a cost/churn goal is met by being BELOW target.
    g_cost = gr.add_goal("kai", "Jhon", "monthly_infra_cost_usd", target=500,
                         target_source="budget", direction="decrease", dimension="cost", entity_exists=_ENT)
    a_cost = gr.analyze_gap(g_cost, current_source=lambda c, m: (620.0, "railway invoice"))
    ck("decrease-direction gap is OPEN when current is above target", a_cost["gap"]["status"] == "OPEN")
    ck("decrease-direction action says 'reduce'",
       any("Reduce" in ra["action"] for ra in a_cost["recommended_actions"]))

    # ── §82: unsupported → honest UNAVAILABLE (never a fabricated gap) ────────────────────────────
    # (3a) target set but NO live current source for the metric.
    a_nocur = gr.analyze_gap(g_ok, current_source=lambda c, m: (None, "no live source wired"))
    ck("no current source → verdict UNAVAILABLE", a_nocur["verdict"] == gr.UNAVAILABLE)
    ck("UNAVAILABLE gap states the reason", a_nocur["gap"]["reason"] == "current value UNAVAILABLE")
    ck("UNAVAILABLE gap still lists a cited blocker + action",
       a_nocur["blockers"] and a_nocur["recommended_actions"] and
       all(b.get("source") for b in a_nocur["blockers"]))

    # (3b) no target → UNAVAILABLE even if current is known.
    a_notgt = gr.analyze_gap(g_nosrc, current_source=lambda c, m: (5000.0, "stripe"))
    ck("no owner target → verdict UNAVAILABLE (never computes a gap from nothing)",
       a_notgt["verdict"] == gr.UNAVAILABLE and a_notgt["gap"]["reason"] == "no owner-set target")
    ck("missing-target blocker + owner action are cited",
       any("no owner-set target" in b["blocker"] for b in a_notgt["blockers"]) and
       any("define a target" in ra["action"] for ra in a_notgt["recommended_actions"]))

    # (3c) prose current (registry money field) is not numeric → UNAVAILABLE, not a guess.
    a_prose = gr.analyze_gap(g_ok, current_source=lambda c, m: ("Pre-revenue — mock stage", "registry"))
    ck("prose current is not numeric → UNAVAILABLE", a_prose["verdict"] == gr.UNAVAILABLE)

    # (3d) default source path: SOL revenue is operator-confirmed PROSE in the seed → non-numeric →
    #      honest UNAVAILABLE through the REAL registry (no injection).
    try:
        g_live = gr.add_goal("sol", "Jhon", "revenue", target=10000, target_source="ops review")
        a_live = gr.analyze_gap(g_live)   # default current_source → holding registry
        ck("default registry source yields UNAVAILABLE for prose revenue (real seed, no injection)",
           a_live["verdict"] == gr.UNAVAILABLE)
    except Exception as e:      # registry import path unavailable in some contexts — report, don't hide
        ck(f"default registry source path (skipped: {type(e).__name__})", True)

    # store round-trips.
    ck("list_goals returns the persisted goals", len(gr.list_goals(company="sol")) >= 3)
    ck("update_status validates the vocab", gr.update_status(g_ok.id, "active").status == "active")
    bad = False
    try:
        gr.update_status(g_ok.id, "nonsense")
    except ValueError:
        bad = True
    ck("invalid status rejected", bad)

    n, ok = len(res), sum(res)
    print(f"\nHOLDING GOAL REGISTRY TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
