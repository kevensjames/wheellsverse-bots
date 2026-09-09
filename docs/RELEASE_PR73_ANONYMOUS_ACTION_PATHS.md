# RELEASE RECORD — PR #73, anonymous action paths and the auth fail-open

**Status: `PRODUCTION_ANONYMOUS_ACTION_PATHS_CONTAINED` — frozen.**

No secret value appears in this document, in the branch, in the diff or in the commit messages.
Credentials are identified only by salted, truncated SHA-256 fingerprints.

---

## 1. Identity

| Field | Value |
|---|---|
| Production SHA | `024368f6d6a54e0cee7f40630b7d020a11f49db4` |
| Parents | `29d90b51f7d76f53ca99c57fbc2fb8d19bdf8add` (previous production) + `7d2d24792820f18dfb7c55c016177926e4c181a1` (branch head) |
| Tree | `4d2dc0f576dbbc434810e31245f5519e11a4431f` |
| PR | #73, merged **2026-09-09T04:16:33Z** by `kevensjames` |
| Branch | `hotfix/admin-auth-foundation` |
| Base at branch creation | `29d90b51` (verified unmoved immediately before merge) |

### Commits

```
7d2d24792820f18dfb7c55c016177926e4c181a1  fix(security): replace broad public prefixes and gate NarAI actions
9ccf6621425dda24e5a503c50056f0da06117797  fix(security): fail closed on missing auth config; never accept a URL credential
```

### Changed files

```
M  core/api.py                            +212/-16
M  core/operator_session_web.py            +19/-9
A  tests/test_admin_auth_foundation.py    +286/-0
A  tests/test_public_route_rules.py       +312/-0
M  tests/test_operator_session_web.py      +17/-5
M  tests/test_scheduler_boundary.py        +61/-28
```

Zero SOL-owned files. Zero unrelated files.

## 2. Provenance

| Field | Value |
|---|---|
| App A deployment | **`4b4586e2-6ffd-4a43-bc1e-8c4b65ce27fa`** · SUCCESS · 2026-09-09T04:16:35Z |
| Its `commitHash` | `024368f6d6a54e0cee7f40630b7d020a11f49db4` — **matches the merge commit exactly** |
| Branch | `production` |
| Source | `kevensjames/wheellsverse-bots`, Git-integrated |
| Staging candidate | `kai-appA-staging`, deployment `f3cd55d1-1125-4e65-a3de-a5b25f338aeb`, from branch head `7d2d2479` |

The staging candidate and the merged tree are the same content: the merge commit's tree
`4d2dc0f576dbbc434810e31245f5519e11a4431f` is identical to the branch head's tree, so the merge
introduced nothing that staging had not already certified.

Unlike the previous incident, this deployment carries a real `commitHash`. Provenance rests on
platform attestation, not on a file-level comparison.

## 3. What was wrong

**Anonymous action paths.** `api_key_middleware` decided public access with `path.startswith(p)`.
A prefix is not a path: `"/api/narai/run"` exempted every route beginning with those characters,
including `POST /api/narai/run_bot`, which nobody exempted on purpose.

Measured with the gate live, anonymously — the handlers **ran**:

```
POST /api/narai/run_bot   -> 200   (138 bots loaded, trigger attempted)
POST /api/narai/revenue   -> 200   (RevenueLoop executed)
```

`/api/narai/run` was never a customer endpoint: *"Run one full NarAI autonomous cycle in the
background — State → Goal → Plan → Execute → Evaluate → Learn."*

**Auth fail-open.** Both gates began `if not _API_KEY: return`. `_API_KEY` is read once at import,
so an unset variable un-gated the whole owner surface for the life of the process, silently. The
incident response had rotated that variable twice.

## 4. What changed

`_PUBLIC_API_PREFIXES` is replaced by `PUBLIC_API_RULES` — a frozen table of `PublicRule(path,
methods, descendants, purpose)`. `_public_rule_for()` is the one matcher, used by the middleware and
`verify_api_key`. Matching is exact, or descendant across a `/` boundary; never a character prefix.
`_norm_path()` collapses duplicate slashes and resolves `.`/`..`. Percent escapes are deliberately
**not** decoded. Method comparison is exact, not upper-cased.

`auth_config_state()` is the single auth-config decision, consulted by all three gates:
`DEV_OPEN` only for a declared local environment; `MISCONFIGURED` → 401 for hosted, unset or
unrecognised. `?api_key=` is removed in every configuration.

## 5. Production refusal matrix

Verified after deployment with **refusal probes only**. No action handler was invoked at any point,
during discovery or verification.

| Request | Result |
|---|---|
| `POST /api/narai/run` | **401** |
| `POST /api/narai/run_bot` | **401** |
| `POST /api/narai/revenue` | **401** |
| `GET /api/store/redeliver` | **401** |
| `POST /api/narai/run_probe` | **401** (was an exempt 404) |
| `POST /api/narai/revenue_probe` | **401** |
| `POST /api/narai/status_probe` | **401** |
| `POST /api/store/redeliver_probe` | **401** |
| `POST /api/narai/status/full` | **401** |
| `GET /api/narai/schedules` | **401** (earlier containment holds) |
| `/admin/ceo` `const API_KEY` | **empty** (earlier containment holds) |
| `GET /api/narai/status` | 200 — keys `category, last_run, name, run_count, status` |
| `GET /api/health` | 200 — `auth_config: OK` |
| `GET /admin/ui-config` | 200 |

Reachability on production was established **only** with non-existent descendants, which cannot
execute anything.

## 6. Tests and mutants

`tests/test_public_route_rules.py` (107 checks) and `tests/test_admin_auth_foundation.py` (84).

Nine unauthorized identities × four action routes; verifier refused on all; sibling names and
descendants across five suffixes; every HTTP method; method-override headers; ten path shapes; the
auth-config truth table; and the bounded status contract.

**Nothing runs**: spies over `get_narai_core`, `subprocess.Popen`, `subprocess.run` and
`urllib.request.urlopen` assert that no refused request entered a handler, shelled out, or opened a
socket.

Mutants killed — twelve:

| Mutant | Result |
|---|---|
| matcher reverts to prefix matching | 2 failed |
| `descendants` flag ignored | 1 failed |
| method check dropped | 2 failed |
| `/api/narai/run` re-added as public | 13 failed |
| path normalisation removed | 5 failed |
| status reduction removed | 1 failed |
| `verify_api_key` early return restored | 2 failed |
| `require_admin_json` early return restored | 30 failed |
| unknown `APP_ENV` treated as dev | 46 failed |
| config wrapper fails open | 1 failed |
| URL credential path restored | 10 failed |
| readiness signal removed | 2 failed |

Two of these **survived the first pass** and are the reason the matcher is tested directly rather
than only through the app: dropping the method check passed because FastAPI answers 405 for an
unrouted method, and removing path normalisation passed because TestClient normalises before the app
sees it. A guard that sits below the framework must be tested below the framework.

**Regression:** `tests/` 931 passed / 44 failed — the 44 byte-identical to the same run on untouched
`29d90b51`. Zero new failures. 895 routes, 12 public rules. All frontend node suites pass.

**CI:** `Workers Builds` failed exactly as it does on the `29d90b51` baseline (pre-existing).
Cloudflare Pages, `ingest`, the Cursor Approval Agent and the **Cursor Security Agent** all passed.

## 7. State unchanged by this release

| | Before | After |
|---|---|---|
| Proposals | 11 (2 executed / 9 proposed) | 11 (2 executed / 9 proposed) |
| Nonce rows | 0 | 0 |
| Migration | `0007_add_holding_action_nonces` | `0007_add_holding_action_nonces` |
| Timeline rows | 15 | 15 |
| Worker jobs | 0 | 0 |
| **Eight authority flags** | **0 ON** | **0 ON** |
| App A / App B health | 200 / 200 | 200 / 200 |

No bot was run, no revenue loop started, no redelivery sent, no scheduler job triggered.

## 8. Credential reflection

71,468 B of diff plus commit messages scanned against all nine known credential fingerprints:
**0 plaintext secrets, 0 connection strings.** The PR body and this record are likewise clean.

## 9. Rollback and recovery

> ⚠ **The credential-publishing deployments are NOT valid rollback targets.**
> `f0d5527a-7121-47d5-8593-d62b23f0db43`, `6e54483d-6b24-418c-be61-ed87d91c35ab`,
> `c81a3b11-d096-4fa5-8c1c-53215ae2e568` and every App A deployment created before `f064fe2e`
> contain `_serve_old_dashboard()` with the owner-key substitution intact. Redeploying any of them
> would publish the **currently active** owner key to anonymous callers.
> They remain **HISTORICAL PRE-INCIDENT — SECURITY-UNSAFE, DO NOT REDEPLOY.**

| # | Action | Identity |
|---|---|---|
| 1 | Redeploy the immediately preceding **contained** artifact | `b6fec152-735c-42b6-b66f-dac47a256a4e` (from `29d90b51`) — has the credential fix and the scheduler fix, but **not** the action-path fix, so the anonymous NarAI action paths reopen |
| 2 | Revert PR #73 on `production` and let the Git deployment rebuild | keeps provenance; same caveat as (1) |
| 3 | If neither can serve | disable `/api/narai/*` and `/api/store/*` at the edge, or put the admin surface into maintenance mode |
| 4 | **Never** | redeploy anything older than `f064fe2e` |

Rolling back reopens anonymous `POST /api/narai/run_bot` and `/api/narai/revenue`. Prefer a
forward fix.

No database change accompanies this release, so there is no migration to reverse. Rollback is
code-only and does not restore the retired credential leak, because both remaining candidates
post-date it.

## 10. Carried forward

| Sev | Item |
|---|---|
| HIGH | `_PUBLIC_PATHS` — exact-match and free of the prefix defect, but contains action entries: `/api/narai-autopilot/start`, `/api/narai-autopilot/stop`, `/api/factory/reset`. Under audit. |
| HIGH | Reported unauthenticated OS-command-execution finding in an unmerged Aikido PR. Under audit. |
| MED | **Customer-facing regression:** `/api/store/redeliver` is now owner-only. Its docstring describes a real customer self-serve flow and Shopify is configured on production, so a customer can no longer re-request a paid order's files. Restoration is designed separately — authenticated customer session, order-ownership check, destination fixed from the order, idempotency, rate limits, audit, enumeration-safe responses. Not a one-line exemption. |
| MED | The two macOS Login Items that bind `0.0.0.0:5050` / `:5051` will restart at next login until disabled. |
| LOW | `/api/narai/status` reduced to five keys; the full payload is owner-gated at `/api/narai/status/full`. |
