# KAI Governed Workforce — Base Reconciliation Report

## 1. Source freeze
- Reviewed branch `feat/kai-hook-foundation-phase1`, impl HEAD `97549b8`, docs tip
  `74d3658`, status `WORKFORCE_INDEPENDENTLY_REVIEWED_LOCALLY`.
- Local annotated milestone tag `kai-workforce-reviewed-local-74d3658` → `74d3658`
  (not pushed). Branch NOT rebased/amended/squashed/reset — frozen.

## 2. Production authority (Phase 1.4–1.6)
- `origin/production` = **`76137360`** (2026-09-11, "fix(loops)… (#83)"). Authoritative
  deploy/hotfix/release line; CI-gated (`ci/phase0-gate-on-production`).
- `origin/main` = `38461cf1` (2026-09-10, docs positioning) — **divergent**, NOT
  authoritative (merge-base with production `e830e16f`; production +287 / main +41;
  neither is an ancestor of the other).
- **Continuity confirmed:** the last-known prod head `b486a138` (PR #82) is an ancestor
  of `76137360` (clean fast-forward). No fork → authority unambiguous → no STOP.

## 3. Ancestry
- merge-base(production, reviewed 97549b8) = `a172205c` (2026-07-14).
- Candidate range `origin/production..97549b8` = **44 linear commits** (0 merges).
- 278 commits on production not in reviewed (production advanced far ahead).

## 4. Alembic reconciliation (Phase 3.7 — do NOT assume 0006)
- Production alembic = single linear head chain `0000 → … → 0006_add_kai_api_keys →
  0007_add_holding_action_nonces → **0008_add_kai_devices**` (single head, **no fork**).
- Production's `0006_add_kai_api_keys.py` is **byte-identical** to the reviewed branch's
  `0006` (sha `5dad08f5…`) → shared ancestor; production advanced 0006→0008.
- The transplant added **no** migration (`git diff 76137360..integration -- backend/alembic`
  is empty). **Reconciled head = `0008_add_kai_devices`**, unchanged. No duplicate revision.

## 5. Additivity (Phase 4)
- Integration diff `origin/production..HEAD` = **75 files, 100% additive** (all `A`;
  zero `M`/`D`). No production file modified or overwritten → no production-base security
  fix can be clobbered.
- Every path is workforce-scoped: `backend/app/services/{workforce,hooks,capability_exchange.py}`,
  `backend/tests`, `frontend-pilots/kai-angular`, `docs/{workforce,kai,kai-frontend}`,
  `scripts/hooks/{deploy_skill_suggester,test_…}`. **No unrelated inherited file entered**
  (no sol-ui, freellmapi, stream_auth/csrf/middleware, tenancy/workspace, services/audit,
  Claude Code dev-hooks, .claude/settings.json, node_modules/dist).
- Workforce/hooks/capability/console CODE is **byte-identical** to reviewed `97549b8`
  (empty tree diff for those paths). All 7 generated artifacts + 5 controlling-doc hashes
  match the reviewed values.

## 6. Full-suite regression — baseline vs integration (no transplant regression)
Same DB + venv, full backend suite (`-o addopts=""`):
- **Baseline** (`origin/production`, no transplant): 137 failed / **723** passed / 19 errors.
- **Integration** (`c8f6fdcf`): 137 failed / **909** passed / 19 errors.
- Failure sets **identical** (156 == 156; delta both directions = 0). Integration adds
  exactly **+186 passing** tests = the workforce/hooks/capability/console suites.
- The 156 pre-existing failures are environment-dependent (auth `403` — local auth not
  configured; `composio` — missing keys/deps) and present on BOTH → **not** transplant-caused.
  Zero workforce/hooks/capability tests are among them.

## 7. Excluded inherited work (NOT required by the workforce; flagged for the owner)
Proven not code-dependencies (reviewed code imports only its own packages):
- **Stage-0 auth hardening** `5ca24296` (L1 `?token=` removal + L2 `CsrfOriginMiddleware`)
  — production's backend lacks `csrf_origin.py`; genuinely unmerged security. Recommend a
  SEPARATE owner landing (touches `main.py`/middleware/deps; unrelated to the inert workforce).
- **Tenancy foundation** `5ab1508b` (workspace/org model + `tenancy.py`; migration withheld).
- **Stage-0 audit drift guard** `fc5fd2cb` (`auditor.py`).
- **Claude Code dev hooks** `bfe16a1c`/`9f78176b` (dev-time governance guards; not app code).
  Only `bfe16a1c`'s `ANGULAR_CAPABILITY_SPEC.md` was scoped-extracted (console README ref).
- **Sol-UI** `d2116888`, **FreeLLMAPI** `3a9da005`/`b58d5c7a` — unrelated inherited features.
- The KAI-wide `REQUIREMENTS_LEDGER.md` was dropped from the transplant (out of scope;
  entangled with Stage-0/tenancy/auth; workforce controlling docs live in `docs/workforce/`).

## 8. Cherry-pick conflicts + resolutions (Phase 3.5)
Only conflict class: `docs/kai/plans/REQUIREMENTS_LEDGER.md` (modify/delete) at the 4
included commits that also edit it (`e888ae28`, `c9841978`, `fbef8ea4`, `1a019a90`) —
its creator (`d50ccd46`) was excluded, so the file is absent in the integration branch.
**Resolution:** drop the ledger from each (keep the commit's code), consistent with the
scoping decision. All code files applied cleanly; the workforce-path trees are byte-identical
to `97549b8`. No wholesale ours/theirs resolution was used.
