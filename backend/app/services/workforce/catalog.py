"""Workforce Phase 4 — the inert WorkforceCatalog (catalog-only, INERT).

A read-only catalog over the 319 normalized `AgentCharacterManifest` declarations.
It can register / retrieve / filter / summarize / index / expose provenance and
propose a SIMULATED mission team. It CANNOT execute, dispatch, invoke, run, spawn,
activate, enable, or bind anything; it never calls an LLM / ModelRouter / tool /
hook / capability / network / device / queue / worker / payment / deployment /
external service; it never creates a mission, changes a character's status beyond
INERT, evaluates an environment flag, mounts a router, or mutates production or
tenant data.

It has NO execution surface by construction (mirrors the HookRegistry / Capability
catalog precedent): every method here is a pure read or a pure data transform over
in-memory manifest dicts. `propose_team` returns a typed, frozen *proposal* — a
description of a team KAI *could* assemble — never an assignment, activation, or
execution request. A proposal mutates nothing and starts nothing.

KAI remains the sole authority. A declaration is not permission: a registered
character is inert until KAI (separately, elsewhere, under owner authorization)
admits it, assigns it to one mission, grants bounded capabilities, and creates an
isolated workplace. None of that happens here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import schemas as S  # noqa: E402  (stdlib + pydantic only; no app import, no runtime pkgs)

GEN = _HERE / "generated"
_FROZEN = ConfigDict(extra="forbid", frozen=True)

# Risk ordering for "add a reviewer when the mission risk requires one".
_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_REVIEWER_MIN_RISK = "HIGH"

# Hard team bounds (smallest sufficient team, normally 3–7).
_TEAM_MIN = 3
_TEAM_MAX = 7
_SPECIALIST_FANOUT_MAX = 4   # planner + verifier + (<=4 specialists) + (<=1 reviewer) <= 7

# Declarable framework expertise (from docs/workforce/FRAMEWORK_CAPABILITY_MATRIX.md).
# A character's frameworks are a DERIVED read-time classification — matched against its
# role name + committed upstream description (MIT reference data). Only these
# allowlisted keywords ever appear as tags; raw upstream text is never emitted,
# injected, or imported. Declaring a framework is NOT authorization to install it.
_FRAMEWORK_KEYWORDS = (
    "angular", "typescript", "react native", "react", "next.js", "nextjs", "vue",
    "nuxt", "svelte", "sveltekit", "solidjs", "astro", "tailwind", "web components",
    "flutter", "swiftui", "swift", "kotlin", "jetpack compose", "electron", "tauri",
    "fastapi", "pydantic", "sqlalchemy", "alembic", "django", "flask", "nestjs",
    "express", "node.js", "nodejs", "golang", "go", "rust", "spring", ".net",
    "postgresql", "postgres", "pgvector", "redis", "rag", "embeddings",
    "knowledge graph", "model routing", "ollama", "python", "java",
    "docker", "kubernetes", "ci/cd", "opentelemetry", "prometheus", "grafana",
    "sentry", "mcp", "pytest", "playwright", "vitest", "jest", "mutation testing",
)
# Word-boundary matcher for alphanumeric keywords (so "go" != "ego", "java" !=
# "javascript"); substring for keywords carrying non-word chars (next.js, ci/cd, .net).
_FRAMEWORK_MATCHERS = tuple(
    (kw, re.compile(rf"\b{re.escape(kw)}\b", re.I) if re.fullmatch(r"[a-z0-9 ]+", kw) else None)
    for kw in _FRAMEWORK_KEYWORDS
)

# Roles that can lead/plan (deterministic planner preference). Upstream
# "orchestrator/chief-of-staff" is treated as advisory planning only.
_PLANNER_HINTS = ("architect", "lead", "planner", "strateg", "principal", "director", "chief")
# Native independent completion verifier (roster: "must NEVER be the worker").
_VERIFIER_ID = "kai.vera_complete"
# Native risk/reality reviewers (deterministic preference order).
_REVIEWER_HINTS = ("mira_proof", "cipher_ward", "aria_shield", "kairos_incident", "tessa_boundary")

# A mission tenant is admissible for owner-scoped characters only when it is the
# owner workspace. Any other tenant is a cross-tenant request -> rejected.
_OWNER_TENANTS = frozenset({"owner_workspace_only", "owner", "owner_workspace"})


class WorkforceCatalogError(Exception):
    """Base for catalog policy violations (never an execution path)."""


class TenantScopeViolation(WorkforceCatalogError):
    """A mission requested a tenant no registered character is scoped to."""


class TeamSizeError(WorkforceCatalogError):
    """The smallest sufficient team exceeds the hard team cap."""


class SeparationOfDutiesViolation(WorkforceCatalogError):
    """A proposed team would overlap worker/verifier or let a planner self-approve."""


class MissionSpec(BaseModel):
    """A simulated mission's staffing request. Pure data; carries no authority and
    triggers nothing. `tenant_scope` is the owner workspace for this single-owner
    estate; a foreign value is a cross-tenant request."""

    model_config = _FROZEN
    mission_id: str
    tenant_scope: str = "owner_workspace_only"
    required_divisions: tuple[str, ...] = ()
    required_frameworks: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    consequential_capabilities: tuple[str, ...] = ()
    risk_tier: str = "LOW"
    max_team_size: int = Field(default=_TEAM_MAX, ge=_TEAM_MIN, le=_TEAM_MAX)

    @field_validator("risk_tier")
    @classmethod
    def _risk(cls, v: str) -> str:
        if v not in _RISK_ORDER:
            raise ValueError(f"risk_tier must be one of {sorted(_RISK_ORDER)}")
        return v


class TeamMember(BaseModel):
    model_config = _FROZEN
    character_id: str
    display_name: str
    role: str  # PLANNER | SPECIALIST | RISK_REVIEWER | VERIFIER
    rationale: str


class SeparationOfDuties(BaseModel):
    model_config = _FROZEN
    worker_verifier_disjoint: bool
    planner_not_verifier: bool
    verifier_independent: bool
    reviewer_not_verifier: bool
    approval_authority: str = "KAI (owner_only) — no team member approves or completes its own work"
    ok: bool


class CoverageGap(BaseModel):
    model_config = _FROZEN
    requested_divisions: tuple[str, ...] = ()
    requested_frameworks: tuple[str, ...] = ()
    requested_capabilities: tuple[str, ...] = ()
    missing_divisions: tuple[str, ...] = ()
    missing_frameworks: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()

    @property
    def has_gap(self) -> bool:
        return bool(self.missing_divisions or self.missing_frameworks or self.missing_capabilities)


class TeamProposal(BaseModel):
    """A typed, frozen PROPOSAL — a team KAI could assemble. Not an assignment, not
    an activation, not an execution request. Every character stays INERT."""

    model_config = _FROZEN
    mission_id: str
    feasible: bool
    members: tuple[TeamMember, ...]
    separation_of_duties: SeparationOfDuties
    coverage_gap: CoverageGap
    risk_tier: str
    notes: tuple[str, ...] = ()
    # Honest, load-bearing constants making the proposal's inertness explicit.
    proposal_only: bool = True
    assigns_anyone: bool = False
    executes_anything: bool = False
    all_members_inert: bool = True


# `from __future__ import annotations` stringizes the nested-model annotations;
# rebuild so Pydantic resolves TeamMember/SeparationOfDuties/CoverageGap refs.
TeamProposal.model_rebuild()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


class WorkforceCatalog:
    """In-memory, read-only catalog of AgentCharacterManifests."""

    def __init__(self) -> None:
        self._by_id: dict[str, dict] = {}
        self._names: set[str] = set()
        self._quarantine: dict[str, dict] = {}
        # Derived framework-index source: role name + committed upstream description
        # (MIT reference data). Used ONLY to compute allowlisted framework tags.
        self._expertise_text: dict[str, str] = {}

    # ── construction (read-only load + validation) ───────────────────────────

    @classmethod
    def load_generated(cls) -> "WorkforceCatalog":
        """Build from the committed generated artifacts. Reads JSON only; no
        quarantine, no network, no generator run."""
        c = cls()
        chars = json.loads((GEN / "characters.json").read_text())["characters"]
        for m in chars:
            c.register(m)
        def _mid(upstream_id: str) -> str:
            return "up." + re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", upstream_id.lower())).strip("_")
        ev_path = GEN / "flagged_evidence.json"
        if ev_path.exists():
            for e in json.loads(ev_path.read_text())["flagged_sources"]:
                c._quarantine[_mid(e["id"])] = e
        inv_path = GEN / "upstream_inventory.json"
        if inv_path.exists():
            for a in json.loads(inv_path.read_text())["agents"]:
                c._expertise_text[_mid(a["id"])] = _norm(a.get("name", "") + " " + a.get("description", ""))
        return c

    def register(self, manifest) -> str:
        """Validate a manifest against the fail-closed schema and hold it. Rejects
        duplicate id / display_name and anything past INERT. NEVER changes status,
        activates, or binds — registration is inert by construction."""
        data = manifest if isinstance(manifest, dict) else manifest
        model = S.AgentCharacterManifest(**data)  # raises on malformed / post-INERT / bad provenance
        d = model.model_dump(mode="json")
        cid = d["identity"]["id"]
        name = d["identity"]["display_name"]
        if cid in self._by_id:
            raise WorkforceCatalogError(f"duplicate character id {cid!r}")
        if name in self._names:
            raise WorkforceCatalogError(f"duplicate display_name {name!r}")
        if d["governance"]["status"] not in {s.value for s in S.PHASE1_MAX_STATES}:
            raise WorkforceCatalogError(f"character {cid} status past INERT")
        self._by_id[cid] = d
        self._names.add(name)
        return cid

    # ── retrieval & filtering (deterministic) ────────────────────────────────

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, character_id: str) -> dict:
        if character_id not in self._by_id:
            raise KeyError(character_id)
        return self._by_id[character_id]

    def frameworks_of(self, character_id: str) -> tuple[str, ...]:
        d = self.get(character_id)
        text = _norm(d["identity"]["role_class"] + " " + d["identity"]["display_name"]
                     + " " + self._expertise_text.get(character_id, ""))
        tags = set()
        for kw, rx in _FRAMEWORK_MATCHERS:
            if (rx.search(text) if rx is not None else kw in text):
                tags.add(kw)
        return tuple(sorted(tags))

    def filter(
        self,
        *,
        division: Optional[str] = None,
        capability: Optional[str] = None,
        risk_tier: Optional[str] = None,
        framework: Optional[str] = None,
        source_kind: Optional[str] = None,
        workplace: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[str, ...]:
        """Deterministic id list (sorted) of characters matching ALL given
        predicates. Unknown / unmatched predicate -> empty tuple (honest)."""
        out = []
        for cid in sorted(self._by_id):
            d = self._by_id[cid]
            idn, cap, gov, wp = d["identity"], d["capabilities"], d["governance"], d["workplace"]
            if division is not None and _norm(idn["division"]) != _norm(division):
                continue
            if source_kind is not None and idn["source_kind"] != source_kind:
                continue
            if risk_tier is not None and gov["risk_tier"] != risk_tier:
                continue
            if status is not None and gov["status"] != status:
                continue
            if workplace is not None and _norm(wp["workplace_profile"]) != _norm(workplace):
                continue
            if capability is not None:
                pool = set(cap["declared"]) | set(cap.get("approval_required", ())) | set(cap.get("consequential", ()))
                if capability not in pool:
                    continue
            if framework is not None and _norm(framework) not in self.frameworks_of(cid):
                continue
            out.append(cid)
        return tuple(out)

    # ── provenance & quarantine-review metadata ──────────────────────────────

    def provenance(self, character_id: str) -> dict:
        idn = self.get(character_id)["identity"]
        q = self._quarantine.get(character_id)
        return {
            "id": idn["id"],
            "source_kind": idn["source_kind"],
            "source_path": idn["source_path"],
            "source_commit": idn["source_commit"],
            "source_hash": idn["source_hash"],
            "license": idn["license"],
            "reviewed_by": idn["reviewed_by"],
            "flagged": q is not None,
            "reason_codes": tuple(q["reason_codes"]) if q else (),
            "evidence_class": q["evidence_class"] if q else None,
        }

    def quarantine_review(self, character_id: str) -> Optional[dict]:
        return self._quarantine.get(character_id)

    # ── deterministic summaries / matrices / org chart ───────────────────────

    def _tally(self, key) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self._by_id.values():
            out[key(d)] = out.get(key(d), 0) + 1
        return dict(sorted(out.items()))

    def summary(self) -> dict:
        return {
            "total": len(self._by_id),
            "by_source_kind": self._tally(lambda d: d["identity"]["source_kind"]),
            "by_division": self._tally(lambda d: d["identity"]["division"]),
            "by_risk_tier": self._tally(lambda d: d["governance"]["risk_tier"]),
            "by_status": self._tally(lambda d: d["governance"]["status"]),
            "flagged_count": len(self._quarantine),
            "all_inert": all(d["governance"]["status"] == "INERT" for d in self._by_id.values()),
        }

    def org_chart(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for cid in sorted(self._by_id):
            out.setdefault(self._by_id[cid]["identity"]["division"], []).append(cid)
        return dict(sorted(out.items()))

    def capability_matrix(self) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for cid in sorted(self._by_id):
            for c in self._by_id[cid]["capabilities"]["declared"]:
                out.setdefault(c, set()).add(cid)
        return {k: sorted(v) for k, v in sorted(out.items())}

    def workplace_matrix(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for cid in sorted(self._by_id):
            out.setdefault(self._by_id[cid]["workplace"]["workplace_profile"], []).append(cid)
        return dict(sorted(out.items()))

    # ── team simulation (typed PROPOSAL only — no assignment, no execution) ───

    def _eligible(self, mission: MissionSpec) -> list[str]:
        """Characters whose tenant scope admits the mission. Owner-scoped chars
        admit only the owner workspace; any other tenant is cross-tenant."""
        if _norm(mission.tenant_scope) not in {_norm(t) for t in _OWNER_TENANTS}:
            raise TenantScopeViolation(
                f"mission tenant_scope {mission.tenant_scope!r} is not the owner workspace; "
                f"no registered character is scoped to it")
        return [cid for cid in sorted(self._by_id)
                if _norm(self._by_id[cid]["workplace"]["tenant_scope"]) in {_norm(t) for t in _OWNER_TENANTS}]

    def _matches_requirement(self, cid: str, *, division=None, framework=None, capability=None) -> bool:
        d = self._by_id[cid]
        if division is not None and _norm(d["identity"]["division"]) != _norm(division):
            return False
        if framework is not None and _norm(framework) not in self.frameworks_of(cid):
            return False
        if capability is not None:
            pool = set(d["capabilities"]["declared"]) | set(d["capabilities"].get("consequential", ()))
            if capability not in pool:
                return False
        return True

    def _pick_planner(self, pool: list[str]) -> Optional[str]:
        natives = [c for c in pool if self._by_id[c]["identity"]["source_kind"] == "KAI_NATIVE"]
        for hint in _PLANNER_HINTS:
            for c in natives:
                if hint in _norm(self._by_id[c]["identity"]["role_class"]):
                    return c
        return natives[0] if natives else (pool[0] if pool else None)

    def _pick_reviewer(self, pool: list[str], exclude: set[str]) -> Optional[str]:
        for hint in _REVIEWER_HINTS:
            for c in pool:
                if c in exclude:
                    continue
                if hint in c:
                    return c
        for c in pool:  # deterministic fallback: lowest-id native reviewer not excluded
            if c not in exclude and self._by_id[c]["identity"]["source_kind"] == "KAI_NATIVE":
                return c
        return None

    def propose_team(self, mission: MissionSpec) -> TeamProposal:
        """Propose the smallest sufficient SIMULATED team. Deterministic for
        identical inputs. Returns a typed proposal; assigns/executes nothing."""
        pool = self._eligible(mission)  # raises TenantScopeViolation on a foreign tenant
        notes: list[str] = []

        # Verifier: the independent completion verifier, pinned and never a worker.
        verifier = _VERIFIER_ID if _VERIFIER_ID in self._by_id else None
        reserved = {verifier} if verifier else set()

        # Planner/lead (advisory; cannot silently execute — all chars are DRAFT_ONLY).
        planner = self._pick_planner([c for c in pool if c not in reserved])
        if planner:
            reserved.add(planner)

        # Coverage: smallest set of specialists covering each required dimension.
        gap = self._coverage(mission)
        specialists: list[tuple[str, str]] = []  # (id, rationale)
        covered_reqs: list[str] = []
        for kind, values in (("division", mission.required_divisions),
                             ("framework", mission.required_frameworks),
                             ("capability", mission.required_capabilities)):
            for val in values:
                if any(self._matches_requirement(sid, **{kind: val}) for sid, _ in specialists):
                    continue  # already covered by a chosen specialist
                pick = next((c for c in pool if c not in reserved
                             and self._matches_requirement(c, **{kind: val})), None)
                if pick is None:
                    continue  # recorded as a gap below
                specialists.append((pick, f"covers required {kind}={val!r}"))
                reserved.add(pick)
                covered_reqs.append(f"{kind}={val}")
                if len(specialists) > _SPECIALIST_FANOUT_MAX:
                    raise TeamSizeError(
                        f"smallest sufficient team needs >{_SPECIALIST_FANOUT_MAX} specialists "
                        f"(> hard cap {_TEAM_MAX}); refuse to over-recruit")

        # If no requirements were given, staff exactly one general specialist so the
        # team is a real (>=3) team, never the whole catalog.
        if not specialists and not gap.has_gap:
            pick = next((c for c in pool if c not in reserved
                         and self._by_id[c]["identity"]["source_kind"] == "UPSTREAM"), None)
            if pick:
                specialists.append((pick, "general specialist (no specific expertise requested)"))
                reserved.add(pick)

        # Risk reviewer when risk requires, or a consequential capability is involved.
        reviewer = None
        needs_reviewer = (_RISK_ORDER[mission.risk_tier] >= _RISK_ORDER[_REVIEWER_MIN_RISK]
                          or bool(mission.consequential_capabilities))
        if needs_reviewer:
            reviewer = self._pick_reviewer(pool, reserved)
            if reviewer:
                reserved.add(reviewer)
                notes.append(f"risk reviewer added (risk_tier={mission.risk_tier}"
                             + (", consequential capability present" if mission.consequential_capabilities else "") + ")")
            else:
                notes.append("RISK REVIEWER REQUIRED but none available — proposal not feasible")

        members = self._assemble(planner, specialists, reviewer, verifier)
        sod = self._separation_of_duties(planner, [s for s, _ in specialists], reviewer, verifier)

        feasible = (
            planner is not None and verifier is not None and bool(specialists)
            and not gap.has_gap and sod.ok
            and (reviewer is not None or not needs_reviewer)
            and _TEAM_MIN <= len(members) <= mission.max_team_size
        )
        if not sod.ok:
            # Structural SoD failure is a hard violation, not a soft proposal.
            raise SeparationOfDutiesViolation(f"mission {mission.mission_id}: {sod.model_dump()}")
        if len(members) > mission.max_team_size:
            raise TeamSizeError(f"team of {len(members)} exceeds max_team_size {mission.max_team_size}")
        if gap.has_gap:
            notes.append("coverage gap — see coverage_gap; proposal not feasible until KAI admits/creates the missing expertise")

        return TeamProposal(
            mission_id=mission.mission_id, feasible=feasible, members=members,
            separation_of_duties=sod, coverage_gap=gap, risk_tier=mission.risk_tier,
            notes=tuple(notes),
        )

    def _assemble(self, planner, specialists, reviewer, verifier) -> tuple[TeamMember, ...]:
        m: list[TeamMember] = []
        if planner:
            m.append(TeamMember(character_id=planner, display_name=self._by_id[planner]["identity"]["display_name"],
                                role="PLANNER", rationale="advisory planner/lead; cannot execute or self-approve"))
        for sid, why in specialists:
            m.append(TeamMember(character_id=sid, display_name=self._by_id[sid]["identity"]["display_name"],
                                role="SPECIALIST", rationale=why))
        if reviewer:
            m.append(TeamMember(character_id=reviewer, display_name=self._by_id[reviewer]["identity"]["display_name"],
                                role="RISK_REVIEWER", rationale="reviews risk/reality; not the completion verifier"))
        if verifier:
            m.append(TeamMember(character_id=verifier, display_name=self._by_id[verifier]["identity"]["display_name"],
                                role="VERIFIER", rationale="independent completion verifier; never a worker on this mission"))
        return tuple(m)

    def _separation_of_duties(self, planner, specialists, reviewer, verifier) -> SeparationOfDuties:
        workers = set(specialists) | ({planner} if planner else set())
        wv = verifier is None or verifier not in workers
        pv = planner is None or verifier is None or planner != verifier
        rv = reviewer is None or verifier is None or reviewer != verifier
        vind = verifier is None or verifier not in (set(specialists) | {planner, reviewer})
        return SeparationOfDuties(
            worker_verifier_disjoint=wv, planner_not_verifier=pv,
            verifier_independent=vind, reviewer_not_verifier=rv,
            ok=(wv and pv and rv and vind),
        )

    def validate_separation_of_duties(self, proposal: TeamProposal) -> SeparationOfDuties:
        """Re-derive separation of duties from a proposal's member roles (a pure
        check a caller can run independently of propose_team)."""
        by_role: dict[str, list[str]] = {}
        for mem in proposal.members:
            by_role.setdefault(mem.role, []).append(mem.character_id)
        planner = (by_role.get("PLANNER") or [None])[0]
        verifier = (by_role.get("VERIFIER") or [None])[0]
        reviewer = (by_role.get("RISK_REVIEWER") or [None])[0]
        return self._separation_of_duties(planner, by_role.get("SPECIALIST", []), reviewer, verifier)

    def _coverage(self, mission: MissionSpec) -> CoverageGap:
        md = tuple(v for v in mission.required_divisions
                   if not any(self._matches_requirement(c, division=v) for c in self._by_id))
        mf = tuple(v for v in mission.required_frameworks
                   if not any(self._matches_requirement(c, framework=v) for c in self._by_id))
        mc = tuple(v for v in mission.required_capabilities
                   if not any(self._matches_requirement(c, capability=v) for c in self._by_id))
        return CoverageGap(
            requested_divisions=mission.required_divisions,
            requested_frameworks=mission.required_frameworks,
            requested_capabilities=mission.required_capabilities,
            missing_divisions=md, missing_frameworks=mf, missing_capabilities=mc,
        )

    def coverage_gap(self, mission: MissionSpec) -> CoverageGap:
        """Public: honest coverage gap for a mission's required expertise."""
        return self._coverage(mission)
