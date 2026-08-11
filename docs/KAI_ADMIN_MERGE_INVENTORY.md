# KAI ⇄ Admin Merge — Capability Inventory

> Generated 2026-08-11 from an 11-reader + synthesis inventory workflow (1.36M subagent tokens, 260 tool calls). **585 capabilities** cataloged across both systems. This is the §0 map — nothing is deleted until it exists.

## ⚠️ Load-bearing correction to the brief

The brief assumes **one buildless FastAPI app with two frontends** and a modular `backend/app/static/nai/nexus` ES-module Nexus. The repo says otherwise, and this changes the plan:

- **There are TWO separate FastAPI deployments.** Production (`railway.json` + `nixpacks.toml` + `Dockerfile`) runs **`uvicorn core.api:app`** — a 15,377-line monolith serving `frontend/admin/*.html` (the green admin at **app.wheellsverse.com**), the ~19k-line legacy `dashboard/index.html`, Sol admin, the NarAI-v2 chat, and all `/api/narai/*` business surfaces.
- The **KAI brain + cinematic Nexus** live in a *different* app, **`backend/app/main.py`** (**kai.wheellsverse.com**), serving `backend/app/static/nai/*` (incl. `nexus/`) plus ~25 governed `admin_*` routers (chat, KG, twin, persona, planning, learning, self-heal, browser, SWE, research, EQ…).
- **`core/api.py` imports zero KAI `admin_*` routers.** The only link today is one iframe in the legacy dashboard pointing at kai.wheellsverse.com.

**Consequence:** "ONE identity / session / memory" is *impossible* until the two apps are bridged same-origin (sub-app mount or reverse-proxy) with a shared session. Identity must come before presence.

## Totals

| Classification | Count |
|---|---|
| ADMIN_ONLY | 321 |
| KAI_ONLY | 171 |
| NEEDS_INTEGRATION | 49 |
| SHARED | 22 |
| DUPLICATE | 22 |

| System of origin | Count |
|---|---|
| BACKEND | 179 |
| KAI | 174 |
| ADMIN | 111 |
| NARAI | 76 |
| CORE | 45 |

| Domain | Count |
|---|---|
| kai | 132 |
| business | 84 |
| agents | 52 |
| other | 48 |
| siteboost | 46 |
| security | 35 |
| finance | 26 |
| memory | 17 |
| auth | 17 |
| portfolio | 16 |
| infra | 15 |
| sol | 11 |
| activity | 9 |
| nexora | 9 |
| deploy | 9 |
| knowledge | 8 |
| shopify | 7 |
| overview | 6 |
| documents | 5 |
| research | 5 |
| narai | 5 |
| nav | 5 |
| admin | 5 |
| code_intel | 4 |
| predictions | 3 |
| core | 2 |
| news | 1 |
| market | 1 |
| world | 1 |
| events | 1 |

## Capabilities by domain

### kai  (132)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| AI Chat tab (Claude-level interface) | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:493-497, 6590-6917` |
| Expert-agent presets (filter_registry / get_preset) | tool | KAI | NEEDS_INTEGRATION | `backend/app/routers/nai.py:70-76, backend/app/routers/admin_chat.py:20` |
| GET /admin → 307 redirect to /kai-ui/admin.html | page | KAI | NEEDS_INTEGRATION | `backend/app/routers/admin_chat.py (redirect tested in backend/tests/te` |
| GET /readyz | api | BACKEND | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/data.js:75 (data.tryReal)` |
| KAI Chat Drawer (floating) | drawer | ADMIN | NEEDS_INTEGRATION | `frontend/admin/index.html:199-408` |
| KAI Command Nexus (backend/app/static/nai/nexus) | page | KAI | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/app.js, data.js, panels/, avatar/, voi` |
| KAI Command Nexus — Agents constellation panel | component | NARAI | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/panels/agents.js (243 lines) + backend` |
| KAI tab (embedded operator dashboard) | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:502` |
| NarAI tab (agent persona, chat, board, trading) | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:485-490,799-1038` |
| SpendCapExceeded handling | tool | KAI | NEEDS_INTEGRATION | `backend/app/routers/nai.py:36,88-91,113-115 (impl in app.services.rout` |
| X-API-Key admin-gate helper (duplicated 3x) | component | NARAI | NEEDS_INTEGRATION | `narai/api/routes/portfolio_admin.py:22-29, portfolio_cockpit_admin.py:` |
| v1.router | route | KAI | NEEDS_INTEGRATION | `backend/app/main.py:305` |
| Mobile KPI cards (Security/Agents/Spend) | component | KAI | DUPLICATE | `backend/app/static/nai/nexus/index.html:62, js/app.js` |
| StaticFiles mount /nai-ui -> backend/app/static/nai (duplicate) | route | KAI | DUPLICATE | `backend/app/main.py:320-324` |
| POST /api/v2/narai/insider/lead | api | NARAI | SHARED | `narai/api/routes/insider_admin.py:79-105` |
| 24 admin_*.py routers, all admin-token gated | api | KAI | KAI_ONLY | `backend/app/routers/admin_audit.py, admin_briefing.py, admin_browser.p` |
| Activate persona trait | api | KAI | KAI_ONLY | `backend/app/routers/admin_persona.py:66-89` |
| Adaptive FPS-based quality downgrade | workflow | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/app.js fpsMonitor()` |
| Add Knowledge Graph edge | api | KAI | KAI_ONLY | `backend/app/routers/admin_kg.py:112-140` |
| Add persona trait | api | KAI | KAI_ONLY | `backend/app/routers/admin_persona.py:55-63` |
| AgentBrain Protocol + DefaultBrain | service | BACKEND | KAI_ONLY | `backend/app/services/swe_runtime/brain.py:1-140+` |
| AgentRuntime Protocol + SandboxCommandRuntime | service | BACKEND | KAI_ONLY | `backend/app/services/swe_runtime/runtime.py:1-36` |
| Ambient background particle field (particles.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/particles.js` |
| Archive persona trait | api | KAI | KAI_ONLY | `backend/app/routers/admin_persona.py:71-94` |
| Avatar backend selector (avatar/controller.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/avatar/controller.js` |
| Check-in history | api | KAI | KAI_ONLY | `backend/app/routers/admin_checkin.py:31-34` |
| Check-in scheduler status | api | KAI | KAI_ONLY | `backend/app/routers/admin_checkin.py:37-39` |
| Cinematic workspace overlay (transitions.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/transitions.js` |
| Command dock + scripted conversation flow | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/app.js (submit/reply)` |
| Create journal entry | api | KAI | KAI_ONLY | `backend/app/routers/admin_journal.py:49-69` |
| DELETE /kai/conversations/{conv_id} (+ /nai alias) | api | KAI | KAI_ONLY | `backend/app/routers/nai.py:185-202` |
| Data honesty / freshness badge system (shared/dataFreshness.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/shared/dataFreshness.js` |
| Dev Avatar Lab overlay | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/dev/avatarLab.js` |
| Digest history | api | KAI | KAI_ONLY | `backend/app/routers/admin_digest.py:31-34` |
| Digest scheduler status | api | KAI | KAI_ONLY | `backend/app/routers/admin_digest.py:43-48` |
| GET /kai/chat/stream (+ /nai alias) | api | KAI | KAI_ONLY | `backend/app/routers/nai.py:122-143` |
| GET /kai/conversations (+ /nai alias) | api | KAI | KAI_ONLY | `backend/app/routers/nai.py:146-163` |
| GET /kai/conversations/{conv_id} (+ /nai alias) | api | KAI | KAI_ONLY | `backend/app/routers/nai.py:166-182` |
| GET /v1/models | api | KAI | KAI_ONLY | `backend/app/routers/v1.py:176-184` |
| GET /version — dashboard build stamp | route | KAI | KAI_ONLY | `backend/app/main.py:360-385` |
| GLB/VRM WebGL avatar backend (avatar/gltf.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/avatar/gltf.js` |
| Generate Daily Brief | api | KAI | KAI_ONLY | `backend/app/routers/admin_briefing.py:36-51` |
| Global 'Demo Data' topbar indicator | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/index.html:36, js/app.js updateDemoFlag()` |
| Idle sleep/wake cycle | workflow | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/app.js (touch/fpsMonitor block)` |
| Journal history | api | KAI | KAI_ONLY | `backend/app/routers/admin_journal.py:38-41` |
| Journal stats | api | KAI | KAI_ONLY | `backend/app/routers/admin_journal.py:44-46` |
| KAI Command Nexus page shell | page | KAI | KAI_ONLY | `backend/app/static/nai/nexus/index.html` |
| KAI Domain Expert Presets (PresetSpec registry) | service | BACKEND | KAI_ONLY | `backend/app/services/presets/registry.py:1-380 (PRESETS list)` |
| KAI state machine (KaiController) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/state.js` |
| Knowledge Graph entity search | api | KAI | KAI_ONLY | `backend/app/routers/admin_kg.py:56-72` |
| Knowledge Graph neighbors | api | KAI | KAI_ONLY | `backend/app/routers/admin_kg.py:75-99` |
| Knowledge Graph stats | api | KAI | KAI_ONLY | `backend/app/routers/admin_kg.py:41-53` |
| Latest digest | api | KAI | KAI_ONLY | `backend/app/routers/admin_digest.py:37-40` |
| List expert-agent presets | api | KAI | KAI_ONLY | `backend/app/routers/admin_presets.py:59-69` |
| Mood/EQ history | api | KAI | KAI_ONLY | `backend/app/routers/admin_eq.py:29-32` |
| Mood/EQ stats | api | KAI | KAI_ONLY | `backend/app/routers/admin_eq.py:24-26` |
| Operator KAI chat (full power) | api | KAI | KAI_ONLY | `backend/app/routers/admin_chat.py:171-339` |
| Operator profile resolution logic | tool | KAI | KAI_ONLY | `backend/app/routers/admin_chat.py:60-116` |
| Operator profile resolver | service | KAI | KAI_ONLY | `backend/app/routers/admin_chat.py:60-116` |
| POST /admin/kai-chat | api | KAI | KAI_ONLY | `backend/app/routers/admin_chat.py:171; tests: backend/tests/test_admin` |
| POST /kai/chat (and /nai/chat legacy alias) | api | KAI | KAI_ONLY | `backend/app/routers/nai.py:52-100 (mounted twice, backend/app/main.py:` |
| POST /kai/transcribe | api | KAI | KAI_ONLY | `backend/app/routers/transcribe.py:55-97` |
| POST /kai/tts | api | KAI | KAI_ONLY | `backend/app/routers/tts.py:52-70` |
| POST /v1/chat/completions | api | KAI | KAI_ONLY | `backend/app/routers/v1.py:87-173` |
| Panel: Capabilities grid (workspace tab, 'Tools' nav) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/tools.js` |
| Panel: Mission Control (workspace tab, 'Tasks' nav label) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/mission.js` |
| Panel: System · Health (left rail) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/system.js (renderSystem)` |
| Panel: Thinking Graph ('LIVE THINKING') | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/thinking.js` |
| Persona stats | api | KAI | KAI_ONLY | `backend/app/routers/admin_persona.py:50-52` |
| Persona traits profile | api | KAI | KAI_ONLY | `backend/app/routers/admin_persona.py:42-47` |
| PgVectorCodeSearchProvider user_id scoping | tool | KAI | KAI_ONLY | `backend/app/services/code_intel/pgvector_provider.py; tested by backen` |
| Portrait presence engine (avatar/portrait.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/avatar/portrait.js` |
| Preview preset effect on chat | api | KAI | KAI_ONLY | `backend/app/routers/admin_presets.py:72-97` |
| Procedural canvas2D avatar (avatar.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/avatar.js` |
| Pub/sub event bus (Bus class) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/state.js` |
| Render quality tier system (shared/quality.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/shared/quality.js` |
| Run check-in now | api | KAI | KAI_ONLY | `backend/app/routers/admin_checkin.py:42-54` |
| Run digest now | api | KAI | KAI_ONLY | `backend/app/routers/admin_digest.py:57-79` |
| Sound design engine (sound.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/sound.js` |
| StaticFiles mount /kai-ui -> backend/app/static/nai | route | KAI | KAI_ONLY | `backend/app/main.py:312-324` |
| Streaming speech subtitle/transcript | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/index.html:65, js/app.js submit()` |
| SuggestAgentTool (suggest_agent) | tool | BACKEND | KAI_ONLY | `backend/app/services/tools/suggest_agent.py:1-46` |
| Toast notification system | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/app.js toast()` |
| Topbar settings segments (Motion/Sound/Quality) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/index.html:19-35, js/app.js` |
| Voice control (voice.js, SpeechRecognition) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/voice.js` |
| Voice embodiment / TTS + viseme driver (voice/speech.js) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/voice/speech.js` |
| Voice/text intent -> view routing + gated-action toast | workflow | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/app.js bus.on('cmd:action', ...)` |
| Workspace tab bar (6 views) | nav | KAI | KAI_ONLY | `backend/app/static/nai/nexus/index.html:76-83, js/app.js openView()` |
| admin_swe.router + admin_swe_tasks.router (non-prod only) | route | KAI | KAI_ONLY | `backend/app/main.py:259-273, app/services/swe_runtime/config.py:swe_ad` |
| agent_router.classify_domain (the 'super-router') | service | BACKEND | KAI_ONLY | `backend/app/services/agent_router.py:1-123` |
| app.js bootstrap/orchestrator | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/app.js` |
| backend/app/static/nai/* KAI Nexus static asset set | page | KAI | KAI_ONLY | `backend/app/static/nai/ (admin.html/js/css, api-keys.*, auth.js, chat.` |
| backend/app/static/nai/admin.html + admin.js + admin.css | page | KAI | KAI_ONLY | `backend/app/static/nai/admin.html, admin.js, admin.css` |
| build_default_registry() / build_default_router() | tool | KAI | KAI_ONLY | `backend/app/routers/nai.py:34-49 (imports app.services.tools, app.serv` |
| classify_domain() super-router | tool | KAI | KAI_ONLY | `backend/app/routers/nai.py:67-68, backend/app/routers/admin_chat.py:19` |
| data.js simulated live-data engine | service | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/data.js` |
| nai.router dual-mounted at /kai and /nai | route | KAI | KAI_ONLY | `backend/app/main.py:306-310` |
| operator = tier='ultra' profile | component | KAI | KAI_ONLY | `backend/app/routers/admin_chat.py (_resolve_operator_profile, _operato` |
| predictions.router | route | KAI | KAI_ONLY | `backend/app/main.py:254` |
| transcribe.router, tts.router | route | KAI | KAI_ONLY | `backend/app/main.py:303-304` |
| ~25 admin_* routers (admin_data, admin_chat, admin_supreme, admin_briefing, admin_presets, admin_kg, admin_failures, admin_research, admin_self_correction, admin_self_heal, admin_planning, admin_browser, admin_learning, admin_twin, admin_persona, admin_eq, admin_relationship, admin_checkin, admin_code_intel, admin_journal, admin_audit, admin_digest, api_keys_admin) | route | KAI | KAI_ONLY | `backend/app/main.py:256-297` |
| GET /admin/relationship/milestones | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_relationship.py:34-38` |
| GET /admin/relationship/state | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_relationship.py:29-31` |
| GET /admin/swe/status | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe.py:47-49` |
| GET /admin/swe/tasks/{task_id} | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:147-154` |
| GET /admin/swe/tasks/{task_id}/patch | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:163-229` |
| GET /admin/swe/tasks/{task_id}/plan | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:155-162` |
| GET /admin/twin/decisions | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:67-70` |
| GET /admin/twin/drafts | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:61-64` |
| GET /admin/twin/profile | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:55-58` |
| GET /admin/twin/stats | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:73-75` |
| GET /api/v2/narai/insider/leads | api | NARAI | ADMIN_ONLY | `narai/api/routes/insider_admin.py:161-169` |
| GET /api/v2/narai/insider/subscribers | api | NARAI | ADMIN_ONLY | `narai/api/routes/insider_admin.py:175-180` |
| Grounded verification pass (verify) | tool | KAI | ADMIN_ONLY | `backend/app/routers/admin_chat.py:301-318 (impl in app.services.ground` |
| Insider admin router mount | route | NARAI | ADMIN_ONLY | `core/api.py:14978, 14980-14985` |
| POST /admin/relationship/milestones | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_relationship.py:41-47` |
| POST /admin/swe/run | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe.py:52-71` |
| POST /admin/swe/tasks | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:116-146` |
| POST /admin/swe/tasks/{task_id}/plan/approve | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:230-300` |
| POST /admin/swe/tasks/{task_id}/push/approve | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:301-347` |
| POST /admin/swe/tasks/{task_id}/reject | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:348-380+` |
| POST /admin/twin/decide | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:144-153,191-195` |
| POST /admin/twin/draft | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:135-141,185-188` |
| POST /admin/twin/entries | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:78-86` |
| POST /admin/twin/entries/{entry_id}/activate | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:125-127,175-177` |
| POST /admin/twin/entries/{entry_id}/archive | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:130-132,180-182` |
| POST /admin/twin/suggest | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_twin.py:116-122,169-172` |
| POST /api/v2/narai/insider/reissue | api | NARAI | ADMIN_ONLY | `narai/api/routes/insider_admin.py:217-267` |
| POST /api/v2/narai/insider/revoke | api | NARAI | ADMIN_ONLY | `narai/api/routes/insider_admin.py:187-210` |
| Self-correction critic+reviser loop (self_correct) | tool | KAI | ADMIN_ONLY | `backend/app/routers/admin_chat.py:260-299 (impl in app.services.self_c` |
| build_preview.mjs static bundler script | tool | KAI | ADMIN_ONLY | `backend/app/static/nai/nexus/build_preview.mjs` |
| nexus.test.mjs test suite | tool | KAI | ADMIN_ONLY | `backend/app/static/nai/nexus/tests/nexus.test.mjs` |

### business  (84)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| GET /sol/admin | page | BACKEND | NEEDS_INTEGRATION | `core/api.py:1260` |
| Shopify tab (in legacy dashboard) | nav | ADMIN | DUPLICATE | `dashboard/index.html:535` |
| SiteBoost tab (iframe embed) | nav | ADMIN | DUPLICATE | `dashboard/index.html:537` |
| Agent health/compliance store (AgentStatus/AgentHealth) | service | CORE | SHARED | `core/compliance.py:60-160+` |
| Ingest/predict task status | api | KAI | KAI_ONLY | `backend/app/routers/admin_data.py:47-54` |
| Trigger ingest all assets | api | KAI | KAI_ONLY | `backend/app/routers/admin_data.py:31-34` |
| Trigger ingest single asset | api | KAI | KAI_ONLY | `backend/app/routers/admin_data.py:37-44` |
| Trigger predict all (stocks+crypto) | api | KAI | KAI_ONLY | `backend/app/routers/admin_data.py:60-68` |
| Trigger predict single asset | api | KAI | KAI_ONLY | `backend/app/routers/admin_data.py:71-78` |
| Ads Board tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:532, 3121-3146` |
| AgentAdapter Protocol + dispatch (W-MOS action envelope) | service | CORE | ADMIN_ONLY | `core/portfolio/actions.py:1-90+` |
| Amazon KDP tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:533, 3178-3277` |
| AnalyticsAgentBot (101_analytics_bot) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/101_analytics_bot/bot.py:19+` |
| BoutiqueAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:316-387` |
| Build Cockpit (W-MOS per-business) page | page | ADMIN | ADMIN_ONLY | `frontend/admin/portfolio_cockpit.html` |
| CEOAgentBot (103_ceo_agent) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/103_ceo_agent/bot.py:27+` |
| CopywriterAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:457-522` |
| Etsy tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:538` |
| FunnelAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:627-708` |
| GET /admin, /admin/hub, /admin/legacy, /admin/theme-picker | page | BACKEND | ADMIN_ONLY | `core/api.py:1639-1662; frontend/admin/index.html, theme-picker.html` |
| GET /admin/leadgen | page | BACKEND | ADMIN_ONLY | `core/api.py:1766; frontend/admin/leadgen.html` |
| GET /admin/leadgen (core.api) | page | ADMIN | ADMIN_ONLY | `core/api.py:1766-1793` |
| GET /admin/portfolio | page | BACKEND | ADMIN_ONLY | `core/api.py:1687-1700; frontend/admin/portfolio.html` |
| GET /admin/portfolio + /admin/portfolio/{slug} (core.api) | page | ADMIN | ADMIN_ONLY | `core/api.py:1687-1739` |
| GET /admin/portfolio/{slug} | page | BACKEND | ADMIN_ONLY | `core/api.py:1703-1713; frontend/admin/portfolio_cockpit.html` |
| GET /admin/scoreboard | page | BACKEND | ADMIN_ONLY | `core/api.py:1739; frontend/admin/scoreboard.html` |
| GET /admin/scoreboard (core.api) | page | ADMIN | ADMIN_ONLY | `core/api.py:1739-1766` |
| GET /admin/shopify | page | BACKEND | ADMIN_ONLY | `core/api.py:1291` |
| GET /admin/shopify (core.api) | page | ADMIN | ADMIN_ONLY | `core/api.py:1291-1293` |
| GET /admin/siteboost | page | BACKEND | ADMIN_ONLY | `core/api.py:1665-1684; frontend/admin/siteboost.html` |
| GET /api/narai/leadgen/campaigns | api | BACKEND | ADMIN_ONLY | `frontend/admin/leadgen.html:52-66` |
| GET /api/narai/opportunities | api | BACKEND | ADMIN_ONLY | `frontend/admin/scoreboard.html:97-106` |
| GET /api/narai/portfolio/biz/{slug}/artifacts | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio_cockpit.html:110-116` |
| GET /api/narai/portfolio/biz/{slug}/overview | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio_cockpit.html:99-109` |
| GET /api/narai/portfolio/overview | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio.html:100-105` |
| GET /api/narai/scoreboard | api | BACKEND | ADMIN_ONLY | `frontend/admin/scoreboard.html:71-95` |
| GET /api/narai/shopify/merchants | api | BACKEND | ADMIN_ONLY | `called from frontend/admin/index.html, frontend/admin/shopify.html` |
| GET /api/narai/siteboost/costs | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html (loadCosts)` |
| GET /api/narai/siteboost/dashboard | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:864-887` |
| GET /api/narai/siteboost/launch-readiness | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:830-857` |
| GET /api/narai/siteboost/runs | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:890-901` |
| GET /digest/preview, POST /digest/send-now | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:761-800` |
| GET /shopify/install | route | BACKEND | ADMIN_ONLY | `frontend/admin/shopify.html:144-151` |
| GET/POST /api/narai/portfolio/approvals | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio.html:106-126` |
| GET/POST /api/narai/portfolio/orchestrator | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio.html:127-133` |
| Gumroad tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:539` |
| Honest portfolio scoreboard | api | BACKEND | ADMIN_ONLY | `core/api.py:1716-1725 (route); core/scoreboard.py` |
| Lead-Gen Campaigns page | page | ADMIN | ADMIN_ONLY | `frontend/admin/leadgen.html` |
| LiteraryQCAgent | agent | CORE | ADMIN_ONLY | `core/literary_qc.py:37-70+` |
| MonitorAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:777-825` |
| NexoraBuilderBot (102_nexora_builder) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/102_nexora_builder/bot.py:29+` |
| OrchestratorAgent (Shopify agent workforce) | service | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:862-1000+` |
| PMBot (100_pm_bot) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/100_pm_bot/bot.py:20+` |
| POST /api/narai/leadgen/run/{slug} | api | BACKEND | ADMIN_ONLY | `frontend/admin/leadgen.html:68-86` |
| POST /api/narai/portfolio/biz/{slug}/seed | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio_cockpit.html:129-133` |
| POST /api/narai/portfolio/biz/{slug}/tick | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio_cockpit.html:134-140` |
| POST /api/narai/shopify/merchants/{id}/test-product | api | BACKEND | ADMIN_ONLY | `frontend/admin/shopify.html:169-192` |
| POST /api/narai/siteboost/instantly/auto-create-campaign | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:802-828` |
| POST /api/narai/siteboost/scan | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:905-931` |
| POST /api/narai/siteboost/selftest | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html (runSelftest)` |
| Payhip tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:540` |
| Per-business Build Cockpit page | page | BACKEND | ADMIN_ONLY | `core/api.py:1703-1712; frontend/admin/portfolio_cockpit.html` |
| Portfolio HQ (W-MOS) page | page | ADMIN | ADMIN_ONLY | `frontend/admin/portfolio.html` |
| Portfolio Scoreboard page | page | ADMIN | ADMIN_ONLY | `frontend/admin/scoreboard.html` |
| Portfolio admin API | api | BACKEND | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py, prefix /api/narai/portfolio` |
| Portfolio cockpit API | api | BACKEND | ADMIN_ONLY | `narai/api/routes/portfolio_cockpit_admin.py, prefix /api/narai/portfol` |
| PricingAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:523-576` |
| Product Factory tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:541` |
| ProductResearchAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:577-626` |
| Publisher Engine tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:534` |
| QC Review tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:552, 5016` |
| ReviewAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:709-776` |
| SEOAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:388-456` |
| Scheduled scans CRUD | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:556-637` |
| Send/dispatch endpoints | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html` |
| Sequences CRUD/actions | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html` |
| Shopify Merchants page | page | ADMIN | ADMIN_ONLY | `frontend/admin/shopify.html` |
| SiteBoost Control Panel page | page | ADMIN | ADMIN_ONLY | `frontend/admin/siteboost.html` |
| SuperAgent (core/superagent.py) | service | CORE | ADMIN_ONLY | `core/superagent.py:84-970` |
| Suppression list CRUD | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:641-714` |
| ThemeAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:197-315` |
| UpgradeAgent | agent | CORE | ADMIN_ONLY | `core/shopify_agent_workforce.py:826-861` |
| W-MOS Portfolio HQ — 10-business rollup | page | BACKEND | ADMIN_ONLY | `core/api.py:1687-1701; frontend/admin/portfolio.html` |
| core/scoreboard.py business metrics module | service | CORE | ADMIN_ONLY | `core/scoreboard.py` |

### agents  (52)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Agent tab (autonomous agent runs) | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:498` |
| Autopilot tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:549` |
| Decision Engine tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:523, 2073-2089` |
| SuperAgent tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:488, 5640-5963` |
| Panel: Agent Constellation (workspace tab) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/agents.js` |
| Panel: Agents (left rail mini-card) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/system.js (renderAgents)` |
| Bot Builder tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:510` |
| Bot Control tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:508` |
| Bots tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:517` |
| GET /admin/browser/log | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_browser.py:50-53` |
| GET /admin/browser/status | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_browser.py:39-47` |
| GET /admin/failures/recent | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_failures.py:47-54` |
| GET /admin/failures/similar | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_failures.py:57-67` |
| GET /admin/failures/stats | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_failures.py:70-83` |
| GET /admin/learning/feedback | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:67-70` |
| GET /admin/learning/lessons | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:73-76` |
| GET /admin/learning/review | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:84-90` |
| GET /admin/learning/stats | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:79-81` |
| GET /admin/planning/list | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:76-92` |
| GET /admin/planning/stats | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:70-73` |
| GET /admin/planning/{plan_id} | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:95-103` |
| GET /admin/self-correction/events | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_self_correction.py:35-38` |
| GET /admin/self-correction/latest | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_self_correction.py:41-44` |
| GET /admin/self-correction/stats | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_self_correction.py:30-32` |
| GET /admin/self-heal/detect | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_self_heal.py:30-33` |
| GET /admin/swe/status | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe.py:47-49` |
| GET /admin/swe/tasks/{task_id} | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:147-152` |
| GET /admin/swe/tasks/{task_id}/patch | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:163-169` |
| GET /admin/swe/tasks/{task_id}/plan | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:155-160` |
| POST /admin/browser/execute | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_browser.py:127-153,185-198` |
| POST /admin/browser/navigate | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_browser.py:89-105,171-173` |
| POST /admin/browser/propose | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_browser.py:108-121,176-182` |
| POST /admin/learning/feedback | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:55-64` |
| POST /admin/learning/lessons/{lesson_id}/activate | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:121-123,154-156` |
| POST /admin/learning/lessons/{lesson_id}/dismiss | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:126-128,159-161` |
| POST /admin/learning/synthesize | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_learning.py:108-118,144-151` |
| POST /admin/planning/create | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:299-305` |
| POST /admin/planning/remediate | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:228-238,345-351` |
| POST /admin/planning/scout-integrate | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:241-255,354-363` |
| POST /admin/planning/{plan_id}/approve | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:187-198,318-320` |
| POST /admin/planning/{plan_id}/execute-next | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:201-214,323-331` |
| POST /admin/planning/{plan_id}/revise | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:217-225,334-342` |
| POST /admin/planning/{plan_id}/steps | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:308-315` |
| POST /admin/self-heal/run | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_self_heal.py:49-59` |
| POST /admin/swe/run | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe.py:52-81` |
| POST /admin/swe/tasks | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:116-144` |
| POST /admin/swe/tasks/{task_id}/plan/approve | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:230-269` |
| POST /admin/swe/tasks/{task_id}/push/approve | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:301-338` |
| POST /admin/swe/tasks/{task_id}/reject | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_swe_tasks.py:348-368` |
| POST /api/narai/leadgen/run/{slug} | api | BACKEND | ADMIN_ONLY | `core/api.py:1759` |
| Pipelines tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:519` |
| Pixel Agents tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:518` |

### other  (48)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Code Studio tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:509` |
| Command tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:590` |
| EngineerBot (99_engineer_bot) | agent | CORE | DUPLICATE | `bots/agent_workforce/99_engineer_bot/bot.py:18+` |
| Toodle tab | nav | ADMIN | DUPLICATE | `dashboard/index.html:544` |
| BaseBot (shared agent foundation) | component | CORE | SHARED | `core/base_bot.py:142-586+` |
| Alerts tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:565, 2352-2366` |
| Analytics tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:575` |
| Auto-Publish tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:559` |
| Automation tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:576` |
| Blog Board tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:558` |
| Canva tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:568` |
| CommunityAgentBot (108_community_agent) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/108_community_agent/bot.py:27+` |
| Content Engine tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:557` |
| ContentFactoryBot (105_content_factory) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/105_content_factory/bot.py:34+` |
| Creative Tools tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:501` |
| GitHub tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:574` |
| Market Data tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:572` |
| Market Live tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:573` |
| MarketIntelBot (106_market_intel) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/106_market_intel/bot.py:25+` |
| Newsletter Bot tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:563, 2940` |
| Notion tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:567` |
| OpsBot (97_ops_bot) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/97_ops_bot/bot.py:20+` |
| Outputs tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:577` |
| ProductAgentBot (107_product_agent) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/107_product_agent/bot.py:35+` |
| Projects tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:585` |
| Prompt Library tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:499` |
| Publish tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:556, 2434-2481` |
| Reddit Blitz tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:561` |
| SalesAgentBot (98_sales_bot) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/98_sales_bot/bot.py:18+` |
| Scheduler tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:520` |
| Schedules tab (NarAI) | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:550` |
| Search Console tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:564` |
| Settings tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:586` |
| Theme Picker page | page | ADMIN | ADMIN_ONLY | `frontend/admin/theme-picker.html` |
| TikTok Blitz tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:562` |
| Twitter Blitz tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:560` |
| Video Engine tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:553` |
| WhatsApp tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:487` |
| WordPress tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:566` |
| app.mount /social-media -> composed social image directory | route | ADMIN | ADMIN_ONLY | `core/api.py:771-779` |
| config.yaml — bot pipeline registry | service | CORE | ADMIN_ONLY | `config.yaml` |
| design_agent (bots/books/publisher_engine) | tool | CORE | ADMIN_ONLY | `bots/books/publisher_engine/design_agent.py:60+ run(manuscript, contex` |
| distribution_agent (bots/books/publisher_engine) | tool | CORE | ADMIN_ONLY | `bots/books/publisher_engine/distribution_agent.py:7+ run(manuscript, c` |
| editing_agent (bots/books/publisher_engine) | tool | CORE | ADMIN_ONLY | `bots/books/publisher_engine/editing_agent.py:30+ run(manuscript, conte` |
| market_agent (bots/books/publisher_engine) | tool | CORE | ADMIN_ONLY | `bots/books/publisher_engine/market_agent.py:50+ run(manuscript, contex` |
| marketing_agent (bots/books/publisher_engine) | tool | CORE | ADMIN_ONLY | `bots/books/publisher_engine/marketing_agent.py:74+ run(manuscript, con` |
| story_agent (bots/books/publisher_engine) | tool | CORE | ADMIN_ONLY | `bots/books/publisher_engine/story_agent.py:33+ run(manuscript, context` |
| style_agent (bots/books/publisher_engine) | tool | CORE | ADMIN_ONLY | `bots/books/publisher_engine/style_agent.py:48+ run(manuscript, context` |

### siteboost  (46)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| frontend/admin/siteboost.html | page | ADMIN | DUPLICATE | `frontend/admin/siteboost.html (1445 lines)` |
| SiteBoost prospect demo sites | page | CORE | KAI_ONLY | `local_prospect/site/index.html, pricing.html, thanks.html, work.html; ` |
| SiteBoost supporting core modules | service | CORE | KAI_ONLY | `core/siteboost_digest.py, core/siteboost_events.py, core/siteboost_ins` |
| DELETE /api/narai/siteboost/schedules/{schedule_id} | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:859-872` |
| GET /admin/siteboost (core.api) | page | ADMIN | ADMIN_ONLY | `core/api.py:1665-1687` |
| GET /api/narai/siteboost/costs | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:617-664` |
| GET /api/narai/siteboost/dashboard | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:210-242` |
| GET /api/narai/siteboost/digest/preview | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1383-1395` |
| GET /api/narai/siteboost/events | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1519-1530` |
| GET /api/narai/siteboost/instantly/active-campaign | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1268-1288` |
| GET /api/narai/siteboost/launch-readiness | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1396-1518` |
| GET /api/narai/siteboost/runs | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:243-247` |
| GET /api/narai/siteboost/runs/{run_id} | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:248-278` |
| GET /api/narai/siteboost/runs/{run_id}/export.csv | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1043-1121` |
| GET /api/narai/siteboost/runs/{run_id}/prospects | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:279-322` |
| GET /api/narai/siteboost/runs/{run_id}/prospects/{slug} | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:323-381` |
| GET /api/narai/siteboost/runs/{run_id}/stats | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1122-1194` |
| GET /api/narai/siteboost/scan/{task_id} | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1531-1541` |
| GET /api/narai/siteboost/schedules | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:824-834` |
| GET /api/narai/siteboost/sequences/{run_id} | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:665-675` |
| GET /api/narai/siteboost/suppressions | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1195-1205` |
| GET /api/narai/siteboost/warmup/status | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1331-1340` |
| PATCH /api/narai/siteboost/schedules/{schedule_id}/toggle | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:873-890` |
| POST /api/narai/siteboost/digest/send-now | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1364-1382` |
| POST /api/narai/siteboost/instantly/auto-create-campaign | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1244-1267` |
| POST /api/narai/siteboost/instantly/refresh-templates | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1289-1313` |
| POST /api/narai/siteboost/scan | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:746-823` |
| POST /api/narai/siteboost/schedules | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:835-858` |
| POST /api/narai/siteboost/schedules/{schedule_id}/run | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:891-917` |
| POST /api/narai/siteboost/selftest | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1542-1568` |
| POST /api/narai/siteboost/send | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:676-745` |
| POST /api/narai/siteboost/send-test | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:382-456` |
| POST /api/narai/siteboost/send-test-all | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:486-553` |
| POST /api/narai/siteboost/sequences/edit | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:592-616` |
| POST /api/narai/siteboost/sequences/override-name | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:918-1011` |
| POST /api/narai/siteboost/sequences/review | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:457-485` |
| POST /api/narai/siteboost/sequences/skip | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:554-591` |
| POST /api/narai/siteboost/sequences/skip-bulk | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1012-1042` |
| POST /api/narai/siteboost/state/block | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1569-1588` |
| POST /api/narai/siteboost/suppressions/add | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1206-1224` |
| POST /api/narai/siteboost/suppressions/remove | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1225-1243` |
| POST /api/narai/siteboost/warmup/advance | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1341-1363` |
| POST /api/narai/siteboost/warmup/start | api | NARAI | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py:1314-1330` |
| SiteBoost admin API (scans/sequences/costs/schedules/warmup/digest/suppressions) | api | BACKEND | ADMIN_ONLY | `narai/api/routes/siteboost_admin.py; mounted core/api.py:15193-15196 u` |
| SiteBoost admin router mount | route | NARAI | ADMIN_ONLY | `core/api.py:15193-15196` |
| SiteBoost control panel page | page | BACKEND | ADMIN_ONLY | `core/api.py:1665-1683; frontend/admin/siteboost.html` |

### security  (35)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| CSP header scoped to /admin and /dashboard paths (core.api) | component | ADMIN | NEEDS_INTEGRATION | `core/api.py:827-838` |
| KAI self-audit / health report | api | KAI | NEEDS_INTEGRATION | `backend/app/routers/admin_audit.py:25-27` |
| Security Scan tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:583` |
| Token Vault tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:587` |
| core.api_auth (is_locked_mutation / requires_api_key) | component | BACKEND | NEEDS_INTEGRATION | `MISSING from wheellsverse-kai-nexus — referenced only by tests/test_wm` |
| settings.cors_origins | component | KAI | NEEDS_INTEGRATION | `backend/app/config.py (referenced backend/app/main.py:241)` |
| tests/test_wmos_containment.py | event | BACKEND | NEEDS_INTEGRATION | `NOT PRESENT in wheellsverse-kai-nexus; found only at /Users/jhonwheele` |
| wvkey secrets vault page | page | BACKEND | NEEDS_INTEGRATION | `frontend/admin/wvkey.html` |
| Panel: Security Command Center (workspace tab) | component | KAI | DUPLICATE | `backend/app/static/nai/nexus/js/panels/security.js` |
| duplicate inline API-key check (line ~857) | component | BACKEND | DUPLICATE | `core/api.py:854-877` |
| @audited scope/approval governance decorator pattern | service | BACKEND | SHARED | `backend/app/services/governance.py (referenced across all 12 admin_* r` |
| Briefing governance audit tail | api | KAI | SHARED | `backend/app/routers/admin_briefing.py:54-58` |
| Panel: Security (left rail mini-card) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/system.js (renderSecurity)` |
| SecurityHeadersMiddleware | component | KAI | KAI_ONLY | `backend/app/main.py:251, backend/app/middleware/security_headers.py` |
| Settings.admin_token | component | KAI | KAI_ONLY | `backend/app/config.py:53-55` |
| Supreme latest proposal | api | KAI | KAI_ONLY | `backend/app/routers/admin_supreme.py:59-66` |
| Supreme proposal by name | api | KAI | KAI_ONLY | `backend/app/routers/admin_supreme.py:69-74` |
| Supreme scan history | api | KAI | KAI_ONLY | `backend/app/routers/admin_supreme.py:52-56` |
| Supreme scanner status | api | KAI | KAI_ONLY | `backend/app/routers/admin_supreme.py:38-49` |
| Topbar Secure/Elevated/Breach label | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/index.html:38, js/app.js bus.on('data:sec` |
| Trigger Supreme scan now | api | KAI | KAI_ONLY | `backend/app/routers/admin_supreme.py:77-90` |
| _enforce_debug_off_in_prod | component | KAI | KAI_ONLY | `backend/app/config.py:128-138` |
| _enforce_strong_admin_token_in_prod | component | KAI | KAI_ONLY | `backend/app/config.py:110-126` |
| _is_trusted_peer / _client_key | component | KAI | KAI_ONLY | `backend/app/dependencies/admin.py:48-79` |
| backend/tests/test_admin_chat.py | event | KAI | KAI_ONLY | `backend/tests/test_admin_chat.py (301 lines)` |
| backend/tests/test_admin_data.py | event | KAI | KAI_ONLY | `backend/tests/test_admin_data.py (195 lines)` |
| backend/tests/test_admin_security.py | event | KAI | KAI_ONLY | `backend/tests/test_admin_security.py (185 lines)` |
| per-client brute-force throttle | component | KAI | KAI_ONLY | `backend/app/dependencies/admin.py:33-97,117-136` |
| require_admin_token | tool | KAI | KAI_ONLY | `backend/app/dependencies/admin.py:99-136` |
| %%API_KEY%% placeholder substitution | component | BACKEND | ADMIN_ONLY | `core/api.py:1671-1900 (repeated per route, e.g. 1678-1683, 1697-1699, ` |
| API Keys tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:588` |
| ComplianceAgentBot (109_compliance_agent) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/109_compliance_agent/bot.py:30+` |
| Sol admin: 2FA/TOTP management | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| verify_api_key | component | BACKEND | ADMIN_ONLY | `core/api.py:186-206` |
| wvkey Vault runbook page | page | ADMIN | ADMIN_ONLY | `frontend/admin/wvkey.html` |

### finance  (26)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| LLM spend rollup | api | KAI | NEEDS_INTEGRATION | `backend/app/routers/admin_data.py:156-208` |
| Money Center tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:542` |
| Revenue V2 tab | nav | ADMIN | DUPLICATE | `dashboard/index.html:531` |
| GET /billing/subscription | api | BACKEND | SHARED | `backend/app/routers/billing.py:89-115` |
| POST /billing/cancellation-reason | api | BACKEND | SHARED | `backend/app/routers/billing.py:186-210` |
| POST /billing/checkout | api | BACKEND | SHARED | `backend/app/routers/billing.py:118-154` |
| POST /billing/portal | api | BACKEND | SHARED | `backend/app/routers/billing.py:157-175` |
| POST /billing/webhook | api | BACKEND | SHARED | `backend/app/routers/billing.py:298-336` |
| POST /billing/winback/apply-discount | api | BACKEND | SHARED | `backend/app/routers/billing.py:225-292` |
| Webhook event handlers (_handle_checkout_completed / _handle_sub_updated / _handle_sub_deleted / _handle_refund_or_dispute / _handle_payment_failed) | service | BACKEND | SHARED | `backend/app/routers/billing.py:376-536` |
| Panel: Costs (left rail mini-card) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/system.js (renderCosts)` |
| _enforce_stripe_money_mode | component | KAI | KAI_ONLY | `backend/app/config.py:140-175` |
| billing.router | route | KAI | KAI_ONLY | `backend/app/main.py:255` |
| Billing tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:589` |
| FinanceAgentBot (104_finance_agent) | agent | CORE | ADMIN_ONLY | `bots/agent_workforce/104_finance_agent/bot.py:26+` |
| Money Board tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:530, 2551-2723` |
| Sol Admin Portal page | page | ADMIN | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: Circles (savings groups) | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: Cycles | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: Email template previews | page | ADMIN | ADMIN_ONLY | `frontend/sol/admin.html:320` |
| Sol admin: Global money-movement halt | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: KYC Queue | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: Payments processing | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: Payouts | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: Reconcile | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |
| Sol admin: Users management | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |

### memory  (17)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| KAI Nexus Memory panel (KG visualization) | component | NARAI | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/panels/memory.js` |
| Memory store (pgvector) | service | BACKEND | NEEDS_INTEGRATION | `backend/app/services/memory/store.py, backend/app/models/memory.py` |
| Memory tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:525` |
| Nexus data.js simulated memory+activity store | service | NARAI | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/data.js:18-66,120-137` |
| Panel: KAI Memory knowledge graph (workspace tab) | component | KAI | DUPLICATE | `backend/app/static/nai/nexus/js/panels/memory.js` |
| Panel: Memory (left rail mini-card) | component | KAI | DUPLICATE | `backend/app/static/nai/nexus/js/panels/system.js (renderMemory)` |
| Failure memory Jaccard similarity search | service | KAI | KAI_ONLY | `backend/app/services/failure_memory/storage.py:171-201` |
| Failure memory write (auto) | service | KAI | KAI_ONLY | `backend/app/services/failure_memory/storage.py:90-126` |
| Journal SQLite storage | service | KAI | KAI_ONLY | `backend/app/services/journal/storage.py` |
| Memory semantic retrieval | service | BACKEND | KAI_ONLY | `backend/app/services/memory/retrieval.py` |
| Memory system-prompt injection | service | KAI | KAI_ONLY | `backend/app/services/nai_brain/memory_injection.py` |
| failure_lookup (chat tool) | tool | KAI | KAI_ONLY | `backend/app/services/tools/failure_lookup.py` |
| memory_tool (chat tool) | tool | KAI | KAI_ONLY | `backend/app/services/tools/memory_tool.py` |
| Create journal entry | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_journal.py:58-69` |
| Failures recent | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_failures.py:47-54` |
| Failures similar | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_failures.py:57-67` |
| Failures stats | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_failures.py:70-83` |

### auth  (17)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| POST /api/auth/login | api | BACKEND | NEEDS_INTEGRATION | `dashboard/index.html checkAuth()` |
| core.api API_KEY auth scheme | component | ADMIN | NEEDS_INTEGRATION | `core/api.py:126-205, 857-875` |
| DELETE /auth/me | api | BACKEND | SHARED | `backend/app/routers/auth.py:167-186` |
| GET /auth/me | api | BACKEND | SHARED | `backend/app/routers/auth.py:239-265` |
| POST /auth/forgot-password | api | BACKEND | SHARED | `backend/app/routers/auth.py:113-127` |
| POST /auth/login | api | BACKEND | SHARED | `backend/app/routers/auth.py:99-110` |
| POST /auth/logout | api | BACKEND | SHARED | `backend/app/routers/auth.py:208-236` |
| POST /auth/refresh | api | BACKEND | SHARED | `backend/app/routers/auth.py:189-205` |
| POST /auth/signup | api | BACKEND | SHARED | `backend/app/routers/auth.py:68-96` |
| DELETE /account/api-keys/{key_id} | api | KAI | KAI_ONLY | `backend/app/routers/api_keys_admin.py:103-113` |
| DELETE /auth/me | api | KAI | KAI_ONLY | `backend/app/routers/auth.py:167-186` |
| GET /account/api-keys | api | KAI | KAI_ONLY | `backend/app/routers/api_keys_admin.py:84-100` |
| GET /auth/me/export | api | BACKEND | KAI_ONLY | `backend/app/routers/auth.py:130-164` |
| POST /account/api-keys | api | KAI | KAI_ONLY | `backend/app/routers/api_keys_admin.py:67-81` |
| UserPrincipal / get_current_user | tool | KAI | KAI_ONLY | `backend/app/dependencies/supabase_jwt.py:52-132` |
| auth.router | route | KAI | KAI_ONLY | `backend/app/main.py:253, backend/app/routers/auth.py` |
| Sol admin auth endpoints | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html (adminLogin/adminLoginTotp)` |

### portfolio  (16)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| frontend/admin/portfolio.html | page | ADMIN | DUPLICATE | `frontend/admin/portfolio.html (151 lines)` |
| frontend/admin/portfolio_cockpit.html | page | ADMIN | DUPLICATE | `frontend/admin/portfolio_cockpit.html (151 lines)` |
| GET /api/narai/portfolio/approvals | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py:45-47` |
| GET /api/narai/portfolio/audit | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py:82-84` |
| GET /api/narai/portfolio/biz/{slug}/artifacts | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_cockpit_admin.py:54-63` |
| GET /api/narai/portfolio/biz/{slug}/audit | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_cockpit_admin.py:66-70` |
| GET /api/narai/portfolio/biz/{slug}/overview | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_cockpit_admin.py:32-51` |
| GET /api/narai/portfolio/orchestrator | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py:62-64` |
| GET /api/narai/portfolio/overview | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py:40-42` |
| POST /api/narai/portfolio/approvals/{approval_id}/execute | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py:57-59` |
| POST /api/narai/portfolio/approvals/{approval_id}/resolve | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py:50-54` |
| POST /api/narai/portfolio/biz/{slug}/seed | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_cockpit_admin.py:82-88` |
| POST /api/narai/portfolio/biz/{slug}/tick | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_cockpit_admin.py:73-79` |
| POST /api/narai/portfolio/orchestrator | api | NARAI | ADMIN_ONLY | `narai/api/routes/portfolio_admin.py:67-79` |
| Portfolio Build Cockpit router mount | route | NARAI | ADMIN_ONLY | `core/api.py:15213-15217` |
| Portfolio HQ admin router mount | route | NARAI | ADMIN_ONLY | `core/api.py:15205-15208` |

### infra  (15)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| GET /api/health | api | BACKEND | SHARED | `frontend/admin/index.html:467` |
| CORS middleware | component | KAI | KAI_ONLY | `backend/app/main.py:239-245` |
| FastAPI app construction + lifespan | service | KAI | KAI_ONLY | `backend/app/main.py:40-160` |
| GET /health — liveness probe | route | KAI | KAI_ONLY | `backend/app/main.py:388-392` |
| GET /readyz — readiness probe | route | KAI | KAI_ONLY | `backend/app/main.py:395-424` |
| Global unhandled-exception handler with Telegram alert | component | KAI | KAI_ONLY | `backend/app/main.py:186-237` |
| Panel: Infrastructure node graph (workspace tab) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/infrastructure.js` |
| SlowAPI global rate limiter | component | KAI | KAI_ONLY | `backend/app/main.py:162-165` |
| html_404_to_kai_ui HTTP middleware | component | KAI | KAI_ONLY | `backend/app/main.py:457-470` |
| kai_ui_cache_control HTTP middleware | component | KAI | KAI_ONLY | `backend/app/main.py:440-454` |
| Bot Health tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:524` |
| Connections tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:584` |
| SUPREMA tab (workspace autorepair) | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:503` |
| System Report tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:582` |
| compose.yaml (playwrightcore service) | service | CORE | ADMIN_ONLY | `compose.yaml` |

### sol  (11)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| GET /sol/admin (core.api) | page | ADMIN | NEEDS_INTEGRATION | `core/api.py:1260-1262` |
| Internal /admin/sol ROSCA engine (parallel/duplicate backend) | route | BACKEND | NEEDS_INTEGRATION | `backend/app/routers/sol.py:44-352; mounted backend/app/main.py:301` |
| Sol Dwolla webhook | api | BACKEND | NEEDS_INTEGRATION | `backend/app/routers/sol.py:361-389; mounted backend/app/main.py:302` |
| Sol tab (iframe or embedded view) | nav | ADMIN | DUPLICATE | `dashboard/index.html:545` |
| Sol design system stylesheet route | route | BACKEND | SHARED | `core/api.py:1274-1280` |
| Sol static asset mount | route | BACKEND | SHARED | `core/api.py:1282-1285` |
| sol.router + sol.webhook_router | route | KAI | KAI_ONLY | `backend/app/main.py:298-302` |
| Sol admin operator app | page | BACKEND | ADMIN_ONLY | `core/api.py:1260; frontend/sol/admin.html (1477 lines)` |
| Sol landing page | page | BACKEND | ADMIN_ONLY | `core/api.py:1247; frontend/sol/index.html` |
| Sol member app | page | BACKEND | ADMIN_ONLY | `core/api.py:1255; frontend/sol/app.html (1387 lines)` |
| app.mount /sol/assets -> frontend/sol/assets + GET /sol-design-system.css | route | ADMIN | ADMIN_ONLY | `core/api.py:1265-1287` |

### activity  (9)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| KAI Nexus Live Activity panel | component | NARAI | NEEDS_INTEGRATION | `backend/app/static/nai/nexus/js/panels/activity.js` |
| Check-in SQLite storage | service | KAI | KAI_ONLY | `backend/app/services/checkin/storage.py` |
| Panel: Live Activity feed (right rail) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/activity.js` |
| GET /api/narai/portfolio/audit | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio.html:134-140` |
| GET /api/narai/portfolio/biz/{slug}/audit | api | BACKEND | ADMIN_ONLY | `frontend/admin/portfolio_cockpit.html:117-123` |
| GET /api/narai/siteboost/events | api | BACKEND | ADMIN_ONLY | `frontend/admin/siteboost.html:716-755` |
| Live Logs tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:578` |
| Operator Tasks tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:504` |
| Sol admin: Audit log | api | BACKEND | ADMIN_ONLY | `frontend/sol/admin.html` |

### nexora  (9)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| NEXORA creator content + subscriptions | api | BACKEND | KAI_ONLY | `core/api.py:10690-10812` |
| NEXORA creator/fan platform auth | api | BACKEND | KAI_ONLY | `core/api.py:10626-10659, 10919-10959` |
| NEXORA data layer | service | CORE | KAI_ONLY | `core/nexora_db.py` |
| NEXORA growth strategy generator | api | BACKEND | KAI_ONLY | `core/api.py:10513-10530` |
| NEXORA marketing/creator pages | page | BACKEND | KAI_ONLY | `core/api.py:10533-10574` |
| NEXORA messaging/stats/webhook/fan-content | api | BACKEND | KAI_ONLY | `core/api.py:10842-10869, 10960-10970` |
| NEXORA platform status | api | BACKEND | KAI_ONLY | `core/api.py:10436-10485` |
| NEXORA recruitment bot trigger | api | BACKEND | KAI_ONLY | `core/api.py:10488-10510` |
| NEXORA tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:543` |

### deploy  (9)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| com.wheellsverse.nai.plist — superseded per-user LaunchAgent | service | KAI | DUPLICATE | `deploy/launchd/com.wheellsverse.nai.plist` |
| deploy/railway.json (Dockerfile-builder variant) | workflow | ADMIN | DUPLICATE | `deploy/railway.json` |
| backend/app/main.py deploy — launchd on Mac mini (KeepAlive) | service | KAI | KAI_ONLY | `deploy/launchd/com.wheellsverse.kai.plist, deploy/start_nai.sh` |
| Dockerfile (main app image) | service | ADMIN | ADMIN_ONLY | `Dockerfile` |
| Dockerfile.kdp (KDP publisher service) | service | CORE | ADMIN_ONLY | `Dockerfile.kdp` |
| core.api:app Railway deploy (root railway.json) | workflow | ADMIN | ADMIN_ONLY | `railway.json` |
| deploy/docker-compose.yml (local/self-host compose) | service | ADMIN | ADMIN_ONLY | `deploy/docker-compose.yml` |
| fly.toml (Fly.io deploy) | service | ADMIN | ADMIN_ONLY | `fly.toml` |
| render.yaml (Render.com deploy) | service | ADMIN | ADMIN_ONLY | `render.yaml` |

### knowledge  (8)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Digital twin storage | service | KAI | NEEDS_INTEGRATION | `backend/app/services/twin/storage.py, backend/app/services/twin/__init` |
| Knowledge Base tab | nav | ADMIN | NEEDS_INTEGRATION | `dashboard/index.html:500` |
| Learning synthesis service | service | KAI | NEEDS_INTEGRATION | `backend/app/services/learning/synthesis.py` |
| Digest synthesis service | service | KAI | KAI_ONLY | `backend/app/services/digest/digest.py` |
| Knowledge Graph SQLite storage | service | KAI | KAI_ONLY | `backend/app/services/kg/storage.py` |
| documents.router | route | KAI | KAI_ONLY | `backend/app/main.py:297` |
| kg_query (chat tool) | tool | KAI | KAI_ONLY | `backend/app/services/tools/kg_query.py` |
| Intelligence tab | nav | ADMIN | ADMIN_ONLY | `dashboard/index.html:526` |

### shopify  (7)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| frontend/admin/shopify.html | page | ADMIN | DUPLICATE | `frontend/admin/shopify.html (258 lines)` |
| GET /api/narai/shopify/merchants | api | NARAI | ADMIN_ONLY | `narai/api/routes/shopify_admin.py:35-66` |
| GET /api/narai/shopify/merchants/{merchant_id} | api | NARAI | ADMIN_ONLY | `narai/api/routes/shopify_admin.py:69-95` |
| GET /api/narai/shopify/plans | api | NARAI | ADMIN_ONLY | `narai/api/routes/shopify_admin.py:98-106` |
| Multi-tenant Shopify admin router mount | route | NARAI | ADMIN_ONLY | `core/api.py:15185-15196` |
| POST /api/narai/shopify/merchants/{merchant_id}/test-product | api | NARAI | ADMIN_ONLY | `narai/api/routes/shopify_admin.py:109-148` |
| POST /api/narai/shopify/test-printify | api | NARAI | ADMIN_ONLY | `narai/api/routes/shopify_admin.py:151-195` |

### overview  (6)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Launch stats | api | KAI | NEEDS_INTEGRATION | `backend/app/routers/admin_data.py:81-129` |
| Recent signups list | api | KAI | NEEDS_INTEGRATION | `backend/app/routers/admin_data.py:132-153` |
| WheellsVerse admin HTML pages — no memory/KG/activity UI | page | ADMIN | NEEDS_INTEGRATION | `frontend/admin/*.html (index, leadgen, portfolio, portfolio_cockpit, s` |
| AI Command Center (legacy dashboard) page | page | ADMIN | DUPLICATE | `dashboard/index.html` |
| Command Hub tab | nav | ADMIN | DUPLICATE | `dashboard/index.html:484` |
| Command Center page | page | ADMIN | ADMIN_ONLY | `frontend/admin/index.html` |

### documents  (5)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| DELETE /account/documents/{doc_id} | api | KAI | KAI_ONLY | `backend/app/routers/documents.py:145-155` |
| GET /account/documents | api | KAI | KAI_ONLY | `backend/app/routers/documents.py:85-101` |
| GET /account/documents/{doc_id}/retrieve | api | KAI | KAI_ONLY | `backend/app/routers/documents.py:117-142` |
| GET /account/documents/{doc_id}/text | api | KAI | KAI_ONLY | `backend/app/routers/documents.py:104-114` |
| POST /account/documents | api | KAI | KAI_ONLY | `backend/app/routers/documents.py:58-82` |

### research  (5)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Market Intel tab | nav | ADMIN | DUPLICATE | `dashboard/index.html:551` |
| GET /admin/research/digests | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_research.py:53-55` |
| GET /admin/research/latest | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_research.py:58-61` |
| GET /admin/research/status | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_research.py:37-50` |
| POST /admin/research/run-now | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_research.py:64-83` |

### narai  (5)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| narai/marketing autopilot | service | NARAI | NEEDS_INTEGRATION | `narai/marketing/api.py, marketing_autopilot.py` |
| narai/core submodules | service | NARAI | KAI_ONLY | `narai/core/{content,creative,kdp,ops,research,sales,shopify_mt,trading` |
| narai/godmode | service | NARAI | KAI_ONLY | `narai/godmode/{adapters,media,browser.py,cli.py,launch.py,launch_queue` |
| narai/integrations | service | NARAI | KAI_ONLY | `narai/integrations/{telegram.py,telegram_subscription.py,scheduler.py,` |
| narai package identity | service | NARAI | ADMIN_ONLY | `narai/__init__.py, narai/api/main.py, ARCHITECTURE.md` |

### nav  (5)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| GET /admin -> 307 /kai-ui/admin.html | route | KAI | NEEDS_INTEGRATION | `backend/app/main.py:351-357` |
| GET / -> 307 /kai-ui/ | route | KAI | KAI_ONLY | `backend/app/main.py:327-331` |
| GET /login -> 307 /kai-ui/login.html | route | KAI | KAI_ONLY | `backend/app/main.py:336-338` |
| GET /pricing -> 307 /kai-ui/pricing.html | route | KAI | KAI_ONLY | `backend/app/main.py:346-348` |
| GET /signup -> 307 /kai-ui/signup.html | route | KAI | KAI_ONLY | `backend/app/main.py:341-343` |

### admin  (5)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| GET /admin (core.api) — legacy 144-bot dashboard | page | ADMIN | NEEDS_INTEGRATION | `core/api.py:1639-1644` |
| GET /admin/legacy (core.api) | page | ADMIN | DUPLICATE | `core/api.py:1651-1653` |
| GET /admin/hub (core.api) | page | ADMIN | ADMIN_ONLY | `core/api.py:1645-1648` |
| GET /admin/theme-picker (core.api) | page | ADMIN | ADMIN_ONLY | `core/api.py:1657-1662` |
| frontend/admin/*.html static page set | page | ADMIN | ADMIN_ONLY | `frontend/admin/index.html, leadgen.html, portfolio.html, portfolio_coc` |

### code_intel  (4)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| POST /admin/code-intel/delete | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_code_intel.py:67-69,88-100` |
| POST /admin/code-intel/index | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_code_intel.py:62-85` |
| POST /admin/code-intel/search | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_code_intel.py:103-120` |
| POST /admin/planning/{plan_id}/draft-adapter | api | BACKEND | ADMIN_ONLY | `backend/app/routers/admin_planning.py:258-279,366-374` |

### predictions  (3)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| GET /predictions/stats | api | BACKEND | ADMIN_ONLY | `backend/app/routers/predictions.py:115-179` |
| GET /predictions/today | api | BACKEND | ADMIN_ONLY | `backend/app/routers/predictions.py:182-213` |
| GET /predictions/{symbol} | api | BACKEND | ADMIN_ONLY | `backend/app/routers/predictions.py:216-238` |

### core  (2)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Global X-API-Key auth gate | component | CORE | NEEDS_INTEGRATION | `core/api.py:120-205 (verify_api_key, _API_KEY, _PUBLIC_PATHS)` |
| Nexora / Store Intelligence public API allowlist | component | CORE | KAI_ONLY | `core/api.py:158-183` |

### news  (1)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Panel: Live Intelligence / News (right rail + tab) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/intelligence.js` |

### market  (1)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Panel: Market Intelligence (workspace tab) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/market.js` |

### world  (1)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Panel: World Pulse globe (workspace tab) | component | KAI | KAI_ONLY | `backend/app/static/nai/nexus/js/panels/world.js` |

### events  (1)

| Capability | Kind | Sys | Class | Location |
|---|---|---|---|---|
| Governance audit log (event/activity source of truth) | service | KAI | KAI_ONLY | `backend/app/services/governance/audit_log.py` |
