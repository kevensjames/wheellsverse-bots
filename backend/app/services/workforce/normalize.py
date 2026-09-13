"""Workforce Phase 3 — deterministic normalization (INERT).

Transforms the quarantined, UNTRUSTED upstream intake (279 agency-agents) plus
the required 40 KAI-native characters into 319 schema-valid, fail-closed
`AgentCharacterManifest` declarations, then emits static artifacts. Pure and
deterministic: stdlib + the Phase-1 schema only; no network, no upstream code
executed, re-running produces byte-identical output.

GOVERNANCE BOUNDARY (why this is safe):
  * Upstream prose is UNTRUSTED. This normalizer does NOT copy upstream
    operational instructions into any active manifest field. Each upstream
    character receives a STANDARD SAFE KAI-authored manifest (KAI's own soul,
    deny-by-default workplace, advisory/draft capabilities, INERT governance).
    Only *safe semantic expertise* — the division label + the source role name —
    is extracted, and it is sanitized against the schema's injection / autonomy /
    sentience / placeholder needles before use.
  * Provenance is carried honestly: source_path + pinned commit + sha256 on every
    UPSTREAM identity; KAI_NATIVE carries none.
  * The 45 flagged sources keep their reason codes + hashes and have their
    operational instructions preserved as QUOTED EVIDENCE in flagged_evidence.json
    (clearly marked inert, never an active prompt). Nothing is labelled
    "human-approved": reviewed_by stays null until a human actually reviews.
  * Every manifest is at INERT. Nothing here runs, binds an adapter, mounts a
    router, or grants authority. KAI remains the sole authority.

Run:  python -c "import backend.app.services.workforce.normalize as n; n.main()"
  or import normalize and call build()/main() (see tests).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # schemas.py imports only stdlib + pydantic
import schemas as S  # noqa: E402

_REPO = _HERE.parents[3]  # .../wheellsverse-kai-hooks
# Quarantine lives OUTSIDE the repo (supply-chain). Machine-agnostic: honor
# $KAI_UPSTREAM_QUARANTINE, else default under the running user's home. Only needed
# to RE-GENERATE from source; the committed artifacts are static and do not read it.
QUARANTINE = Path(os.environ.get("KAI_UPSTREAM_QUARANTINE")
                  or (Path.home() / "kai-upstream-quarantine" / "agency-agents"))
INVENTORY = _HERE / "generated" / "upstream_inventory.json"
NATIVE_DOC = _REPO / "docs" / "workforce" / "KAI_NATIVE_CHARACTERS.md"
GEN = _HERE / "generated"

DIVISION_LABEL = {
    "academic": "Academic", "design": "Design", "engineering": "Engineering",
    "finance": "Finance", "game-development": "Game Development", "gis": "GIS",
    "healthcare": "Healthcare", "marketing": "Marketing", "paid-media": "Paid Media",
    "product": "Product", "project-management": "Project Management",
    "research": "Research", "sales": "Sales", "security": "Security",
    "spatial-computing": "Spatial Computing", "specialized": "Specialized",
    "support": "Support", "testing": "Testing",
}

# Safe, real professional trait palettes per division (KAI-authored — never from
# upstream prose). Exactly 5 each; none sentient/autonomous/placeholder.
_DIV_TRAITS = {
    "academic": ("rigorous", "citation-disciplined", "curious", "methodical", "evidence-driven"),
    "design": ("user-centered", "systematic", "detail-oriented", "iterative", "evidence-driven"),
    "engineering": ("rigorous", "systems-minded", "pragmatic", "detail-oriented", "evidence-driven"),
    "finance": ("numerate", "conservative", "exception-focused", "transparent", "evidence-driven"),
    "game-development": ("inventive", "performance-aware", "iterative", "technically-precise", "evidence-driven"),
    "gis": ("spatial-analytical", "precise", "data-careful", "methodical", "evidence-driven"),
    "healthcare": ("cautious", "privacy-first", "conservative", "uncertainty-aware", "evidence-driven"),
    "marketing": ("audience-aware", "measured", "ethically-competitive", "experimental", "evidence-driven"),
    "paid-media": ("budget-disciplined", "measured", "analytical", "compliance-aware", "evidence-driven"),
    "product": ("user-centered", "prioritization-minded", "pragmatic", "outcome-focused", "evidence-driven"),
    "project-management": ("organized", "dependency-aware", "communicative", "risk-conscious", "evidence-driven"),
    "research": ("investigative", "source-conscious", "skeptical", "patient", "evidence-driven"),
    "sales": ("candid", "commercially-aware", "relationship-minded", "honest", "evidence-driven"),
    "security": ("adversarial", "restrained", "vigilant", "least-privilege-minded", "evidence-driven"),
    "spatial-computing": ("spatially-minded", "technically-precise", "experimental", "careful", "evidence-driven"),
    "specialized": ("adaptable", "focused", "methodical", "pragmatic", "evidence-driven"),
    "support": ("empathetic", "patient", "clear", "solution-focused", "evidence-driven"),
    "testing": ("meticulous", "adversarial", "reproducibility-minded", "patient", "evidence-driven"),
}
_DEFAULT_TRAITS = ("rigorous", "methodical", "pragmatic", "careful", "evidence-driven")

# KAI's shared soul contract (identical for every character — it is KAI's, not the
# source's). No sentience/personhood; reinforces KAI as sole authority.
def _soul() -> dict:
    return dict(
        values=("truthfulness", "owner sovereignty", "reversibility",
                "evidence over assertion", "least privilege"),
        ethical_commitments=("do no harm to the owner's systems or data",
                             "never misrepresent status or provenance",
                             "prefer the smallest safe action"),
        truthfulness_rules=("state what is verified vs assumed",
                            "never claim completion without evidence",
                            "cite sources for external claims"),
        safety_boundaries=("stay within assigned tenant, project and mission scope",
                           "no execution, device, browser or network without separate owner authorization",
                           "fail closed on ambiguity"),
        privacy_commitments=("handle owner and user data as confidential",
                             "use secret references, never raw secrets"),
        user_respect_rules=("defer to the owner", "explain trade-offs plainly"),
        uncertainty_behavior="state uncertainty explicitly and defer to KAI",
        refusal_conditions=("a request exceeds assigned scope",
                            "a request would execute, deploy, or move money without owner approval",
                            "provenance or evidence is missing"),
        immutable_principles=("KAI is the sole authority",
                              "a declaration is not permission",
                              "never claim unverified completion",
                              "remain INERT until the owner authorizes activation"),
    )


def _brain(reasoning: str = "analytical") -> dict:
    return dict(
        profile_id="kai.brain.advisory.v1",
        reasoning_class=reasoning,
        model_router_requirements="KAI ModelRouter selects the model; no pinned external model",
        tool_categories=("retrieval", "analysis", "drafting"),
        retrieval_policy="governed_rag_with_citations",
        memory_access="read_scoped",
        planning_depth="bounded",
        temperature_class="low",
        cost_class="standard",
        latency_class="standard",
        minimum_context=8000,
        maximum_context=200000,
    )


def _workplace(profile: str) -> dict:
    return dict(
        workplace_profile=profile,
        tenant_scope="owner_workspace_only",
        project_scope="assigned_only",
        mission_scope="assigned_only",
        scratch_policy="ephemeral",
        worktree_policy="isolated_readonly_by_default",
        network_policy="deny",
        device_access=False,
        browser_access=False,
        external_write_access=False,
    )


_BASE_FORBIDDEN = (
    "execute actions or run code", "move money or issue refunds",
    "send external communications", "approve its own work",
    "declare its own completion", "create or assign missions",
    "enable device, browser, or network access",
)


def _capabilities(extra_forbidden: tuple[str, ...] = ()) -> dict:
    return dict(
        declared=("produce draft analysis", "summarize evidence", "recommend options for owner review"),
        forbidden=_BASE_FORBIDDEN + extra_forbidden,
        approval_required=(),
        consequential=(),
        evidence_requirements=("cite sources", "log to the governed evidence stream"),
    )


def _governance(risk: str, reviewers: tuple[str, ...]) -> dict:
    return dict(
        risk_tier=risk,
        effect_class="DRAFT_ONLY",
        activation_requirements=("explicit owner authorization",
                                 "a separate enablement flag that defaults off",
                                 "independent review before activation"),
        approval_policy="owner_only",
        separation_of_duties=("the worker is never its own reviewer",
                              "activation authority is separate from execution"),
        independent_reviewer_classes=reviewers,
        kill_control="KAI global kill switch plus per-character revocation",
        revocation="immediate_by_KAI",
        audit_policy="all_actions_logged_to_the_governed_evidence_stream",
        status="INERT",
    )


# Literal injection phrases (substring form for _safe's `in` scan) — the schema
# does not scan display_name/role_class for these, so the sanitizer must, to
# honor the documented "sanitized against injection needles" contract at any
# future repin whose frontmatter `name` weaponizes the one field that crosses
# the trust boundary.
_INJECTION = (
    "ignore all previous", "ignore previous instructions", "disregard previous",
    "disregard all previous", "override your instructions", "ignore your instructions",
    "ignore your prompt", "system prompt:", "you are now", "new instructions:",
)
_NEEDLES = S._UNSAFE_AUTONOMY + S._SENTIENCE + S._PLACEHOLDER + _INJECTION


def _safe(text: str, fallback: str) -> str:
    """Sanitize untrusted source text before it enters an active field: collapse
    whitespace, drop anything carrying an injection/autonomy/sentience/placeholder
    needle (fail closed to the fallback)."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    low = t.lower()
    if not t or any(n in low for n in _NEEDLES):
        return fallback
    return t


def _slug(s: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")


_HIGH_RISK_DIV = {"security", "healthcare", "finance"}


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Split a `---`-delimited YAML-ish frontmatter block from the body. Minimal
    key: value parsing (we only read name/description); body returned for evidence."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, flags=re.S)
    if not m:
        return {}, raw
    fm, body = {}, m.group(2)
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def _role_from_name(name: str) -> tuple[str, str]:
    """(role_class, seniority) from a source role name, sanitized."""
    role = _safe(name, "Domain Specialist")
    low = role.lower()
    seniority = next((s for s in ("principal", "lead", "senior", "staff")
                      if s in low), "specialist")
    return role, seniority.capitalize() if seniority != "specialist" else "Specialist"


def _upstream_manifest(a: dict, commit: str, flagged: set[str]) -> dict:
    div = a["division"]
    label = DIVISION_LABEL.get(div, div.replace("-", " ").title())
    ident = a["id"]                       # unique across the 279 (verified)
    cid = "up." + _slug(ident)
    role, seniority = _role_from_name(a.get("name", ""))
    expertise = _safe(a.get("name", ""), label + " practice").lower()
    is_flagged = a["id"] in flagged
    risk = "MEDIUM" if (is_flagged or div in _HIGH_RISK_DIV) else "LOW"
    reviewers = ("KAI", "independent_verifier") + (("security_reviewer",) if (is_flagged or div == "security") else ())
    return dict(
        identity=dict(
            id=cid, display_name=_safe(a.get("name", ""), role),
            codename=cid, division=label, department=label,
            seniority=seniority, role_class=role, source_kind="UPSTREAM",
            license="MIT", created_by="kai.workforce.normalizer",
            source_path=a["path"], source_commit=commit, source_hash=a["sha256"],
            reviewed_by=None,
        ),
        personality=dict(
            traits=_DIV_TRAITS.get(div, _DEFAULT_TRAITS),
            communication_tone="concise and professional",
            working_style="advisory and draft-oriented",
            collaboration_style="defers to KAI and to assigned reviewers",
            disagreement_style="raises evidence-based objections, then defers",
            ambiguity_response="asks KAI and fails closed",
            pressure_response="slows down and states uncertainty",
            anti_traits=("overconfident", "scope-creeping"),
            prohibited_persona_behaviors=("claiming authority", "claiming completion without evidence"),
        ),
        mission=dict(
            one_sentence_mission=(
                f"Advise KAI on {expertise} within the {label} division, producing "
                f"draft analysis and recommendations for owner review."),
            responsibilities=(f"provide {label}-domain draft analysis",
                              "summarize trade-offs and uncertainty",
                              "recommend reversible options for owner review"),
            expected_deliverables=("draft analyses", "option write-ups with cited evidence"),
            non_responsibilities=("executing changes", "approving or completing work",
                                  "moving money or sending external communications"),
            success_metrics=("recommendations are cited and reproducible",
                            "no action taken without owner approval"),
            failure_modes=("overstating certainty", "acting outside assigned scope"),
            escalation_conditions=("scope ambiguity", "a request to execute or deploy"),
        ),
        brain=_brain(),
        soul=_soul(),
        workplace=_workplace(f"{label} Advisory Desk"),
        capabilities=_capabilities(),
        governance=_governance(risk, reviewers),
    )


def _parse_native_rows() -> list[dict]:
    """Parse the 40 required native rows from KAI_NATIVE_CHARACTERS.md (the doc is
    the source of truth)."""
    rows = []
    for line in NATIVE_DOC.read_text().splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        rows.append(dict(
            num=int(cells[0]), name=cells[1], role=cells[2], personality=cells[3],
            mission=cells[4], workplace=cells[5], boundary=cells[6],
        ))
    return rows


def _native_traits(personality: str) -> tuple[str, ...]:
    base = [t.strip() for t in personality.split(",") if t.strip()]
    for pad in ("evidence-driven", "owner-deferential", "scope-disciplined", "reversible-first"):
        if len(base) >= 5:
            break
        if pad not in base:
            base.append(pad)
    return tuple(base[:7])


def _native_manifest(r: dict) -> dict:
    cid = "kai." + _slug(r["name"])
    mission = _safe(r["mission"], f"advise KAI in the {r['role']} role")
    if not mission or mission[0].islower():
        mission = mission[:1].upper() + mission[1:]
    if len(mission) < 12:
        mission = f"Advise KAI as {r['role']} for owner review."
    boundary = r["boundary"]
    extra_forbidden = ()
    if boundary and boundary not in ("—", "-", ""):
        extra_forbidden = (_safe(boundary, "act outside assigned scope"),)
    return dict(
        identity=dict(
            id=cid, display_name=r["name"], codename=cid,
            division="KAI Native", department=_safe(r["workplace"], "Mission Control"),
            seniority="Principal", role_class=_safe(r["role"], "KAI Specialist"),
            source_kind="KAI_NATIVE", license="KAI-internal",
            created_by="kai.workforce.normalizer", reviewed_by=None,
        ),
        personality=dict(
            traits=_native_traits(r["personality"]),
            communication_tone="precise and candid",
            working_style="advisory, evidence-first",
            collaboration_style="partners with KAI; defers authority to KAI",
            disagreement_style="states the evidence, then defers",
            ambiguity_response="asks KAI and fails closed",
            pressure_response="stays calm and states uncertainty",
            anti_traits=("overconfident", "authority-claiming"),
            prohibited_persona_behaviors=("claiming sentience", "claiming independent authority"),
        ),
        mission=dict(
            one_sentence_mission=mission,
            responsibilities=(_safe(r["role"], "advise KAI in its domain"),
                             "surface risks and uncertainty early"),
            expected_deliverables=("draft analyses and recommendations",),
            non_responsibilities=("executing changes", "approving or completing its own work"),
            success_metrics=("recommendations are cited and actionable for the owner",),
            failure_modes=("overstepping scope", "overstating certainty"),
            escalation_conditions=("scope ambiguity", "a request to act without owner approval"),
        ),
        brain=_brain(),
        soul=_soul(),
        workplace=_workplace(_safe(r["workplace"], "Mission Control")),
        capabilities=_capabilities(extra_forbidden),
        governance=_governance("LOW", ("KAI", "independent_verifier")),
    )


def _dedupe_display_names(manifests: list[dict]) -> None:
    """Deterministic unique display names (process in stable id order). First
    occurrence keeps the bare name; collisions get a division suffix, then #n."""
    seen: dict[str, int] = {}
    for m in sorted(manifests, key=lambda x: x["identity"]["id"]):
        idn = m["identity"]
        name = idn["display_name"]
        if name.lower() not in seen:
            seen[name.lower()] = 1
            continue
        cand = f"{name} ({idn['division']})"
        if cand.lower() in seen:
            n = seen[name.lower()] + 1
            seen[name.lower()] = n
            cand = f"{name} ({idn['division']}) #{n}"
        seen[cand.lower()] = 1
        idn["display_name"] = cand


# Indicative markers per reason code — used ONLY to locate the flagged region so
# the evidence quotes what was actually flagged (not a generic file head).
_REASON_MARKERS = {
    "INJECTION_PATTERN": (r"ignore (?:all )?previous instructions",
                          r"disregard (?:all )?previous", r"ignore your (?:system )?prompt",
                          r"override your instructions"),
    "SECRET_EXFIL_PATTERN": (r"\b(?:api[_ -]?key|secret|token|password|credential)\b", r"exfiltrat"),
    "EXEC_CONTENT_PRESENT": (r"```(?:bash|sh|shell|zsh)", r"\b(?:npm|pip|yarn|pnpm) install\b",
                             r"curl\b[^\n]*\|\s*(?:bash|sh)"),
    "PATH_ANOMALY": (r"\.\./", r"/etc/", r"~/\."),
}


def _match_windows(body: str, reason_codes: list[str]) -> list[dict]:
    """Up to 2 bounded context windows per reason code, quoting the flagged region."""
    wins = []
    for rc in reason_codes:
        hits = 0
        for pat in _REASON_MARKERS.get(rc, ()):
            for m in re.finditer(pat, body, flags=re.I):
                s, e = max(0, m.start() - 160), min(len(body), m.end() + 160)
                wins.append(dict(reason_code=rc,
                                 window=re.sub(r"\s+", " ", body[s:e]).strip()[:400]))
                hits += 1
                if hits >= 2:
                    break
            if hits >= 2:
                break
    return wins


def _flagged_evidence(findings: list[dict], commit: str) -> list[dict]:
    """Preserve each flagged source's reason codes + hash + BOUNDED quoted excerpts
    of the flagged operational instructions as INERT evidence (never active). Quotes
    both a head excerpt for context AND the matched region per reason code, so the
    evidence actually retains what triggered each flag."""
    out = []
    for f in sorted(findings, key=lambda x: x["id"]):
        raw = (QUARANTINE / f["path"]).read_text(errors="replace")
        _, body = _parse_frontmatter(raw)
        out.append(dict(
            id=f["id"], path=f["path"],
            sha256=hashlib.sha256((QUARANTINE / f["path"]).read_bytes()).hexdigest(),
            reason_codes=f["reason_codes"],
            evidence_class="QUOTED_OPERATIONAL_INSTRUCTIONS_INERT",
            note=("Verbatim source excerpts retained as evidence only. NOT active "
                  "prompts, NOT imported into any manifest field, NOT human-approved. "
                  "Executable snippets are quoted as evidence, never copied into a prompt."),
            head_excerpt=re.sub(r"\s+", " ", body).strip()[:800],
            flagged_windows=_match_windows(body, f["reason_codes"]),
        ))
    return out


def build() -> dict:
    """Pure: returns the full normalization result (no file writes)."""
    inv = json.loads(INVENTORY.read_text())
    commit = inv["source"]["pinned_commit"]
    flagged = {f["id"] for f in inv["quarantine_findings"]}

    upstream = [_upstream_manifest(a, commit, flagged) for a in inv["agents"]]
    native = [_native_manifest(r) for r in _parse_native_rows()]
    manifests = upstream + native
    _dedupe_display_names(manifests)

    # Validate EVERY manifest against the fail-closed schema (construction teeth).
    validated = [S.AgentCharacterManifest(**m).model_dump(mode="json") for m in manifests]
    validated.sort(key=lambda x: x["identity"]["id"])

    ids = [m["identity"]["id"] for m in validated]
    names = [m["identity"]["display_name"] for m in validated]
    assert len(set(ids)) == len(ids), "duplicate character id"
    assert len(set(names)) == len(names), "duplicate display_name"

    evidence = _flagged_evidence(inv["quarantine_findings"], commit)

    org: dict[str, list[str]] = {}
    for m in validated:
        org.setdefault(m["identity"]["division"], []).append(m["identity"]["id"])

    norm = dict(
        schema_version=S.SCHEMA_VERSION,
        source_commit=commit,
        source_inventory_sha256=hashlib.sha256(INVENTORY.read_bytes()).hexdigest(),
        counts=dict(
            upstream=len(upstream), native=len(native), total=len(validated),
            flagged_sources=len(evidence),
        ),
        reconciliation=dict(
            equation="upstream (279) + native (40) == total (319)",
            holds=(len(upstream) == 279 and len(native) == 40 and len(validated) == 319),
        ),
        all_inert=all(m["governance"]["status"] == "INERT" for m in validated),
        unique_ids=len(set(ids)) == len(ids),
        unique_display_names=len(set(names)) == len(names),
        upstream_provenance_complete=all(
            m["identity"]["source_hash"] and m["identity"]["source_commit"] and m["identity"]["source_path"]
            for m in validated if m["identity"]["source_kind"] == "UPSTREAM"),
        native_carry_no_provenance=all(
            not (m["identity"]["source_hash"] or m["identity"]["source_commit"] or m["identity"]["source_path"])
            for m in validated if m["identity"]["source_kind"] == "KAI_NATIVE"),
        no_human_approval_claimed=all(m["identity"]["reviewed_by"] is None for m in validated),
    )
    return dict(characters=validated, normalization=norm, flagged_evidence=evidence, org_chart=org)


def main() -> int:
    r = build()
    GEN.mkdir(exist_ok=True)
    (GEN / "characters.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "characters": r["characters"]},
                   indent=1, sort_keys=True) + "\n")
    (GEN / "normalization_manifest.json").write_text(
        json.dumps(r["normalization"], indent=1, sort_keys=True) + "\n")
    (GEN / "flagged_evidence.json").write_text(
        json.dumps({"flagged_sources": r["flagged_evidence"]}, indent=1, sort_keys=True) + "\n")
    (GEN / "org_chart.json").write_text(
        json.dumps(r["org_chart"], indent=1, sort_keys=True) + "\n")
    n = r["normalization"]
    print(f"WORKFORCE_NORMALIZED_INERT_LOCALLY: total={n['counts']['total']} "
          f"(upstream={n['counts']['upstream']} + native={n['counts']['native']}); "
          f"reconciliation_holds={n['reconciliation']['holds']}; all_inert={n['all_inert']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
