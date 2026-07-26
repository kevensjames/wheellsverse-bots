# KAI User-Readiness Audit + Completion Plan

Grounded audit (5 dimensions) of the **merged future state** (`integration/verify-all`,
all 10 PRs). Verdict, blockers, and a three-lane plan with honest ownership.

## Verdict

**KAI cannot accept real users today.** The foundation is sound (signup/login fixed,
strong security headers, correct Stripe trust boundary, non-streaming chat fails over),
but it is not merged to a protected branch, not deployed, and carries release-grade
blockers even in code. Shortest path to "yes": Lane A (code, mine) → Lane B (operator:
merge, legal, credentials, money-mode) → Lane C (gated deploy).

## Blockers to accepting users

### Two governance gates (both mine to prepare, neither mine to open)
- **Gate 1 — protected merge** `[OPERATOR]` — the 10-PR foundation onto `istanbul`/`main`.
- **Gate 2 — deploy + credentials + money-mode** `[OPERATOR/DEPLOY]` — Stripe env vars,
  webhook registration, and a *deliberate* live-vs-test money decision.

### Everything else, by user impact
| # | sev | owner | gap |
|---|-----|-------|-----|
| 1 | BLOCKER | OPERATOR | Privacy policy misdescribes KAI's data processing (no disclosure of chat storage / LLM sub-processors / mood+memory profiling) — GDPR Art. 13/14. `privacy.html:33`. I draft, legal adopts. |
| 2 | BLOCKER | CODE | No self-serve account deletion or data export (GDPR Art. 17/20). `delete_user` admin-only, skips ~11 sidecars. |
| 3 | BLOCKER | CODE | No password-reset flow — a forgotten password locks a user out permanently. |
| 4 | BLOCKER | CODE | Streaming chat has no provider failover — a routine 429 shows a raw error mid-turn and loses history (`router.py:198-213`). |
| 5 | BLOCKER | OPERATOR + CODE | Stripe money-mode implicit/unguarded — a live key in staging charges real cards (`config.py:84-98`). CODE half = a latch; the decision is operator's. |
| 6 | HIGH | CODE | Per-user spend ceiling is a no-op in cloud (falls back to OpenAI when Ollama absent) — unbounded cost. |
| 7 | HIGH | CODE | Prod failures silent — DB-blind `/health`, no 5xx alerting, monitor on the watched box. |
| 8 | HIGH | OPERATOR | No DB backup anywhere. |
| 9 | HIGH | CODE | Refund/chargeback never downgrades tier (`billing.py`). |
| 10 | HIGH | CODE | Sidecar DBs untenanted PII (latent tenant break the instant a scope is on with >1 user). |
| 11 | HIGH | CODE | Signup rate limit is one global bucket behind the tunnel. |
| 12 | MED | mixed | free/paid indistinguishable in chat; adapter timeouts; logout doesn't revoke; JWKS cold-start; crisis clause; log rotation; DEBUG default; `/kai/chat` unlimited. |

## What's already done (honest starting point)
10 PRs integrated; 422 signup/login break fixed (#46); auth core + cookie rotation; Postgres
PII tenanted + RLS + cascade-delete; non-streaming chat fails over OpenAI→Anthropic→local;
all 4 Stripe events signature-verified + idempotent; Dwolla sandbox-locked/HMAC/idempotent;
strong CSP+HSTS, prod admin-token guard, SWE routes unmounted in prod, CORS allowlist,
LaunchDaemon supervision + Telegram alerts; legal docs exist (wrong product).

## Completion plan

### Lane A — CODE I execute now (in-repo, no merge/deploy). Each with a verify check.
Built on this branch (`feat/kai-user-readiness`, based on the merged state). Status tracked
in this repo's commits. See "Execution status" below.

1. Stripe money-mode latch (`config.py` validator) — `sk_live_` iff production.
2. Deep `/readyz` — `SELECT 1` + Redis ping; `/health` stays liveness-only.
3. Per-user spend ceiling — refuse over-cap when no local adapter; call monthly cap.
4. Refund/chargeback handler — `charge.refunded`/`dispute.created` → `tier=free`.
5. `DELETE /me` + JSON export — cascade Postgres + purge sidecars; export conversations/messages/memory.
6. `POST /auth/forgot-password` — proxy Supabase recover (delivery needs operator SMTP).
7. Streaming failover — retry fallback / degrade to one-shot before erroring.
8. Global exception→alert middleware; chat rate limit; per-IP signup limiter; adapter timeouts; logout revoke; `DEBUG=False` default; log-rotation paths; sidecar tenancy guard.
9. Privacy-policy + crisis-terms **drafts** (operator/legal adopts).

### Lane B — OPERATOR (business/legal/credentials — not mine)
Merge (Gate 1); adopt legal drafts; set Stripe env + webhook + decide money-mode (Gate 2);
Supabase SMTP + confirmation redirect; define what a paid tier buys; confirm DB backup;
rotate any exposed secrets.

### Lane C — DEPLOY (gated on B)
Pin `APP_ENV=production`+`DEBUG=false`; assert the `profiles` trigger exists; deploy with
live Stripe only after the latch is green; off-box `/readyz` probe; verify Telegram from a
real box; full smoke (signup→chat→pay→refund→delete).

## Definition of "ready to accept users" (operator sign-off)
See the checklist boxes in Lane C + Blockers above; the shortest honest list: merged, legal
accurate, password reset works, export+delete work, streaming survives a 429, spend ceiling
bites, money-mode asserted, `/readyz` + alerting live, DB backed up, sidecars tenanted/off.

## Honest limits
I can write and verify every Lane-A item, but I cannot make KAI live. Merging to a protected
branch is a human review decision (no agent self-approves into a release line), and deployment
binds real credentials, real legal liability, and the choice to move real money. Everything I
ship in Lane A is dark and reversible until a human opens Gate 1 and Gate 2.

---

## Execution status (updated as Lane A lands)

Branch `feat/kai-user-readiness` (based on the merged state). Full suite after these:
**1035 passed / 18 skipped / 0 failed** (was 1020 pre-Lane-A).

| Lane A item | status | test |
|---|---|---|
| 1. Stripe money-mode latch | ✅ done | `test_money_mode.py` (6) |
| 2. Deep `/readyz` | ✅ done | `test_health_readyz.py` (3) |
| 3. Refund/chargeback → free | ✅ done | `test_refund_downgrade.py` (3) |
| 4. `POST /auth/forgot-password` | ✅ done (delivery needs operator SMTP) | `test_forgot_password.py` (3) |
| 5. `DELETE /me` + export | ⏳ remaining | **entangled with #10 sidecar tenancy** — untenanted sidecars (eq/relationship/twin) have no `user_id`, so per-user deletion there is impossible until tenancy lands; a truthful `DELETE /me` must either tenant them first or delete only Postgres + declare the gap. Do NOT ship a "GDPR-complete" delete that silently leaves sidecar PII. |
| 6. Per-user spend ceiling | ⏳ remaining | touches `router.py` select path; moderate regression risk — dedicated care + a router test needed. |
| 7. Streaming failover | ⏳ remaining | **highest-risk** change to the core paid streaming path; must be done carefully with a forced-provider-failure test, not rushed. |
| 8. exception→alert middleware, chat rate-limit, per-IP signup limiter, adapter timeouts, logout revoke, DEBUG default, log-rotation, sidecar tenancy | ⏳ remaining | the HIGH/MED cluster; #10 (sidecar tenancy) gates #5. |
| 9. privacy/crisis-terms drafts | ⏳ remaining (OPERATOR adopts) | legal text — I draft, a human adopts. |

**Why I stopped at 4 and did not rush the rest:** items 5–7 either depend on the sidecar-tenancy fix (#5) or carry real regression risk in the core paid path (#6, #7). Shipping them hastily would undermine "make it perfect," not serve it. They are the clear next increment, each with a defined approach above.
