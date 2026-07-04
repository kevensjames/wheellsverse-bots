# Sol v1 — Deploy Runbook (operator)

**Audience:** operator (steps to run yourself). Nothing here has been executed — the assistant
prepared this but did **not** touch the production database or restart the daemon (those are your
go). Migrations `0007`→`0015` are additive and were proven to apply cleanly on real Postgres; still,
**back up the DB first**.

**Where Sol runs:** the local Mac daemon `com.wheellsverse.nai` (launchd) serves both the API
(`/sol/v1/*`) and the member SPA (`/sol-app/`) **same-origin** from `~/wheellsverse_bots` via
`deploy/start_nai.sh`. The Sol code is already in that clone (edited in place), so a **daemon restart
is what deploys it** — there is no separate Railway push for Sol (Railway runs the *other* app).

---

## 0. Pre-flight

```bash
cd ~/wheellsverse_bots
git log --oneline -1            # expect the tip of feat/sol-v1
git status -s                   # working tree clean
```

- The working tree is on **`feat/sol-v1`**. Decide whether to deploy from it or merge into your usual
  deploy branch (`master`) first — the daemon runs whatever is checked out here.
- **Back up the daemon's Postgres** before migrating (a dump, or a Railway/provider snapshot).

## 1. Apply the migrations (0007→0015)

Run against the **same DATABASE_URL the daemon uses** — `deploy/start_nai.sh` sets it, so source that
env (or export the URL yourself), then:

```bash
cd ~/wheellsverse_bots
export DATABASE_URL='...'            # the SAME url deploy/start_nai.sh gives the daemon
cd backend
../.venv/bin/alembic current         # expect head = 0006_add_kai_api_keys (or your current head)
../.venv/bin/alembic upgrade head    # applies 0007..0015 (sol_* tables + additive column changes)
../.venv/bin/alembic current         # expect 0015_sol_payment_method_stripe
```

What these add (all additive — new tables + a nullable column + widened CHECKs; no destructive change):
`sol_groups/memberships/cycles/payments/payment_profiles/payment_proofs` (0007), method nullable
(0008), a UNIQUE (0009), `disputed_at` (0010), `sol_consents` (0011), `sol_stripe_accounts` (0012),
`sol_member_subscriptions` (0013), `sol_stripe_payments` (0014), method='stripe' allowed (0015).

**Rollback:** `../.venv/bin/alembic downgrade 0006_add_kai_api_keys` (each migration has a downgrade).

## 2. Restart the daemon (this is the deploy)

```bash
launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai
# then confirm it came up (check your usual health endpoint / logs)
```

The restart loads the new routers and mounts the SPA at `/sol-app`.

## 3. Live smoke test — the MANUAL rail (no Stripe needed)

Open the SPA (e.g. `https://kai.wheellsverse.com/sol-app/` or `http://localhost:8001/sol-app/`) and,
signed in with a **real Supabase account**, walk the flow:

1. Sign in → you should land on **Circles**.
2. Tap **+ New circle** → you're gated to the **consent screen** → accept → create a circle.
3. Copy the invite link; from a second account, open it → consent → **Join**.
4. As organizer: **Lock circle** → **Start this cycle**.
5. As a payer: open the payment → **I paid this** (pick a method) → as the recipient: **Confirm received**.
6. Check **Payments** (owed/incoming) and **You** (reliability score + payment handles).

This exercises the entire non-custodial manual rail live. The Connect UI (Membership / card payouts /
pay-with-card) stays **hidden** because the Stripe rail is off — that's expected.

## 4. Feature flags (env) — what to set, what to leave OFF

Set in the daemon's env (as `start_nai.sh` reads it), then restart.

| Flag | For | Launch value |
|---|---|---|
| *(none)* | the manual rail | works with no new env |
| `SOL_V1_REMINDERS_ENABLED` / `SOL_V1_REMINDERS_HOUR_UTC` | daily due/overdue Telegram digest (opt-in) | optional (default off) |
| `SOL_V1_SUPERVISOR_ENABLED` / `SOL_V1_SUPERVISOR_HOUR_UTC` | daily read-only integrity + health sweep → operator alert | optional (default off) |
| `SOL_NOTIFY_EMAIL_ENABLED` + `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM`/`SMTP_STARTTLS` | email members their notifications (in-app always works regardless) | optional — needs BOTH the flag AND SMTP config, else silent no-op |
| `STRIPE_CONNECT_ENABLED` | turn the Stripe rail ON | **leave off** until approved |
| `STRIPE_CONNECT_LIVE_APPROVED` | allow a live Stripe key | **leave off** — only after Stripe + counsel |
| `STRIPE_PRICE_SOL_MEMBER` | the $9.99/mo recurring price id | set when you enable the subscription |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | the Sol webhook signing secret | set when you configure the Stripe webhook |
| `SOL_REQUIRE_SUBSCRIPTION` | gate create/join on an active sub | **leave off** to keep the manual rail free |

**The Stripe rail is fail-closed:** even with `STRIPE_CONNECT_ENABLED=1`, a live key is refused unless
`STRIPE_CONNECT_LIVE_APPROVED=1`, and that flag is set only after Stripe's written OK + counsel sign-off
(see `NON_CUSTODIAL_ARCHITECTURE.md`). In test mode you can exercise the whole Stripe flow with a
`sk_test_` key without any of that.

## 5. Notes / gotchas

- **Edits are in the HOME clone** (`~/wheellsverse_bots`), which is what the daemon runs — no SSD→HOME
  copy is needed (that TCC landmine applies to editing the `/Volumes` clone; we didn't).
- **Same-origin auth:** the SPA authenticates via the httpOnly `nai_access` cookie because it's served
  from the daemon; keep it served from the daemon (don't move `/sol-app` to a different origin without
  revisiting CORS/cookies).
- **Off-machine backup / PR:** `git push` to GitHub is currently blocked by push-protection on a
  *synthetic* Stripe key in a pre-existing test fixture (`backend/tests/security/test_runner_secrets.py`
  — not a real secret). To back up to GitHub, either allow that one finding via the URL GitHub printed,
  or scrub it from history first.

## 6. Security

**Rate limits (active now on `/sol/v1/*`).** The member API is rate-limited per IP (slowapi). The caps
are backstops for real users and abuse-defense for attackers; legitimate use never hits them:

| Endpoint(s) | Limit | Defends against |
|---|---|---|
| `POST /sol/v1/groups/join` | **10/min** | **invite-code brute-force** (guessing codes to join a circle) |
| `POST /sol/v1/groups` | 15/min | circle spam |
| `activate` / `mark` / `confirm` / `dispute` | 30/min each | write flooding (and notification spam) |
| `lock` / `proofs` / `payment-profiles` / `legal/accept` | 20–30/min | write abuse |
| subscription / stripe / charges writes | 15–20/min | external-call abuse |
| notifications read / read-all | 60/min | benign; light cap |

In-memory counters are fine for the single-worker daemon we ship (`--workers 1`). If you ever run
multiple workers/hosts, set `storage_uri="redis://…"` on the limiter so all workers share the counters
(see `app/core/rate_limit.py`).

**Operator action — set a dedicated `ADMIN_TOKEN`.** The `/admin/*` control plane (including the Sol
operator dashboard `/admin/sol-v1`) is gated by `X-Admin-Token`. If `ADMIN_TOKEN` is unset, the gate
*falls back* to `JWT_SECRET_KEY` (a deliberate transition convenience — see `app/dependencies/admin.py`).
That works, but couples the admin surface to a long-lived legacy secret you can't rotate independently, and
that dashboard exposes every circle/member/payment. **Recommended:** set a dedicated, random `ADMIN_TOKEN`
in the daemon env and rotate it on its own schedule; do not rely on the fallback in production. (Not changed
in code because a hard requirement could lock the operator out mid-transition — it's your call to set it.)

**Already in place:** member auth (Supabase JWT, httpOnly cookie), admin-token gate (constant-time,
fail-closed), webhook HMAC verification, Pydantic input validation, parameterized SQL, XSS-safe SPAs
(textContent only), non-custodial invariant (verifier-checked every stage). MFA is available via Supabase
(operator toggle, no code change).
