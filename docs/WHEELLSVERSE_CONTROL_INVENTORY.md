# WHEELLSVERSE Command Center — Control Inventory (§1)

Enumerated from the live DOM (Playwright §34) + traced to backend. Baseline SHA `0a2f399`.
**77 interactive controls.** Status vocab: WORKING / NAV (navigation) / GOVERNED (routes to KAI
governed bridge) / DISPLAY / DISABLED_CORRECTLY / BROKEN / EXTERNAL_SERVICE.

## Architecture truth (read first)
The Command Center is a **registry-driven navigation + honest-telemetry + governed-action** plane
over App A. Controls fall into four honest classes, and after this pass there are **0 BROKEN and 0
dead** controls:
1. **Navigation** — open a real App-A route or a drawer (registry-backed). Works.
2. **Console/search/drill-down** — execute locally against real data (registry/fleet/caps). Works.
3. **Governed actions** — quick actions + KAI chips route through the KAI governed bridge
   (`window.KAI.ask`), which requires App B + operator approval; falls back to `/admin/nexus` when the
   bridge is offline. This is BY DESIGN (a prior directive required "nothing destructive fires directly").
4. **Cross-service** — deep per-startup operations (SOL money ops, per-company live metrics) live in
   SEPARATE services (wheellsverse-sol, etc.); the dashboard NAVIGATES to them, never re-implements them.

## Sidebar (27) — all resolve
| Control | Handler | Target | Status |
|---|---|---|---|
| Mission Control / All Startups / Scoreboard / KAI Flight Director / Deployments / Infrastructure / Workers & Queues / Incidents / Finance Center / Analytics Hub | `CC.scrollTo` | on-page section | WORKING (scroll-nav) |
| Portfolio HQ / W-MOS | href | `/admin/portfolio` (200) | NAV |
| AI Workforce | href | `/admin/hub` (200) | NAV |
| Capability Fabric / Security Center / Knowledge | href | `/admin/capabilities` (200) | NAV |
| Command Nexus / NarAI | href | `/admin/nexus` (200) | NAV |
| **SOL / SOLCIRCLE, Reconciliation** | href | ~~`/admin/sol` (404)~~ → **`/sol/admin` (200)** | **FIXED this pass** |
| Nexora | href | `/nexora/dashboard` (200) | NAV |
| SiteBoost | href | `/admin/siteboost` (200) | NAV |
| Suprema / Automations / Audit Logs / Legacy Dashboard | href | `/admin/legacy` (200) | NAV (approximate — nearest real surface; no dedicated page yet) |
| Toodle | href | `/admin/toodle` (200) | NAV |
| Nurtelle | (no href, `data-disabled`) | — | DISABLED_CORRECTLY (pre-deploy) |

## Top bar (4)
| Search | searches `REG.systems`, opens drawer / KAI fallback | WORKING (real registry search) |
| LIVE / DEMO toggle | `CC.setMode` | WORKING |
| Notifications | `CC.scrollTo('#s-alerts')` | WORKING (nav) |

## KPI cards (8) — DISPLAY + drill-down (added this pass)
Real values (registry/scoreboard/fleet); each now **clickable → drills** to its section (§4). No
fabricated numbers; unconnected surfaces show "—".

## WHEELLSVERSE Universe (13)
12 nodes → `CC.openDrawer('<real registry id>')` (WORKING). Core → **clickable → overview** (added). All
use real registry IDs — a snapshot test guarantees resolution.

## Startup cards (10) → `CC.openDrawer('<id>')` — WORKING (drawer: Overview/Deploy/Recovery/Governance; SOL adds Money Ops/Providers)

## Quick actions (8) — GOVERNED
`New Circle / New Campaign / Create Agent / Deploy Service / Run Automation / Generate Report / Health
Check / Emergency Halt` → `CC.kai('Request: …')` → governed KAI bridge (approval-gated) / Nexus
fallback. Destructive ones labeled "needs approval". Emergency Halt maps to the **recommend-only** ROI
killswitch (`core/portfolio/killswitch.py`) — never a direct destructive execute.

## KAI Assistant (8) — chips → `CC.kai('…')` governed; input → governed. WORKING (governed routing)

## Command Console (1) — **now a real command registry (§28, added this pass)**
`help · health · status · companies · incidents · workers · capabilities · metrics · open <system> ·
find <q> · ask <q>` execute locally against REAL data; unknown → governed KAI. No arbitrary shell.

## Mission Alerts (8) — counts are DISPLAY (real, derived from registry statuses); **alert rows now clickable → open affected system** (§27, added this pass).

## Remaining (honest, not dead)
- **Nav approximate routes** (Automations/Audit Logs/Knowledge/Security Center/Analytics Hub) point to
  the nearest real surface, not a dedicated page — NAV, flagged for future dedicated views.
- **Governed actions** require App B (KAI runtime) live to execute; locally they route to Nexus.
- **Cross-service ops** (SOL money, per-startup metrics) are navigation-to-service by design.
