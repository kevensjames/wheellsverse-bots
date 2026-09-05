"""§88 Challenge mode — anti-sycophancy / reviewer≠author guard. Zero-framework — mirrors
test_approval_dialog.py. The reviewer seam is a stub here (NO model runs). Run (from backend/):
    python3 -m app.services.holding.test_challenge
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import challenge as ch                # noqa: E402
from app.services.holding.challenge import (                    # noqa: E402
    challenge, refute_brief, CHALLENGE_RULES_VERSION, REFUTED, UPHELD, INSUFFICIENT_EVIDENCE,
    REJECTED_SYCOPHANTIC, REJECTED_MALFORMED, REJECTED_UNSOURCED)
from app.services.capability import coding                      # noqa: E402

REC = {"id": "rec-1", "author": "kai-planner",
       "claim": "Migrate SOL's queue to Redis Streams to cut p95 latency",
       "rationale": "Redis Streams removes the polling loop; the polling loop is the p95 driver",
       "evidence": [{"source": "log_inspect:sol-worker", "freshness": "FRESH", "note": "poll interval 500ms"}]}


def _stub(reply):
    """A reviewer seam that returns a fixed reply and counts calls (bounded: exactly one call)."""
    calls = []
    def reviewer(brief):
        calls.append(brief); return reply
    reviewer.calls = calls
    return reviewer


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    # ── reviewer≠author is the ONE shared rule ─────────────────────────────────────────────────────
    r = _stub({"stance": "AGREE"})
    try:
        challenge(REC, reviewer=r, reviewer_id="kai-planner"); ok = False
    except ValueError:
        ok = True
    ck("author challenging its own recommendation -> ValueError, reviewer never invoked", ok and r.calls == [])
    try:
        challenge(REC, reviewer=r, reviewer_id=""); ok = False
    except ValueError:
        ok = True
    ck("empty reviewer identity -> ValueError (fail closed)", ok)
    ck("identity rule IS capability.coding.assert_independent_reviewer (no second copy)",
       ch.assert_independent_reviewer is coding.assert_independent_reviewer)

    # ── the brief tells the reviewer to REFUTE ────────────────────────────────────────────────────
    brief = refute_brief(REC)
    ck("brief instructs REFUTE + forbids restating/unsourced numbers; deterministic",
       "REFUTE" in brief["instruction"] and "Restating" in brief["instruction"]
       and "cannot source" in brief["instruction"] and refute_brief(REC) == brief
       and brief["rules_version"] == CHALLENGE_RULES_VERSION == "1.0.0")

    # ── a bad recommendation is refuted WITH counter-evidence ─────────────────────────────────────
    r = _stub({"stance": "REFUTE",
               "argument": "The p95 driver is the DB lock wait, not polling; the poll loop is idle-cheap.",
               "counter_evidence": [{"source": "log_inspect:sol-db", "freshness": "FRESH", "note": "lock waits"},
                                    {"source": "kpi_history:sol.p95", "timestamp": "2026-09-01"}]})
    v = challenge(REC, reviewer=r, reviewer_id="reviewer-model-b")
    ck("REFUTE with sourced counter-evidence -> REFUTED, counter-evidence returned, quality graded HIGH",
       v["outcome"] == REFUTED and len(v["counter_evidence"]) == 2 and v["counter_evidence_quality"] == "HIGH")
    ck("advisory: KAI (caller) is final_decision_by; reviewer recorded; exactly ONE reviewer call (§79)",
       v["advisory"] is True and "KAI" in v["final_decision_by"] and v["reviewer"] == "reviewer-model-b"
       and v["author"] == "kai-planner" and len(r.calls) == 1 and r.calls[0] == brief)
    ck("REFUTE without a sourced counter -> INSUFFICIENT_EVIDENCE (an opinion is not a challenge)",
       challenge(REC, reviewer=_stub({"stance": "REFUTE", "argument": "I doubt it.",
                                      "counter_evidence": [{"note": "gut feel"}, {"source": "UNKNOWN"}]}),
                 reviewer_id="b")["outcome"] == INSUFFICIENT_EVIDENCE)

    # ── sycophancy is rejected mechanically ───────────────────────────────────────────────────────
    syc = challenge(REC, reviewer=_stub({"stance": "AGREE",
                                         "argument": "Yes — migrate SOL's queue to Redis Streams to cut p95 latency."}),
                    reviewer_id="b")
    ck("AGREE that restates the claim with no independent check -> REJECTED_SYCOPHANTIC",
       syc["outcome"] == REJECTED_SYCOPHANTIC and any("independent" in f for f in syc["flags"]))
    syc2 = challenge(REC, reviewer=_stub({"stance": "AGREE",
                                          "argument": "Great plan: migrate SOL's queue to Redis Streams, "
                                                      "removes the polling loop, cuts p95 latency.",
                                          "checks": [{"source": "kpi_history:sol.p95"}]}),
                     reviewer_id="b")
    ck("AGREE with a check but an argument that merely restates the claim -> REJECTED_SYCOPHANTIC",
       syc2["outcome"] == REJECTED_SYCOPHANTIC and any("restates" in f for f in syc2["flags"]))
    up = challenge(REC, reviewer=_stub({"stance": "AGREE",
                                        "argument": "Independently sampled worker traces; blocking time sits "
                                                    "inside the consumer wait, so streaming removes it.",
                                        "checks": [{"source": "log_inspect:sol-worker-traces", "freshness": "FRESH"},
                                                   {"source": "repo_inspect:sol/worker.py", "timestamp": "2026-09-01"}]}),
                   reviewer_id="b")
    ck("AGREE with independent sourced checks and its own reasoning -> UPHELD (agreement is allowed, sycophancy is not)",
       up["outcome"] == UPHELD and up["counter_evidence_quality"] == "HIGH" and len(up["checks"]) == 2)

    # ── no invented numbers (§0 #16-19) ───────────────────────────────────────────────────────────
    un = challenge(REC, reviewer=_stub({"stance": "REFUTE", "argument": "Polling is only 12% of p95.",
                                        "counter_evidence": [{"source": "log_inspect:sol-db"}]}),
                   reviewer_id="b")
    ck("a number in the argument that appears in no evidence -> REJECTED_UNSOURCED",
       un["outcome"] == REJECTED_UNSOURCED and "12%" in un["flags"][0])
    un2 = challenge(REC, reviewer=_stub({"stance": "REFUTE", "argument": "Polling is only 12% of p95.",
                                         "counter_evidence": [{"note": "12% from memory"}]}),
                    reviewer_id="b")
    ck("an UNSOURCED counter-evidence item cannot vouch for that number", un2["outcome"] == REJECTED_UNSOURCED)
    ok_num = challenge(REC, reviewer=_stub({"stance": "REFUTE", "argument": "Polling is only 12% of p95.",
                                            "counter_evidence": [{"source": "kpi_history:sol.p95", "share": "12%"}]}),
                       reviewer_id="b")
    ck("the same number carried by a SOURCED item is accepted", ok_num["outcome"] == REFUTED)
    ck("a number already in the claim's own evidence (500ms) is not 'invented'",
       challenge(REC, reviewer=_stub({"stance": "REFUTE", "argument": "500ms polling is not the p95 driver.",
                                      "counter_evidence": [{"source": "log_inspect:sol-db"}]}),
                 reviewer_id="b")["outcome"] == REFUTED)

    # ── malformed / bounded ───────────────────────────────────────────────────────────────────────
    ck("stance missing or unknown -> REJECTED_MALFORMED",
       challenge(REC, reviewer=_stub({"stance": "MAYBE"}), reviewer_id="b")["outcome"] == REJECTED_MALFORMED
       and challenge(REC, reviewer=_stub("nope"), reviewer_id="b")["outcome"] == REJECTED_MALFORMED)
    ck("INSUFFICIENT_EVIDENCE stance passes through as INSUFFICIENT_EVIDENCE",
       challenge(REC, reviewer=_stub({"stance": "INSUFFICIENT_EVIDENCE", "argument": "cannot verify"}),
                 reviewer_id="b")["outcome"] == INSUFFICIENT_EVIDENCE)
    ck("deterministic: same recommendation + same reply -> identical verdict",
       challenge(REC, reviewer=_stub({"stance": "AGREE"}), reviewer_id="b")
       == challenge(REC, reviewer=_stub({"stance": "AGREE"}), reviewer_id="b"))
    src = Path(ch.__file__).read_text()
    ck("module runs no model and executes nothing (reviewer is injected; no brain/subprocess/http import)",
       all(t not in src for t in ("import subprocess", "import requests", "httpx", "capability.brain", "nai_brain")))

    n = len(res); ok = sum(res)
    print(f"\nCHALLENGE MODE (§88) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
