# WHEELLSVERSE Command Center — Control → Backend Matrix (§19)

Anti-regression contract. Pass-2 final SHA in commit log. Every functional control, its
handler, backend, auth, post-condition, and test disposition. **APP 404 = 0, APP 5XX = 0**
(verified via Playwright network capture; the only 404 is `/admin/session/whoami` from the
injected `kai-presence.js` orb — external, allowlisted).

| Control | Frontend handler | Backend | Method | Auth | Post-condition (asserted) | Test |
|---|---|---|---|---|---|---|
| Universe node ×12 | `CC.openDrawer(id)` | `/admin/registry.json` | in-page | none (registry public) | drawer opens, title = system name | ✓ 12/12 |
| Startup card ×10 | `CC.openDrawer(id)` | registry | in-page | — | drawer opens | ✓ 10/10 |
| Universe core | `CC.scrollTo('#s-overview')` | — | in-page | — | scrolls to overview | ✓ |
| KPI ×8 | `CC.scrollTo(section)` | metrics/registry | in-page | — | drills to section | ✓ 8/8 clickable |
| Alert row | `CC.openDrawer(id)` | registry | in-page | — | affected system opens | ✓ |
| Console `health/status` | `CC.cmd` | registry counts | in-page | — | real counts printed | ✓ `/\d+ systems/` |
| Console `companies` | `CC.cmd` | registry | in-page | — | company list | ✓ |
| Console `incidents` | `CC.cmd` | registry (DEGRADED/UNKNOWN) | in-page | — | incident list | ✓ |
| Console `workers` | `CC.cmd` | `/admin/command/metrics.json` fleet | in-page | — | real fleet stats | ✓ `/fleet:/` |
| Console `capabilities/metrics` | `CC.cmd` | caps/metrics | in-page | — | real values | ✓ |
| Console `open <sys>` / `find <q>` | `CC.cmd` | registry | in-page | — | drawer / matches | ✓ |
| Console injection (`;whoami`,`$(id)`,`<script>`) | `CC.cmd` | — | — | — | **inert** (no exec, no DOM injection) | ✓ |
| Global search | Enter handler | registry | in-page | — | matching system → drawer; XSS escaped | ✓ narai→drawer, XSS inert |
| Health Check (quick action) | `CC.cmd('health')` | registry | in-page | — | prints real health | ✓ |
| Quick actions ×7 (New Circle, Deploy Service, …) | `CC.kai('Request: …')` | KAI governed bridge `/admin/kai/*` (App B) | governed | operator + approval | routes to KAI; Nexus fallback when bridge offline | GOVERNED (App B offline locally) |
| Emergency Halt | `CC.kai` | `core/portfolio/killswitch.py` (RECOMMEND-ONLY) | governed | approval | recommend-only ROI, never direct execute | GOVERNED |
| KAI chips ×7 + Ask KAI | `CC.kai` | KAI bridge | governed | operator | governed prompt | GOVERNED |
| LIVE/DEMO toggle | `CC.setMode` | localStorage | in-page | — | mode switches, demo watermarked | ✓ |
| Nav → `/admin/portfolio,/hub,/capabilities,/nexus,/siteboost,/toodle,/scoreboard,/shopify,/second-brain-inbox,/leadgen,/mission-nexus,/avatar-lab,/theme-picker,/ceo,/legacy` | href | serve routes | GET | (page-level) | **all 200** | ✓ route check |
| Nav → SOL / Reconciliation | href | `/sol/admin` | GET | — | **200** (was `/admin/sol` 404 — FIXED) | ✓ + CI guard |
| Nav → wvkey (registry) | href | `/admin/wvkey` | GET | — | **200** (route added — was 404) | ✓ |
| **Nav → Automations** | href | `/admin/automations` + `/admin/automations.json` | GET | — | real autopilot+delivery; scheduler null→NOT CONNECTED | ✓ 200, real data |
| Nav → Audit Logs | (disabled) | — | — | — | honest NOT_CONNECTED (App B audit log unreachable) | ✓ disabled+tip |
| Nav → Nurtelle | (disabled) | — | — | — | pre-deploy, honestly disabled | ✓ |

## E2E journeys (§6)
A system-discovery **PASS** · F SOL **PASS** (read-only, canonical `/sol/admin` 200) · G security
**PASS** (capability catalog + tiers) · H deployments **PARTIAL** (real build/fleet/uptime; per-deploy
logs = no App-A endpoint → BLOCKED) · **B/C/D/E BLOCKED_EXTERNAL** (KAI live answer / worker-retry /
incident-ack / automation-run require App B or separate services + §47 forbids prod mutation).

## Honest architecture note
App A is an **observability + navigation + governed-routing** plane. Direct mutations
(retry/acknowledge/run/deploy/money) are NOT executed in-dashboard by design — they live in App B
(offline) or separate services and route through governed approval. This is the correct, safe posture,
not a defect; those controls are GOVERNED or BLOCKED_EXTERNAL, never fake.
