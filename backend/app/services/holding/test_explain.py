"""§87 self-explanation — observable-inputs-only / no-hidden-reasoning guard. Zero-framework (mirrors
test_registry.py). Fixtures are in the EXACT shapes the holding streams emit. Run (from backend/):
    python3 -m app.services.holding.test_explain
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import explain as ex                                  # noqa: E402
from app.services.holding.explain import explain, EXPLAIN_VERSION, UNKNOWN, UNAVAILABLE   # noqa: E402
from app.services.holding.priorities import rank_key, LADDER, _SEVERITY_RUNG   # noqa: E402
from app.services.holding.timeline import _COT_KEYS, _contains_cot, is_cot_key   # noqa: E402
from app.services.holding.health_score import evidence_quality                 # noqa: E402
from app.services.holding.holding_problems import _mk                          # noqa: E402

# ── fixtures in the emitted shapes ────────────────────────────────────────────────────────────────────
PRIORITY = {"rank": 1, "severity": "CRITICAL", "rung": "broken_prod", "title": "KAI: incident — App B 502",
            "source": "registry:kai.incidents", "entity": "kai"}                      # priorities.derive_priorities
OWNER_ACTION = {"severity": "HIGH", "title": "Rotate the API key", "source": "registry:kai.risks"}   # severity-only
PROPOSAL = {"id": 12, "source_key": "risk:kai:api-key", "severity": "HIGH", "entity": "kai",       # proposals_store
            "title": "Rotate the API key", "action": {"type": "CREATE_MISSION"}, "status": "proposed",
            "created_at": "2026-09-01 06:00:00+00:00"}
GAP_OPEN = {"goal_id": "g1", "company": "sol", "metric": "customers", "verdict": "GAP",            # goal_registry.analyze_gap
            "gap": {"status": "OPEN", "current": 40, "target": 100, "remaining_to_target": 60,
                    "source": "computed: current=registry:sol.customers · target=owner:2026-08-01"},
            "evidence": [{"claim": "target for customers", "value": 100, "source": "owner:2026-08-01"},
                         {"claim": "current customers", "value": 40, "source": "registry:sol.customers"}],
            "blockers": [],
            "recommended_actions": [{"action": "Increase customers on sol by 60", "source": "current=registry:sol.customers"}]}
GAP_UNAVAILABLE = {"goal_id": "g2", "company": "sol", "metric": "mrr", "verdict": UNAVAILABLE,
                   "gap": {"status": UNAVAILABLE, "reason": "no owner-set target", "source": "current=registry · target="},
                   "evidence": [{"claim": "target for mrr", "value": UNAVAILABLE, "source": "no target on record"},
                                {"claim": "current mrr", "value": UNAVAILABLE, "source": "registry:sol.revenue_metrics"}],
                   "blockers": [{"blocker": "no owner-set target for 'mrr' on sol", "source": "goal:g2.target"}],
                   "recommended_actions": [{"action": "Owner: define a target for 'mrr' on sol", "source": "goal:g2"}]}
PROBLEM = _mk(root_signature="health:app_b", company="kai", system="app_b", severity="CRITICAL", category="HEALTH",
              observed_facts="App B health probe HTTP 0", evidence=[{"source": "live-signal:appB_health", "value": "HTTP 0"}],
              confidence="HIGH", now="2026-09-01T10:00:00+00:00")                   # holding_problems.HoldingProblem
ITEMS = {"priority": PRIORITY, "recommendation": OWNER_ACTION, "proposal": PROPOSAL, "goal_gap": GAP_OPEN,
         "goal_gap_unavailable": GAP_UNAVAILABLE, "problem": PROBLEM}
_ATTEST = "hidden_reasoning_exposed"                 # the ONE boolean attestation (§17/§87 convention, attention_model)


def _keys(o, acc=None):
    acc = [] if acc is None else acc
    if isinstance(o, dict):
        for k, v in o.items():
            acc.append(str(k)); _keys(v, acc)
    elif isinstance(o, (list, tuple)):
        for x in o:
            _keys(x, acc)
    return acc


def _no_cot_field(out) -> bool:
    ks = _keys(out)
    banned = [k for k in ks if k != _ATTEST
              and (is_cot_key(k) or any(w in k.lower() for w in ("reasoning", "thought", "thinking", "monologue", "scratchpad")))]
    return not banned and not _contains_cot(out) and out.get(_ATTEST) is False


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    outs = {k: explain(v) for k, v in ITEMS.items()}
    raws = {k: (v.as_dict() if hasattr(v, "as_dict") else v) for k, v in ITEMS.items()}

    # ── deterministic + versioned ─────────────────────────────────────────────────────────────────
    ck("same item -> byte-identical explanation, versioned", explain(PRIORITY) == explain(PRIORITY)
       and all(o["version"] == EXPLAIN_VERSION == "1.0.0" for o in outs.values()))
    ck("output carries exactly the §87 fields (facts / policy / priority / evidence refs / alternatives / uncertainty)",
       all(set(o) == {"version", "subject", "facts", "policy_applied", "priority", "evidence_refs", "alternatives",
                      "uncertainty", "stripped_hidden_fields", _ATTEST} for o in outs.values()))
    ck("subject kind is derived from the item's observable shape",
       {k: o["subject"]["kind"] for k, o in outs.items()} ==
       {"priority": "priority", "recommendation": "recommendation", "proposal": "proposal", "goal_gap": "goal_gap",
        "goal_gap_unavailable": "goal_gap", "problem": "problem"})
    ck("accepts an object with as_dict() (HoldingProblem) and keys the subject by its real id",
       outs["problem"]["subject"]["id"] == PROBLEM.problem_id == "health:app_b")

    # ── §87 NO hidden reasoning: no CoT-like field anywhere, ever ─────────────────────────────────
    ck("no 'reasoning'/'thought'/CoT-like field on ANY explanation (only the False attestation)",
       all(_no_cot_field(o) for o in outs.values()))
    ck("§61 vocabulary is the ONE filter and covers the bare forms too",
       {"reasoning", "thought", "chain_of_thought", "thoughts"} <= set(_COT_KEYS) and all(is_cot_key(k) for k in _COT_KEYS))
    variants = {**PRIORITY, "reasoning_v2": "v2 steps", "llm_thoughts": "llm hmm", "cot_trace": "trace-1",
                "reasoning trace": "spaced", "detail": {"llmThoughts": "camel hmm", "http": 502}}
    v = explain(variants)
    ck("token rule: reasoning_v2 / llm_thoughts / cot_trace / 'reasoning trace' / llmThoughts are stripped (exact-match would have leaked them)",
       v["stripped_hidden_fields"] == sorted(["cot_trace", "llm_thoughts", "llmThoughts", "reasoning trace", "reasoning_v2"]) and _no_cot_field(v)
       and not any(s in json.dumps(v) for s in ("v2 steps", "llm hmm", "trace-1", "spaced", "camel hmm"))
       and next(f for f in v["facts"] if f["claim"] == "detail")["value"] == {"http": 502})
    _cc = ex._contains_cot
    try:
        ex._contains_cot = lambda o: True                # simulate the scan finding hidden reasoning in the OUTPUT
        try:
            explain(PRIORITY); leaked = "returned"
        except ValueError:
            leaked = "raised"
        except AssertionError:
            leaked = "assert"
    finally:
        ex._contains_cot = _cc
    ck("hidden_reasoning_exposed is the SCAN result and a positive scan RAISES ValueError (never a stripped assert, never returned)",
       leaked == "raised" and explain(PRIORITY)[_ATTEST] is False and "assert " not in Path(ex.__file__).read_text())
    # sentinel values: 'hidden-why' cannot collide with the mandated 'applied_because' policy key (line ~126)
    dirty = {**PRIORITY, "reasoning_trace": "step 1 ...", "detail": {"thoughts": "hmm", "reasoning": "hidden-why", "http": 502}}
    d = explain(dirty)
    ck("hidden-reasoning keys on the INPUT are stripped (recursively) and reported, never carried",
       d["stripped_hidden_fields"] == ["reasoning", "reasoning_trace", "thoughts"] and _no_cot_field(d)
       and "hmm" not in json.dumps(d) and "hidden-why" not in json.dumps(d)
       and next(f for f in d["facts"] if f["claim"] == "detail")["value"] == {"http": 502})

    # ── §22: the priority shown IS priorities.rank_key on the same record ─────────────────────────
    ck("priority.rank_key == priorities.rank_key(item) for every kind (no second ranker)",
       all(o["priority"]["rank_key"] == list(rank_key(raws[k])) for k, o in outs.items()))
    ck("priority.rung is the LADDER rung at rank_key[0] for every kind",
       all(LADDER.index(o["priority"]["rung"]) == rank_key(raws[k])[0] and o["priority"]["ranker"] == "priorities.rank_key"
           for k, o in outs.items()))
    ck("explicit rung on the item is reported as explicit; a severity-only item shows the derived rung (priorities._SEVERITY_RUNG)",
       outs["priority"]["priority"]["derivation"] == "explicit rung on the item"
       and outs["recommendation"]["priority"]["derivation"] == ex._SEVERITY_RUNG_NOTE
       and outs["recommendation"]["priority"]["rung"] == _SEVERITY_RUNG["HIGH"] == "reliability")
    ck("the ladder shown is THE ladder", all(o["priority"]["ladder"] == list(LADDER) for o in outs.values()))

    # ── facts are fields read straight off the item ───────────────────────────────────────────────
    def facts_observable(k):
        raw, o = raws[k], outs[k]
        allowed = set(raw) | {e.get("claim") for e in raw.get("evidence") or [] if isinstance(e, dict)} | {"gap"}
        return all(f["claim"] in allowed for f in o["facts"]) and \
            all(f["value"] == raw[f["claim"]] for f in o["facts"] if f["claim"] in raw)
    ck("every fact is (claim, value) copied from the item — nothing narrated", all(facts_observable(k) for k in ITEMS))
    ck("a DERIVED fact (problem impact from the category card) says so in its source",
       "DERIVED from category" in next(f["source"] for f in outs["problem"]["facts"] if f["claim"] == "impact"))
    ck("goal-gap facts carry the gap numbers as recorded (40 / 100 / 60), never recomputed",
       next(f for f in outs["goal_gap"]["facts"] if f["claim"] == "gap")["value"] == GAP_OPEN["gap"]
       and GAP_OPEN["gap"]["current"] == 40 and GAP_OPEN["gap"]["target"] == 100 and GAP_OPEN["gap"]["remaining_to_target"] == 60)

    # ── policy applied: named rules that OBSERVABLY fired, each citing its module ─────────────────
    def pol(k): return {p["policy"] for p in outs[k]["policy_applied"]}
    ck("every policy line names the module holding the rule",
       all(p["ref"] and "." in p["ref"] and p["applied_because"] for o in outs.values() for p in o["policy_applied"]))
    ck("§22 ladder policy is always present", all("§22 single prioritization ladder" in pol(k) for k in ITEMS))
    ck("proposal -> §0 #11 owner-only decision (KAI never self-approves)", "§0 #11 owner-only decision" in pol("proposal"))
    ck("CRITICAL problem -> §18 owner-required escalation + plural causes",
       {"§18 owner-required escalation", "§18 causes are plural hypotheses"} <= pol("problem"))
    ck("UNAVAILABLE gap -> §81 no-invented-target + §82 deterministic-gap-only policies",
       {"§81 / §0 #19 no invented target", "§82 deterministic gap only from real numbers"} <= pol("goal_gap_unavailable")
       and not ({"§81 / §0 #19 no invented target"} & pol("goal_gap")))
    ck("an UNKNOWN/UNAVAILABLE input fires the §0 #16-19 zero-fabrication policy",
       "§0 #16-19 zero-fabrication" in pol("goal_gap_unavailable") and "§0 #16-19 zero-fabrication" not in pol("priority"))

    # ── evidence refs + uncertainty come from the item's evidence[] via the §58 primitive ─────────
    ck("evidence refs are the real sources on the item (problem cites its live signal)",
       outs["problem"]["evidence_refs"] == ["live-signal:appB_health"]
       and outs["goal_gap"]["evidence_refs"] == ["owner:2026-08-01", "registry:sol.customers"])
    ck("evidence_quality is health_score.evidence_quality over the same evidence[] (no second scorer)",
       all(o["uncertainty"]["evidence_quality"] == evidence_quality(raws[k].get("evidence") or [])
           for k, o in outs.items() if raws[k].get("evidence")))
    bare = explain({"title": "no evidence at all", "severity": "LOW"})
    ck("no evidence + no source -> refs [UNAVAILABLE] + an explicit 'unverified' caveat, never a filled-in ref",
       bare["evidence_refs"] == [UNAVAILABLE] and "unverified" in bare["uncertainty"]["caveat"]
       and bare["uncertainty"]["evidence_quality"] == "LOW")
    unk = explain({**OWNER_ACTION, "confidence": UNKNOWN, "detail": UNAVAILABLE})
    ck("unknown_fields lists exactly the item's UNKNOWN/UNAVAILABLE fields",
       unk["uncertainty"]["unknown_fields"] == ["confidence", "detail"] and unk["uncertainty"]["confidence"] == UNKNOWN)

    # ── alternatives are RECORDED on the item, none invented ─────────────────────────────────────
    pr = raws["problem"]
    alts = outs["problem"]["alternatives"]
    ck("problem alternatives = its possible_causes (>=2 hypotheses) + recommended_actions, verbatim",
       [a["text"] for a in alts if a["type"] == "alternative_hypothesis"] == pr["possible_causes"]
       and len(pr["possible_causes"]) >= 2
       and [a["text"] for a in alts if a["type"] in ("recommended", "alternative_action")] == pr["recommended_actions"])
    ck("open proposal offers 'reject' as the owner's alternative; blockers are surfaced as blockers",
       any(a["type"] == "alternative_action" and "reject" in a["text"] for a in outs["proposal"]["alternatives"])
       and [a["text"] for a in outs["goal_gap_unavailable"]["alternatives"] if a["type"] == "blocker"]
       == ["no owner-set target for 'mrr' on sol"])
    ck("an item with nothing recorded has NO alternatives (none invented)", bare["alternatives"] == [])

    # ── robustness: unhashable observable values never crash the explanation ─────────────────────
    try:
        odd = explain({"severity": "LOW", "source": ["a", "b"], "evidence": [{"source": ["x"]}], "detail": {"k": [1, 2]}})
        ok_odd = odd["subject"]["kind"] == "priority" and _no_cot_field(odd)
    except Exception as e:      # noqa: BLE001
        ok_odd = False; print("       ", repr(e))
    ck("list-valued fields (unhashable) are explained, not crashed on", ok_odd)

    # ── consolidation + purity (source inspection) ────────────────────────────────────────────────
    src = Path(ex.__file__).read_text()
    ck("composes priorities.rank_key/LADDER, health_score.evidence_quality, timeline.is_cot_key/_contains_cot (no second CoT vocabulary here)",
       "from app.services.holding.priorities import LADDER, rank_key" in src
       and "from app.services.holding.health_score import evidence_quality" in src
       and "from app.services.holding.timeline import is_cot_key, _contains_cot" in src
       and "_COT_KEYS" not in src and "_COT_TOKENS" not in src)
    ck("no LLM / network / clock — a pure function of the item",
       all(t not in src for t in ("datetime.now", "time.time", "openai", "ollama", "httpx", "requests",
                                  "capability.brain", "nai_brain", "subprocess")))

    n = len(res); ok = sum(res)
    print(f"\nEXPLAIN (§87) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
