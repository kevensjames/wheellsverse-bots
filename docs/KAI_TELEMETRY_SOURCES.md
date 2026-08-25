# KAI Telemetry Source Inventory (Phase 4A)

Ground truth for the Systems / Topology views. **No random numbers** (§4F): every
datum below maps to a real source or is honestly `UNAVAILABLE`. The reality of
this codebase: KAI exposes **liveness/status endpoints**, not deep metrics — so
the Systems view derives **discrete states** (NOMINAL/DEGRADED/…) from HTTP
probes and shows `UNAVAILABLE` for metrics that have no source, rather than
inventing gauges.

Provenance: `REAL` (measured), `DERIVED` (computed from a real signal, e.g. a
200 → NOMINAL), `DEMO` (fixture, `?scenario=` only), `UNAVAILABLE` (no source).

## Liveness / status — probeable (REAL probe → DERIVED state)

| Metric | Source | Endpoint | Provenance | Poll | Refresh | On failure |
|---|---|---|---|---|---|---|
| App B (KAI brain) up | App B FastAPI | `/health` | DERIVED (200→NOMINAL) | poll | 20s | UNKNOWN + last-probe age |
| App A (core/api) up | App A | `/api/v2/narai/health` | DERIVED | poll | 20s | UNKNOWN |
| KAI bridge enabled/up | App A | `/admin/kai-bridge/health` | DERIVED (`{enabled}`) | poll | 20s | UNKNOWN |
| Market engine | App A | `/api/market/status` | DERIVED | poll | 30s | UNKNOWN |
| Factory | App A | `/api/factory/status` | DERIVED | poll | 30s | UNKNOWN |
| Business bots (shopify/etsy/gumroad/payhip/pod/sa/nexora/…) | App A | `/api/<x>/status` | DERIVED | on-demand | 30s | UNKNOWN |
| Agent workforce | App A | `/api/shopify/agents/status` | DERIVED | on-demand | 30s | UNKNOWN |

## Provider config presence (DERIVED — presence, NOT live latency)

| Metric | Source | Field | Provenance | Notes |
|---|---|---|---|---|
| OpenAI configured | admin audit `_runtime()` | `openai_key_set` | DERIVED | key present ≠ reachable |
| Anthropic configured | admin audit | `anthropic_key_set` | DERIVED | — |
| Ollama configured | admin audit | `ollama_base_set` | DERIVED | — |

## UNAVAILABLE — no source exists (must NOT be faked)

CPU · RAM · GPU · VRAM · disk · network throughput · request rate · error rate ·
DB connection-pool stats · Redis memory/hit-rate · queue depth · worker heartbeat ·
scheduler heartbeat · provider latency · token usage · cost-per-request.

These render as `UNAVAILABLE` with the reason "no telemetry endpoint" until a
metrics endpoint (or a Prometheus/Railway metrics bridge) is added. **Never** a
random percentage. Adding a single aggregate `/admin/telemetry` endpoint on App A
would upgrade many of these from UNAVAILABLE → REAL (see D8).

## Topology (DERIVED from repository architecture, not invented)

```
CLIENT → CLOUDFLARE(apex) → APP A (core/api, admin/api) → BRIDGE(/admin/kai/*)
       → APP B (KAI brain) → { POSTGRES, REDIS, PROVIDERS(ollama/openai/anthropic) }
```

Node status = the probe result above; edge "active" animates only when a real
event traverses it (governed chat → bridge → App B). Edges with no probe show
`UNKNOWN`, not green.

## Failure & staleness (§4F/§4H)

- A probe that fails → node `UNKNOWN`/`OFFLINE` + "last successful probe: Nm Ns ago".
- Never backfill a failed probe with DEMO unless `?scenario=` is active.
- Polling is bounded, backs off on repeated failure, and pauses when the tab is
  hidden (see D8 / §4H).
