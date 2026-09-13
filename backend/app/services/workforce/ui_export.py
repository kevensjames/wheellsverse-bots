"""Workforce Phase 5A — static UI view-model exporter (read-only, INERT).

Emits a compact, deterministic view-model for the DARK Angular workforce console
as a generated TypeScript data module. Pure catalog consumer: it reads the inert
WorkforceCatalog and writes static data only — no network, no execution, no
status change. The console imports this at compile time (no HttpClient, no runtime
fetch), so the UI can render the catalog but trigger nothing.

Every example team proposal here is produced by the authoritative Python
`WorkforceCatalog.propose_team` (KAI's catalog is the sole source of truth); the
console never re-computes a proposal and carries no planning logic of its own.

Regenerate:  python -c "import importlib.util,sys; \
  s=importlib.util.spec_from_file_location('u','backend/app/services/workforce/ui_export.py'); \
  m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.main()"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import catalog as K  # noqa: E402  (inert WorkforceCatalog; stdlib + pydantic + schemas only)

_REPO = _HERE.parents[3]
OUT_TS = _REPO / "frontend-pilots" / "kai-angular" / "src" / "app" / "workforce" / "workforce-data.ts"

# Representative simulated missions shown in the console's (inert) team view. Each
# is resolved by the authoritative catalog; the UI only displays the result.
_EXAMPLE_MISSIONS = [
    ("Angular frontend feature", dict(required_frameworks=("angular",))),
    ("Go + Rust data-plane refactor", dict(required_frameworks=("go", "rust"))),
    ("Security hardening review (HIGH risk)", dict(required_divisions=("Security",), risk_tier="HIGH")),
    ("Billing reconciliation (consequential)", dict(required_divisions=("Finance",),
                                                    consequential_capabilities=("issue_refund",))),
    ("Unavailable expertise (coverage gap)", dict(required_frameworks=("cobol",))),
]


def _char_view(cat: "K.WorkforceCatalog", cid: str) -> dict:
    d = cat.get(cid)
    idn, cap, gov, wp = d["identity"], d["capabilities"], d["governance"], d["workplace"]
    prov = cat.provenance(cid)
    return dict(
        id=idn["id"], displayName=idn["display_name"], codename=idn["codename"],
        division=idn["division"], department=idn["department"], seniority=idn["seniority"],
        roleClass=idn["role_class"], sourceKind=idn["source_kind"],
        riskTier=gov["risk_tier"], effectClass=gov["effect_class"], status=gov["status"],
        workplaceProfile=wp["workplace_profile"],
        networkPolicy=wp["network_policy"], deviceAccess=wp["device_access"],
        browserAccess=wp["browser_access"], externalWriteAccess=wp["external_write_access"],
        frameworks=list(cat.frameworks_of(cid)),
        declaredCapabilities=list(cap["declared"]), forbidden=list(cap["forbidden"]),
        flagged=prov["flagged"], reasonCodes=list(prov["reason_codes"]),
        provenance=dict(sourcePath=prov["source_path"], sourceCommit=prov["source_commit"],
                        sourceHash=prov["source_hash"], license=prov["license"],
                        reviewedBy=prov["reviewed_by"]),
    )


def _proposal_view(label: str, mission: "K.MissionSpec", proposal) -> dict:
    return dict(
        label=label, missionId=proposal.mission_id, feasible=proposal.feasible,
        riskTier=proposal.risk_tier,
        requested=dict(divisions=list(mission.required_divisions),
                       frameworks=list(mission.required_frameworks),
                       capabilities=list(mission.required_capabilities),
                       consequential=list(mission.consequential_capabilities)),
        members=[dict(characterId=m.character_id, displayName=m.display_name,
                      role=m.role, rationale=m.rationale) for m in proposal.members],
        coverageGap=dict(missingDivisions=list(proposal.coverage_gap.missing_divisions),
                         missingFrameworks=list(proposal.coverage_gap.missing_frameworks),
                         missingCapabilities=list(proposal.coverage_gap.missing_capabilities),
                         hasGap=proposal.coverage_gap.has_gap),
        notes=list(proposal.notes),
        # Inert markers echoed verbatim from the typed proposal — the UI asserts these.
        proposalOnly=proposal.proposal_only, assignsAnyone=proposal.assigns_anyone,
        executesAnything=proposal.executes_anything, allMembersInert=proposal.all_members_inert,
    )


def build_ui_data() -> dict:
    cat = K.WorkforceCatalog.load_generated()
    ids = list(cat.ids())
    characters = [_char_view(cat, cid) for cid in ids]
    frameworks = sorted({f for cid in ids for f in cat.frameworks_of(cid)})

    proposals = []
    for label, kwargs in _EXAMPLE_MISSIONS:
        spec = K.MissionSpec(mission_id="example." + label.lower().split(" ")[0], **kwargs)
        proposals.append(_proposal_view(label, spec, cat.propose_team(spec)))

    return dict(
        generatedFrom=dict(
            characterCount=len(ids),
            sourceCommit=next(c["provenance"]["sourceCommit"] for c in characters
                              if c["sourceKind"] == "UPSTREAM"),
            allInert=cat.summary()["all_inert"],
        ),
        governance=dict(
            notAvailableLabel="NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED",
            banner=("DARK · INERT — this console renders the governed workforce catalog as "
                    "static, read-only data. Nothing here can activate, assign, execute, "
                    "deploy, or call a model/tool/network. KAI remains the sole authority."),
            actionsAdmitted=False,
        ),
        summary=cat.summary(),
        divisions=sorted(cat.org_chart().keys()),
        orgChart=[dict(division=div, characterIds=ids_) for div, ids_ in cat.org_chart().items()],
        workplaceMatrix=[dict(workplace=wp, characterIds=ids_)
                         for wp, ids_ in cat.workplace_matrix().items()],
        capabilityMatrix=[dict(capability=c, characterIds=ids_)
                          for c, ids_ in cat.capability_matrix().items()],
        frameworks=frameworks,
        characters=characters,
        exampleProposals=proposals,
    )


_HEADER = """// AUTO-GENERATED by backend/app/services/workforce/ui_export.py — DO NOT EDIT BY HAND.
// Source of truth: the inert WorkforceCatalog over the 319 normalized manifests.
// All data is read-only and INERT. The DARK console renders it but can activate,
// assign, execute, deploy, or call a model/tool/network — NONE of these. Every
// example team proposal was produced by KAI's authoritative catalog.propose_team;
// the console carries no planning logic and re-computes nothing.
import { WorkforceData } from './workforce.types';

export const WORKFORCE_DATA: WorkforceData = """


def main() -> int:
    data = build_ui_data()
    OUT_TS.parent.mkdir(parents=True, exist_ok=True)
    OUT_TS.write_text(_HEADER + json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + ";\n")
    print(f"WORKFORCE_UI_DATA_WRITTEN: {OUT_TS.relative_to(_REPO)} "
          f"(characters={data['generatedFrom']['characterCount']}, "
          f"proposals={len(data['exampleProposals'])}, all_inert={data['generatedFrom']['allInert']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
