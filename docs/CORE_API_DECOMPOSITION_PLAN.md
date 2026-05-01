# `core/api.py` Decomposition Plan

**Status:** plan only — no execution without your sign-off.

## Why this is risky

- `core/api.py` is ~541 KB / 13,000+ lines. It registers the entire FastAPI app: middleware, ~80 v1 routes, the v2 narai loader, the bot manager, code engine, narai memory, schedule stats, narai webhooks, Stripe, Shopify, Telegram, Sol ROSCA endpoints, etc.
- Every route on prod is reached through this single file. A bad rename, missing re-export, or stale import path → 500s on whatever route depends on the broken symbol.
- There is no test suite that exercises every route. Refactor regressions surface only at request time.
- Multiple sessions/agents are continuously editing this file (memory shows ongoing churn). A long-lived branch will rot.

## Strategy: incremental extraction, not a single rewrite

Each step independently shippable + revertable. After each, deploy + smoke-test before starting the next.

### Phase 1 — Extract pure helpers (lowest risk)

Move all constants, dataclasses, helper functions that don't touch FastAPI's `app` directly into:

- `core/api/_models.py` — Pydantic models, dataclasses
- `core/api/_helpers.py` — utility functions (formatters, validators, simple service calls)

`core/api.py` re-exports them for backward compat: `from core.api._helpers import *`. No behavior change. ~2,000 lines moved. Risk: rename collisions.

### Phase 2 — Extract route groups by domain

One module per logical domain:

| Module | Routes | Approx LOC |
|---|---|---|
| `core/api/routes_health.py` | `/api/health`, `/api/version` | ~50 |
| `core/api/routes_botctl.py` | `/api/botctl/*` (existing `core/bot_router.py` may already cover) | ~300 |
| `core/api/routes_narai_v1.py` | All `/api/narai/*` (status, run, feed, log, profile, memory, conversations, voice_chat, etc.) | ~3,000 |
| `core/api/routes_narai_v2_loader.py` | The v2 narai try/except registration block | ~150 |
| `core/api/routes_shopify.py` | `/api/shopify/*` | ~2,000 |
| `core/api/routes_stripe.py` | Stripe webhook + Stripe API | ~800 |
| `core/api/routes_telegram.py` | Telegram webhook + admin | ~600 |
| `core/api/routes_sol.py` | Sol ROSCA endpoints | ~1,500 |
| `core/api/routes_kdp.py` | KDP endpoints | ~400 |
| `core/api/routes_inbox.py` | Second-brain inbox routes | ~300 |
| `core/api/middleware.py` | Rate limit, security headers, CORS, API key middleware | ~400 |

Each module exposes an `APIRouter`. `core/api.py` becomes a slim ~200-line composition root: build `app`, attach middleware, `app.include_router(...)` for each module.

### Phase 3 — Validate

After each module extraction:

1. Smoke-test the routes that lived in the extracted module via CLI.
2. Watch Railway logs for 5 minutes after deploy for 5xx spikes.
3. If any regression — `git revert` the extraction commit. Should never block prod for >5 min.

### Phase 4 — Rotate the slim root file

After all routes are extracted, move the remaining glue into `core/main.py` and reduce `core/api.py` to a backward-compat shim that just imports from `core.main`. After 1 week without external imports of the old shape, delete `core/api.py`.

## Why I won't do this autonomously

- **Scope:** 4–8 hours of careful work, dozens of commits.
- **Coordination:** other agents/sessions edit `core/api.py` constantly. A long-lived branch would conflict on every push.
- **Rollback:** if Phase 2 breaks Stripe webhooks at 3am, you'd be down without me to debug.
- **Testing gap:** no end-to-end coverage means manual smoke-testing each domain after each extraction. That's a tight feedback loop with you.

## What I'd need from you to proceed

1. **A 4-hour window where you're available** to confirm smoke tests pass after each phase.
2. **Permission** to leave Phase 1 as the only deployment for 24h before starting Phase 2 (let prod soak).
3. **Authority** to revert if anything regresses (rather than push fixes forward into a half-extracted state).

## Better-and-cheaper alternative I recommend instead

Don't decompose. Instead:

- **Add coverage:** write integration tests for the top 20 route paths (`/api/health`, `/api/v2/narai/chat`, Stripe webhook, Shopify webhooks). ~1 day. Massively reduces future refactor risk.
- **Add a route inventory:** generate a markdown table of all routes from FastAPI's `app.routes` introspection at startup, dump to `docs/ROUTE_INVENTORY.md`. ~2 hours. Makes the size problem manageable without changing behavior.
- **Tag domains via comments:** add `# === DOMAIN: shopify ===` markers around blocks of routes. Editor folding + grep navigability. ~1 hour. Zero risk.

Decomposition becomes urgent only if the file genuinely blocks development. Right now the symptoms are cosmetic (size feels gross) rather than functional (routes still work, deploys still succeed). Coverage + navigability buys ~80% of the benefit at ~5% of the risk.

---

**Decision:** if you say "go," I'll do Phase 1 only over a single session and have you smoke-test before going further. If you say "no, do the cheaper alternative," I'll add the route inventory + domain comments instead.
