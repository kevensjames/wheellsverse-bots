# INCIDENT RECORD — PR #74, anonymous action paths, CSRF, and side-effecting GETs

**Status: `PR74_27_CONFIRMED_ANONYMOUS_ACTION_PATHS_CONTAINED` — frozen.**

**Certification: `LOCAL_CERTIFIED_EMERGENCY — HOSTED_STAGING_UNAVAILABLE`.** This release is **not**
hosted-certified. See §9.

No secret value appears in this document, in the branch, in the diff or in any commit message.

---

## 1. Identity

| Field | Value |
|---|---|
| Production SHA | `92bd5678adeb90e292b93e213b387641879c9091` |
| Parents | `024368f6d6a54e0cee7f40630b7d020a11f49db4` (previous production) + `5c38cef8a0e15a4beb7d8eb1d39e92c5ba52d52c` (branch head) |
| Tree | `27f92c59d3c3ac204630df1f0a6aba2b98021cd6` — byte-identical to the approved head's tree |
| PR | #74, merged 2026-09-09T08:23:06Z |
| Branch | `hotfix/public-action-routes`, base `024368f6` verified unmoved immediately before merge |
| **Approved head** | **`5c38cef8a0e15a4beb7d8eb1d39e92c5ba52d52c`** |

### Commits

```
c622989f  fix(security): no unauthenticated route may start, stop, reset or publish
5569c4c5  fix(security): a GET that computes is not a read
5c38cef8  fix(security): CSRF on cookie-authenticated actions, and GETs that no longer compute
```

### Changed files

```
M  core/api.py                                  +238/-50
M  core/viral_trend_engine.py                    +36/-0
A  tests/test_public_action_routes.py           +387/-0
A  tests/test_csrf_and_side_effect_free_get.py  +332/-0
```

Zero SOL-owned files. Zero `backend/` files — **App B was correctly not deployed** (its latest
deployment, 2026-09-08T22:49:12Z, predates this merge).

## 2. Provenance

| Field | Value |
|---|---|
| App A deployment | **`4f5d13f4`** · SUCCESS · 2026-09-09T08:23:08Z |
| Its `commitHash` | `92bd5678adeb` — matches the merge commit |
| Branch | `production` · Git-triggered, not `railway up` |
| Project / service | `grateful-flexibility` (`5407586d`) / `wheellsverse-v2` |
| SOL project | `wheellsverse-sol` unchanged — latest `517caedc`, 2026-08-21T01:05:46Z |

Corroborated behaviourally: `GET /api/sa/trend-scan` and `GET /api/shopify/intelligence/opportunities`
answer **401** anonymously on production. At `024368f6` both were public-list members and would have
answered 200. The old artifact is not serving.

## 3. What was wrong

### 3.1 Twenty-seven anonymous action routes

Invocable by anyone with no credential of any kind — no dependency, no in-handler check.

| Route | What an anonymous caller could do |
|---|---|
| `POST /api/narai-autopilot/start` | publish to the live Facebook, Instagram, X, Telegram and WordPress accounts; **create and publish priced Gumroad products**; create Etsy listings; spend the Anthropic budget |
| `POST /api/pod/start` | paid DALL-E generation → Printify products → published to the live Shopify store |
| `POST /api/shopify/discount` | create a real discount code |
| `POST /api/shopify/register-webhooks` | **repoint where the store delivers its webhooks** |
| `DELETE /api/factory/reset` | clear today's products, truncate the log |
| `GET /api/sa/trend-scan` | on a cold cache, run the full scrape + LLM classification |
| + 21 more | start/stop/dispatch/reset across autopilot, factory, QC, POD, shopify-agents, intelligence, nexora |

`POST /api/narai-autopilot/start` takes no body, making it a CORS **simple request**: no preflight,
firable cross-origin from any page.

### 3.2 The structural cause

App A's public surface is assembled at **fourteen scattered sites** — the `_PUBLIC_PATHS` literal,
eleven `_PUBLIC_PATHS.add(...)` calls, and three import-time `for _p in [...]` loops, one of them
~3,000 lines below the declaration and directly above the handlers it exempts. The effective public
surface cannot be read from any single place. Four consecutive incidents each found *a* route and
missed the rest.

PR #73 carried part of this forward, and that was mine. It replaced `startswith()` matching with an
explicit `PublicRule` table, then copied three entries over as `descendants=True` on the strength of
their comments — *"with its own auth"*, *"with their own token check"*. The handlers had none. The
purpose field was meant to force that judgement; it recorded a claim instead.

### 3.3 CSRF

Owner-only stops an anonymous caller. It does not stop another site making the owner's **own browser**
issue the request. Two things that look like they prevent this do not:

- **SameSite=Lax** blocks cross-**site** cookie sending on unsafe methods, and "site" is the
  registrable domain. It stops `evil.com`. It does **not** stop
  `kai.wheellsverse.com → app.wheellsverse.com` — cross-origin but same-site. Every
  `wheellsverse.com` subdomain, the Cloudflare Pages apex included, is inside the boundary Lax draws.
- **CORS** does not stop state change at all. A cross-origin POST with a form or `text/plain` body is
  a simple request: the browser sends it and withholds only the *response*. By the time CORS blocks
  the read, the product is published.

`OPERATOR_SESSION_ENABLED=1` on production, so the cookie path is live and this was reachable.

### 3.4 GETs that compute

`GET /api/sa/trend-scan` called `run_trend_scan(refresh=False)`, which returns the cache only when it
is truthy and otherwise falls through to the full scrape, the LLM classification, and a file write.
`GET /api/shopify/intelligence/opportunities` had the identical shape. SameSite=Lax deliberately
**does** send cookies on top-level GET navigation, so owner-only never protected these — a link was
enough. Found by probing the running app (a 500 from inside the Anthropic client), not by reading it:
the handler source shows only an import and an await, because the cost is one call deeper.

## 4. What changed

Six descendant families became **GET-only**, so every read a dashboard polls stays public while every
mutating verb under them is gated; action entries were removed from the method-blind exact set; and
`_NEVER_PUBLIC`, checked first in `_public_rule_for`, closes the residue. Both exemption mechanisms had
to go for every route — either alone leaves the hole open.

The CSRF check sits at `_session_owner_ok`, the single point where cookie authentication is decided
for all three gates — not at 27 call sites. `_origin_of` parses with `urlsplit` rather than comparing
strings, because the hostile inputs are exactly the ones hand-parsing gets wrong:
`https://trusted@evil.com` (userinfo), `https://evil.com/https://trusted` (path),
`https://trusted.evil.com` (suffix). A prefix comparison accepts all three — the same defect as the
`startswith()` route matching that began this sequence, in a different field.

**The machine path is deliberately exempt.** Setting `X-API-Key` forces a CORS preflight an attacker
cannot satisfy, so a header credential cannot be attached by a foreign page and carries no CSRF risk.
Cookie = browser = checked; header = machine = not. `Principal.source == "session"` is the distinction.

Both GETs now read cache and nothing else, reporting `OK` / `STALE` / `UNAVAILABLE`.
`cached_opportunities()` separates never-written from unreadable from genuinely-empty — three states
the old reader collapsed into `[]`.

Config: `CSRF_TRUSTED_ORIGINS` set on App A production to the three real browser origins, applied with
`--skip-deploys` so the merge deployment picked it up. A `CORS_ORIGINS="*"` value would fail **closed**
in the guard — verified.

## 5. One route the earlier commit missed, and why it matters

`POST /api/shopify/register-webhooks` stayed public through the commit meant to close this class,
because the test scanned handler source for an auth signal and the word "webhook" in its path
satisfied the scan. The same technique **falsely accused** `/api/v2/narai/insider/revoke` and
`/reissue` (guarded by `_require_admin`, a name not on the list) and all thirteen mutating `/api/nx`
routes (guarded in-body by `_nx_require_creator(request)`, invisible to a `Depends`-only scan).

Detecting "is this authenticated?" from source needs a name list or a regex, and both are guesses
about vocabulary — wrong in both directions within one session. **The guard no longer guesses.** It
answers only what it can answer exactly — can an anonymous request reach this route — and pins the
result to a reviewed set of entry points, webhooks and confirmed in-handler guards. A new
anonymously-reachable mutating route fails the test until someone places it in a group deliberately.

This is why the final count is **27, not 26**.

## 6. Production refusal matrix

Refusal probes only. Reachability was established solely with **non-existent sibling paths**, which
cannot execute anything, and with methods the routes do not accept.

| Probe | Result |
|---|---|
| `POST` × 12 non-existent siblings (`…/start_probe`, `…/reset_probe`, `…/discount_probe`, …) | **401** — gate refuses before routing |
| `GET /api/pod/start`, `/api/pod/stop`, `/api/nexora/recruit`, `/api/nexora/growth` | **401** — not public for any method |
| `GET /api/sa/trend-scan`, `GET /api/shopify/intelligence/opportunities` | **401** |
| `POST /api/shopify/register-webhooks` | **401** |
| `GET /api/health`, `/api/overview`, `/api/narai/status`, `/admin/ui-config`, `/admin/ceo` | 200 |
| apex `https://wheellsverse.com/api/health` | 200 |
| `POST /api/lead`, `POST /api/subscribe` | 422 — reachable, validation-rejected |
| App A `/api/health` · App B `/health` | 200 · 200 |

Eight authority flags: **all OFF** (`KAI_HOLDING_COMMAND_ENABLED`, `KAI_CAPABILITY_EXECUTION_ENABLED`,
`KAI_HOLDING_DELIVERY_ENABLED`, `KAI_HOLDING_CYCLE_ENABLED`, `KAI_PROACTIVE_ENABLED`,
`KAI_VOICE_ENABLED`, `KAI_CAMERA_ENABLED`, `KAI_CYBER_OPS_ENABLED`).

## 7. Local HTTP certification

Against a locally booted App A with a real owner session and a real owner key:

```
cookie + Origin evil.com                            -> 401
cookie + Origin null                                -> 401
cookie + Origin kai.wheellsverse.com                -> 401   (the same-site hole)
cookie + Origin app.wheellsverse.com.evil.com       -> 401   (the suffix trap)
cookie + no Origin at all                           -> 401   (fails closed)
cookie + Origin app.wheellsverse.com                -> 200   (the owner is not locked out)
cookie + GET                                        -> 200   (reads unaffected)
X-API-Key + Origin evil.com                         -> 200   (machine path preserved)
X-API-Key + no Origin                               -> 200
GET /api/sa/trend-scan  -> {"status":"UNAVAILABLE"}, no work performed
anonymous trend-scan / opportunities / register-webhooks -> 401
```

Zero Anthropic, OpenAI, Printify, scrape or traceback lines in the server log for the entire run.

**One handler was invoked deliberately and locally:** `POST /api/factory/start` from a trusted origin,
to prove the guard does not lock the owner out. It was a local instance without production
credentials; nothing external resulted.

## 8. Tests and mutants

`tests/test_public_action_routes.py` and `tests/test_csrf_and_side_effect_free_get.py` — **190
targeted checks**. Nothing in them invokes an action: record-and-refuse spies over the autopilot
module, the POD engine, factory persistence, the trend engine, `subprocess`, `urlopen` and `threading`
assert that no refused request entered a handler, spawned a thread, spent money or published.

Ten mutants killed, one per mechanism:

| Mutant | Result |
|---|---|
| matcher reverts to prefix matching | failed |
| `descendants` flag ignored | failed |
| method check dropped | failed |
| path normalisation removed | failed |
| autopilot family back to GET/POST | 42 failed |
| `/api/pod/start` re-added to `_PUBLIC_PATHS` | 12 failed |
| `/api/shopify/discount` re-exempted (a route no test names) | 2 failed — caught only by the enumeration guard |
| `register-webhooks` re-exempted | 6 failed |
| CSRF check removed from the cookie path | 4 failed |
| origin compared with `startswith` | 3 failed |
| missing Origin failing open | 2 failed |
| guard extended to header credentials | 1 failed |
| the GET computing again | 2 failed |

**Regression:** 1096 passed / 44 failed — the 44 byte-identical to the same run on untouched
`024368f6`. Zero new failures.

An earlier run showed 54 failures. That was **my test's fault, not a regression**: this module fires
the action matrix repeatedly and exhausted the process-global per-IP rate limiter, starving later
tests into 429s that read exactly like an authorization regression. The limiter is now cleared around
each test in that file.

**CI:** Cloudflare Pages, `ingest`, Cursor Approval Agent and **Cursor Security Agent** all passed.
`Workers Builds` failed — verified failing identically on the `024368f6` baseline, pre-existing.

## 9. What was NOT verified

- **No hosted staging run.** The `kai-appA-staging` service used for PR #73 no longer resolves in any
  reachable Railway project. All pre-merge evidence is local-HTTP. Restoring an isolated hosted
  staging App A is required follow-up. This is why the certification reads
  `LOCAL_CERTIFIED_EMERGENCY — HOSTED_STAGING_UNAVAILABLE` and **not** hosted-certified.
- **Cross-origin cookie rejection was not exercised against production itself.** That requires a live
  production owner session, and the standing rule is not to use production owner credentials in
  automation. Verified exhaustively locally, and on production by provenance and configuration only.
- **Database state: UNVERIFIED.** Release verification performed no deliberate state-changing request;
  the database tuple was **not re-read** and is therefore **UNVERIFIED**. Proposals, statuses, digest,
  nonces, timeline rows and worker jobs are not asserted unchanged. Existing tables can change without
  a migration, and the absence of a migration in this diff is not evidence about their contents.

## 10. Rollback

> ⚠ **The previous App A deployment is NOT a security-safe rollback target.** `4b4586e2`
> (from `024368f6`) contains all 27 anonymous action paths, the CSRF exposure and both side-effecting
> GETs. Every deployment before it is worse.

Recovery is **fix-forward**, redeploying the contained artifact `4f5d13f4`, or temporarily disabling
the affected surface at the edge. No database change accompanies this release, so there is no
migration to reverse.

## 11. Carried forward — explicitly open

**Not every anonymous action path is eliminated.** The honest status is: **27 confirmed action paths
contained; four webhook trust boundaries and the remaining public-route inventory still open.**

| Sev | Item |
|---|---|
| HIGH | **Four unsigned webhook receivers** — `telegram`, `whatsapp`, `beehiiv`, `payhip` accept unsigned payloads. Beehiiv additionally takes its token in a **query string** and, per its own docstring, *accepts any request when the secret is unset* (`core/api.py:4952-5065`). Next work item. |
| HIGH | Reported unauthenticated **OS-command-execution** finding (Aikido PR #65) — read-only reachability analysis in progress. |
| MED | **The remaining public-route inventory has not been exhaustively reviewed.** `/api/nx` and `/api/v2/narai` keep mutating descendant rules; their in-handler guards were sampled, not exhaustively verified. |
| MED | `DELETE /api/factory/reset` is owner-only and CSRF-protected but does **not** use the fresh action-bound confirmation contract. That contract binds a `proposal_id` and needs a nonce store App A does not have; wiring it is a feature build, not containment. |
| MED | **Hosted staging App A unavailable.** |
| MED | App B `backend/app/dependencies/cookie_auth.py:64-65` deletes auth cookies **without matching attributes** — no Secure, no HttpOnly, no SameSite. This is the exact defect App A already fixed and documented at `core/operator_session_web.py:132-135`. |
| LOW | `narai/api/main.py:57` and `second_brain_inbox/api/main.py:26` configure **wildcard CORS with credentials**. Neither app is mounted in App A — only their routers are imported — so neither is currently exploitable through App A. They become live defects the moment either app is served directly. |
| LOW | Three plaintext `http://localhost` origins sit in App A's credentialed CORS allowlist. |
| LOW | `CHANGELOG.md:44` still claims App A's CORS "falls back to `["*"]` if unset". Stale — it falls back to a six-entry explicit list. |

## 12. Customer-facing regression still outstanding

`/api/store/redeliver` remains owner-only from PR #73. A customer can no longer re-request a paid
order's files. Restoration is designed separately — authenticated customer session, order-ownership
check, destination fixed from the order, idempotency, rate limits, audit, enumeration-safe responses.
Not a one-line exemption.
