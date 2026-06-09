# AGI Roadmap — KAI Sprint Plan

This document plans the 4 features the operator selected from a 14-point
"AGI-like KAI" roadmap on 2026-06-09. The other 10 items either already
exist in KAI (smart routing, MCP, tool use, partial governance) or need
real product specs before implementation (self-correction, long-term
planning, learning system, full digital twin, computer control).

## What's already shipped (for context)

| Roadmap item | Where it lives in KAI |
|---|---|
| Multi-Brain Architecture | [router/router.py](../backend/app/services/router/router.py) + [intent.py](../backend/app/services/router/intent.py) — `Intent.CODE→Claude`, `REALTIME→Perplexity`, `SIMPLE→Cloudflare`, `GENERAL→GPT-4o`, `prefer_local→Ollama` |
| Tool use | [tools/__init__.py](../backend/app/services/tools/__init__.py) — Composio (200+ SaaS) + native (web_fetch, web_search, memory, trading_signal) + MCP (any external server) |
| MCP Everywhere | [mcp_tools.py](../backend/app/services/mcp_tools.py) + [mcp_config.example.json](../deploy/mcp_config.example.json) |
| Persistent Knowledge (user memory only) | pgvector schema + [memory_injection.py](../backend/app/services/nai_brain/memory_injection.py) |
| Local Infrastructure (partial) | Ollama runs locally; CloudflareAdapter offloads cheap intents |
| Agent Governance (partial) | Spend tracker (caps $/day), tier gates, rate limits via slowapi |
| Voice loop | Whisper IN ([transcribe.py](../backend/app/routers/transcribe.py)) + Piper TTS OUT with OpenAI fallback ([tts.py](../backend/app/services/tts.py)) |

---

## Sprint order (1 feature per session)

Each feature should be a single session, with a clean commit + tests +
short demo. Don't bundle.

### 1. Expert-agent presets (#9) — ~1 day, smallest first

**Why first**: Reuses 100% of existing infrastructure (router, tools,
memory). Pure system-prompt + tool-subset configuration. Big UX win
because users see "expert agents" — what they actually get is a smart
preset switcher with curated tool whitelists per persona.

**Files to touch**:
- New: `backend/app/services/presets.py` — preset definitions (list of dicts)
- New: `backend/app/routers/presets.py` — `GET /kai/presets` returns the list
- `backend/app/routers/nai.py` (or wherever chat lives) — accept `preset_id` in request body, look it up, inject system prompt + filter tool registry
- `backend/app/static/nai/chat.html` — dropdown above the input
- `backend/app/static/nai/chat.js` — send selected preset_id with each message
- `backend/tests/test_presets.py` — preset lookup + system prompt + tool filtering

**Preset starter list** (5 to ship):
| ID | Name | System prompt seed | Tool whitelist |
|---|---|---|---|
| `swe` | Software Engineer | "You're a senior engineer. Show code with file paths and line numbers. Prefer practical over theoretical." | web_fetch, web_search, memory, mcp_filesystem__*, mcp_git__* |
| `marketing` | Marketing Strategist | "You're a B2B marketing strategist. Think in funnels, ICPs, channels. Default to data-driven." | web_search, notion, memory |
| `finance` | Finance Analyst | "You're a finance analyst. Use numbers, not adjectives. Always state assumptions." | trading_signal, web_search, web_fetch, memory |
| `research` | Research Assistant | "You're a research assistant. Cite sources. Prefer primary over secondary." | web_search, web_fetch, memory |
| `legal_research` | Legal Researcher | "You're a legal research assistant. NEVER give legal advice. Surface relevant case law + statutes only." | web_search, web_fetch, memory |

**Acceptance**:
- `GET /kai/presets` returns the 5 presets
- POST chat with `preset_id="swe"` injects the SWE system prompt
- Tool registry passed to the chat loop is filtered to the preset's whitelist
- Unknown `preset_id` → 400, not silent fallback
- Frontend dropdown changes the active preset; chat header shows current preset

---

### 2. Failure + tool memory (#2) — ~1 day, small schema change

**Why second**: Builds on existing pgvector memory. New memory types,
same retrieval infrastructure.

**Files to touch**:
- New Alembic migration: add `memory_type` column to `user_memory`
  table (currently single-table), or create `memory_type` enum
- `backend/app/services/memory/embeddings.py` — already exists
- `backend/app/services/memory/retrieval.py` — accept `types: list[str]`
  filter; default = all types
- `backend/app/services/memory/storage.py` — `add_memory(user_id, text,
  type)` where type in {"user", "project", "company", "tool", "failure"}
- `backend/app/services/router/router.py` — after a tool returns an
  error OR a chat response gets a thumbs-down (future: explicit feedback
  endpoint), auto-write a "failure" memory with the prompt + the failure
- `backend/app/services/nai_brain/memory_injection.py` — when injecting
  memories, prioritize failure-type memories for tasks similar to past
  failures (boost their retrieval rank)
- `backend/tests/test_memory_types.py`

**Acceptance**:
- Memory schema supports type filtering
- Failed tool calls auto-write a failure memory
- Retrieving memories with `types=["failure"]` returns only failures
- Brain injection includes a failure-memory warning when the user's prompt
  semantically matches a past failure

---

### 3. Knowledge graph MVP (#5) — ~2 days

**Why third**: Distinct subsystem. Bigger lift but unlocks "digital twin"
later (#13). MVP uses SQLite, not Neo4j — same query patterns, no extra
infrastructure.

**Files to touch**:
- New Alembic migration for `kg_entities` (id, label, type, attributes
  jsonb) and `kg_edges` (id, src, dst, relation, attributes jsonb,
  created_at)
- New: `backend/app/services/kg/storage.py` — `add_entity()`,
  `add_edge()`, `find_entities()`, `traverse()`
- New: `backend/app/services/kg/extraction.py` — on every chat message,
  run a structured-output extraction pass ("identify entities + relations
  in this turn") that proposes new edges. LLM-judge filter for high-confidence
  additions only.
- New: `backend/app/services/tools/kg_query.py` — KAI tool: query KG with
  natural language → return matching triples
- `backend/app/services/nai_brain/memory_injection.py` — when injecting
  memories, also surface relevant KG facts for entities mentioned in the
  prompt
- `backend/tests/test_kg.py`

**Acceptance**:
- Storage round-trips entities + edges
- Extraction extracts {entity, relation, entity} from sample turns
- KG tool can be invoked from chat
- Brain injection surfaces relevant KG context

**Defer to v2**: Visualizations, manual KG editing UI, KG export.

---

### 4. Continuous research cron (#14) — ~3 days

**Why last**: Most ops surface (cron + alerting). Mirrors NarAI Supreme
scanner pattern (per memory `narai_supreme_v1.md`).

**Files to touch**:
- New: `backend/app/services/research/sources.py` — fetchers for arXiv
  (cs.AI category), Hacker News top stories, GitHub Trending (daily),
  CVE feed
- New: `backend/app/services/research/scorer.py` — relevance scorer using
  the cheap router tier (Cloudflare Llama). Score each item against the
  user's project descriptions stored in memory.
- New: `backend/app/services/research/digest.py` — synthesize a daily
  digest from top-scored items per source
- New: `scripts/research_daily.py` — entrypoint
- New: `deploy/com.wheellsverse.kai.research-daily.plist` — LaunchAgent
  at 08:00 daily
- New: Telegram alert when any item scores ≥ HIGH threshold
- `backend/tests/test_research.py`

**Acceptance**:
- Each source returns items
- Scorer assigns 0-1 relevance scores
- Digest groups + summarizes top items
- Cron fires daily, digest persists to a `research_digests` table
- Telegram alerts on HIGH-relevance items
- Operator can read digests via a `/kai/research/digests` endpoint

**Defer to v2**: User-facing research UI, per-user source preferences,
weekly + monthly rollups.

---

## Cross-cutting notes for whoever picks this up

- **Don't pre-build**: each feature is a *complete sprint*. Don't try to
  ship 2 in one session — that's how the bug list grows.
- **Tier gate**: presets and KG are fine for free tier (read-only).
  Failure memory needs to be tier-aware (cap entries per free user).
  Continuous research is operator-only initially; later expose as a
  Max-tier feature.
- **MCP intersection**: when MCP servers are configured, the SWE preset's
  whitelist should auto-include all `mcp_filesystem__*` and `mcp_git__*`
  tools. This is why presets ship before failure memory — preset filtering
  is the layer where MCP tools get scoped per persona.
- **Memory dependencies**: features #2, #3, and #4 all extend the pgvector
  memory infrastructure. Coordinate schema changes — don't ship two
  conflicting Alembic migrations.

## Items NOT in this sprint (need separate spec)

| # | Item | Why deferred |
|---|---|---|
| 4 | Self-Correction | Eval framework + judge model + retry loop. 2-4 weeks. Needs a concrete success metric first. |
| 6 | Long-Term Planning | Durable goal DB + scheduler + replanning. 3-4 weeks. Conflicts with KAI's "chat-first" positioning until UX is figured out. |
| 7 | Computer Control | Playwright + browser-use on a Mac mini hosting chat traffic = resource risk. Needs a dedicated host or quota-per-user system. |
| 8 | Learning System | Months. Needs telemetry + feedback collection + A/B + auto-tuning. Build #2 + #4 first; learning emerges. |
| 13 | Digital Twin | Composes from #2 + #3 + #6. Not buildable in isolation. |
