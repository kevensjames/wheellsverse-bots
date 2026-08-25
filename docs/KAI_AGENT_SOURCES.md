# KAI Agent Source Inventory (Phase 5A)

Ground truth for the Agent Command Center. **No fake agents** (§5A). There is
**no unified agent-registry endpoint** — truth is scattered across two apps and
~8 status surfaces. The only real "agent catalog" is App B `GET /admin/presets`
(11 expert personas), which carries **no runtime/health/cost state**.

## REAL_AGENT — AI agents KAI can delegate a task to

| id | name | source | invoke path | status source | scope |
|---|---|---|---|---|---|
| swe / marketing / crm / finance / research / legal_research / medical_research / dental_research / engineering / self_improvement / accounting | Expert-agent presets (11) | `backend/app/services/presets/registry.py:35` | `POST /admin/kai-chat` `{preset_id}` (or `auto_route`→`agent_router.classify_domain`) | `GET /admin/presets` (catalog only) | owner-only `kai.ultra` (`require_kai_ultra`) |
| nai_brain | NAI Brain (the agent substrate the presets run on) | `backend/app/services/nai_brain/brain.py` | `POST /admin/kai-chat[/stream]` | spend_tracker (per-turn) | `kai.ultra` |
| superagent | App A SuperAgent (autonomous bot operator) | `core/superagent.py:84` | `POST /api/superagent/cycle` / `/api/agent/run` | `GET /api/superagent/status` | App A operator_session |
| planning | Planning (semi-autonomous, human-in-loop) | `backend/app/services/planning/planner.py` | `POST /admin/planning/{id}/execute-next` | `GET /admin/planning/stats` | approve-then-execute |
| twin | Digital Twin (advisory-only, never executes) | `backend/app/services/twin/decide.py` | `POST /admin/twin/decide` | `GET /admin/twin/stats` | `kai.ultra` |

## WORKER — background jobs / cron / queues (NOT AI agents)
- **Shopify "Agent Workforce"** (10 threaded task-workers, fixed action handlers): `core/shopify_agent_workforce.py`; `GET /api/shopify/agents/status`. Misleadingly named "agents".
- Orchestrator + BaseBot fleet (`core/orchestrator.py`, `/api/bots`), autopilots (`core/autopilot.py`, narai_*), Product Factory, Toodle dispatcher, suprema/autorepair (cron), App B schedulers (research/supreme/self-heal/digest/checkin/sol), Celery (`backend/app/workers/tasks.py`).

## SERVICE — subsystems, not agents
self_correction, kg, memory, learning, persona, eq, relationship, journal, failure_memory, briefing, browser (read-only), sol, governance/audit.

## TOOL — callable tools agents USE (not delegable)
`services/tools/*`: web_search, web_fetch, memory, kg_query, failure_lookup, document_search, verify_claim, trading_signal, twenty_crm, composio_*, site_builder, image_gen, video_gen, github_scout, audit_query, pubmed/who/clinicaltrials/courtlistener/sec_edgar_search, browser_tool, dwolla_tool, suggest_agent, …

## BOT — messaging bots
`core/discord_bot.py`, `core/telegram_bot.py`.

## DUPLICATES to reconcile (one identity in the UI, never rendered twice)
- **"Research" ×3:** preset `research` (REAL_AGENT) ≠ `admin_research` scheduler (WORKER) ≠ `ProductResearchAgent` (Shopify WORKER).
- "Supreme/Suprema" ×2, "self-*" ×3, "Orchestrator" ×3, "Autopilot" ×3, "Browser" ×2, "Memory" ×3.
The registry keys by canonical id + classification, so the collisions don't double-render.

## Runtime reality (§5AC)
The **catalog** (`/admin/presets`) is REAL identity; **live status/health/cost is
UNAVAILABLE** without the running backend (Docker daemon down) + the aggregator
(D9). The frontend loads the catalog and marks runtime state UNAVAILABLE; DEMO
scenarios simulate activity with the REAL agent identities, DEMO-tagged. We do
**not** claim REAL agent activity until a real endpoint/event is exercised.
