# KAI ⇄ Admin Merge — Surgical Migration Ledger (§34)

> 2026-08-11. One row per capability that needs migration decision. Status vocabulary: DISCOVERED · MAPPED · INTEGRATING · VERIFIED · DUPLICATE_REMOVED · EXTERNAL_BLOCKED. **No capability may disappear silently.** All rows start at DISCOVERED/MAPPED — nothing is INTEGRATING yet (the identity-before-presence bridge is a pending human decision).

## Canonical implementations (source of truth per domain)

| Domain | Canonical | Absorbs | Why |
|---|---|---|---|
| Assistant / chat brain | KAI daemon chat (backend/app/routers/admin_chat.py :171-339 /admin/kai-chat + /kai/chat via app.routers.nai) with govern | NarAI v2 chat (core/api.py :14892-14932 /api/v2/narai/chat), the Cmd+K drawer in | The KAI daemon is the only chat with tool-governance (@audited scope/approval), knowledge graph, digital twin, persona/EQ, memory and self-c |
| Identity / session / auth | New unified server-side operator session + RBAC, seeded from KAI's require_admin_token model (backend/app/dependencies/a | X-API-Key middleware core/api.py:855-880 (incl. query_params.get('api_key') :873 | There are today 4-5 auth schemes across two apps. RBAC 'must never be bypassed', and C1 (API_KEY string-injected into unauth /admin HTML in  |
| Admin shell / navigation | frontend/admin/index.html Command Center as the shell; per-surface pages (portfolio/siteboost/shopify/leadgen/scoreboard | dashboard/index.html nav('hub') Command Hub, nav('shopify'), nav('siteboost') if | The static green-accent admin pages are small, purpose-built and already the intended shell. The 19k-line dashboard/index.html is the legacy |
| Revenue / money truth | frontend/admin/scoreboard.html + /api/narai/scoreboard (core/api.py:1720) for portfolio revenue; KAI /admin/spend (admin | dashboard nav('revenue') Money Board :2551-2723, nav('revenue2') Revenue V2, nav | scoreboard.html is the one surface that honestly marks each metric connected-vs-not. The four legacy revenue tabs overlap and fake-fill. |
| Shopify merchant ops | frontend/admin/shopify.html + narai/api/routes/shopify_admin.py (/api/narai/shopify/*) | dashboard/index.html nav('shopify') :535 iframe embed | Single multi-tenant merchant surface with real Supabase-backed data and the test-product pipeline. The dashboard tab just iframes it. |
| Secrets / token vault | Decision required, but keep wvkey (frontend/admin/wvkey.html) as the local AES-256-GCM operator vault of record; expose  | nothing yet — flag for consolidation; do NOT merge stores until an owner is pick | wvkey is the local-machine source of truth (217 keys, Keychain master). The DB-backed dashboard token store and narai/godmode/vault.py are s |
| Governance / audit backbone | backend/app/services/governance.py @audited(scope, destructive) pattern | ad-hoc X-API-Key-only mutations in narai/api/routes/*_admin.py (siteboost send,  | ~40 of KAI's mutating endpoints already route through scope-gated, approval-gated, audit-logged governance. Any admin write action pulled in |

## Duplicate truth to consolidate (do NOT remove until replacement verified)

| Capability | Admin impl | KAI impl | Recommendation |
|---|---|---|---|
| AI assistant / chat | NarAI v2 chat — core/api.py:14892-14932 (/api/v2/narai/chat, own JWT), embedded as Cmd+K d | KAI daemon chat — backend/app/routers/admin_chat.py:171-339 (/admin/kai-chat, synthetic 'u | Two entirely separate LLM brains claiming the same role. Make KAI daemon canonical; repoint the admin drawer/orb to it. Requires cross-app wiring (see risks) si |
| Operator identity / auth | X-API-Key shared platform key, HMAC-compared, string-injected into HTML — core/api.py:855- | X-Admin-Token in sessionStorage (backend/app/static/nai/admin.js:10, require_admin_token d | Same truth ('who is the operator') expressed 4-5 ways across two apps. Unify to one server-side session + RBAC. This is the single highest-priority merge item a |
| Admin overview / launch stats | frontend/admin/index.html 4 stat tiles (merchants/MRR/products/uptime) via /api/narai/shop | backend/app/routers/admin_data.py:81-153 /admin/stats + /admin/recent-users + :156-208 /ad | Both compute 'how is the business doing' from different data (Supabase merchants vs KAI Profile/llm_call_log). Surface both in one overview; neither is wrong, t |
| Security scanning | dashboard/index.html nav('security') :583 (generic scan); nav('suprema') :503 workspace au | backend/app/routers/admin_supreme.py Supreme scanner (/admin/supreme/status|scan|history|l | Overlapping 'security posture' surfaces. KAI Supreme is the governed one; fold the dashboard security/suprema tabs into it or clearly scope them (Sol admin Secu |
| Secrets / token storage | frontend/admin/wvkey.html (local AES-256-GCM vault, 217 keys) vs dashboard nav('tokens') : | narai/godmode/vault.py (autonomous-launch secrets vault) | Three stores hold overlapping credentials with no single source of truth. Pick wvkey as vault-of-record; make the others read-only mirrors. Do not auto-merge —  |
| Command Center hub | frontend/admin/index.html (route /admin/hub, served core/api.py:1646) | dashboard/index.html nav('hub') :484 (same name, different SPA tab) | Two surfaces named 'Command Center'/'Command Hub'. Keep the static index.html as the shell; retire the dashboard hub tab. |
| Portfolio HQ operator UI | frontend/admin/portfolio.html + portfolio_cockpit.html served with '%%API_KEY%%' injection | n/a (W-MOS is App A only) — but classified DUPLICATE in the inventory because the same pag | Not a cross-system dup; it's the C1 injection vector. Replace injection with the unified session; keep one page. |

## Needs-integration seams

1. Cross-app bridge: core.api:app (railway.json start command) and backend/app/main.py are separate FastAPI apps/deployments; core/api.py never imports the KAI admin_* routers. The merge requires either mounting backend/app as a sub-app under core.api, or a same-origin reverse-proxy + shared session cookie. Nothing 'shares one memory/session' until this is resolved.
2. Unified operator session + RBAC replacing X-API-Key injection (core/api.py:855-880, 1688-1716) and X-Admin-Token (admin.js:10), with role scopes gating every surface so the orb/drawer respects RBAC on every page.
3. Global KAI presence layer (orb -> drawer -> full Nexus) injected into the shared head/shell of every frontend/admin/*.html page, replacing the single-page Cmd+K drawer in index.html:199-408.
4. Repoint the assistant surface from NarAI v2 (/api/v2/narai/chat) to the KAI daemon (/kai/chat, /admin/kai-chat) so one brain, one tool registry, one governance layer answers everywhere.
5. Page-context awareness: pass current admin route/entity (portfolio slug, merchant id, siteboost run) into KAI chat context so 'what's next' is scoped to the surface the operator is on.
6. Bring KAI memory/KG/twin/persona (backend/app/routers/admin_kg.py, admin_twin.py, admin_persona.py) into the shell so the drawer and full Nexus read/write one memory.
7. Apply KAI's @audited governance (backend/app/services/governance.py) to admin write actions currently gated only by X-API-Key (siteboost send narai/api/routes/siteboost_admin.py:676-745, portfolio orchestrator arm/kill portfolio_admin.py:67-79).
8. Voice: unify KAI TTS/voice (/kai/tts, chat.js:113) and NarAI /api/narai/tts,/speak,/voice_chat into one voice pipeline for the presence layer.
9. Sol admin (frontend/sol/admin.html) has its own TOTP identity and money-halt kill switch — decide whether it joins the unified session or stays a hard-isolated money-domain island (recommended: island, linked but separately authed).
10. Consolidate the ~15 ad-hoc scheduler threads in core/api.py _lifespan_bg and the KAI schedulers (digest/checkin/research) into one job model so 'what is KAI doing' has a single answer.

## Phase plan (mapped to real files)

### P1 — Freeze the seam & kill key injection
- **Goal:** Replace '%%API_KEY%%' HTML injection and query-param key with a real server-side operator session cookie; keep tests/test_wmos_containment.py green.
- **Files:** `core/api.py:855-880 (middleware), :1688-1716 (serve_portfolio_admin/cockpit), :1669 (serve_siteboost_admin), frontend/admin/portfolio.html:82 (INJECTED const), tests/test_wmos_containment.py`

### P2 — Unify identity model
- **Goal:** Introduce one operator-session + RBAC role scopes; make X-Admin-Token (KAI) and admin session resolve to the same principal.
- **Files:** `backend/app/dependencies/admin.py (require_admin_token), new core/session.py, core/api.py:186-203 (verify_api_key), backend/app/static/nai/admin.js:1-24`

### P3 — Bridge the two apps
- **Goal:** Make backend/app KAI routers reachable same-origin from the admin shell (mount as sub-app or reverse-proxy) so cookies/session flow to KAI.
- **Files:** `core/api.py (add app.mount for KAI), backend/app/main.py:183-234 (router includes + static mount), railway.json:7 (start command / two-service topology)`

### P4 — Extract the shell chrome
- **Goal:** Factor the shared header/nav/theme out of frontend/admin/index.html into an includable shell so every page gets the same frame and a mount point for the orb.
- **Files:** `frontend/admin/index.html, frontend/admin/{portfolio,siteboost,shopify,leadgen,scoreboard,wvkey,theme-picker}.html, core/api.py _serve_frontend`

### P5 — Build the presence orb
- **Goal:** Ship minimized orb -> assistant drawer -> full Nexus state machine as one component mounted in the shell head, replacing index.html's inline Cmd+K drawer.
- **Files:** `new frontend/admin/kai-presence.js + .css, frontend/admin/index.html:199-408 (remove inline drawer), backend/app/static/nai/chat.js (reuse SSE client logic)`

### P6 — Point the orb at the KAI brain
- **Goal:** Wire drawer/Nexus to /kai/chat + /admin/kai-chat instead of /api/v2/narai/chat; carry the session cookie.
- **Files:** `frontend/admin/kai-presence.js, backend/app/routers/admin_chat.py:171-339, core/api.py:14892-14932 (deprecate v2 chat drawer path)`

### P7 — Context awareness
- **Goal:** Feed current route/entity into KAI context so answers are page-scoped.
- **Files:** `frontend/admin/kai-presence.js (context provider), backend/app/routers/admin_chat.py (AdminChatRequest context field), frontend/admin/portfolio_cockpit.html (slug), shopify.html (merchant id)`

### P8 — Shared memory / KG / twin in-shell
- **Goal:** Expose KAI KG/twin/persona/memory read+write through the Nexus mode so one memory backs the orb.
- **Files:** `backend/app/routers/admin_kg.py, admin_twin.py, admin_persona.py, admin_journal.py, frontend/admin/kai-presence.js (Nexus panels)`

### P9 — Governance on admin writes
- **Goal:** Route admin mutating actions through @audited scope/approval so RBAC + audit cover business ops too.
- **Files:** `backend/app/services/governance.py, narai/api/routes/siteboost_admin.py:676-745 (send), narai/api/routes/portfolio_admin.py:67-79 (orchestrator)`

### P10 — Overview consolidation
- **Goal:** Merge the duplicate stat surfaces into one honest overview (Supabase merchants + KAI /admin/stats + /admin/spend + scoreboard).
- **Files:** `frontend/admin/index.html (tiles), frontend/admin/scoreboard.html, backend/app/routers/admin_data.py:81-208, narai/api/routes/shopify_admin.py:35-66`

### P11 — Retire legacy dashboard duplicates
- **Goal:** Remove the iframe-embed tabs that duplicate standalone pages; migrate any unique legacy tabs (whatsapp, kdp, pipelines) as real shell pages.
- **Files:** `dashboard/index.html nav('shopify'/'siteboost'/'sol'/'toodle'/'hub'/'revenue2'/'money'), core/api.py:1640-1652 (serve_admin_dashboard/hub/legacy)`

### P12 — Voice + secrets unification
- **Goal:** One voice pipeline (KAI TTS) for the presence layer; make wvkey the vault-of-record and the dashboard token store a read-only mirror.
- **Files:** `backend/app/static/nai/chat.js:113 (/kai/tts), core/api.py (/api/narai/tts,/speak), frontend/admin/wvkey.html, dashboard/index.html nav('tokens')`

### P13 — Sol island decision + cutover
- **Goal:** Decide Sol admin stays a separately-authed money island linked from the shell; verify RBAC never bypassed end-to-end; delete the dead auth schemes.
- **Files:** `frontend/sol/admin.html, backend/app/routers/sol.py, core/api.py:14904 (v2 auth), dashboard /api/auth/login, tests/test_wmos_containment.py`

## Risks

- FALSE PREMISE IN THE BRIEF: the KAI Nexus is not at backend/app/static/nai/nexus (no such subdir) and is not ES modules — it is the flat backend/app/static/nai/ with vanilla-JS chat.js/admin.js/auth.js. Any plan assuming a modular 'nexus' bundle is wrong; confirm the real files first.
- TWO SEPARATE DEPLOYMENTS: railway.json runs core.api:app; backend/app/main.py is a different app/deploy (kai.wheellsverse.com). 'ONE identity/session/memory' is impossible until P3 bridges them — this is the load-bearing risk, not a detail.
- TWO CHAT BRAINS: NarAI v2 (/api/v2/narai/chat) and KAI daemon (/kai/chat) are different LLM stacks with different memory. Repointing the drawer (P6) silently changes behavior, tool access and cost — needs explicit cutover, not a URL swap.
- C1 still live: API_KEY is string-injected into unauthenticated /admin HTML (core/api.py:1688-1716) and query-param keys are accepted (:873). Until P1/P2 land, the orb-on-every-page work expands the exposed surface.
- RBAC bypass hazard: KAI /admin/kai-chat spins up a synthetic 'ultra' operator profile bypassing all tier gates (admin_chat.py:60-116). If the unified session lets any admin reach it, that is a privilege-escalation path — RBAC scoping in P2/P9 must gate it.
- Sol money domain: frontend/sol/admin.html controls real/mock ACH movement with its own TOTP + global halt. Folding it into a shared session risks weakening the strongest auth boundary in the system; keep it an island (P13).
- Three secret vaults (wvkey local, dashboard DB, narai/godmode/vault.py) — auto-consolidation could leak or lose credentials; treat as read-before-merge, owner-picked only.
- Multi-worker persistence: W-MOS and many caches use JSON/JSONL + process-local locks (per the transformation plan §0); unifying sessions across gunicorn workers needs a shared store (cookie+DB), not in-memory.

## Per-capability ledger (NEEDS_INTEGRATION + DUPLICATE)

| ID | Capability | Domain | Class | Location | Status |
|---|---|---|---|---|---|
| dash-nav-aichat | AI Chat tab (Claude-level interface) | kai | NEEDS_INTEGRATION | `dashboard/index.html:493-497, 6590-6917` | MAPPED |
| dash-nav-agentmode | Agent tab (autonomous agent runs) | agents | NEEDS_INTEGRATION | `dashboard/index.html:498` | MAPPED |
| dash-nav-autopilot | Autopilot tab | agents | NEEDS_INTEGRATION | `dashboard/index.html:549` | MAPPED |
| core-api-admin-csp-scoping | CSP header scoped to /admin and /dashboard paths (core.api) | security | NEEDS_INTEGRATION | `core/api.py:827-838` | MAPPED |
| dash-nav-codestudio | Code Studio tab | other | NEEDS_INTEGRATION | `dashboard/index.html:509` | MAPPED |
| dash-nav-command | Command tab | other | NEEDS_INTEGRATION | `dashboard/index.html:590` | MAPPED |
| dash-nav-decisions | Decision Engine tab | agents | NEEDS_INTEGRATION | `dashboard/index.html:523, 2073-2089` | MAPPED |
| twin-storage-service | Digital twin storage | knowledge | NEEDS_INTEGRATION | `backend/app/services/twin/storage.py, backend/app/services/t` | MAPPED |
| kai-presets | Expert-agent presets (filter_registry / get_preset) | kai | NEEDS_INTEGRATION | `backend/app/routers/nai.py:70-76, backend/app/routers/admin_` | MAPPED |
| core-api-legacy-admin-root | GET /admin (core.api) — legacy 144-bot dashboard | admin | NEEDS_INTEGRATION | `core/api.py:1639-1644` | MAPPED |
| kai-redirect-admin | GET /admin -> 307 /kai-ui/admin.html | nav | NEEDS_INTEGRATION | `backend/app/main.py:351-357` | MAPPED |
| kai-admin-dashboard-page | GET /admin → 307 redirect to /kai-ui/admin.html | kai | NEEDS_INTEGRATION | `backend/app/routers/admin_chat.py (redirect tested in backen` | MAPPED |
| api-readyz | GET /readyz | kai | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/data.js:75 (data.tryReal)` | MAPPED |
| wmos-sol-legacy-page | GET /sol/admin | business | NEEDS_INTEGRATION | `core/api.py:1260` | MAPPED |
| core-api-sol-admin | GET /sol/admin (core.api) | sol | NEEDS_INTEGRATION | `core/api.py:1260-1262` | MAPPED |
| global-api-key-middleware | Global X-API-Key auth gate | core | NEEDS_INTEGRATION | `core/api.py:120-205 (verify_api_key, _API_KEY, _PUBLIC_PATHS` | MAPPED |
| sol-internal-admin-router | Internal /admin/sol ROSCA engine (parallel/duplicate backend) | sol | NEEDS_INTEGRATION | `backend/app/routers/sol.py:44-352; mounted backend/app/main.` | MAPPED |
| admin-index-kai-chat-drawer | KAI Chat Drawer (floating) | kai | NEEDS_INTEGRATION | `frontend/admin/index.html:199-408` | MAPPED |
| kai-nexus-static-app | KAI Command Nexus (backend/app/static/nai/nexus) | kai | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/app.js, data.js, panels/, av` | MAPPED |
| kai-nexus-agents-panel | KAI Command Nexus — Agents constellation panel | kai | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/panels/agents.js (243 lines)` | MAPPED |
| nexus-activity-panel | KAI Nexus Live Activity panel | activity | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/panels/activity.js` | MAPPED |
| nexus-memory-panel | KAI Nexus Memory panel (KG visualization) | memory | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/panels/memory.js` | MAPPED |
| admin-audit-run | KAI self-audit / health report | security | NEEDS_INTEGRATION | `backend/app/routers/admin_audit.py:25-27` | MAPPED |
| dash-nav-kai-iframe | KAI tab (embedded operator dashboard) | kai | NEEDS_INTEGRATION | `dashboard/index.html:502` | MAPPED |
| dash-nav-kb | Knowledge Base tab | knowledge | NEEDS_INTEGRATION | `dashboard/index.html:500` | MAPPED |
| admin-spend-rollup | LLM spend rollup | finance | NEEDS_INTEGRATION | `backend/app/routers/admin_data.py:156-208` | MAPPED |
| admin-launch-stats | Launch stats | overview | NEEDS_INTEGRATION | `backend/app/routers/admin_data.py:81-129` | MAPPED |
| learning-synthesis-service | Learning synthesis service | knowledge | NEEDS_INTEGRATION | `backend/app/services/learning/synthesis.py` | MAPPED |
| memory-pgvector-store | Memory store (pgvector) | memory | NEEDS_INTEGRATION | `backend/app/services/memory/store.py, backend/app/models/mem` | MAPPED |
| dash-nav-memory | Memory tab | memory | NEEDS_INTEGRATION | `dashboard/index.html:525` | MAPPED |
| dash-nav-money | Money Center tab | finance | NEEDS_INTEGRATION | `dashboard/index.html:542` | MAPPED |
| dash-nav-narai | NarAI tab (agent persona, chat, board, trading) | kai | NEEDS_INTEGRATION | `dashboard/index.html:485-490,799-1038` | MAPPED |
| nexus-data-layer-memory-activity-sim | Nexus data.js simulated memory+activity store | memory | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/data.js:18-66,120-137` | MAPPED |
| api-auth-login | POST /api/auth/login | auth | NEEDS_INTEGRATION | `dashboard/index.html checkAuth()` | MAPPED |
| admin-recent-users | Recent signups list | overview | NEEDS_INTEGRATION | `backend/app/routers/admin_data.py:132-153` | MAPPED |
| dash-nav-security | Security Scan tab | security | NEEDS_INTEGRATION | `dashboard/index.html:583` | MAPPED |
| sol-webhook-dwolla | Sol Dwolla webhook | sol | NEEDS_INTEGRATION | `backend/app/routers/sol.py:361-389; mounted backend/app/main` | MAPPED |
| kai-spend-cap | SpendCapExceeded handling | kai | NEEDS_INTEGRATION | `backend/app/routers/nai.py:36,88-91,113-115 (impl in app.ser` | MAPPED |
| dash-nav-superagent | SuperAgent tab | agents | NEEDS_INTEGRATION | `dashboard/index.html:488, 5640-5963` | MAPPED |
| dash-nav-tokens | Token Vault tab | security | NEEDS_INTEGRATION | `dashboard/index.html:587` | MAPPED |
| admin-html-no-memory-surface | WheellsVerse admin HTML pages — no memory/KG/activity UI | overview | NEEDS_INTEGRATION | `frontend/admin/*.html (index, leadgen, portfolio, portfolio_` | MAPPED |
| shared-admin-key-pattern | X-API-Key admin-gate helper (duplicated 3x) | kai | NEEDS_INTEGRATION | `narai/api/routes/portfolio_admin.py:22-29, portfolio_cockpit` | MAPPED |
| core-api-key-auth-scheme | core.api API_KEY auth scheme | auth | NEEDS_INTEGRATION | `core/api.py:126-205, 857-875` | MAPPED |
| wmos-api-auth-module-missing | core.api_auth (is_locked_mutation / requires_api_key) | security | NEEDS_INTEGRATION | `MISSING from wheellsverse-kai-nexus — referenced only by tes` | MAPPED |
| narai-marketing | narai/marketing autopilot | narai | NEEDS_INTEGRATION | `narai/marketing/api.py, marketing_autopilot.py` | MAPPED |
| kai-cors-origins-config | settings.cors_origins | security | NEEDS_INTEGRATION | `backend/app/config.py (referenced backend/app/main.py:241)` | MAPPED |
| wmos-containment-test-suite | tests/test_wmos_containment.py | security | NEEDS_INTEGRATION | `NOT PRESENT in wheellsverse-kai-nexus; found only at /Users/` | MAPPED |
| kai-router-v1 | v1.router | kai | NEEDS_INTEGRATION | `backend/app/main.py:305` | MAPPED |
| wmos-wvkey-page | wvkey secrets vault page | security | NEEDS_INTEGRATION | `frontend/admin/wvkey.html` | MAPPED |
| legacy-dashboard-shell | AI Command Center (legacy dashboard) page | overview | DUPLICATE | `dashboard/index.html` | DISCOVERED |
| dash-nav-hub | Command Hub tab | overview | DUPLICATE | `dashboard/index.html:484` | DISCOVERED |
| bot-workforce-engineer | EngineerBot (99_engineer_bot) | other | DUPLICATE | `bots/agent_workforce/99_engineer_bot/bot.py:18+` | DISCOVERED |
| core-api-admin-legacy-alias | GET /admin/legacy (core.api) | admin | DUPLICATE | `core/api.py:1651-1653` | DISCOVERED |
| dash-nav-marketintel | Market Intel tab | research | DUPLICATE | `dashboard/index.html:551` | DISCOVERED |
| nexus-mobile-kpi-cards | Mobile KPI cards (Security/Agents/Spend) | kai | DUPLICATE | `backend/app/static/nai/nexus/index.html:62, js/app.js` | DISCOVERED |
| nexus-panel-memory-workspace | Panel: KAI Memory knowledge graph (workspace tab) | memory | DUPLICATE | `backend/app/static/nai/nexus/js/panels/memory.js` | DISCOVERED |
| nexus-panel-memory-mini | Panel: Memory (left rail mini-card) | memory | DUPLICATE | `backend/app/static/nai/nexus/js/panels/system.js (renderMemo` | DISCOVERED |
| nexus-panel-security-workspace | Panel: Security Command Center (workspace tab) | security | DUPLICATE | `backend/app/static/nai/nexus/js/panels/security.js` | DISCOVERED |
| dash-nav-revenue2 | Revenue V2 tab | finance | DUPLICATE | `dashboard/index.html:531` | DISCOVERED |
| dash-nav-shopify | Shopify tab (in legacy dashboard) | business | DUPLICATE | `dashboard/index.html:535` | DISCOVERED |
| dash-nav-siteboost | SiteBoost tab (iframe embed) | business | DUPLICATE | `dashboard/index.html:537` | DISCOVERED |
| dash-nav-sol | Sol tab (iframe or embedded view) | sol | DUPLICATE | `dashboard/index.html:545` | DISCOVERED |
| kai-static-mount-nai-ui | StaticFiles mount /nai-ui -> backend/app/static/nai (duplicate) | kai | DUPLICATE | `backend/app/main.py:320-324` | DISCOVERED |
| dash-nav-toodle | Toodle tab | other | DUPLICATE | `dashboard/index.html:544` | DISCOVERED |
| kai-launchd-legacy-agent | com.wheellsverse.nai.plist — superseded per-user LaunchAgent | deploy | DUPLICATE | `deploy/launchd/com.wheellsverse.nai.plist` | DISCOVERED |
| deploy-railway-json-stale | deploy/railway.json (Dockerfile-builder variant) | deploy | DUPLICATE | `deploy/railway.json` | DISCOVERED |
| wmos-second-api-key-check | duplicate inline API-key check (line ~857) | security | DUPLICATE | `core/api.py:854-877` | DISCOVERED |
| page-portfolio-html | frontend/admin/portfolio.html | portfolio | DUPLICATE | `frontend/admin/portfolio.html (151 lines)` | DISCOVERED |
| page-portfolio-cockpit-html | frontend/admin/portfolio_cockpit.html | portfolio | DUPLICATE | `frontend/admin/portfolio_cockpit.html (151 lines)` | DISCOVERED |
| page-shopify-html | frontend/admin/shopify.html | shopify | DUPLICATE | `frontend/admin/shopify.html (258 lines)` | DISCOVERED |
| page-siteboost-html | frontend/admin/siteboost.html | siteboost | DUPLICATE | `frontend/admin/siteboost.html (1445 lines)` | DISCOVERED |
