# KAI Governed Workforce — Traceability Matrix (Integration HEAD)

Integration HEAD `c8f6fdcf` on `feat/kai-governed-workforce-inert-integration`
(base `origin/production` `76137360`). Verdicts from the fresh 10-lens integration
review (all CLEAN). Code is byte-identical to the reviewed `97549b8` for all workforce
paths; this matrix additionally carries the integration-specific rows (I1–I4).

| # | Requirement | Code | Test(s) | Evidence | Verdict |
|---|---|---|---|---|---|
| R1 | Fail-closed 8-part frozen character contract | `workforce/schemas.py` | `test_workforce_schemas.py` | AGENT_CHARACTER_CONTRACT.md `916bf5ea…` | CLEAN (L1,L3) |
| R2 | Reflective autonomy/sentience/placeholder scans; pure-prohibition fields excluded | `schemas.py` `_affirmative_free_text` + `_AUTONOMY_SCAN_EXCLUDED` | `test_workforce_normalization.py` | INTEGRATION_REVIEW_REPORT §2 | CLEAN (L1,L3) |
| R3 | Provenance honesty (UPSTREAM triple / KAI_NATIVE none / reviewed_by null) | `schemas.py`, `normalize.py` | `test_workforce_normalization.py` | NORMALIZATION_REPORT / UPSTREAM_INTAKE | CLEAN (L2) |
| R4 | 279 upstream deterministic from pinned MIT commit; 45 flagged quarantined | `normalize.py` | `test_workforce_normalization.py`, `test_workforce_intake.py` | generated/*.json; inventory `6a70b00c…` | CLEAN (L2) |
| R5 | 40 KAI-native, INERT, no provenance | `normalize.py` | `test_workforce_normalization.py` | KAI_NATIVE_CHARACTERS.md `a5585119…` | CLEAN (L2,L3) |
| R6 | Catalog-only (no execute/dispatch/router/status-change) | `catalog.py` | `test_workforce_catalog.py` | REVIEW §2 | CLEAN (L4) |
| R7 | Catalog returns immutable (get/quarantine_review deepcopy) | `catalog.py` | `test_workforce_catalog.py` | — | CLEAN (L4) |
| R8 | INERT cap at schema + catalog.register | `schemas.py`, `catalog.py` | `test_workforce_schemas.py`, `test_workforce_catalog.py` | — | CLEAN (L1,L4) |
| R9 | Team-sim pure/SoD/tenancy/bounded/deterministic; shared `_cap_pool` | `catalog.py` | `test_workforce_catalog.py` | — | CLEAN (L4) |
| R10 | Deny-by-default; uniform network/device/browser/external-write gate | `schemas.py` | `test_workforce_schemas.py` | AGENT_CHARACTER_CONTRACT §2 | CLEAN (L1,L3) |
| R11 | Hook registry INERT; register pins INERT | `hooks/` | `test_hook_registry.py`, `test_hook_schemas.py` | KAI_HOOKS_MASTER_BUILD_PLAN | CLEAN (L5) |
| R12 | Capability Exchange inert; CONSEQUENTIAL gated | `capability_exchange.py` | `test_capability_exchange.py` | — | CLEAN (L5) |
| R13 | Deploy-hook detector fail-closed (self-contained) | `scripts/hooks/deploy_skill_suggester.py` | `scripts/hooks/test_deploy_skill_suggester.py` | DEPLOY_HOOK_HARDENING.md | CLEAN (L5) |
| R14 | Angular console dark/inert; no network/planning; catalog outputs only | `frontend-pilots/kai-angular/**`, `ui_export.py` | `test_workforce_console_honesty.py`, `test_workforce_ui_export.py` | ANGULAR_CONSOLE_5A.md | CLEAN (L6) |
| R15 | Step-2 deps: pinned lockfile; SBOM bijective+disclosed; bundle inert | `kai-angular/package-lock.json` | `test_workforce_console_honesty.py` (SBOM) | STEP2_DEPENDENCY_ADMISSION.md; sbom `c182ddf8…` | CLEAN (L7) |
| R16 | Ceiling: no migration added; browser flag off | (absence) | ceiling assertions | REVIEW §2 | CLEAN (L8) |
| R17 | Test integrity — teeth mutation-checked | (suite) | mutation checks (L9) | REVIEW §2 | CLEAN (L9) |
| R18 | Scope/hygiene — additive, no unrelated files | (diff) | — | REVIEW §2 | CLEAN (L10) |
| **I1** | **Code equivalence to reviewed `97549b8`** (workforce paths byte-identical) | git diff empty | 186 tests pass identically | REVIEW §2 | CLEAN (L1,L2,L10) |
| **I2** | **Additive-only vs production** (75 files, all `A`) | git diff --name-status | — | REVIEW §2 | CLEAN (L10) |
| **I3** | **No unrelated inherited files / no ledger / no machine paths** | (added set) | — | REVIEW §2 | CLEAN (L10) |
| **I4** | **Single Alembic head `0008`, no fork; no migration added** | `backend/alembic` unchanged | — | BASE_RECONCILIATION §4 | CLEAN (L8) |

**Summary:** 18 workforce requirements + 4 integration properties, all CLEAN at
`c8f6fdcf`. Full suite: +186 workforce tests pass, 0 transplant-caused regressions.
