# KAI Governed Workforce — Transplant Manifest

Source (frozen, reviewed): `feat/kai-hook-foundation-phase1` @ impl HEAD `97549b8`
(docs tip `74d3658`, tag `kai-workforce-reviewed-local-74d3658`).
Target base: `origin/production` @ `76137360` (continuous fast-forward from the
last-known prod head `b486a138`; `main` is a divergent positioning branch and is
NOT authoritative).
Candidate range: `origin/production..97549b8` = **44 linear commits** (0 merges).

**Dependency-closure proof:** the reviewed workforce/hooks/capability code imports
ONLY from within its own packages (`app.services.workforce.schemas`,
`app.services.hooks.*`; `capability_exchange.py` imports no `app.*`). "tenant"
references are self-contained manifest-field logic in `catalog.py`, not an import of
`app.services.tenancy`. The deploy-skill-suggester imports only `re`/`sys`.
Therefore tenancy, Stage-0 auth, and audit-drift are NOT code dependencies.

**Additivity proof:** the INCLUDE set touches 75 distinct files; **0** already exist
in `origin/production` → the transplant is 100% additive (no production file is
modified or overwritten; no production security fix can be clobbered).

## Decisions

| # | SHA | Purpose | Category | Prod has equiv? | Decision | Evidence |
|---|-----|---------|----------|-----------------|----------|----------|
| 1 | d2116888 | Sol-UI checkout safeUrl | sol-ui (unrelated) | n/a | **EXCLUDE** | touches only `frontend/sol`; no workforce dep |
| 2 | 3a9da005 | FreeLLMAPI gateway | freellmapi (unrelated) | n/a | **EXCLUDE** | backend adapters/router/docker/env; not imported by workforce |
| 3 | b58d5c7a | FreeLLMAPI task tracking | freellmapi (unrelated) | n/a | **EXCLUDE** | `data/operator-tasks.json` only |
| 4 | bfe16a1c | Claude Code dev hooks P0-P2 + Angular spec | dev-tooling (mixed) | n/a | **EXCLUDE** (scoped-extract `docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md`) | hooks are dev-time, not imported/deployed; deploy-suggester self-contained; `.gitignore` change is `.kai-*` dev markers only; spec is referenced by the console README (doc link) |
| 5 | 9f78176b | stop-guard WARN-only | dev-tooling | n/a | **EXCLUDE** | `scripts/hooks` dev hook fix |
| 6 | fc5fd2cb | Stage-0 audit router drift | Stage-0 audit | (separate) | **EXCLUDE** | `audit/auditor.py`; not imported by workforce; workforce mounts 0 routes so drift-guard irrelevant to it |
| 7 | 67fc8deb | inert capability_exchange registry | capability-exchange | absent | **INCLUDE** | reviewed R12; `capability_exchange.py` imports no `app.*` |
| 8 | 2f3383fd | DARK Angular skeleton | Angular console | absent | **INCLUDE** | R14 base |
| 9 | a194dbac | repin Angular 17→22 | Angular console | absent | **INCLUDE** | prereq of console build |
| 10 | c69c4dfd | capability-exchange LOW fixes | capability-exchange | absent | **INCLUDE** | R12 |
| 11 | ccef12b7 | hooks + capability plans | docs (hooks/capability) | absent | **INCLUDE** | KAI_HOOKS_MASTER_BUILD_PLAN + capability research |
| 12 | d0b80fd7 | hooks Phase-1 unit#1 (EventEnvelope/HookDefinition) | hooks | absent | **INCLUDE** | R11 |
| 13 | d50ccd46 | ledger: reconciliation/Phase-1 status | docs (ledger) | absent | **EXCLUDE** | pure Stage-0/planning ledger prose; ledger rebuilt coherently during conflict resolution |
| 14 | 65d56eff | ledger: operator decisions | docs (ledger) | absent | **EXCLUDE** | pure planning ledger prose |
| 15 | 438ab6d4 | ledger: Stage-0 reconciliation | docs (ledger, Stage-0) | absent | **EXCLUDE** | Stage-0-auth-specific ledger prose |
| 16 | 5ca24296 | Stage-0 auth L1 (?token=) + L2 (CSRF) | Stage-0 security | prod lacks `csrf_origin.py` | **EXCLUDE** | not imported by workforce; touches `main.py`/middleware/deps → would risk overwriting prod auth; UNMERGED security — flag for separate owner landing |
| 17 | a995af94 | ledger: mark L1/L2 applied | docs (ledger, Stage-0) | absent | **EXCLUDE** | documents excluded #16; would misleadingly claim auth applied |
| 18 | 5ab1508b | tenancy foundation (workspace model + service) | tenancy | absent | **EXCLUDE** | not imported by workforce (self-contained tenant-field logic); touches `models/__init__.py`; migration withheld; separate foundation |
| 19 | 6b70d517 | hooks Phase-1 unit#2 (inert registry) | hooks | absent | **INCLUDE** | R11 |
| 20 | 57f20008 | workforce Phase-0 master plan | docs (workforce) | absent | **INCLUDE** | controlling plan |
| 21 | e888ae28 | HookRegistry catalog-only | hooks | absent | **INCLUDE** | R11; also edits ledger (resolve) |
| 22 | b4091090 | workforce controlling companions (§0 hashes) | docs (workforce) | absent | **INCLUDE** | the 5 hash-reconciled companions |
| 23 | 8b91ab0b | capability-exchange catalog-only split | capability-exchange | absent | **INCLUDE** | R12 |
| 24 | a4ac703c | catalog test allowlist hardening | tests | absent | **INCLUDE** | test teeth |
| 25 | 1560b85f | workforce Phase-1 schemas | workforce | absent | **INCLUDE** | R1 |
| 26 | 1d112a88 | workforce Phase-2 upstream intake | workforce | absent | **INCLUDE** | R4 |
| 27 | 32e17101 | Phase-2 review Unit-1 | workforce | absent | **INCLUDE** | R4 |
| 28 | 8f837584 | deploy-skill-suggester (Phase-2 U2) | hooks (detector) | absent | **INCLUDE** | R13; self-contained (`re`/`sys`) |
| 29 | 95449118 | Unit-2 review fixes | hooks (detector) | absent | **INCLUDE** | R13 |
| 30 | db947193 | workforce Phase-3 (319 manifests) | workforce | absent | **INCLUDE** | R2/R4/R5 |
| 31 | 2bad9a81 | Phase-3 review fixes | workforce | absent | **INCLUDE** | R2 |
| 32 | c9841978 | workforce Phase-4 catalog | workforce | absent | **INCLUDE** | R6; also edits ledger (resolve) |
| 33 | fbef8ea4 | Phase-4 5-lens fixes | workforce | absent | **INCLUDE** | R6/R9; also edits ledger (resolve) |
| 34 | 9eb03398 | canonical order-invariant proposals | workforce | absent | **INCLUDE** | R9 |
| 35 | a9f9679c | Phase-5A Angular console | Angular console | absent | **INCLUDE** | R14 |
| 36 | eb5ada66 | Phase-5A UI-honesty/security fixes | Angular console | absent | **INCLUDE** | R14 |
| 37 | ea1c2293 | Phase-5A re-review test teeth | tests | absent | **INCLUDE** | R14/R17 |
| 38 | 49361f03 | Step-2 dependency admission | Angular console + evidence | absent | **INCLUDE** | R15 |
| 39 | a72e5a3f | final-review r1 | workforce | absent | **INCLUDE** | review fixes |
| 40 | 871c5c8c | final-review r2 | workforce | absent | **INCLUDE** | review fixes |
| 41 | 7f5458da | final-review r3 (reflective scan) | workforce | absent | **INCLUDE** | review fixes |
| 42 | 1a019a90 | final-review r4 | workforce | absent | **INCLUDE** | review fixes; also edits ledger (resolve) |
| 43 | 589dd0e9 | final-review r5 | workforce | absent | **INCLUDE** | review fixes |
| 44 | 97549b83 | final-review r6 | workforce | absent | **INCLUDE** | review fixes |

**INCLUDE = 32 commits** (7,8,9,10,11,12,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44).
**EXCLUDE = 12 commits** (1,2,3,4,5,6,13,14,15,16,17,18) + scoped-extract ANGULAR_CAPABILITY_SPEC.md from #4.

## Excluded-but-notable (separate owner-landable work, NOT required by workforce)
- **Stage-0 auth hardening** (5ca24296): L1 `?token=` URL-auth removal + L2 CSRF origin
  middleware. Production's backend lacks `csrf_origin.py` — this is genuinely unmerged
  security. Recommend the owner land it separately (it touches `main.py`/middleware and
  is unrelated to the inert workforce).
- **Tenancy foundation** (5ab1508b): workspace/org model + `tenancy.py` (migration
  withheld). Not needed by the inert workforce; land separately if tenancy is wanted.
- **Stage-0 audit drift guard** (fc5fd2cb): `auditor.py` router-coverage guard.
- **Claude Code dev hooks** (bfe16a1c/9f78176b): dev-time governance guards; not app code.

## Dependency closure
The INCLUDE set is closed: every included commit's code depends only on other included
commits (workforce/hooks/capability packages + their tests + controlling docs). No
included commit imports auth/tenancy/audit/sol-ui/freellmapi. Verified additive (0
production files touched).

## Expected conflicts (internal to the cherry-pick sequence)
`docs/kai/plans/REQUIREMENTS_LEDGER.md` — created by an excluded commit (d50ccd46) and
edited by included commits (e888ae28, c9841978, fbef8ea4, 1a019a90). Resolve by
building a coherent workforce/hooks/capability ledger (no Stage-0-auth/tenancy "applied"
claims); record each resolution. Possibly `.gitignore` if an included commit touches it
(none do). All other included files are net-new → clean adds.
