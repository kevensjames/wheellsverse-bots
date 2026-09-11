# Loop & Authority Audit — 2026-09-11

Evidence-backed record of the delivery-flag correction, the authority-reporting
correction, and the loop investigations ordered after the PR #82 merge.

All timestamps UTC. The production database (`kai-prod`) reports `Etc/UTC` and read
`2026-09-11 01:06:29Z` during this audit.

---

## 1. Database tuple — CHANGED, and the merge did not cause it

The post-merge check required a "database tuple unchanged" verification. **It is not
unchanged.** Recorded honestly rather than restated as clean:

| Field | Baseline | After | Δ |
|---|---|---|---|
| `holding_timeline` | 15 | 17 | +2 |
| `proposal_status` | executed=2, proposed=9 | executed=2, proposed=8, approved=1 | one `proposed → approved` |
| `holding_proposals` total | 11 | 11 | — |
| devices / pairings / nonces | 0/0/0 | 0/0/0 | — |
| migration head | `0008_add_kai_devices` | `0008_add_kai_devices` | — |

**Sequence:**

- `2026-09-10 09:33:40Z` — 2 timeline rows written
- `2026-09-10 09:33:57Z` — `holding.proposal.approved` id=11, `decided_by='owner'`
- `2026-09-11 00:58:51Z` — PR #82 merged

The change precedes the merge by ~15.4 hours. The merge is exonerated by the clock.

**The two timeline rows are derived observations, not new business events:**

- `proposal:8:APPROVED` — a *backfill* of an approval whose real `ts` is `2026-08-31 05:04:28`
- `deployment:production:073c9a46c39f` — an *observation* row; `073c9a46c39f` is PR #70's
  merge commit and **is** an ancestor of `origin/production` (it is `origin/main` that lacks
  it — the known `main`/`production` divergence). The Holding OS reported honestly.

So exactly **one** genuine state change occurred: proposal 11 `proposed → approved`,
`executed_at` NULL. Its twin (proposal 9, identical title) executed on 2026-09-07 with
evidence `{"kind": "REQUEST_INFO", "read_only": true}` — this proposal class queues a
read-only information request. Nothing executed; no money moved; no external send.

### Corrections this forces

1. **The baseline timestamp label was wrong.** The handoff recorded the baseline as
   "verified live 2026-09-10 ~10:15 UTC". If true, that read would already have shown
   `approved=1` / `timeline=17`, since both landed at 09:33. The *readings* were correct;
   the timestamp attached to them was not. The baseline was taken before 09:33:40Z.

2. **Audit trail cannot identify the actor.** All five decision events in `audit_log` have
   `actor_id = NULL`, including two from 2026-08-31. `holding_proposals.decided_by` is the
   literal string `'owner'`. The record shows *that* an owner-authenticated session approved
   it and **cannot distinguish which one**. A gap in the record, not a breach. Flagged, not fixed.

---

## 2. Delivery containment — step 1 done, step 2 UNVERIFIED

Ordered: set `KAI_HOLDING_DELIVERY_ENABLED=false` on both cron services, and ensure the
**running deployment** — not merely the stored variable — observes false.

**Step 1 — COMPLETE.** Stored value now `false` on `kai-briefing-cron` and `kai-watch-cron`.
Applied with `--skip-deploys`. Deployment IDs identical before and after
(`fc3811e7`, `b7f5f856`) — **zero deployments triggered**, as required.

**Step 2 — NOT YET PROVEN.** `railway redeploy` refuses a completed cron deployment
("cannot be redeployed"). Whether a cron run resolves variables fresh or inherits the
deployment's snapshot is **not established**: cron runs create no deployment records, but
that shows runs aren't recorded, not that the environment is stale. Those are different
claims and must not be conflated.

The clean test: the flag write landed ~01:10Z, so the **02:11Z run is unambiguously after
it**. Discriminating signatures in the deployed code:

- flag `true` + placeholder token → `send error: HTTP Error 404: Not Found`
- flag `false` → `delivery disabled (default) — opt in via KAI_HOLDING_DELIVERY_ENABLED`

Until that run is observed, containment is: **stored false, running state unverified.**

### The token was never installed

| Service | `TELEGRAM_BOT_TOKEN` | `TELEGRAM_CHAT_ID` |
|---|---|---|
| `kai-briefing-cron` | `PASTE_YOUR_RE…` | `PASTE_YOUR_REAL_CHAT_ID` |
| `kai-watch-cron` | `<real token from kai-…>` | `<your chat id>` |

Both hold **literal placeholder instruction text**. The 404s were never "token invalid or
revoked" — no token was ever installed. Every failed delivery was therefore harmless: no
message reached any recipient.

This is why the ordering matters: **a real token installed before the schedule is fixed
would begin sending 24 messages a day immediately.** The broken credential has been the
only thing preventing it.

Note: production returns the raw `HTTP Error 404` string, not the classified
"bot token invalid or revoked" message. That classification lives on `fix/loop-repairs`
and is **not deployed**.

### The schedule is hourly — proven twice

`kai-briefing-cron` deployment manifest: `cronSchedule: "011 * * * *"` — verbatim, minute=11,
hour=`*`. Almost certainly `0 11 * * *` (daily 11:00) with the space lost.

Confirmed independently by behaviour — `holding.morning_briefing.generated` events at
`21:13:29, 22:11:43, 23:12:39, 00:15:44, 01:11:47`. **24 runs/day.**

Production's schedule was deliberately **not** changed; that repair is ordered for staging.

---

## 3. Authority reporting — the "0/8" claim, superseded

The earlier "eight authority flags: 0 ON" claim was read from App A and App B **only** and
was never evidence about the estate. Full inventory, production environment:

| Service | Authority keys SET | Vars readable |
|---|---|---|
| `grateful-flexibility / wheellsverse-v2` (App A) | none of the 17 | 192 |
| `grateful-flexibility / kai-prod-monitor` | none | 19 |
| `kai-production / kai-prod` (App B) | `APP_ENV=production`, `KAI_CAPABILITY_EXECUTION_ENABLED=false`, `KAI_COMPUTER_OPS_ENABLED=false`, **`KAI_HOLDING_ENABLED=true`** | 28 |
| `kai-production / kai-briefing-cron` | `APP_ENV=production`, **`KAI_HOLDING_BRIEFING_ENABLED=true`**, `KAI_HOLDING_DELIVERY_ENABLED=false`, **`KAI_HOLDING_ENABLED=true`** | 19 |
| `kai-production / kai-watch-cron` | `APP_ENV=production`, `KAI_HOLDING_DELIVERY_ENABLED=false`, **`KAI_HOLDING_ENABLED=true`**, **`KAI_HOLDING_WATCH_ENABLED=true`** | 19 |
| `adorable-fulfillment / kdp-scheduler` | none | 8 |

Each row records how many variables were readable, so "none set" is distinguishable from
"the read failed". That distinction is precisely what made an earlier credential scan lie.

**Execution-authority flags remain off everywhere** (`MONEY_MODE`, `KAI_A2_EXECUTION_ENABLED`,
`HOLDING_AUTONOMY_ENABLED`, `KAI_CAPABILITY_EXECUTION_ENABLED`, `KAI_SELF_IMPROVEMENT_ENABLED`,
`KAI_HOLDING_COMMAND_ENABLED`, `KAI_PROACTIVE_ENABLED`, `KAI_HOLDING_CYCLE_ENABLED`) —
unset or explicitly false. `KAI_COMPUTER_OPS_ENABLED=false` on App B: containment holds.

What the narrow scope **missed** is that `KAI_HOLDING_DELIVERY_ENABLED` — a surface flag, not
one of the eight — was `true` on two cron services the report never looked at.

**Also load-bearing:** five flags are *not declared on the production lineage*
(`KAI_HOLDING_COMMAND_ENABLED`, `KAI_VOICE_ENABLED`, `KAI_CAMERA_ENABLED`,
`KAI_HOLDING_CYCLE_ENABLED`, `KAI_PROACTIVE_ENABLED`). Setting one of those against
production is **silently dropped**. None are set, so there is no live risk — but reporting
them as "explicitly OFF" would be false comfort. They are off by code default.

---

## 4. tier-heal — root cause found; it is NOT a Stripe webhook defect

`tier-heal` is not a Railway service. It is a **macOS LaunchAgent on the developer's Mac**,
`com.wheellsverse.kai.tier-heal`, running `/Users/jhonwheeler/wheellsverse_bots/scripts/heal_tier_mirror.py`
daily at 04:00 local. It performs a **write against production customer data from a laptop**:

```sql
UPDATE profiles SET tier = 'free'
WHERE tier IN ('pro','max','ultra')
  AND id NOT IN (SELECT user_id FROM subscriptions WHERE status IN ('active','trialing'))
RETURNING id, email, tier
```

It commits (line 75). On any hit it fires a Telegram alert reading
*"Check whether webhooks are dropping customer.subscription.deleted events."*
**That attribution is wrong.**

### Data (read-only aggregates, no PII)

| Store | `profiles` | `subscriptions` |
|---|---|---|
| Railway `kai-prod` (deployed App B) | 1 row, `ultra` | **0 rows** |
| Supabase (the laptop heal's target, via `aws-1-us-west-2.pooler.supabase.com`) | 10 `free` + 1 `ultra` | 2 rows, **both `canceled`** |

**Zero active subscriptions in either store — there are no paying NAI customers today.**
Rows the 04:00 heal would demote tonight: **1** — the comped operator profile.

### The actual loop

1. `backend/app/routers/admin_chat.py::_resolve_operator_profile` pins the operator profile
   to `tier='ultra'` **on every call**, by design ("so a stray DB edit can't silently
   downgrade"), logging *"operator profile … was tier=… — restoring to ultra"*.
2. That profile correctly has no Stripe subscription — the owner does not pay themselves.
3. At 04:00 the LaunchAgent demotes it to `free` and alerts, blaming webhooks.
4. The next admin-chat call pins it back to `ultra`. Repeat nightly.

Two subsystems fighting over one comped row. **No dropped webhook is involved.**

### Genuine latent gap (separate from the above)

`narai/integrations/nai_subscription.py` implements `handle_subscription_deleted` — the only
code that demotes `profiles.tier` on cancellation — and is imported **only by its own test**.
It is wired into no dispatcher. The live path is inline at `core/api.py:11331-11342`, which
**promotes** on `checkout.session.completed` and never demotes. `core/api.py` dispatches
`customer.subscription.deleted` for telegram (`_ts`) and discord (`_ds`) only.

The `subscriptions` table's only writer is that same dead module — so no live path ever
creates a subscription row.

**Consequence:** tiers go up via the webhook and never come down server-side. The only
demotion mechanism in the estate runs on a personal Mac at 04:00 and requires it to be awake.
Harmless today (zero paying customers); a revenue-integrity defect the moment one exists.

### Availability bug in the same loop

`KAI_OPERATOR_USER_ID` is **unset** on `kai-prod`, so `_resolve_operator_profile` falls back to
"first `ultra` profile, oldest first". If the heal demotes the only `ultra` profile in the store
an instance uses, that resolver finds none and raises `OperatorNotConfigured` — and cannot
self-heal, because the restore path runs only *after* a profile resolves.

### Recommended fix (not applied — requires a production merge)

1. Stop the false alarm: set `KAI_OPERATOR_USER_ID` and exempt that profile from the heal —
   a comped account must not be judged against Stripe subscription state.
2. Close the real gap: wire a server-side demotion on `customer.subscription.deleted`,
   rather than leaving it to a laptop.

---

## 5. Loop dispositions

**`kai-watch-cron` — has a real purpose; keep disabled for now.**
`ops/holding-watch-cron/run.py` runs a read-only watch loop, alerting only on material change,
gated by `KAI_HOLDING_WATCH_ENABLED` + `KAI_HOLDING_DELIVERY_ENABLED`; it mutates nothing but
its own watch-state row. Designed for ~15 min cadence; it has **no schedule**. It is not hollow —
it is unscheduled. With delivery now false and the token a placeholder, scheduling it would run a
watch that can alert nobody. **Recommendation: keep disabled** until a real channel exists.

**`kdp-scheduler` — deletion candidate, presented NOT deleted.**
Correction to the handoff: it does **not** lack a deployment. It has **20 deployments**, schedule
`0 0 * * *`, and **all 20 are SKIPPED** back to `2026-08-23`, each with
*"Cron skipped: no running container and the deployment did not become ready"*. Its build config
is empty. It has never executed once. **Presented for a decision; nothing deleted.**

---

## 6. Production workers are running on a personal Mac

`launchctl` shows six WheellsVerse LaunchAgents installed, four live:

| LaunchAgent | PID | State |
|---|---|---|
| `com.wheellsverse.kai-holding-worker` | 840 | running |
| `com.wheellsverse.kai-holding-worker-staging` | 841 | running |
| `com.wheellsverse.nai` | 849 | running |
| `com.wheellsverse.missioncontrol` | 836 | running |
| `com.wheellsverse.kai.tier-heal` | — | scheduled 04:00 daily |
| `com.wheellsverse.kai-si-detect-staging` | — | scheduled |

Production-adjacent loops depending on one laptop being awake is an availability and
data-integrity exposure in its own right, independent of any single defect above.

---

## 7. Standing hazard — worktree Railway linkage

`/Users/jhonwheeler/conductor/workspaces/wheellsverse-bots/istanbul` and
`/Users/jhonwheeler/conductor/repos/wheellsverse-bots` are both linked to the Railway project
**`wheellsverse-sol`**. This is the exact configuration that earlier in this sequence began
uploading App A into the SOL project. **Never run `railway up` from those directories.**
`/Users/jhonwheeler/wheellsverse-actionfix` is linked to `kai-production`.

---

## Outstanding — owner action only

- Rotate the Obsidian key
- Contain Gitea on `0.0.0.0:3000`
- Provision `WHATSAPP_APP_SECRET` + `BEEHIIV_WEBHOOK_SECRET` (Payhip stays `FAIL_CLOSED_UNAVAILABLE`)
- Grant the Railway GitHub App
- Enable branch protection requiring `gate`
- Supply the `kai-briefing-cron` Telegram token — **only after** bot identity and recipient are
  verified, the schedule is fixed, and one controlled staging delivery has completed

---

## 8. Branch protection — ready, not enabled (owner action)

`production` is currently **unprotected** (`GET .../branches/production/protection` → 404
"Branch not protected"). The repo's default branch is `main`, but `production` is the real trunk.

The gate emits four check runs. **Only `gate` may be required:**

| Check run | Conclusion on PR #82 |
|---|---|
| Security tests | success |
| Secret scan | success |
| Dependency scan (report-only) | **failure — by design** |
| `gate` | **success** |

Requiring "all checks" would block every merge, because the dependency scan is report-only
and fails intentionally. The workflow's own comment says to require `gate`.

Confirmed the gate now runs on releases: run `34537964163` (PR #82) — **success**, 48s.
Before PR #80 it had run exactly once in its life and never on anything that shipped.

Command (owner to run; requires admin, which is held):

```bash
gh api -X PUT repos/kevensjames/wheellsverse-bots/branches/production/protection \
  --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["gate"] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

`enforce_admins: false` deliberately — it preserves an owner break-glass path during an
incident. Tighten once the gate has proven stable across several releases.

---

## 9. kai-briefing-cron repair — evidence and the one unproven variable

**Cadence: established.** The manifest says `011 * * * *` and behaviour confirms 24 runs/day.
The intended expression is almost certainly `0 11 * * *` — a lost space.

**Timezone: NOT established, and this is the one thing still unproven.** Railway cron runs in
**UTC**. The repo's commits carry `-0400`, so the operator is America/New_York (EDT). Therefore:

- `0 11 * * *` UTC = **07:00 local** — coherent for a task literally named
  `holding.morning_briefing`
- `0 15 * * *` UTC = 11:00 local — if "11:00" meant wall-clock local time

Both readings are plausible and they differ by four hours. Per standing instruction, delivery
stays **OFF** until the owner states which is intended. Do not guess.

**Repair sequence (in order, none of it started):**

1. Owner confirms cadence + timezone (the choice above).
2. Validate in staging — no briefing cron exists in either `kai-staging` project, so one must
   be created there rather than testing on production.
3. Install a real `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` via stdin or Railway's protected
   variable UI — **after** verifying bot identity and recipient. Never paste a token in chat.
4. Fix the production schedule.
5. Only then re-enable `KAI_HOLDING_DELIVERY_ENABLED`, and confirm exactly one controlled
   staging delivery before production.

Ordering is not cosmetic: installing a working token while `011 * * * *` stands would begin
sending 24 messages a day immediately.

---

## 10. SOL — untouched and healthy; changes belong in the standalone repo

`wheellsverse-sol`: `sol-scheduler` last SUCCESS `2026-08-20T07:26:05`, `sol-api` SUCCESS
`2026-08-21T01:05:46`. Both predate this session entirely, independently confirming the earlier
mis-targeted `railway up` left no trace. `sol-scheduler` carries no Railway cron
(`cronSchedule: None`) — it is a long-running service scheduling internally. Per instruction,
any scheduler work happens **only in the standalone SOL repository**. Nothing changed here.

---

## 11. Post-merge verification of PR #82 — including one qualification

**WebSocket auth suites pass on the merged code.** Run from a detached worktree at
`b486a138` (the merge commit), because the earlier failure — `ImportError: cannot import
name 'ws_auth' from 'narai.api'` — was purely a checkout artifact: `fix/loop-repairs` was
branched pre-merge and lacks `narai/api/ws_auth.py`. Confirmed: the file is present on
`origin/production` and absent on that branch.

`tests/test_ws_principal_resolver.py` + `tests/test_websocket_auth_boundary.py` +
`tests/test_router_manifest_gate.py` → **70 passed**. Properties confirmed: non-owner
sessions refused (`operator`, `viewer`); foreign-secret sessions refused; owner-from-trusted
origin accepted; cookie handshakes refused from `https://evil.com`, `null`,
`https://app.wheellsverse.com.evil.com`, and `https://kai.wheellsverse.com` (the cross-app
origin — the SameSite=Lax gap that motivated the CSRF work).

### Qualification: staging did not run the merged head

| Commit | UTC | Content |
|---|---|---|
| `48095a6a` | 22:24:45 | the functional security change (ws_auth, voice, router manifest) |
| `c10871f8` | 22:31:39 | docs + the `ws_ticket_store` health field |
| `b486a138` | 00:58:51 | the merge |

Staging App A deployment `af0ba44d` reports `build_time 2026-09-10T22:25:14Z` — **29 seconds
after `48095a6a` and 6½ minutes before `c10871f8`**. Confirmed independently: staging's
`/api/health` **omits `ws_ticket_store` entirely**, while the merged code emits it
unconditionally (`core/api.py:4399`, always `PERSISTENT` or `EPHEMERAL`).

So the 19/19 staging certification ran against `48095a6a`. That commit contains the **entire
functional security boundary**; the untested delta is a docs commit plus one health-payload
field — observability, not a security control. The accurate statement is therefore:
*"the security behaviour was certified on staging; the merged head additionally carries a
docs commit and one health field that staging never ran."* Not: *"the merged head was
certified on staging."*

### Production provenance — and a reporting defect

Production genuinely runs the merged code: `deploy_id f937da79`, `build_time
2026-09-11T01:00:42Z` (immediately after the 00:58:51Z merge), `ws_ticket_store: PERSISTENT`,
`routers_missing: []`.

**But `/api/health` reports `git_sha: 5e767a4`** — the PR #69 merge from 2026-09-07, not
`b486a138`. This is the known stale-SHA defect (App A is deployed by upload, so the SHA comes
from an env var nobody updates). Production's self-reported provenance is **wrong**, and any
verification trusting `git_sha` would draw a false conclusion. Trust `deploy_id` + `build_time`
+ feature presence instead. Staging reports `git_sha: unknown`.

---

## 12. The most consequential finding: production loops run stale code from the unsecured Gitea

`tier-heal` is not the only thing running on this Mac, and *where its code comes from* matters
more than the bug it carries.

The LaunchAgent executes `/Users/jhonwheeler/wheellsverse_bots/scripts/heal_tier_mirror.py`.
That working copy:

| Property | Value |
|---|---|
| branch | `feat/sol-v1` |
| HEAD | `01bb127`, dated **2026-07-06** — over two months stale |
| **origin** | **`http://localhost:3000/jhonwheeler/wheellsverse-bots.git`** |
| uncommitted | 16 entries (15 untracked + `frontend/nexora/landing.html`) |

The origin is the **local Gitea** — the instance already flagged as bound to `0.0.0.0:3000`
with anonymous read and open self-registration. The same tree backs the other live agents
(`com.wheellsverse.kai-holding-worker` PID 840, `com.wheellsverse.nai` PID 849,
`com.wheellsverse.missioncontrol` PID 836).

So: **code that writes to the production customer database nightly is served from an
unsecured Git server on a laptop, from a branch two months behind GitHub.** "Contain Gitea"
is therefore not merely an exposed-service item — Gitea is an upstream supply-chain path into
production data. Anyone who can write to that Gitea can change what runs at 04:00 against
`profiles`.

None of the security work in PRs #73-#82 reaches these processes. They do not run App A or
App B; they run a July checkout.

### Fix applied tonight (bounded, reversible)

The heal script in that working copy was **byte-identical** to the pre-fix version (verified
by diff against `HEAD~1`), and none of the 16 uncommitted entries touched it. The fixed file
was installed there so tonight's 04:00 run does not repeat the demotion:

- backup: `scripts/heal_tier_mirror.py.prefix-backup-2026-09-11`
- guard present; `py_compile` OK under `/Users/jhonwheeler/wheellsverse_bots/.venv/bin/python`
- the installed copy's `HEAL_SQL` executed against a fixture: demotes only the cancelled
  Stripe customer, spares the comped operator
- dry check against live data: **0 rows** would be demoted tonight (was 1)

Reverting is a `mv` of the backup. This does **not** address the Gitea exposure, the
two-month staleness, or production loops living on a laptop — those need an owner decision.

### Recommended (needs a decision, not started)

1. Contain Gitea, or repoint these working copies at GitHub.
2. Decide whether these four LaunchAgents should run at all - and if so, not from a laptop.
3. Wire a server-side demotion on `customer.subscription.deleted` so no laptop job is the
   only mechanism keeping paid tiers honest.
