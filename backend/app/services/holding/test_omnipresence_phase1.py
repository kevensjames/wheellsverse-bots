"""KAI Omnipresence Phase 1 checks (§1/§62/§63/§99, §16, §14, §15). Zero-framework — mirrors
test_registry.py. Run (from backend/):
    python3 -m app.services.holding.test_omnipresence_phase1
or:
    python3 backend/app/services/holding/test_omnipresence_phase1.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding.self_model import OperationalSelfModel, _derive_limitations, UNAVAILABLE  # noqa: E402
from app.services.holding.digital_twin import HoldingDigitalTwin, fact  # noqa: E402
from app.services.holding import registry as reg  # noqa: E402
from app.services.holding.knowledge_index import SystemKnowledgeIndex, FOUND, UNKNOWN  # noqa: E402

res = []
def ck(n, ok):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


# ── §1/§62 self-model exposes the FULL field set, each REAL/DERIVED/UNAVAILABLE, none fabricated ──
def _sm(**flags):
    fl = {"MONEY_MODE": "MOCK", "KAI_A2_EXECUTION_ENABLED": False, "HOLDING_AUTONOMY_ENABLED": False}
    fl.update(flags)
    return OperationalSelfModel(
        software_version="cyber-v1", environment="production", owner_principal="owner",
        sources={
            "capabilities": lambda: {"available": ["kai-memory"], "available_count": 5,
                                     "unavailable_count": 121, "catalog_total": 126},
            "companies": lambda: ["sol", "kai"],
            "autonomy": lambda: {"overall": "AUTONOMOUS_READ_ONLY"},
            "workers": lambda: [{"worker_id": "w1", "online": True}],
            "open_proposals": lambda: [{"id": 7, "entity_id": "sol", "title": "Approve staging cert"}],
            "deployment": lambda: {"shas": {"app_a": "abc123def456", "app_b": "abc123def456",
                                            "staging": "UNKNOWN"}, "environment": "production",
                                   "this_app_sha": "abc123def456", "money_mode": "MOCK"},
            "flags": lambda: fl,
            "finance_available": lambda: False,
            "coding_workers": lambda: [{"id": "jcode", "name": "jcode", "available": False, "state": "DISCOVERED"}],
            "self_last_verified": lambda: "2026-08-30",
        })

_SNAP = _sm().snapshot()
_FIELD62 = ("identity", "system_role", "software_version", "production_sha", "staging_sha",
            "environment", "runtime", "model", "model_provider", "available_capability_count",
            "workers_online", "workers_known", "current_attention", "autonomy_class",
            "known_limitations", "last_verified", "claims_consciousness")
ck("§62 self-model snapshot exposes the full field set", all(k in _SNAP for k in _FIELD62))
ck("§62 production SHA is REAL from deployment truth", _SNAP["production_sha"] == "abc123def456")
ck("§62 staging SHA honestly UNAVAILABLE (none deployed)", _SNAP["staging_sha"] == UNAVAILABLE)
ck("§62 runtime is REAL/measured (Python version)", _SNAP["runtime"].startswith("Python "))
ck("§62 model/latency UNAVAILABLE when not measurable (never fabricated)",
   _SNAP["model"] == UNAVAILABLE and _SNAP["model_provider"] == UNAVAILABLE and _SNAP["model_latency_ms"] == UNAVAILABLE)
ck("§62 last_verified DERIVED from registry (real date)", _SNAP["last_verified"] == "2026-08-30")
ck("§62 autonomy_class DERIVED from flags (A0/A1 auto, A2 disabled)",
   "A0_OBSERVE" in _SNAP["autonomy_class"] and "A2_PREPARE DISABLED" in _SNAP["autonomy_class"])
ck("§62 current_attention is bounded live text (not hidden CoT)",
   isinstance(_SNAP["current_attention"], str) and "AUTONOMOUS_READ_ONLY" in _SNAP["current_attention"])

# ── §1/§141 consciousness invariant ──
ck("§141 claims_consciousness is False", _SNAP["claims_consciousness"] is False)
ck("§141 describe() disclaims consciousness", "no claim to consciousness" in _sm().describe().lower())

# ── §63/§99 limitations LIVE-DERIVED (flip a flag → text changes), not static ──
_lim_a2_off = _sm(KAI_A2_EXECUTION_ENABLED=False).snapshot()["known_limitations"]
_lim_a2_on = _sm(KAI_A2_EXECUTION_ENABLED=True).snapshot()["known_limitations"]
ck("§63 A2-disabled limitation present when flag OFF",
   any("A2 execution is DISABLED" in l for l in _lim_a2_off))
ck("§63 limitations CHANGE when the flag flips (not static)",
   _lim_a2_off != _lim_a2_on and not any("A2 execution is DISABLED" in l for l in _lim_a2_on))
ck("§99 self-approval limitation is a permanent invariant (always present)",
   any("cannot self-approve" in l.lower() for l in _lim_a2_off) and any("cannot self-approve" in l.lower() for l in _lim_a2_on))
ck("§63 auth-blocked coding worker surfaces as a live limitation",
   any("jcode" in l and "not AVAILABLE" in l for l in _lim_a2_off))
# no-live-finance limitation reflects the real absence of a wired feed; flips when a feed is present
_lim_fin = _derive_limitations({"MONEY_MODE": "MOCK"}, finance_available=True, coding_workers=[])
ck("§63 finance limitation drops when a live feed is wired",
   any("No live finance" in l for l in _lim_a2_off) and not any("No live finance" in l for l in _lim_fin))

# ── §16 digital_twin.fact() carries confidence + evidence_ref, additively/back-compat ──
_f_bare = fact("v", "src", observed_at="2026-09-01", fact_type="money", today="2026-09-01")
ck("§16 fact() with no confidence/evidence_ref keeps the original 5-key shape (back-compat)",
   set(_f_bare) == {"value", "source", "observed_at", "freshness", "status"})
_f_full = fact("v", "src", confidence="VERIFIED", evidence_ref="holding.registry:sol.revenue_metrics")
ck("§16 fact() carries confidence + evidence_ref when supplied",
   _f_full.get("confidence") == "VERIFIED" and _f_full.get("evidence_ref") == "holding.registry:sol.revenue_metrics")


def _ent(eid, name, etype="product", **kw):
    base = dict(entity_id=eid, brand_name=name, entity_type=etype, stage="live", operational_status="LIVE",
                products=[], repository=None, deployment=None, domains=[], integrations=[], kpis=[],
                incidents=[], risks=[], last_verified_at="2026-08-30")
    base.update(kw)
    return SimpleNamespace(**base)


def _money(mapping):
    def rv(eid, fld):
        v = mapping.get((eid, fld))
        return (v, "source: test · confidence=VERIFIED") if v is not None else (None, f"{fld} REQUIRES_OPERATOR_CONFIRMATION")
    return rv


def _twin(entities, *, money=None, today="2026-09-01", hierarchy=None):
    return HoldingDigitalTwin(observed_at=today + "T08:00:00", today=today, sources={
        "entities": lambda: entities, "report_value": _money(money or {}),
        "open_proposals": lambda: [], "priorities": lambda: [], "autonomy": lambda: {"overall": "OK"},
        "workers": lambda: [], "capabilities": lambda: {"available_count": 5, "catalog_total": 126},
        "hierarchy": lambda: (hierarchy if hierarchy is not None else []),
    })

_st = _twin([_ent("sol", "SOL")], money={("sol", "revenue_metrics"): "Pre-revenue (confirmed)"}).companies()[0]
ck("§16 twin money fact carries confidence (parsed from provenance)",
   _st.revenue_summary.get("confidence") == "VERIFIED")
ck("§16 twin money fact carries evidence_ref pointing at the source record",
   _st.revenue_summary.get("evidence_ref") == "holding.registry:sol.revenue_metrics")
_st_un = _twin([_ent("sol", "SOL")]).companies()[0]
ck("§16 un-sourced money fact confidence UNAVAILABLE (never fabricated)",
   _st_un.revenue_summary.get("confidence") == UNAVAILABLE and _st_un.revenue_summary["value"] == UNAVAILABLE)

# ── portfolio_view() still works (not broken by the additive changes) ──
_pv = _twin([_ent("sol", "SOL"), _ent("nex", "Nexora", incidents=["vuln"])]).portfolio_view()
ck("portfolio_view() still works after additive changes",
   set(_pv) == {"needs_attention", "healthy", "blocked", "owner_work_count", "kai_work_count"}
   and "sol" in _pv["healthy"] and "nex" in _pv["needs_attention"])

# ── §14 explicit hierarchy edges present ──
_edges = reg.hierarchy_edges()
_pairs = {(e["parent"], e["child"]) for e in _edges}
ck("§14 registry emits explicit parent→child edges", len(_edges) > 0
   and all(set(e) >= {"parent", "child", "relation", "child_name"} for e in _edges))
ck("§14 multi-level chain is explicit (sol→solcircle→holdings)",
   ("solcircle", "sol") in _pairs and ("wheellsverse_holdings", "solcircle") in _pairs)
ck("§14 SOLCIRCLE (an LLC) 'operates' SOL, holding 'owns'",
   any(e["parent"] == "solcircle" and e["child"] == "sol" and e["relation"] == "operates" for e in _edges))
_snap_h = _twin([_ent("sol", "SOL")], hierarchy=[{"parent": "wheellsverse_holdings", "child": "sol",
                                                  "relation": "owns", "child_name": "SOL"}]).snapshot()
ck("§14 twin snapshot surfaces the hierarchy edges", _snap_h.get("hierarchy") and _snap_h["hierarchy"][0]["child"] == "sol")

# ── §15 SystemKnowledgeIndex answers a dependency question WITH cited evidence, honest UNKNOWN otherwise ──
_ents = [_ent("sol", "SOL", integrations=["Stripe Checkout (Go Premium)", "Dwolla (MOCK)"]),
         _ent("siteboost", "SiteBoost", integrations=["Stripe", "Resend"]),
         _ent("kai", "KAI", integrations=["OpenAI (prod)"])]
_ki = SystemKnowledgeIndex(today="2026-09-01", sources={
    "entities": lambda: _ents, "report_value": _money({}),
    "deployment": lambda: {"this_app_sha": "abc", "features": [], "drift": {"state": "IN_SYNC"}},
    "kg_neighbors": lambda label, direction, relation: [],
    "capabilities": lambda: {"available": [], "catalog_total": 126},
})
_dep = _ki.services_depending_on("stripe")
ck("§15 dependency question answered FROM real evidence (FOUND)",
   _dep["status"] == FOUND and "sol" in _dep["answer"] and "siteboost" in _dep["answer"])
ck("§15 dependency answer carries CITED evidence_refs",
   any(r == "holding.registry:sol.integrations" for r in _dep["evidence_refs"]) and _dep["evidence_refs"])
ck("§15 dependency answer carries a freshness state (§16)",
   _dep["freshness"] in ("FRESH", "STALE", "UNKNOWN"))
_ask = _ki.ask("which service depends on stripe?")
ck("§15 ask() routes a dependency question deterministically", _ask["status"] == FOUND and _ask["evidence_refs"])
_dep_none = _ki.services_depending_on("kafka")
ck("§15 unsupported dependency → honest UNKNOWN (no fabrication)",
   _dep_none["status"] == UNKNOWN and _dep_none["evidence_refs"] == [])
_ask_none = _ki.ask("what is the meaning of life?")
ck("§15 out-of-scope question → honest UNKNOWN", _ask_none["status"] == UNKNOWN)
_desc = _ki.ask("what does sol do?")
ck("§15 describe question answered with cited evidence", _desc["status"] == FOUND and _desc["evidence_refs"])

# ── §15 works over the REAL registry too (integration smoke, not just injected fakes) ──
_ki_real = SystemKnowledgeIndex(today="2026-09-03")
_real = _ki_real.services_depending_on("stripe")
ck("§15 real registry: Stripe dependents FOUND with evidence",
   _real["status"] == FOUND and _real["evidence_refs"])

n = len(res); ok = sum(res)
print(f"\nOMNIPRESENCE PHASE 1 TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
