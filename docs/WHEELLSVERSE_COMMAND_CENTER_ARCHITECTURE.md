# WHEELLSVERSE Command Center — Architecture

Phase-0 truth, then the target. The Command Center is a **registry-driven observability + control**
plane over the *actual* ecosystem — never a hand-maintained card list.

## Ground truth: TWO FastAPI apps + separate company repos

```
                         app.wheellsverse.com  (+ apex wheellsverse.com via Cloudflare Pages)
                                     │
                    ┌────────────────┴─────────────────┐
   APP A  core.api:app  (v2.0.0, LIVE)            APP B  backend/app/main.py  (KAI brain daemon, LOCAL-only)
   Railway grateful-flexibility / wheellsverse-v2      not deployed; Postgres+Alembic+Celery; the governed KAI runtime
   image built from `main` via docker-push.yml         reached from App A only through the same-origin bridge /admin/kai/*
   serves: /admin dashboards, 146-bot fleet,           houses: NarAI v2 (/api/v2/narai/*), the LLM router/adapters
   Shopify/Toodle/SiteBoost/LeadGen/Scoreboard,
   Sol proxy links, the Capability Fabric API

   SOL / SOLCIRCLE  →  SEPARATE repo kevensjames/wheellsverse-sol
                       Railway wheellsverse-sol / sol-api·sol-worker·sol-scheduler → sol-api-production.up.railway.app
                       FastAPI + async-SQLAlchemy + Postgres + Redis/RQ · money mode = MOCK (APP_ENV=staging)

   NURTELLE  →  SEPARATE repo kevensjames/chenara (public brand "Nurtelle")
                Next.js 16 monorepo (apps/web + apps/marketing) · pre-deployment · LOCAL
```

**Key implication:** a single Command Center at App A must *federate* status from App A, App B (via the
governed bridge), the Sol API (cross-origin, its own admin), and Nurtelle (separate) — never pretend
one runtime owns them. Honest per-runtime status is mandatory (§24 of the directive).

## The registry-driven target (directive §22)

```
                       Wheellsverse Registry  (the single source of truth)
        ┌───────────┬───────────┬───────────┬───────────┬───────────┬───────────┬───────────┐
     Companies    Services    Agents/Bots  Infra      Deployments  Providers  Automations  Capabilities
        └───────────┴───────────┴───────────┴───────────┴───────────┴───────────┴───────────┘
                                             │
                                  Telemetry / Control adapters   (READ from real sources: /api/health,
                                             │                    /api/overview, Sol admin, App B bridge,
                                             │                    Railway/Cloudflare, capability registry)
                                             ▼
                             WHEELLSVERSE COMMAND CENTER  (the executive flight deck UI)
                                             │
                                             ▼
                                            KAI  (intelligence layer: plans, routes, governs, stops)
```

- **Adapters over one-off integrations** (§22): each domain (Sol, NarAI, bots, capability fabric,
  Railway, …) has a status adapter that returns a typed `SystemStatus`/`CompanyStatus` (§23) with
  `source`, `last_updated`, `freshness`, `status`, `permissions`, `links`.
- **Honest status model (§24):** `HEALTHY / DEGRADED / FAILED / OFFLINE / DORMANT / BLOCKED / UNKNOWN /
  NOT_CONFIGURED`. UNKNOWN never becomes HEALTHY; no-data never becomes 0; configured ≠ running;
  installed ≠ available; available ≠ authorized; authorized ≠ executed.
- **The Command Center is observability + control only.** It must never bypass a system's own
  invariants — especially Sol's append-only balanced ledger + settlement gating + reconciliation holds.

## Visual architecture (approved reference)

Top command bar (search / ⌘K / clock / env / deploy status / notifications / system health / operator) →
left nav (Overview, Portfolio, KAI, AI Workforce, W-MOS, Startups…, Security, Finance, Infra, Deployments,
Automations, Incidents, Analytics, Knowledge, Settings) → center (executive KPI strip → **WHEELLSVERSE
UNIVERSE** galaxy → startup/system status cards → real-time telemetry → command console / quick actions /
KAI assistant) → right rail (system health / live activity / mission timeline / alerts). Dark aerospace,
cyan/teal/blue/violet, Bloomberg-density, subtle cosmic environment.

## Recovery, not replacement

The 30 surfaces the current `/admin` lost (see the inventory) are recovered by driving the Universe +
company cards from the registry, and by keeping the old hubs reachable (`/admin/legacy`, `/admin/index`).
A **canonical-inventory snapshot test** (§25) fails CI if any recovered company/system/capability
silently disappears again.
