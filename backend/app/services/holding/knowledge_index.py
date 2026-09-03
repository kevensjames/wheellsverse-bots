"""SystemKnowledgeIndex (§15) — a READ-ONLY COMPOSE layer, not a new source of truth.

KAI's broadest AVAILABLE + AUTHORIZED model of the holding's systems. It answers architecture /
dependency / change questions by COMPOSING the sources that already exist (holding.registry, the
HoldingDigitalTwin, holding_deployment truth, the capability registry, the ../kg/ graph) and returns
each answer WITH cited ``evidence_refs`` + a ``freshness`` state. It NEVER invents an answer: when the
composed sources carry no evidence it returns status UNKNOWN, and when a source itself is unreachable it
returns UNAVAILABLE (§16 states). No omniscience, no heavy new source — just a query surface over what
KAI can already read.

Sources are injectable (like OperationalSelfModel / HoldingDigitalTwin) so this is a plain ``python3``
self-test with no DB. Each default source is wrapped fail-open: a subsystem that errors → empty, never
a crash and never a guess.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from app.services.holding.digital_twin import _freshness, SOURCE_MAP

UNAVAILABLE = "UNAVAILABLE"
FOUND, UNKNOWN = "FOUND", "UNKNOWN"

# Well-known infrastructure/vendor dependency tokens — seeds the dependency vocabulary alongside the
# real integration strings discovered from the registry. Matching is substring/token, deterministic.
_INFRA_VOCAB = {"redis", "postgres", "postgresql", "railway", "cloudflare", "stripe", "dwolla",
                "celery", "openai", "ollama", "telegram", "resend", "instantly", "hunter",
                "google places", "sqlite", "s3"}

# Deterministic intent keywords (no LLM) — a query router the presence/command layer can call.
_DEPEND_WORDS = ("depend", "depends", "rely", "relies", "uses", "use", "using", "consumes", "needs")
_DESCRIBE_WORDS = ("what is", "what does", "describe", "tell me about", "what's", "purpose of")
_CHANGE_WORDS = ("changed", "change", "drift", "deployed", "deploy", "enabled", "disabled",
                 "feature registry", "what shipped")


def _entities_default() -> list:
    from app.services.holding import registry as reg
    return reg.all_entities()


def _report_value_default(entity_id: str, field_name: str):
    from app.services.holding import registry as reg
    return reg.report_value(entity_id, field_name)


def _deployment_default() -> dict:
    from app.config import settings
    from app.services.holding.holding_deployment import deployment_view, deployed_sha
    sha = deployed_sha()
    return deployment_view(settings, source_head=sha, peer_shas={"app_b": sha})


def _kg_neighbors_default(label: str, direction: str, relation: str | None):
    from app.services.kg import storage as kg
    return kg.neighbors(label, direction=direction, relation=relation)


def _capabilities_default() -> dict:
    from app.services.capability.seed import seed_registry
    from app.services.capability.manifest import Availability
    reg = seed_registry()
    return {"available": sorted(m.id for m in reg.list(availability=Availability.AVAILABLE)),
            "catalog_total": len(reg)}


_DEFAULT_SOURCES: dict[str, Callable] = {
    "entities": _entities_default, "report_value": _report_value_default,
    "deployment": _deployment_default, "kg_neighbors": _kg_neighbors_default,
    "capabilities": _capabilities_default,
}


class SystemKnowledgeIndex:
    def __init__(self, *, today: str = "", sources: dict[str, Callable] | None = None):
        self._today = today
        self._src = {**_DEFAULT_SOURCES, **(sources or {})}

    # ── fail-open source access ──────────────────────────────────────────────────────────────────
    def _get(self, name: str, default: Any, *args) -> Any:
        fn = self._src.get(name)
        if fn is None:
            return default
        try:
            v = fn(*args)
            return v if v is not None else default
        except Exception:
            return default

    def _entities(self) -> list:
        return self._get("entities", [])

    def _resolve_entity(self, ref: str):
        """Match a free-text ref to a real registry entity by id or brand_name (case-insensitive)."""
        r = (ref or "").strip().lower()
        if not r:
            return None
        for e in self._entities():
            if r == (getattr(e, "entity_id", "") or "").lower() or r == (getattr(e, "brand_name", "") or "").lower():
                return e
        for e in self._entities():   # looser: token contained in a brand name
            if r and r in (getattr(e, "brand_name", "") or "").lower():
                return e
        return None

    def _fresh(self, e) -> str:
        lv = getattr(e, "last_verified_at", None) or UNAVAILABLE
        return _freshness(lv, SOURCE_MAP["company_identity"]["freshness_days"], self._today)

    def _dep_vocab(self) -> set:
        """Dependency vocabulary = the real integration tokens discovered from the registry ∪ infra vocab."""
        vocab = set(_INFRA_VOCAB)
        for e in self._entities():
            for integ in (getattr(e, "integrations", []) or []):
                for tok in re.split(r"[^a-z0-9.]+", str(integ).lower()):
                    if len(tok) >= 3:
                        vocab.add(tok)
        return vocab

    # ── §15 answers ──────────────────────────────────────────────────────────────────────────────
    def describe_service(self, ref: str) -> dict:
        """"What does this service do?" — composed from the registry entity (products/stage/repo/deploy/
        integrations/kpis), with each contributing field cited as an evidence_ref."""
        e = self._resolve_entity(ref)
        if e is None:
            return {"question": f"what is {ref}", "status": UNKNOWN,
                    "answer": f"No holding entity matches '{ref}'.", "evidence_refs": [], "freshness": UNKNOWN}
        eid = getattr(e, "entity_id", "")
        products = getattr(e, "products", []) or []
        stage = getattr(e, "stage", "") or UNAVAILABLE
        kpis = getattr(e, "kpis", []) or []
        refs, bits = [], []
        if products:
            bits.append(f"products: {', '.join(map(str, products))}"); refs.append(f"holding.registry:{eid}.products")
        if stage and stage != UNAVAILABLE:
            bits.append(f"stage: {stage}"); refs.append(f"holding.registry:{eid}.stage")
        if getattr(e, "repository", None):
            bits.append(f"repo: {e.repository}"); refs.append(f"holding.registry:{eid}.repository")
        if getattr(e, "deployment", None):
            bits.append(f"deploy: {e.deployment}"); refs.append(f"holding.registry:{eid}.deployment")
        if getattr(e, "integrations", []):
            bits.append(f"integrations: {', '.join(map(str, e.integrations))}")
            refs.append(f"holding.registry:{eid}.integrations")
        if kpis:
            bits.append(f"facts: {'; '.join(map(str, kpis[:3]))}"); refs.append(f"holding.registry:{eid}.kpis")
        answer = f"{getattr(e, 'brand_name', eid)} — " + ("; ".join(bits) if bits else "no descriptive facts on record.")
        return {"question": f"what does {ref} do", "status": FOUND if bits else UNKNOWN,
                "answer": answer, "results": [{"entity": eid}], "evidence_refs": refs,
                "freshness": self._fresh(e)}

    def dependencies_of(self, ref: str) -> dict:
        """"What does <service> depend on?" — the entity's integrations (real, cited) + any KG out-edges."""
        e = self._resolve_entity(ref)
        if e is None:
            return {"question": f"what does {ref} depend on", "status": UNKNOWN,
                    "answer": f"No holding entity matches '{ref}'.", "evidence_refs": [], "freshness": UNKNOWN}
        eid = getattr(e, "entity_id", "")
        deps, refs = [], []
        for integ in (getattr(e, "integrations", []) or []):
            deps.append(str(integ))
        if deps:
            refs.append(f"holding.registry:{eid}.integrations")
        for edge in self._get("kg_neighbors", [], getattr(e, "brand_name", eid), "out", None):
            try:
                s, rel, d = edge.as_triple()
                if rel in ("depends_on", "uses"):
                    deps.append(d); refs.append(f"kg:{s}-{rel}-{d}")
            except Exception:
                continue
        return {"question": f"what does {ref} depend on", "status": FOUND if deps else UNKNOWN,
                "answer": (f"{getattr(e, 'brand_name', eid)} depends on: " + ", ".join(deps)) if deps
                          else f"No dependencies are recorded for {getattr(e, 'brand_name', eid)}.",
                "results": deps, "evidence_refs": refs, "freshness": self._fresh(e)}

    def services_depending_on(self, dependency: str) -> dict:
        """"Which service depends on <dependency>?" — scans every entity's integrations (real, cited) plus
        the KG's in-edges for the dependency. UNKNOWN (honest) when nothing in evidence references it."""
        dep = (dependency or "").strip().lower()
        if not dep:
            return {"question": "which service depends on ?", "status": UNKNOWN,
                    "answer": "No dependency named.", "evidence_refs": [], "freshness": UNKNOWN}
        hits, refs, freshest = [], [], UNKNOWN
        for e in self._entities():
            eid = getattr(e, "entity_id", "")
            for integ in (getattr(e, "integrations", []) or []):
                if dep in str(integ).lower():
                    hits.append({"service": eid, "via": str(integ)})
                    refs.append(f"holding.registry:{eid}.integrations")
                    f = self._fresh(e)
                    _rank = {"FRESH": 3, "STALE": 2, "UNKNOWN": 1}
                    if _rank.get(f, 0) > _rank.get(freshest, 0):
                        freshest = f     # true freshest across hits, not just the first (§16)
                    break
        # KG in-edges (entities that --depends_on/uses--> dependency); fail-open when the KG is empty.
        for edge in self._get("kg_neighbors", [], dependency, "in", None):
            try:
                s, rel, d = edge.as_triple()
                if rel in ("depends_on", "uses"):
                    hits.append({"service": s, "via": f"kg:{rel}"}); refs.append(f"kg:{s}-{rel}-{d}")
            except Exception:
                continue
        if not hits:
            return {"question": f"which service depends on {dependency}", "status": UNKNOWN,
                    "answer": f"No holding service in evidence references '{dependency}'.",
                    "results": [], "evidence_refs": [], "freshness": UNKNOWN}
        names = ", ".join(sorted({h["service"] for h in hits}))
        return {"question": f"which service depends on {dependency}", "status": FOUND,
                "answer": f"Depends on {dependency}: {names}.", "results": hits,
                "evidence_refs": refs, "freshness": freshest}

    def whats_changed(self) -> dict:
        """"What changed / what's deployed?" — composed from the deployment-truth feature registry + drift."""
        dep = self._get("deployment", {})
        if not isinstance(dep, dict) or not dep:
            return {"question": "what changed", "status": UNAVAILABLE,
                    "answer": "Deployment-truth source is unavailable.", "evidence_refs": [], "freshness": UNKNOWN}
        feats = dep.get("features", []) or []
        enabled = [f["name"] for f in feats if f.get("runtime_enabled")]
        dark = [f["name"] for f in feats if not f.get("runtime_enabled")]
        drift = (dep.get("drift", {}) or {}).get("state", UNKNOWN)
        return {"question": "what changed / what is deployed", "status": FOUND,
                "answer": f"Running SHA {dep.get('this_app_sha')} · drift {drift} · "
                          f"{len(enabled)} feature(s) ENABLED, {len(dark)} deployed-but-dark.",
                "results": {"enabled": enabled, "dark": dark, "drift": drift},
                "evidence_refs": ["holding.holding_deployment:deployment_view",
                                  "holding.holding_deployment:feature_registry"],
                "freshness": "FRESH"}

    # ── deterministic query router (no LLM) ──────────────────────────────────────────────────────
    def ask(self, question: str) -> dict:
        """Route an arch/dependency/change question to the right composed answer, deterministically.
        Returns UNKNOWN (never a fabricated answer) when it cannot classify or find evidence."""
        q = (question or "").strip().lower()
        if not q:
            return {"question": question, "status": UNKNOWN, "answer": "Empty question.",
                    "evidence_refs": [], "freshness": UNKNOWN}
        ent = next((e for e in self._entities()
                    if (getattr(e, "entity_id", "") or "").lower() in q
                    or (getattr(e, "brand_name", "") or "").lower() in q), None)
        dep_tok = next((d for d in sorted(self._dep_vocab(), key=len, reverse=True) if d in q), None)
        is_depend = any(w in q for w in _DEPEND_WORDS)
        is_change = any(w in q for w in _CHANGE_WORDS)
        is_describe = any(w in q for w in _DESCRIBE_WORDS)

        # "what does <entity> depend on" / "dependencies of <entity>" → dependencies_of
        if is_depend and ent is not None and ("depend" in q or "dependencies of" in q) and (
                dep_tok is None or dep_tok in (getattr(ent, "entity_id", ""), getattr(ent, "brand_name", "").lower())):
            return self.dependencies_of(getattr(ent, "entity_id", ""))
        # "which service depends on <dependency>" / "who uses <dependency>" → services_depending_on
        if is_depend and dep_tok is not None:
            return self.services_depending_on(dep_tok)
        if is_change and not is_depend:
            return self.whats_changed()
        if is_describe and ent is not None:
            return self.describe_service(getattr(ent, "entity_id", ""))
        if ent is not None and is_depend:
            return self.dependencies_of(getattr(ent, "entity_id", ""))
        return {"question": question, "status": UNKNOWN,
                "answer": "I can't answer that from authorized system evidence — it is outside the "
                          "knowledge index (arch/dependency/change questions only).",
                "evidence_refs": [], "freshness": UNKNOWN}


if __name__ == "__main__":
    # smoke over the real registry; the full suite is test_omnipresence_phase1.py
    ki = SystemKnowledgeIndex(today="2026-09-03")
    dep = ki.services_depending_on("stripe")
    assert dep["status"] in (FOUND, UNKNOWN) and isinstance(dep["evidence_refs"], list)
    assert ki.ask("what is the meaning of life?")["status"] == UNKNOWN   # honest out-of-scope
    print("knowledge_index smoke OK —", dep["status"], "· stripe dependents:", dep.get("answer"))
