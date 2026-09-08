# INCIDENT 2026-09-08 — anonymous owner-key exposure and open scheduler control

**Status: CONTAINED AND ROTATED.** Production and staging patched, credentials rotated, old
credentials and old sessions proven rejected.

No secret value appears in this document, in the commits, in the diff, or in any artifact produced
during the response. Credentials are identified only by salted, truncated SHA-256 fingerprints.

---

## 1. What was wrong

### 1a. The owner API key was served to anonymous callers

`core/api.py::_serve_old_dashboard()` substituted the live owner API key into the dashboard HTML:

```python
if _API_KEY:
    html = html.replace("const API_KEY = '';", f"const API_KEY = '{_API_KEY}';")
```

| Environment | Route | HTTP | Bytes | Key |
|---|---|---:|---:|---|
| production | `GET /admin/ceo` | 200 | 33,764 | POPULATED len=32 · fp `063fb42b756c00d0` |
| production | `GET /admin/legacy` | 200 | 1,108,228 | same fingerprint |
| staging | `GET /admin/ceo` | 200 | 33,796 | POPULATED len=64 · fp `7eebb068cfd08f88` |
| staging | `GET /admin/legacy` | 200 | 1,108,260 | same fingerprint |

All four measured with **no credential presented**. Production and staging carried **different**
keys, so both families were treated as compromised.

A **third** route was found by a route sweep rather than by inspection: `/admin` reaches the same
function whenever `WHEELLSVERSE_COMMAND_CENTER` is off. Production had it on, which is why an
inspection of `/admin` looked clean there — a single config change would have exposed it.

**Authority reachable from that key — full owner compromise, not a read leak:**

- `verify_api_key` accepts it as `X-API-Key` across the owner `/api/*` surface, **writes included**;
- `core/api.py:146` passes it as the session `owner_key`, so
  `POST /admin/session/login {"secret": <key>}` **mints an owner session cookie**;
- `resolve_secret` maps it to `ROLE_OWNER` = `ALL_SCOPES` — read, write, high_impact, financial,
  destructive, kai.chat, **kai.ultra** — so it also reaches App B through the bridge.

**Introduced:** pre-existing; present at `5e767a4` (the pre-PR#70 production parent).

### 1b. The NarAI scheduler accepted anonymous reads *and* mutations

| Route | Effect |
|---|---|
| `GET /api/narai/schedules` | 17 schedules: id, name, description, category, frequency, day, time, enabled, last_run, last_status, run_count, next_run, **`trigger_fn`** (internal Python path) |
| `GET /api/narai/schedules/stats` | totals |
| `PATCH /api/narai/schedules/{id}` | **enable/disable a schedule, change its run time** |
| `POST /api/narai/schedules/{id}/trigger` | **run a job now** |

Control: `/api/scheduler/jobs`, the same `/api` surface without an exemption, answered 401.

**Two independent exemptions**, which is why fixing either alone would have looked like a fix:

1. `_PUBLIC_PATHS.add("/api/narai/schedules")` — exact path, exempting the list.
2. `_PUBLIC_PREFIXES` contained `"/api/narai/schedules"` **without a trailing slash**, and the
   middleware tests it with `path.startswith()`. One missing character exempted the whole subtree,
   PATCH and trigger included. Every neighbouring entry ends in `/` for exactly this reason.

---

## 2. What was changed

Branch `hotfix/production-owner-key-and-scheduler-containment`, from production `073c9a46`.

| Commit | Change |
|---|---|
| `2b21d1b4` | Deleted the key substitution. Removed `ceo.html`'s three routes to a browser-held key: the server injection, a `?key=` URL parameter, and a `prompt()` that wrote to `sessionStorage`. The page authenticates by session cookie. |
| `868e320e` | Removed both scheduler exemptions. Added an explicit verifier refusal on the two consequential routes. Made an unreadable scheduler state file report `UNAVAILABLE` instead of fabricating `run_count: 0 / last_status: "never"`. |

The key is **not** restored under authentication. An authenticated owner does not need the server's
own credential in browser JavaScript, where it reaches sessionStorage, localStorage, extensions,
screenshots and any XSS.

Containment reuses the existing boundary — no new authority system. `operator_session_enabled` is
`true` in both environments and `verify_api_key` already accepts an owner session, so the pages keep
working with no key in the page.

**Tests:** 145 checks across two new suites, plus 53 scheduler checks. Seven identities × nine admin
pages for credential bytes; a sweep asserting no GET route in the app serves the key; eight
unauthorized identities against every scheduler route; dispatcher and writer tripwires proving no
unauthorized call reached them. Every guard mutation-tested.

**Regression:** `tests/` 739 passed / 44 failed — the 44 byte-identical to the same run on untouched
`073c9a46`. Zero new failures. All frontend node suites pass.

---

## 3. Deployment record

| Field | Value |
|---|---|
| Source SHA deployed | `868e320e7f620c0935f89e2c17cf1e8e5e0356e6` |
| Staging App A deployment | `7ab3d2ab-64b3-4748-8a04-bd104f9d307b` (SUCCESS 2026-09-08T22:26:52Z) |
| Production App A deployment | `f064fe2e-58f4-4f4f-9e57-90c6f6304bf1` |
| **Production rollback target** | `f0d5527a-7121-47d5-8593-d62b23f0db43` (SUCCESS 2026-09-08T04:26:17Z) |
| Image digests | **UNAVAILABLE** — App A is deployed by `railway up` (CLI upload, NIXPACKS), not a git-integrated build, so no image digest or attested SHA is exposed by the platform. Binding evidence is the deployment id plus the uploaded tree having been a clean checkout of `868e320e`. |

A single 502 was observed on production during the deploy swap and once during the credential
redeploy. Both are the expected fail-closed window.

---

## 4. Rotation

Rotated **only what fingerprint evidence proved exposed**, plus the session secret required to
invalidate anything the leaked key could have minted.

| Environment | Variable | Consumers updated | Old fp → New fp |
|---|---|---|---|
| production | `API_KEY` | App A `wheellsverse-v2` | `063fb42b756c00d0` → `c0a5890d833d104c` |
| production | `SESSION_SIGNING_SECRET` | App A, App B `kai-prod`, monitor `kai-prod-monitor` | `4e179623bb767266` → `96065a2cc60b143d` |
| staging | `API_KEY` | `kai-appA-staging` | `7eebb068cfd08f88` → `6073eb5d28194084` |
| staging | `SESSION_SIGNING_SECRET` | `kai-appA-staging`, `kai-staging` | `9f70c45e2e4b53fe` → `2dd83ae29b26e952` |

**Deliberately NOT rotated:**

- **App B production `API_KEY`** (fp `b043ac441b3cb1f9`). It is a *different* 64-char credential from
  App A's exposed 32-char key. Fingerprint evidence proves it was not the value served, so rotating
  it would have been unevidenced churn.
- `RELEASE_VERIFIER_SIGNING_SECRET`, database, Redis and provider credentials — none appeared in any
  served response.

**Method.** New secrets generated with `secrets.token_hex(32)` straight into mode-0600 files, set
with `railway variable set --stdin` so no value ever appeared on a command line or in shell history.
Redeploy order App B → App A → monitor, to keep the shared session secret matched for as short a
window as possible. Staging was rotated first as a rehearsal of the exact procedure.

**Monitor caveat:** `kai-prod-monitor` is a `*/5` cron service with no long-running deployment, so it
cannot be redeployed. Its variable is set and it picks the new secret up on its next scheduled run.
Until then its authenticated probes fail closed.

**Proof of revocation** (production):

```
old API key   -> 401      new API key   -> 200      anonymous -> 401
session minted with OLD signing secret -> 401
session minted with NEW signing secret -> 200
```

Staging showed the same transition. All seven temporary secret files were shredded; a rescan of
3,446 session artifacts found zero occurrences of any old or new key material.

---

## 5. Post-containment verification

| Check | Result |
|---|---|
| `/admin/ceo` carries no owner credential | ✅ `const API_KEY` empty |
| `/admin/legacy` carries no owner credential | ✅ empty |
| `/admin`, `/admin/hub`, `/admin/command` | ✅ assignment absent |
| Scheduler GET / stats / PATCH / trigger, anonymous | ✅ 401 / 401 / 401 / 401 |
| Old API key rejected · new accepted | ✅ 401 / 200 |
| Old owner session rejected · new accepted | ✅ 401 / 200 |
| Proposals unchanged | ✅ 11 total — 2 executed, 9 proposed |
| Nonce rows unchanged | ✅ 0 |
| Migration unchanged | ✅ `0007_add_holding_action_nonces` |
| Timeline / worker jobs | ✅ 15 / 0 |
| No unexpected job executed | ✅ worker jobs 0; tripwire tests proved no unauthorized dispatch |
| Eight authority flags | ✅ 0 ON |
| App A / App B health | ✅ 200 / 200 |
| Browser, desktop + 390px | ✅ `API_KEY` empty in the live page; sessionStorage and localStorage both empty; new sign-in banner renders |
| Credential reflection in diff, commits, artifacts | ✅ zero |

Browser console showed 7 errors on both viewports: a **pre-existing** CSP block on the three.js CDN
script, and 401s from the anonymous API calls, which are the correct signed-out behaviour.

---

## 6. Residuals — recorded, not fixed

| Sev | Item |
|---|---|
| HIGH | `require_admin_json` **fails OPEN** when `API_KEY` is unset: it returns before any check, and `_API_KEY` is read once at import, so an unset variable silently un-gates the admin JSON surface for the life of the process. |
| HIGH | `resolve_api_key` accepts `?api_key=` in the URL when `OPERATOR_SESSION_ENABLED` is off. That flag is `true` in both environments today, so the path is inert — but it is the documented rollback state, and a rollback would re-enable URL-borne credentials. |
| MED | `/api/narai/status` is anonymous on production (200, 2,014 B: env, mood, mind, skills, `last_report_summary`, `run_count`). Same `_PUBLIC_PREFIXES` mechanism, outside this authorization. |
| MED | Three further prefix entries lack a trailing slash and therefore exempt whole subtrees: `/api/narai/run`, `/api/narai/revenue`, `/api/store/redeliver`. Pinned by test as a known set so a fourth cannot appear quietly. |
| LOW | `/api/settings` masks secrets as `"***" + val[-4:]`, exposing a 4-character suffix to an owner-authenticated caller. |
| LOW | App A is not git-integrated, so no deployment can attest its own source SHA. |

---

## 7. What this response did not do

- Did not rotate any credential without fingerprint evidence of exposure.
- Did not execute, approve or mutate a production proposal.
- Did not trigger a real scheduled job. Write-path tests use a deliberately non-existent id.
- Did not run a scanner.
- Did not print, store or commit any secret value.
- Did not touch `hotfix/kai-admin-capability-auth` (four commits, preserved, unpushed).
- Did not expand scope to the residuals above.
