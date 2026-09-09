# INCIDENT 2026-09-08 — anonymous owner-key exposure and open scheduler control

**Status: `INCIDENT_CONTAINED_PENDING_GIT_RECONCILIATION`**

Production and staging are patched, credentials are rotated, and old credentials and old sessions are
proven rejected. The incident is **not** closed: the serving artifact has no Git provenance until the
incident PR merges, and the monitor has not yet been observed recovering.

---

## 0. ⚠ CORRECTED — the rollback target named in the first draft was unsafe

An earlier version of this document named App A deployment
`f0d5527a-7121-47d5-8593-d62b23f0db43` as the "rollback target". **That was wrong and dangerous, and
the statement is superseded here rather than deleted.**

`f0d5527a` contains `_serve_old_dashboard()` with the credential substitution intact. Redeploying it
now — after rotation — would publish the **newly rotated** owner key to anonymous callers, recreating
the incident with the replacement credential.

> **`f0d5527a-7121-47d5-8593-d62b23f0db43` — HISTORICAL PRE-INCIDENT DEPLOYMENT — SECURITY-UNSAFE,
> DO NOT REDEPLOY.**
>
> The same designation applies to every App A deployment created before `f064fe2e`, including
> `6e54483d-6b24-418c-be61-ed87d91c35ab` and `c81a3b11-d096-4fa5-8c1c-53215ae2e568`: all predate the
> fix and all contain the publishing implementation.

### Safe recovery hierarchy

| # | Action | Identity |
|---|---|---|
| 1 | **Redeploy the currently contained artifact** — the primary recovery reference | App A deployment **`f7b56e12-3522-492e-8166-baa1f92de4f9`** (SUCCESS, 2026-09-08T22:49:44Z) |
| 2 | Deploy the Git-reconciled identical artifact | the merge commit of the incident PR, once its tree is proven identical |
| 3 | If neither can serve | disable `/admin/ceo`, `/admin/legacy` and the `/api/narai/schedules` subtree, or put the administrative surface into maintenance mode |
| 4 | **Never** | restore the credential-publishing implementation |

`f064fe2e-58f4-4f4f-9e57-90c6f6304bf1` was the first contained deployment; it is now `REMOVED`,
superseded by `f7b56e12` (the redeploy that picked up the rotated variables). Both are contained;
`f7b56e12` is the one currently serving.

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

### Commits (full SHAs)

```
2b21d1b46dc7c07c506b52202f09823b27b60a20  fix(security): stop serving the owner API key to browsers
868e320e7f620c0935f89e2c17cf1e8e5e0356e6  fix(security): close the NarAI scheduler boundary
ca0c8fa845c0dd8c85442534b6b6625fba9336ec  docs: incident record
```

| Field | Value |
|---|---|
| Branch | `hotfix/production-owner-key-and-scheduler-containment` |
| Branch head | `ca0c8fa845c0dd8c85442534b6b6625fba9336ec` |
| Branch tree | `273e4954a33d680e670dfe0c5b000441fa473bce` |
| Base | production `073c9a46c39f2fa9969f8126f9c06bf004a75cf3` |
| Code SHA deployed | `868e320e7f620c0935f89e2c17cf1e8e5e0356e6` (the doc commit adds no served file) |

### Changed files

```
M  core/api.py
M  core/narai_scheduler.py
M  dashboard/ceo.html
A  docs/INCIDENT_2026-09-08_owner_key_and_scheduler.md
A  tests/test_owner_key_not_served.py
A  tests/test_scheduler_boundary.py
```

Zero SOL-owned files. Zero unrelated files.

### Deployments

| Service | Deployment | Note |
|---|---|---|
| Staging App A `kai-appA-staging` | `7ab3d2ab-64b3-4748-8a04-bd104f9d307b` | SUCCESS 2026-09-08T22:26:52Z |
| Production App A — first contained | `f064fe2e-58f4-4f4f-9e57-90c6f6304bf1` | REMOVED, superseded |
| **Production App A — currently serving** | **`f7b56e12-3522-492e-8166-baa1f92de4f9`** | SUCCESS 2026-09-08T22:49:44Z — **primary recovery reference** |
| Pre-incident App A | `f0d5527a-7121-47d5-8593-d62b23f0db43` | **SECURITY-UNSAFE — DO NOT REDEPLOY** (see §0) |

`commitHash` on the serving deployment is `None`. App A is deployed by `railway up`, a CLI upload
with no Git integration, so **no image digest and no platform-attested source SHA exist.** Provenance
rests on the file-level attestation in §3a, not on platform metadata.

A single 502 was observed on production during the code deploy swap, and one more during the
credential redeploy. Both are the expected fail-closed window.

---

## 3a. Artifact identity — running container vs branch tree

Every file under App A's application roots (`core/`, `dashboard/`, `frontend/`, `narai/`) was
SHA-256 hashed inside the running container and compared with the same roots in the branch.

| Result | Count |
|---|---:|
| **Mismatched (present in both, different bytes)** | **0** |
| Present in both, byte-identical | 538 |
| In branch, absent from container | 124 |
| In container, absent from branch | 1 |

**The three changed served files are byte-identical in the container:** `core/api.py`,
`core/narai_scheduler.py`, `dashboard/ceo.html`. (`tests/` and `docs/` are outside the served roots
and are not deployed, by design.)

**The one extra file** is `narai/data/narai.db` — a SQLite database created at runtime inside the
container. Not source.

**The 124 absent files**, classified:

| Count | Files | Explained by |
|---:|---|---|
| 2 | `frontend/admin/nexus-assets/*.mp4` | `.railwayignore` rule `*.mp4` |
| 2 | `narai/.env.example`, `narai/marketing/.env.example` | `.railwayignore` rule `.env.*` |
| 1 | `narai/godmode/logs/media_pipeline.log` | `.railwayignore` rule `logs/` |
| 114 | `frontend/blog/_archive/*.html` | **no ignore rule** — unexplained |
| 5 | `frontend/blueprint.pdf`, 4 × `frontend/tiktok*.txt` | **no ignore rule** — unexplained |

The 119 unexplained absences are **all static content, no code**, and none is currently served:
`/blueprint.pdf` and `/tiktok…txt` both return **404** on production, so this is a pre-existing
content-delivery gap unrelated to the incident. It is recorded, not fixed.

### Served-bytes comparison

| Route | Result |
|---|---|
| `/admin/ceo` | served SHA-256 **identical** to branch `dashboard/ceo.html` |
| `/admin/legacy` | served SHA-256 **identical** to branch `dashboard/index.html` |
| `/admin` | server-composed (presence layer injected, +64,145 B over any single source file), so not byte-comparable to one file. Verified to contain **no `const API_KEY`**. |

The first two are the strongest available evidence that the substitution is gone: the server now
returns the source file **unmodified**. Under the old code these bytes could not have matched,
because the key was injected into them.

### Attestation limitation — stated, not glossed

This is a **complete file-level attestation of App A's application roots** — zero mismatches, all
changed files identical, every absence classified — combined with **served-byte equality on both
incident routes**. It is **not** cryptographic source provenance: `railway up` produces no image
digest, the deployment carries no `commitHash`, and base layers, installed wheels and OS packages
are outside the comparison. Reproducible provenance requires the Git-integrated deployment in §5.

Manifest digests (SHA-256 of the sorted hash listing): container `2c79e5674de64011bd6616539c6b7392`,
branch `2b32368c4f5b193ee430826576a91f19`. They differ only by the 124 absences and 1 runtime file
enumerated above.

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

**Monitor — BROKEN BY THE ROTATION, THEN RECOVERED. Observed, not inferred.**

`kai-prod-monitor` is a `*/5` cron service. `railway redeploy` refuses it ("the latest deployment
cannot be redeployed") because there is no long-running deployment to restart. Its
`SESSION_SIGNING_SECRET` was set with `--skip-deploys`, so the **running deployment kept its old env
snapshot** while App A and App B moved to the new secret.

That mattered, because the monitor is not a passive prober: `ops/monitor/collectors.py:104-106`
mints an owner session in-memory from `SESSION_SIGNING_SECRET` and probes App A and App B with it.
A stale secret means every authenticated probe fails.

Measured, every run from 23:25Z to 01:00Z:

```
cron_tick=true environment="production" healthy=false did_canary=false alerts=1 sent=… 
```

A no-secret marker variable (`MONITOR_ROTATION_EPOCH`) was then set **without** `--skip-deploys`,
purely to force a new deployment that picks up the already-rotated secret — deployment
`c69e495d-2aa4-4572-a685-ca0421b6bbaa`. The very next run flipped:

```
2026-09-09T01:05:38Z  healthy=true  did_canary=false  alerts=0  sent=3  delivery_failures=0
2026-09-09T01:10:29Z  healthy=true  did_canary=false  alerts=0  sent=0  delivery_failures=0
```

`sent=3` on the first clean run is the recovery notification for the signals that had been alerting.

**Alerting gap: none — but a ~2h16m degraded window.** From rotation (2026-09-08T22:49Z) to
2026-09-09T01:05Z the monitor ran on schedule and *was* alerting (`alerts=1`, deliveries succeeding,
`delivery_failures=0`). It was correctly reporting its own broken authentication rather than going
silent. The risk in that window was masking: a genuine stack problem would have been hard to
distinguish from the standing auth alert.

**Lesson for the runbook:** `--skip-deploys` is right for a service you will redeploy immediately
afterwards, and wrong for a cron service you cannot redeploy. Rotate cron consumers with a normal
(deploy-triggering) variable set, or force a deployment straight after.

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

## 6a. Scheduler authorization matrix (production, post-containment)

| Identity | `GET /schedules` | `GET /stats` | `PATCH /{id}` | `POST /{id}/trigger` |
|---|---|---|---|---|
| anonymous | 401 | 401 | 401 | 401 |
| wrong API key | 401 | 401 | 401 | 401 |
| operator session | 401 | 401 | 401 | 401 |
| viewer session | 401 | 401 | 401 | 401 |
| signed-out / garbage cookie | 401 | 401 | 401 | 401 |
| session signed with a foreign secret | 401 | 401 | 401 | 401 |
| forged verifier token | 401 | 401 | 401 | 401 |
| release verifier (validly signed) | 401 | 401 | 401 + 403 guard | 401 + 403 guard |
| **owner (API key or session)** | **200** | **200** | **200** | **200** |

The release verifier is refused on reads as well. Its scope on App A is `require_admin_json` for
`/admin` JSON; extending it onto `/api` during an incident would broaden authority rather than
contain it. A deliberate decision, not an oversight.

No production job was triggered while establishing this. Write-path tests use a deliberately
non-existent schedule id, and tripwires on `trigger_schedule` / `update_schedule` assert no
unauthorized call reached the dispatcher or the writer.

---

## 8. Open items before this incident can be CLOSED

1. **Git reconciliation** — push the branch, open the incident PR against `production`, prove the PR
   tree matches the contained runtime source, merge, and verify the Git-triggered deployment builds
   the exact merged commit with an identical tree and introduces no new behaviour. Only then does
   App A gain reproducible provenance.
2. ~~**Monitor recovery**~~ — **CLOSED 2026-09-09T01:05:38Z.** The rotation did break it (stale env
   snapshot on a cron service set with `--skip-deploys`); a forced deployment recovered it, and two
   consecutive runs report `healthy=true alerts=0`. See §4.

Until item 1 is satisfied the status remains `INCIDENT_CONTAINED_PENDING_GIT_RECONCILIATION`.

---

## 7. What this response did not do

- Did not rotate any credential without fingerprint evidence of exposure.
- Did not execute, approve or mutate a production proposal.
- Did not trigger a real scheduled job. Write-path tests use a deliberately non-existent id.
- Did not run a scanner.
- Did not print, store or commit any secret value.
- Did not touch `hotfix/kai-admin-capability-auth` (four commits, preserved, unpushed).
- Did not expand scope to the residuals above.
