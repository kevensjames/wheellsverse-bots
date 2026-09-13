"""Workforce Phase 4 — WorkforceCatalog tests + negative controls (must have teeth).

Covers: 319 re-derived from generated artifacts; duplicate id/name rejection;
invalid hash/provenance + malformed + post-INERT rejection; deterministic filters/
summaries/matrices/proposals; empty-result + missing-capability behavior;
cross-tenant / worker-verifier-overlap / oversized / recursive-recruitment
rejection; consequential→reviewer; registration never changes status; simulated
teams cause no execution or mutation; forbidden public AND private execution-style
callables absent (with a teeth control); no runtime-execution imports; no workforce
router/worker/handler/adapter/background-task mounted. Pure; no network, no DB.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

_WF = Path(__file__).resolve().parents[1] / "app" / "services" / "workforce"
_CATALOG_PY = _WF / "catalog.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wf_catalog", _CATALOG_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _load_module()


@pytest.fixture(scope="module")
def cat():
    return C.WorkforceCatalog.load_generated()


def _base_manifest(cat, source_kind="UPSTREAM"):
    cid = next(c for c in cat.ids() if cat.get(c)["identity"]["source_kind"] == source_kind)
    return copy.deepcopy(cat.get(cid))


# ── 319 re-derived ───────────────────────────────────────────────────────────

def test_loads_exactly_319_rederived(cat):
    # Derived from the artifacts, cross-checked three independent ways.
    assert len(cat) == 319
    assert len(cat.ids()) == 319
    assert len(set(cat.ids())) == 319
    s = cat.summary()
    assert s["total"] == 319
    assert s["by_source_kind"] == {"KAI_NATIVE": 40, "UPSTREAM": 279}
    assert s["all_inert"] is True


# ── registration guards ──────────────────────────────────────────────────────

def test_duplicate_id_rejected(cat):
    m = _base_manifest(cat)
    with pytest.raises(C.WorkforceCatalogError, match="duplicate character id"):
        C.WorkforceCatalog.load_generated().register(m)  # id already present


def test_duplicate_display_name_rejected(cat):
    fresh = C.WorkforceCatalog.load_generated()
    m = _base_manifest(cat)
    m["identity"]["id"] = "up.zz_dupe_name_probe"
    m["identity"]["codename"] = "up.zz_dupe_name_probe"
    # keep the existing display_name -> duplicate name
    with pytest.raises(C.WorkforceCatalogError, match="duplicate display_name"):
        fresh.register(m)


def test_invalid_upstream_provenance_rejected(cat):
    fresh = C.WorkforceCatalog.load_generated()
    m = _base_manifest(cat, "UPSTREAM")
    m["identity"]["id"] = "up.zz_bad_prov"
    m["identity"]["codename"] = "up.zz_bad_prov"
    m["identity"]["display_name"] = "Bad Provenance Probe"
    m["identity"]["source_hash"] = ""  # UPSTREAM must carry a hash
    with pytest.raises(ValueError):
        fresh.register(m)


def test_native_with_provenance_rejected(cat):
    fresh = C.WorkforceCatalog.load_generated()
    m = _base_manifest(cat, "KAI_NATIVE")
    m["identity"]["id"] = "kai.zz_bad_native"
    m["identity"]["codename"] = "kai.zz_bad_native"
    m["identity"]["display_name"] = "Bad Native Probe"
    m["identity"]["source_hash"] = "a" * 64  # KAI_NATIVE must carry none
    with pytest.raises(ValueError):
        fresh.register(m)


def test_malformed_manifest_rejected(cat):
    fresh = C.WorkforceCatalog.load_generated()
    m = _base_manifest(cat)
    del m["soul"]  # drop a required section
    with pytest.raises(ValueError):
        fresh.register(m)


def test_post_inert_manifest_rejected(cat):
    fresh = C.WorkforceCatalog.load_generated()
    m = _base_manifest(cat)
    m["identity"]["id"] = "up.zz_running_probe"
    m["identity"]["codename"] = "up.zz_running_probe"
    m["identity"]["display_name"] = "Running Probe"
    m["governance"]["status"] = "RUNNING"
    with pytest.raises((ValueError, C.WorkforceCatalogError)):
        fresh.register(m)


def test_registration_never_changes_status(cat):
    fresh = C.WorkforceCatalog.load_generated()
    before = {c: fresh.get(c)["governance"]["status"] for c in fresh.ids()}
    assert set(before.values()) == {"INERT"}
    # registering a new valid character does not mutate any existing status
    m = _base_manifest(cat)
    m["identity"]["id"] = "up.zz_new_probe"
    m["identity"]["codename"] = "up.zz_new_probe"
    m["identity"]["display_name"] = "New Probe Character"
    fresh.register(m)
    assert fresh.get("up.zz_new_probe")["governance"]["status"] == "INERT"
    assert all(fresh.get(c)["governance"]["status"] == "INERT" for c in before)


# ── deterministic filters / summaries / matrices ─────────────────────────────

def test_filters_deterministic_and_scoped(cat):
    assert cat.filter(division="Engineering") == cat.filter(division="Engineering")
    assert len(cat.filter(source_kind="KAI_NATIVE")) == 40
    assert len(cat.filter(status="INERT")) == 319
    assert cat.filter(status="RUNNING") == ()            # nothing past INERT
    assert cat.filter(division="NoSuchDivision") == ()   # empty-result behavior
    assert cat.filter(risk_tier="CRITICAL") == ()        # none are CRITICAL
    # combined predicate narrows
    eng_med = cat.filter(division="Engineering", risk_tier="MEDIUM")
    assert set(eng_med) <= set(cat.filter(division="Engineering"))


def test_summaries_and_matrices_deterministic(cat):
    assert cat.summary() == cat.summary()
    assert cat.org_chart() == cat.org_chart()
    assert cat.capability_matrix() == cat.capability_matrix()
    assert cat.workplace_matrix() == cat.workplace_matrix()
    assert sum(len(v) for v in cat.org_chart().values()) == 319


def test_framework_index_derived_and_allowlisted(cat):
    allow = {kw for kw, _ in C._FRAMEWORK_MATCHERS}
    for cid in cat.ids():
        assert set(cat.frameworks_of(cid)) <= allow  # only allowlisted tags ever appear
    # the required framework filter is functional (not vacuous)
    assert len(cat.filter(framework="angular")) >= 1
    assert len(cat.filter(framework="react")) >= 1
    assert cat.filter(framework="cobol") == ()  # honest empty


# ── team proposals ───────────────────────────────────────────────────────────

def test_team_proposal_smallest_sufficient_and_roles(cat):
    p = cat.propose_team(C.MissionSpec(mission_id="t1", required_divisions=("Engineering",)))
    assert p.feasible is True
    assert 3 <= len(p.members) <= 7
    roles = [m.role for m in p.members]
    assert "PLANNER" in roles and "VERIFIER" in roles and "SPECIALIST" in roles
    # every member carries a selection rationale
    assert all(m.rationale for m in p.members)


def test_team_proposal_deterministic(cat):
    spec = C.MissionSpec(mission_id="t2", required_divisions=("Engineering", "Security"), risk_tier="HIGH")
    assert cat.propose_team(spec).model_dump() == cat.propose_team(spec).model_dump()


def test_missing_capability_returns_honest_gap(cat):
    p = cat.propose_team(C.MissionSpec(mission_id="t3", required_frameworks=("cobol",)))
    assert p.feasible is False
    assert p.coverage_gap.has_gap is True
    assert "cobol" in p.coverage_gap.missing_frameworks


def test_cross_tenant_proposal_rejected(cat):
    with pytest.raises(C.TenantScopeViolation):
        cat.propose_team(C.MissionSpec(mission_id="t4", tenant_scope="someone_elses_workspace"))


def test_worker_verifier_overlap_prevented(cat):
    p = cat.propose_team(C.MissionSpec(mission_id="t5", required_divisions=("Engineering",)))
    verifiers = {m.character_id for m in p.members if m.role == "VERIFIER"}
    workers = {m.character_id for m in p.members if m.role in ("PLANNER", "SPECIALIST", "RISK_REVIEWER")}
    assert verifiers.isdisjoint(workers)
    assert p.separation_of_duties.ok is True


def test_sod_validator_has_teeth(cat):
    # A hand-built proposal that makes the verifier also a specialist must FAIL the
    # independent SoD check (proves the validator is not vacuous).
    vid = C._VERIFIER_ID
    bad = C.TeamProposal(
        mission_id="bad", feasible=True,
        members=(
            C.TeamMember(character_id="kai.astra_vale", display_name="Astra Vale", role="PLANNER", rationale="x"),
            C.TeamMember(character_id=vid, display_name="Vera Complete", role="SPECIALIST", rationale="x"),
            C.TeamMember(character_id=vid, display_name="Vera Complete", role="VERIFIER", rationale="x"),
        ),
        separation_of_duties=C.SeparationOfDuties(
            worker_verifier_disjoint=True, planner_not_verifier=True,
            verifier_independent=True, reviewer_not_verifier=True, ok=True),
        coverage_gap=C.CoverageGap(), risk_tier="LOW",
    )
    assert cat.validate_separation_of_duties(bad).ok is False


def test_oversized_team_rejected(cat):
    with pytest.raises(C.TeamSizeError):
        cat.propose_team(C.MissionSpec(
            mission_id="t6",
            required_divisions=("Engineering", "Security", "Design", "Finance", "Sales"),
            risk_tier="HIGH"))


def test_no_recursive_recruitment_or_whole_catalog(cat):
    p = cat.propose_team(C.MissionSpec(
        mission_id="t7", required_divisions=("Engineering", "Security", "Design")))
    # bounded, never the whole catalog, no duplicate members, no nested team object
    assert len(p.members) <= 7 < len(cat)
    ids = [m.character_id for m in p.members]
    assert len(ids) == len(set(ids))
    blob = p.model_dump()
    assert "members" not in json.dumps([m for m in blob["members"]])  # members are flat TeamMembers, not nested proposals
    for m in p.members:
        assert set(m.model_dump().keys()) == {"character_id", "display_name", "role", "rationale"}


def test_consequential_capability_requires_reviewer(cat):
    p = cat.propose_team(C.MissionSpec(
        mission_id="t8", required_divisions=("Finance",),
        consequential_capabilities=("issue_refund",)))
    assert any(m.role == "RISK_REVIEWER" for m in p.members)


def test_high_risk_requires_reviewer(cat):
    p = cat.propose_team(C.MissionSpec(mission_id="t9", required_divisions=("Security",), risk_tier="HIGH"))
    assert any(m.role == "RISK_REVIEWER" for m in p.members)


def test_simulated_team_causes_no_execution_or_mutation(cat):
    fresh = C.WorkforceCatalog.load_generated()
    snapshot = json.dumps({c: fresh.get(c) for c in fresh.ids()}, sort_keys=True)
    p = fresh.propose_team(C.MissionSpec(mission_id="t10", required_divisions=("Engineering",), risk_tier="HIGH"))
    # proposal is explicitly inert
    assert p.proposal_only and not p.assigns_anyone and not p.executes_anything and p.all_members_inert
    # every proposed member is still INERT; catalog state is byte-identical
    for m in p.members:
        assert fresh.get(m.character_id)["governance"]["status"] == "INERT"
    assert json.dumps({c: fresh.get(c) for c in fresh.ids()}, sort_keys=True) == snapshot


# ── inertness: no execution surface, no runtime imports, no router/worker ────

_FORBIDDEN_VERBS = (
    "execute", "dispatch", "invoke", "run", "spawn", "activate", "enable", "bind",
    "mount", "deploy", "assign", "call_model", "call_tool", "model_router",
    "create_mission", "start_worker", "schedule", "approve",
)


def _all_method_names(cls):
    return [n for n in dir(cls) if not (n.startswith("__") and n.endswith("__"))]


def test_no_forbidden_execution_callables_public_or_private():
    for name in _all_method_names(C.WorkforceCatalog):
        attr = getattr(C.WorkforceCatalog, name, None)
        if callable(attr):
            low = name.lower()
            assert not any(v in low for v in _FORBIDDEN_VERBS), f"forbidden execution-style callable: {name}"


def test_public_api_is_exact_allowlist():
    public = {n for n in _all_method_names(C.WorkforceCatalog)
              if not n.startswith("_") and callable(getattr(C.WorkforceCatalog, n))}
    assert public == {
        "load_generated", "register", "get", "ids", "filter", "frameworks_of",
        "provenance", "quarantine_review", "summary", "org_chart",
        "capability_matrix", "workplace_matrix", "propose_team",
        "validate_separation_of_duties", "coverage_gap",
    }


def test_forbidden_callable_detector_has_teeth():
    # A subclass that adds an execution method MUST be caught by the same scan.
    class Rogue(C.WorkforceCatalog):
        def execute_mission(self):  # pragma: no cover - only its name is inspected
            return "boom"
    caught = any(v in n.lower() for n in _all_method_names(Rogue)
                 for v in _FORBIDDEN_VERBS)
    assert caught is True


def _code_without_strings_comments(src: str) -> str:
    # Drop STRING + COMMENT tokens so documentation describing the prohibitions
    # (e.g. the docstring that says it never calls a ModelRouter) can't false-match.
    import io
    import tokenize
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def test_no_runtime_execution_imports_or_flag_eval():
    import ast
    src = _CATALOG_PY.read_text()
    # (a) AST: no forbidden runtime-execution module is imported; imports are a
    #     subset of a known-safe set.
    imported = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    forbidden_imports = {
        "subprocess", "httpx", "requests", "aiohttp", "socket", "celery",
        "asyncio", "threading", "fastapi", "starlette", "sqlalchemy", "app", "os",
    }
    assert imported.isdisjoint(forbidden_imports), f"forbidden imports: {imported & forbidden_imports}"
    assert imported <= {"json", "re", "sys", "pathlib", "typing", "pydantic", "schemas", "__future__"}, \
        f"unexpected imports: {imported}"
    # (b) code-only scan (strings + comments removed) for dangerous call / flag patterns
    code = _code_without_strings_comments(src)
    for tok in ("os.environ", "getenv", "APIRouter", "include_router", "ModelRouter",
                "create_engine", ".dispatch(", ".execute(", "eval(", "exec(", "Popen",
                "__import__", "os.system", "os.popen"):
        assert tok not in code, f"catalog.py code references {tok!r}"


def test_no_workforce_router_worker_or_background_task():
    # The whole workforce package must mount no router/worker/handler/adapter.
    for py in _WF.glob("*.py"):
        src = py.read_text()
        for tok in ("APIRouter", "include_router", "@app.", "BackgroundTasks",
                    "Celery", "create_task", "@router."):
            assert tok not in src, f"{py.name} must not reference {tok!r}"
