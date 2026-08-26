"""KAI Capability Fabric — the Capability Brain (§16, §28, §29, §60, §61, §63).

The decision system that answers: what does the user want, which capabilities could solve
it, which are available AND authorized, which combination is best, in what order, which need
approval, and when to stop. KAI stays the brain — external repos never self-select.

Pipeline (§16):
    REQUEST → INTENT → CANDIDATE SEARCH → POLICY FILTER → RESOURCE FILTER
            → RANK (§28 weighted) → CONFLICT/DEPENDENCY RESOLUTION → EXECUTION PLAN

Selection is OBSERVABLE (§28/§63): every candidate carries a numeric score and a concise,
human-readable rationale — never hidden chain-of-thought. Pure stdlib; testable as python3.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .manifest import CapabilityManifest, RiskClass, Certification, ActionClass
from .registry import CapabilityRegistry
from .graph import CapabilityGraph
from .risk import Principal, Decision, evaluate_policy, PolicyResult


# ── §28 selection weights (sum = 1.0). May become config. ──────────────────────
WEIGHTS = {
    "task_fit": 0.30, "security": 0.20, "reliability": 0.15, "data_quality": 0.10,
    "latency": 0.10, "resource_cost": 0.05, "financial_cost": 0.05, "context_cost": 0.05,
}

# coarse intent tags → the keywords that imply them (observable, not an LLM hunch)
INTENT_KEYWORDS = {
    "code": ["code", "bug", "fix", "implement", "refactor", "repository", "repo", "codebase", "function"],
    "docs": ["documentation", "docs", "api", "library", "framework", "current version", "changelog"],
    "security": ["security", "audit", "vulnerability", "reverse", "binary", "malware", "exploit", "pentest", "cve"],
    "learning": ["learn", "explain", "concept", "fundamentals", "tutorial", "teach"],
    "memory": ["remember", "memory", "recall", "persist", "what we learned"],
    "local_model": ["locally", "local model", "offline", "vram", "gpu", "on-device", "own hardware"],
    "geo": ["map", "geospatial", "coordinates", "region", "location", "gis", "geographic"],
    "browser": ["browser", "screenshot", "mobile", "render", "verify the page", "web page"],
    "collaboration": ["collaborate", "workspace", "team", "channel", "share with"],
    "research": ["research", "investigate", "analyze", "step by step", "think through"],
}


def classify_intent(request: str) -> set[str]:
    r = (request or "").lower()
    return {tag for tag, kws in INTENT_KEYWORDS.items() if any(k in r for k in kws)}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", (text or "").lower()))


@dataclass
class ResourceState:
    """Measured local reality (§26) — chosen from truth, not marketing."""
    ram_mb: int = 32000
    vram_mb: int = 8000
    gpu: bool = True
    disk_mb: int = 500000
    pressure: bool = False          # true → prefer light capabilities, avoid heavy runtimes


@dataclass
class Candidate:
    manifest: CapabilityManifest
    score: float
    factors: dict
    policy: PolicyResult
    matched_triggers: list[str]
    rationale: str
    needs_approval: bool


@dataclass
class Step:
    cap_id: str
    action_class: str
    decision: str
    needs_approval: bool
    rationale: str
    is_dependency: bool = False
    fallback: str | None = None


@dataclass
class CapabilityPlan:
    request: str
    intent: set[str]
    steps: list[Step] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)   # (cap_id, reason)
    summary: str = ""

    def selected_ids(self) -> list[str]:
        return [s.cap_id for s in self.steps]


_RISK_SCORE = {RiskClass.LOW: 1.0, RiskClass.MEDIUM: 0.7, RiskClass.HIGH: 0.4, RiskClass.RESTRICTED: 0.1}
_CERT_SCORE = {
    Certification.CERTIFIED: 1.0, Certification.PARTIAL: 0.6, Certification.EXPERIMENTAL: 0.4,
    Certification.EXTERNAL_BLOCKED: 0.0, Certification.REJECTED: 0.0, Certification.UPSTREAM_UNRESOLVED: 0.1,
}


class CapabilityBrain:
    def __init__(self, registry: CapabilityRegistry, graph: CapabilityGraph | None = None,
                 weights: dict | None = None) -> None:
        self.registry = registry
        self.graph = graph or CapabilityGraph()
        self.weights = weights or WEIGHTS

    # ── candidate search ──────────────────────────────────────────────────────
    def _matched_triggers(self, m: CapabilityManifest, request: str) -> list[str]:
        r = (request or "").lower()
        return [t for t in m.triggers if t.lower() in r]

    def _score(self, m: CapabilityManifest, matched: list[str], intent: set[str],
               resources: ResourceState) -> tuple[float, dict]:
        # task fit: how strongly the request hits this capability's triggers + intent overlap
        trig = min(1.0, len(matched) / max(1, min(3, len(m.triggers) or 1)))
        intent_overlap = 1.0 if (intent & _tokens(" ".join(m.capabilities) + " " + m.type.value.lower())) else 0.0
        task_fit = min(1.0, 0.7 * trig + 0.3 * intent_overlap + (0.15 if matched else 0.0))
        rp = m.resource_profile
        latency = 1.0 if rp.est_latency_ms == 0 else max(0.1, 1.0 - min(1.0, rp.est_latency_ms / 8000.0))
        resource_cost = 0.3 if (rp.heavy and resources.pressure) else (0.7 if rp.heavy else 1.0)
        factors = {
            "task_fit": round(task_fit, 3),
            "security": _RISK_SCORE.get(m.risk_class, 0.5),
            "reliability": _CERT_SCORE.get(m.certification, 0.4),
            "data_quality": 0.9 if m.type.value in ("KNOWLEDGE_PACK", "MEMORY_PROVIDER", "MCP") else 0.7,
            "latency": round(latency, 3),
            "resource_cost": resource_cost,
            "financial_cost": 1.0,       # local/free default; a paid provider would lower this
            "context_cost": 1.0,
        }
        score = sum(self.weights[k] * factors[k] for k in self.weights)
        return round(score, 4), factors

    def _rationale(self, m: CapabilityManifest, matched: list[str], policy: PolicyResult) -> str:
        if matched:
            why = f"matched {', '.join(matched[:3])}"
        else:
            why = "intent match"
        tail = "" if policy.decision == Decision.ALLOW else f"; {policy.decision.value.lower().replace('_', ' ')}"
        return f"Selected {m.name} — {why}{tail}."

    def plan(self, request: str, principal: Principal,
             resources: ResourceState | None = None) -> CapabilityPlan:
        resources = resources or ResourceState()
        intent = classify_intent(request)
        plan = CapabilityPlan(request=request, intent=intent)

        # 1. candidate search — selectable capabilities whose triggers appear in the request
        candidates: list[Candidate] = []
        for m in self.registry.list(selectable_only=True):
            matched = self._matched_triggers(m, request)
            if not matched:
                continue
            # 2. policy filter — governance decides; DENY drops the candidate
            policy = evaluate_policy(m, m.default_action_class, principal)
            if policy.decision == Decision.DENY:
                plan.rejected.append((m.id, f"policy: {policy.reason}"))
                continue
            # 3. resource filter — never plan a capability the machine can't run (§26)
            rp = m.resource_profile
            if rp.vram_mb > resources.vram_mb or rp.ram_mb > resources.ram_mb:
                plan.rejected.append((m.id, f"resource: needs {rp.vram_mb}MB vram / {rp.ram_mb}MB ram"))
                continue
            score, factors = self._score(m, matched, intent, resources)
            candidates.append(Candidate(
                manifest=m, score=score, factors=factors, policy=policy, matched_triggers=matched,
                rationale=self._rationale(m, matched, policy),
                needs_approval=(policy.decision == Decision.REQUIRE_APPROVAL),
            ))

        # 4. rank
        candidates.sort(key=lambda c: c.score, reverse=True)

        # 5. conflict + alternative resolution (§61) — greedily keep the highest-ranked
        selected: list[Candidate] = []
        chosen_ids: set[str] = set()
        for c in candidates:
            cid = c.manifest.id
            clash = self.graph.conflicts_with(cid) & chosen_ids
            if clash:
                plan.rejected.append((cid, f"conflicts with already-selected {sorted(clash)[0]}"))
                continue
            alt = self.graph.alternatives(cid) & chosen_ids
            if alt:
                plan.rejected.append((cid, f"alternative to already-selected {sorted(alt)[0]} (higher-ranked kept)"))
                continue
            selected.append(c)
            chosen_ids.add(cid)

        # 6. dependency resolution (§60) + execution plan ordering (§29): deps first
        emitted: set[str] = set()
        for c in selected:
            cid = c.manifest.id
            try:
                deps = self.graph.requires_closure(cid)
            except ValueError as exc:
                plan.rejected.append((cid, f"dependency: {exc}"))
                continue
            for dep in deps:
                if dep in emitted:
                    continue
                if not self.registry.has(dep) or not self.registry.get(dep).selectable():
                    # a required dependency is unavailable → offer a fallback, don't fake readiness (§30)
                    fb = sorted(self.graph.fallbacks_for(dep))
                    plan.steps.append(Step(cap_id=dep, action_class="READ_ONLY", decision="BLOCKED",
                                           needs_approval=False, is_dependency=True,
                                           rationale=f"required by {cid} but unavailable",
                                           fallback=fb[0] if fb else None))
                    emitted.add(dep)
                    continue
                dm = self.registry.get(dep)
                emitted.add(dep)
                plan.steps.append(Step(cap_id=dep, action_class=dm.default_action_class.value,
                                       decision="ALLOW", needs_approval=False, is_dependency=True,
                                       rationale=f"required by {cid}"))
            if cid in emitted:
                continue
            emitted.add(cid)
            fb = sorted(self.graph.fallbacks_for(cid))
            plan.steps.append(Step(cap_id=cid, action_class=c.policy.action_class.value,
                                   decision=c.policy.decision.value, needs_approval=c.needs_approval,
                                   rationale=c.rationale, fallback=fb[0] if fb else None))

        picks = [s.cap_id for s in plan.steps if not s.is_dependency]
        plan.summary = ("No capability required." if not picks
                        else "Selected: " + ", ".join(picks) + f" (intent: {', '.join(sorted(intent)) or 'general'}).")
        return plan
