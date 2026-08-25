# KAI Memory Source Inventory (Phase 9A)

Ground truth for the **Memory Constellation**. Built from a 5-reader audit of App A
memory routes + App B knowledge-graph / episodic / semantic stores. Provenance per
datum: `REAL` · `DERIVED` · `DEMO` · `UNAVAILABLE`.

## The ONE real graph: the App B Knowledge Graph
`backend/app/services/kg/storage.py` — a real **directed, typed, labeled property graph**
in SQLite (`data/kg/kg.db`):
- **Entities (nodes):** `{id, label (UNIQUE COLLATE NOCASE), type ∈ person|product|company|service|concept|event|other, attributes(JSON), created_at, updated_at}` — HTTP responses key nodes by **label**.
- **Edges:** `{id, src_id→entity, dst_id→entity (DIRECTED), relation (normalized lowercase_underscore), attributes(JSON), created_at}`, `UNIQUE(src_id,dst_id,relation)`. **No weight column** — edges carry only a free-form `attributes` blob.

Read surface (`backend/app/routers/admin_kg.py`, `require_admin_token`):
| Endpoint | Returns | Honesty note |
|---|---|---|
| `GET /admin/kg/stats` | `{entity_count, relation_count_distinct, edge_count_by_relation[]}` | `entity_count` is `len(find_entities(limit=500))` — a **≤500 sample cap**, NOT `COUNT(*)`; show **"500+"** at cap |
| `GET /admin/kg/search?q=&type=` | `{entities:[{label,type,attributes,updated_at}]}` | substring+recency, clamp ≤500. Closest to "list nodes" — **no full dump** |
| `GET /admin/kg/neighbors?label=&direction=` | `{edges:[{src,relation,dst,attributes}]}` | **single-hop only**; multi-hop must be stitched client-side |
| `POST /admin/kg/add-edge` | `{edge_id, triple}` | the **ONLY** writer; `@audited` scope=`kg.add_edge`, destructive, `approved=true` required |

**Honesty consequences (enforced in the UI, D13):**
- **Empty at rest:** `data/kg/kg.db` is 0 bytes; **no auto-population / NER / extraction** — the graph contains exactly the triples the operator hand-taught. At rest the constellation renders an honest empty state.
- **Ego-graph, not full graph:** there is no whole-graph dump and no HTTP `traverse` (BFS lives only in the `kg_query` chat tool). A truthful constellation is a **bounded ego-graph** (seed → `/neighbors`), header counts from `/stats`. Never claim to render the full graph.
- **No edge weights** → uniform edges; a numeric in `attributes` is shown as a label, never as thickness/strength.
- **Reachability (live path = EXTERNAL_BLOCKED):** the App-A-served Nexus reaches the KG only via the governed bridge `/admin/kai/kg/*` (`kai.chat` scope; **`KAI_BRIDGE_ENABLED` default OFF → 404**) and App B is down (Docker) → **UNAVAILABLE** until the bridge is enabled + triples exist. Coded fail-soft.

## Flat memory stores — NOT a graph (no edges)
| Store | Endpoint | Reach | Provenance |
|---|---|---|---|
| NarAI tiered memory (core/market/creation/personal/autopilot) | `GET /api/narai/memory/{stats,search,context}` (**PUBLIC**) | App A same-origin | REAL counts, but `data/narai_memory/` **absent on disk → all zero**; `context` is a formatted STRING not a graph; 170GB/500k capacity is docstring **DERIVED** |
| `core.memory` (operator/bot ops) | `GET /api/memory`, `/api/memory/search` (owner-gated) | App A | REAL; `memory/` **absent → empty**; embeddings OFF by default |
| Supabase `memory_notes` (per-user chat facts) | `GET /api/narai/memory` (Bearer, per-user) | App A | REAL when Supabase configured; only dimension is `category`; the one relational link (`source_conversation_id`) is **not even returned** |
| pgvector `memories` (episodic/semantic) | **none** | — | REAL embeddings but **NO read endpoint anywhere** → UNAVAILABLE |
| twin / persona | `/admin/{twin,persona}/*` | App-B bridge | REAL flat rows grouped by `section` — **not edges** |
| relationship / journal / learning / checkin / failures | `/admin/*` | **App-B only** (not in bridge allowlist) | REAL flat; single KAI↔operator dyad; UNREACHABLE from Nexus |

## Does NOT exist — do not fake
- **No memory-to-memory edges / kNN graph:** pgvector cosine similarity is query-time and **never stored**; there is no similarity/co-occurrence/tag edge anywhere. Fabricating links between flat stores is forbidden.
- **No cross-store IDs:** the stores share no key; `twin.source='kg'` is a provenance tag, **not** a stored edge.
- **No stored recency or importance** as node properties → **no recency-glow, no importance-sizing** (recency is query-time; `importance` is a manual 1–10 default or absent).
- **No full-graph dump, no HTTP traverse, no delete/prune** on the KG.
- **No memory aggregator** — 8 stores across 2 apps, 4 storage layers, 3 auth realms; no federating service.
- **No force-directed engine** — layout is deterministic static SVG (reuse the agent-constellation pattern).

## What the constellation honestly shows
The **KG ego-graph** (real typed nodes + directed named-relation edges, uniform width,
deterministic layout) — DEMO-fixtured now, live via the bridge when enabled + taught.
Header counts from `/stats` ("500+" at cap). Flat stores appear only as a labeled
**records summary** (counts by tier/category), explicitly non-graph, with **no invented edges**.
Every node/edge carries a `REAL/DERIVED/DEMO/UNAVAILABLE` chip; empty/unreachable states
are shown honestly, never faked.
