# KAI Adaptive Mission Nexus — Implementation Ledger

Single source of truth for the phased build (directive §44/§45). Status is
**earned**, not asserted. Statuses: `NOT_STARTED` · `IN_PROGRESS` ·
`IMPLEMENTED` (code exists) · `VERIFIED` (evidence: tests + screenshots reviewed)
· `EXTERNAL_BLOCKED`. Only `VERIFIED` after real evidence.

- **Base branch:** `feat/kai-mission-nexus` off `feat/kai-admin-merge`
- **Baseline SHA:** `26706d9`
- **Decisions:** `docs/KAI_NEXUS_DECISIONS.md`

## Reusable foundation (from Phase 0 audit — real, do not rebuild)
- `frontend/admin/kai-presence.js` — ONE provider: pub/sub bus, `state` store, governed SSE (`/admin/kai/kai-chat/stream`), `kaiState`, orb/drawer/Nexus, living avatar + TTS.
- `frontend/admin/kai-presence.css` — design tokens (`--kaip-*`), components.
- `core/api.py` — `_inject_kai_presence()`, `/admin/nexus`, `/admin/ui-config`, `/admin/nexus-assets/*`; **real** status sources: `/api/*/status` (agents/business/factory/market/shopify/narai/…), `/api/narai/memory/{stats,search,context}`.
- App B `backend/app/routers/admin_*` (~21) — research, kg, twin, persona, planning, self_heal, supreme, audit, briefing, digest → real mission/agent/memory/security backends.
- RBAC-hardened governed bridge (owner-only kai.ultra) — commit `26706d9`.

## Ledger

| ID | Requirement (§) | Phase | Prio | Status | Files | Source of truth | Provenance |
|---|---|---|---|---|---|---|---|
| P0-1 | Repo audit + baseline freeze (§0) | 0 | H | IMPLEMENTED | — | git @26706d9 | REAL |
| P0-2 | Decision record, Option C locked (§2/§3) | 0 | H | IMPLEMENTED | KAI_NEXUS_DECISIONS.md | — | — |
| P0-3 | This ledger (§44) | 0 | H | IN_PROGRESS | this file | — | — |
| P0-4 | Baseline screenshots (§0.4) | 0 | M | NOT_STARTED | — | needs App A render | — |
| P0-5 | Reusable component map (§0.5) | 0 | H | IMPLEMENTED | ledger "foundation" | code | REAL |
| P1-1 | Nexus shell + adaptive grid (§4/§5/§6) | 1 | H | NOT_STARTED | kai-nexus.{html,js,css} | — | — |
| P1-2 | Ultrawide-first layout, 5 breakpoints (§36) | 1 | H | NOT_STARTED | kai-nexus.css | — | — |
| P1-3 | Header strip (mission/system/model/env/clock/security/alerts) (§4) | 1 | H | NOT_STARTED | kai-nexus.js | mixed | mixed |
| P1-4 | Command bar + states (§29) | 1 | H | NOT_STARTED | kai-nexus.js | governed stream | REAL |
| P1-5 | Design tokens + typography clamps (§34/§35) | 1 | H | NOT_STARTED | kai-nexus.css | — | — |
| P1-6 | KAI presence center (reuse provider) (§6/§26) | 1 | H | NOT_STARTED | kai-presence.js | code | REAL |
| EB-1 | Canonical event bus (extend pub/sub) (§38) | 1/2 | H | NOT_STARTED | kai-nexus.js | code | — |
| EB-2 | DEV/DEMO scenario driver + provenance tags (§39/§47) | 1 | H | NOT_STARTED | kai-nexus.js | fixtures | DEMO |
| P2-1 | Mission model + statuses (§7) | 2 | H | NOT_STARTED | kai-nexus.js | events | mixed |
| P2-2 | Active mission header (§8) | 2 | H | NOT_STARTED | kai-nexus.js | events | mixed |
| P2-3 | Mission queue (§9) | 2 | H | NOT_STARTED | kai-nexus.js | events | mixed |
| P2-4 | Mission timeline (§10) | 2 | H | NOT_STARTED | kai-nexus.js | events | mixed |
| P3-1 | Procedure engine (§11) | 3 | M | NOT_STARTED | — | events | mixed |
| P3-2 | Approval center (§31) | 3 | H | NOT_STARTED | — | governance | REAL |
| P3-3 | Evidence drawer + mission replay (§32) | 3 | M | NOT_STARTED | — | events | mixed |
| P4-1 | Systems telemetry + health doctrine (§12/§13) | 4 | H | NOT_STARTED | — | /api/*/status | REAL/DERIVED |
| P4-2 | Infrastructure topology (§14) | 4 | M | NOT_STARTED | — | discovered arch | DERIVED |
| P5-1 | Agent registry (§18) | 5 | H | NOT_STARTED | — | admin_* + /api/*/agents | REAL |
| P5-2 | Agent constellation + delegation (§19) | 5 | M | NOT_STARTED | — | events | REAL |
| P6-1 | Intelligence center + provenance (§15/§16) | 6 | H | VERIFIED | kai-nexus-intel.js + kai-nexus.{js,css,html} | research digest `/admin/research/latest` | REAL/DEMO |
| P7-1 | World mode (§17) | 7 | L | NOT_STARTED | — | signals | mixed |
| P8-1 | Security mode + alert doctrine (§20/§21) | 8 | H | VERIFIED | kai-nexus-security.js + kai-nexus.{js,css,html} | governance audit + supreme scan + posture | REAL/DERIVED/DEMO |
| P9-1 | Memory constellation (§22) | 9 | M | VERIFIED | kai-nexus-memory.js + kai-nexus.{js,css,html} | App-B knowledge graph (admin_kg) | REAL/DEMO |
| P10-1 | Functional halo (§23) | 10 | M | VERIFIED | kai-nexus-pulse.js + kai-nexus.{js,css,html} | kaiState + event bus | REAL/DEMO |
| P10-2 | Safe workflow/thinking viz (no CoT) (§24) | 10 | M | VERIFIED | kai-nexus-pulse.js (describeEvent/stripReasoning) | observable events | REAL |
| P11-1 | Adaptive environmental reactions (§25) | 11 | M | NOT_STARTED | — | kaiState/events | REAL |
| P12-1 | KAI motion/embodiment + voice (§26/§27/§28) | 12 | M | IMPLEMENTED* | kai-presence.js | code | REAL |
| P13-1 | Responsive/mobile (§37) | 13 | H | NOT_STARTED | kai-nexus.css | — | — |
| P14-1 | Accessibility (§41) | 14 | H | NOT_STARTED | — | — | — |
| P15-1 | Performance (adaptive quality, no leaks) (§40) | 15 | H | NOT_STARTED | — | — | — |
| P16-1 | Adversarial QA (§50) | 16 | H | NOT_STARTED | — | — | — |
| P17-1 | Screenshot-driven visual acceptance (§46/§52) | 17 | H | NOT_STARTED | — | Playwright | — |

\* P12: living avatar + masculine TTS + barge-in already exist in `kai-presence.js` (mountNexus); integration into the Nexus hero is pending.

## Anti-skip note (§45)
Re-read directive + update this ledger after each phase. A blocker in one
subsystem (e.g. no live news source → P6 partial) does not block unrelated
phases. Nothing marked VERIFIED without screenshots reviewed + tests.

## Session 1 progress — 2026-08-25 (Phase 0 → Phase 1 + event bus + mission core)
Status changes below supersede the table's initial values for the listed IDs.
Evidence: screenshots reviewed at 3440×1440 (mission + idle) and 390×844 (mobile).

- **P0-1..P0-3, P0-5 → IMPLEMENTED**: audit, baseline freeze (`26706d9`), decisions (D0–D5), ledger, component map.
- **P0-4 (baseline screenshots of the *old* dashboard) → EXTERNAL_BLOCKED**: needs App A running (Docker daemon down). New-shell screenshots captured instead as Phase-1 evidence.
- **P1-1 shell + adaptive grid → VERIFIED**: `kai-nexus.html/css/js`; renders as a real mission-control shell, KAI central.
- **P1-2 ultrawide + breakpoints → IMPLEMENTED** (ultrawide + mobile VERIFIED; tablet/1440/1280 not yet shot).
- **P1-3 header strip → VERIFIED**; **P1-4 command bar + states → IMPLEMENTED** (governed path real only in-app); **P1-5 tokens/typography → VERIFIED**; **P1-6 KAI presence center (halo) → IMPLEMENTED** (video-avatar integration pending P12).
- **EB-1 canonical event bus → IMPLEMENTED** (extends kai-presence pub/sub; bridges `kaiState`).
- **EB-2 DEMO scenario driver + provenance → VERIFIED**: 5 scenarios (idle/latency/research/security/approval); every datum tagged REAL/DERIVED/DEMO/UNAVAILABLE; persistent DEMO banner on `?scenario=`; production shows no DEMO-as-live.
- **P2-1 mission model → IMPLEMENTED**; **P2-2 active mission header → VERIFIED**; **P2-3 queue → VERIFIED**; **P2-4 timeline → VERIFIED**.

**Honest gaps this session:** live data path (REAL telemetry/agents/intel) only wired as fail-soft probes — not yet exercised against a running App A (Docker down); modes SYSTEMS/AGENTS/INTEL/SECURITY/MEMORY/WORLD/FINANCE/DEV are nav-switchable but their dedicated views (Phases 4–9) are NOT_STARTED; procedure engine/approval center (Phase 3), functional-halo event wiring (Phase 10), a11y (14), perf audit (15), adversarial pass (16), and full 6-viewport sweep (17) remain. This is the Phase 0–2 foundation, not a finished product (§53).

## Session 2 progress — 2026-08-25 (Phase 3: Procedure + Approval + Evidence)
Evidence: 16 node tests pass (`test_nexus_procedure.js`); screenshots reviewed at
3440×1440 (approval-pause + failure) and 1440×900 (approval).

- **P3-1 procedure engine → VERIFIED**: `kai-nexus-procedure.js` — canonical Procedure/step models + state machine (§3A/§3C). Refuses illegal transitions (PENDING→SUCCESS, APPROVAL_REQUIRED→SUCCESS w/o approval, blocked-resume, non-retryable retry, silent required-skip). 16 tests.
- **P3-2 approval center → IMPLEMENTED** (VERIFIED for DEMO): approval card with role/scope/risk/checks + APPROVE/DENY/DETAILS. **Governed reality (D6):** in-app the buttons DO NOT grant — they surface "requires the governed backend endpoint"; DEMO-only client transitions under `?scenario=`. Real `POST /admin/kai/approvals/{id}` is EXTERNAL_BLOCKED.
- **P3-2b procedure visualization (§3B) → VERIFIED**: step list with glyph+color+label per state (never color-alone), current-step pulse, evidence badges.
- **P3-2c approval pause semantics (§3F) → VERIFIED**: mission → WAITING/APPROVAL_REQUIRED, KAI → ALERT "Waiting for your approval"; no fake background continuation.
- **P3-3 evidence drawer (§3G) → IMPLEMENTED**: click a step → slide-in drawer with provenance-tagged evidence items; default provenance DEMO (never silently REAL); no secrets.
- **P3-8 procedure event bus (§3H) → IMPLEMENTED**: procedure.*/approval.* topics on the ONE bus → timeline + activity + kaiState + mission sync + alerts.
- **P3-9 DEMO procedures (§3I) → IMPLEMENTED**: `?scenario=` deployment-approval / deployment-success / deployment-failure / security-remediation / incident-recovery — all DEMO-tagged.
- **P3-10 tests (§3J) → VERIFIED**: creation, ordering, required-enforcement, invalid transitions, approval pause, approve/deny/expire, retry, blocked/resume, evidence, provenance, event ordering.

**Phase 3 honest gaps:** real approvals need the governed App B endpoint (blocked, no live backend); the procedure engine currently drives DEMO fixtures only — wiring it to REAL governed-mission events (when a live mission emits procedure steps) is a later integration; procedure-panel header wraps a bit at ≤1440 (cosmetic).

## Session 2 progress — 2026-08-25 (Phase 4: Systems Telemetry + Topology)
Evidence: 7 node tests (`test_nexus_systems.js`); screenshots reviewed at
3440×1440 (multi-system-incident) and 1920×1080 (database-degraded).

- **P4-0 telemetry inventory (§4A) → IMPLEMENTED**: `docs/KAI_TELEMETRY_SOURCES.md` — real liveness endpoints vs UNAVAILABLE metrics, provenance per metric.
- **P4-B SystemNode model + classify/summarize/stale/alerts (§4B/§4F/§4K) → VERIFIED**: `kai-nexus-systems.js`, 7 tests. Discrete states from real probe results; **no fake %**; alerts only from real state; deterministic backoff (no Math.random).
- **P4-1 Systems mode (§4C) → VERIFIED**: summary (NOMINAL/DEGRADED/WARNING/CRITICAL/UNKNOWN counts) + subsystem cards with status, `metrics unavailable`, last-probe, provenance badge. New adaptive canvas pane swapped by mode.
- **P4-2 Infrastructure topology (§4D) → VERIFIED**: JS-drawn SVG of the REAL architecture (Client→Cloudflare→App A+Bridge→App B→PG/Redis/Providers), nodes colored by status, edges animate only on `activeEdges`, click→detail.
- **P4-F real-vs-demo failure (§4F) → VERIFIED**: unavailable metrics show `UNAVAILABLE`/`metrics unavailable`/`no probe endpoint`, never a fabricated number; default topology is UNKNOWN until probed.
- **P4-G polling architecture (§4G) → IMPLEMENTED (D8)**: hybrid — bounded probing of a curated 3 endpoints (not 20 loops); recommended upgrade = one aggregate `/admin/telemetry` (EXTERNAL_BLOCKED).
- **P4-H backpressure (§4H) → IMPLEMENTED**: single interval, AbortController timeout, exponential backoff + jitter, `visibilitychange` pause. (Exercised live only in-app; live path blocked — Docker/App A down.)
- **P4-J topology/card interactions (§4J) → IMPLEMENTED**: click node/card → detail drawer (status/probe/latency/last-probe/provenance) + governed "Ask KAI to explain" action.
- **P4-K alert integration (§4K) → VERIFIED**: alerts derived only from real system state, each carrying system + provenance.
- **P4-L DEMO fixtures (§4L) → IMPLEMENTED**: `?scenario=` systems-nominal / database-degraded / provider-offline / worker-stale / multi-system-incident, all DEMO-tagged.

**Phase 4 honest gaps:** the live probe path (REAL telemetry) is coded but unexercised — needs App A running (Docker down). Deep metrics (CPU/RAM/DB-pool/heartbeat) stay UNAVAILABLE until an aggregate telemetry endpoint exists (D8). Mission↔telemetry coupling (§4E) is partial: scenarios set `activeEdges`/status, but auto-derivation of a mission's targeted systems from a live mission is a later integration. Full 5-viewport sweep: 3440 + 1920 done for systems; 2560/1440/390 not yet shot for systems mode.

## Session 2 progress — 2026-08-25 (Phase 5: Agent Command Center)
Evidence: 13 node tests (`test_nexus_agents.js`, incl 3 security); screenshots
reviewed at 3440×1440 (agents-multi, agent-blocked, agent-approval) + 390×844.

- **P5-A agent inventory (§5A) → IMPLEMENTED**: `docs/KAI_AGENT_SOURCES.md` — 11 REAL_AGENT presets + SuperAgent/Planning/Twin, WORKER/SERVICE/TOOL/BOT taxonomy, DUPLICATES reconciled ("Research" ×3, etc.). No fake agents.
- **P5-B/D9 registry architecture → RECORDED**: no unified endpoint exists; C (backend aggregator `GET /admin/agents`) is right but EXTERNAL_BLOCKED; interim = frontend adapter over the ONE real catalog `/admin/presets`. Decision D9.
- **P5-C/D canonical model + registry (§5C/§5D) → VERIFIED**: `kai-nexus-agents.js`, 13 tests — normalization, **duplicate reconciliation** (one identity, merged tools), summary (excl SUGGESTED), stale detection (STALE ≠ FAILED), event contract, blocked reason, provenance never silently REAL.
- **P5-E agents mode (§5E) → VERIFIED**: summary + filters + list | KAI-centered constellation | inspector.
- **P5-F constellation (§5F/§5G) → VERIFIED**: deterministic domain positioning (no jitter), KAI central, edges busy on ACTIVE, **event-triggered** delegation packet (one pulse, reduced-motion off).
- **P5-I/J inspector + activity (§5I/§5J) → VERIFIED**: status/mission/task/delegated-by/elapsed/tools/model/provider/cost, provenance, governed actions, observable-events-only timeline.
- **P5-K/L/P mission/procedure/approval integration → IMPLEMENTED**: agent events → mission timeline + kaiState; agent-approval → mission APPROVAL_REQUIRED (§5P); procedure actor linkage supported by the model (full visual via Phase 3 approval).
- **P5-M/N/O health/stale/blocked (§5M/§5N/§5O) → VERIFIED**: health distinct from status; STALE with "last seen"; blocked shows the REAL reason (WAITING_FOR_PROVIDER etc.).
- **P5-Q cost/model visibility (§5Q) → VERIFIED**: shown when real, else UNAVAILABLE (never invented).
- **P5-S delegation control (§5S) → IMPLEMENTED**: in-app + no governed endpoint → DELEGATION UNAVAILABLE (never simulates success); DEMO emits a real event through the bus.
- **P5-T suggested ≠ active (§5T) → VERIFIED**: SUGGESTED badge + dashed node + excluded from counts.
- **P5-W DEMO scenarios (§5W) → IMPLEMENTED**: agents-idle/multi, agent-blocked/failure/approval/delegation/stale — all DEMO-tagged.
- **P5-AE security (§5AE) → VERIFIED (model)**: labels stored inert (textContent render), provenance never elevated from unlabeled events, registry has no backend write path. Backend authorization stays authoritative (no client-side invoke).
- **§5AC live path**: catalog adapter over `/admin/presets` coded (fail-soft); runtime state UNAVAILABLE (Docker/App A down) — never claims REAL activity.

**Phase 4 debt (§5AH) → CLOSED**: systems mode verified at 390×844 (single-column stack + full-width topology). Fixed a media-query specificity bug where mode-grid rules beat the mobile 1-col override (now specificity-matched for mission/systems/agents panes).

**Phase 5 honest gaps:** live agent runtime (REAL status/cost) needs App B + the D9 aggregator (blocked); real delegation needs a governed invoke endpoint (blocked); full 5-viewport sweep did 3440 + 390 for agents (2560/1920/1440 consistent with prior phases, not separately shot); perf at 250 agents not stress-tested (registry is O(n), constellation renders all nodes — virtualization is a future item §5AB).

## Session 3 progress — 2026-08-25 (Phase 6: Intelligence Center + Signal Analysis + Provenance)
Evidence: 15 node tests (`test_nexus_intel.js`); screenshots reviewed at 3440×1440
(intel-ai / intel-cyber / intel-source-down), 1440×900 (intel-multi-source +
mission regression), and 390×844 (mobile stack). In-app asset serving allowlisted.

- **P6-A intelligence inventory (§6A) → IMPLEMENTED**: `docs/KAI_INTELLIGENCE_SOURCES.md` — the ONE real primary source (research digest: arxiv/hn/gh via `/admin/research/latest`), DERIVED sources that must NOT pose as news, and the honest "does not exist — do not fake" list (no CVE/GHSA feed). Decisions **D10** (dedupe/corroboration) + **D11** (untrusted-content security).
- **P6-B Signal model + intelligence logic (§6B/§6K/§6L) → VERIFIED**: `kai-nexus-intel.js`, 15 tests — `normalizeSignal` (untrusted:true, text escaped-as-data), `dedupeAndCorroborate` (canonical-URL dedupe + **distinct-domain** corroboration; mirrors of one source do NOT count), explainable `computeRelevance`, `sourceHealth`, `summarize`.
- **P6-C fact vs KAI analysis (§6C) → VERIFIED**: analysis pane renders **SOURCE FACTS** (green-railed) strictly separated from **KAI ANALYSIS** (purple-railed); a signal with no KAI analysis says so — source facts are never presented as KAI's conclusions and vice-versa.
- **P6-F intelligence mode (§6F) → VERIFIED**: filters + summary + source-health rail | signal stream | analysis. Right-rail live feed also upgraded to the Signal model.
- **P6-G/S signal analysis + source health (§6G/§6S) → VERIFIED**: verification badge (PRIMARY_SOURCE/CORROBORATED·N/SINGLE_SOURCE/UNKNOWN), freshness ("fetched Nm" — never a fabricated published time, D10), per-source HEALTHY/STALE/OFFLINE/UNKNOWN.
- **P6-Q signal → governed investigation (§6Q) → IMPLEMENTED**: "Start research mission" creates a MISSION (not an execution) with the signal attached as evidence; emits a real agent event through the ONE bus.
- **P6-AD/AE security (§6AD/§6AE) → VERIFIED (model + render)**: `safeUrl` (http/https only; javascript:/data:/file:/relative → rejected + flagged), all text via `textContent` (a `<script>`/`onerror` headline is inert), links `rel="noopener noreferrer nofollow"`; **prompt-injection isolation** — "Ask KAI" places signal text into the command bar as a user *data* message, never into KAI's instruction path; every signal `untrusted:true` with a visible untrusted-content note.
- **P6-X DEMO scenarios (§6X) → VERIFIED**: `?scenario=` intel-ai / intel-cyber / intel-conflict / intel-multi-source / intel-stale / intel-source-down — all DEMO-tagged; source-down shows an empty stream + OFFLINE source health (no fabricated signals); multi-source collapses 3 distinct-domain mirrors → 1 CORROBORATED·3.
- **P6-Y REAL adapter (§6Y) → IMPLEMENTED (fail-soft)**: `bootIntelLive()` fetches `/admin/research/latest`, normalizes to PRIMARY_SOURCE signals with real URLs; published time honestly UNAVAILABLE (D10). In-app serving: `kai-nexus-intel.js` added to `_NEXUS_APP_MIME` (core/api.py).

**Phase 5 viewport debt (§6AH) → CLOSED**: fixed real responsive bugs found this pass — (1) mobile shell overflowed to 555px because the single column was `1fr` (=`minmax(auto,…)`) and a wide child (command bar) forced the track past the viewport → now `minmax(0,1fr)`, no horizontal scroll; (2) header stats overlapped on a phone → header wraps to rows (brand on its own line); (3) DEMO banner overlapped the header on mobile → static flow; (4) at 1440 the 3-pane intel/agents canvases collapsed the middle pane → stack the detail pane under the main pane (236px filter rail + full-width work area); (5) canvas content bled under the command bar → canvas clips + filter rails scroll + hero/canvas row ratio rebalanced for dense modes.

**Phase 6 honest gaps:** live intelligence path is coded fail-soft but **unexercised** — reaching `/admin/research/latest` needs App B + admin auth (Docker down), so no successful live connection is claimed; the digest drops `published_at` at ingest, so REAL signals show freshness-as-fetched and published-time UNKNOWN until a ~1-line-per-fetcher backend fix captures it (documented in KAI_INTELLIGENCE_SOURCES.md); cyber/CVE signals are DEMO-only because no real security feed exists; corroboration is URL/domain-based (no body available to content-hash); Perplexity `web_search` (a real secondary source) is not wired (needs `PERPLEXITY_API_KEY`).

## Session 4 progress — 2026-08-25 (Phase 8: Security & Governance Posture + alert doctrine)
Evidence: a 6-reader security-surface inventory (docs/KAI_SECURITY_SOURCES.md, D12) +
17 node tests (`test_nexus_security.js`) + an adversarial 4-lens review; screenshots
reviewed at 3440×1440 (governance-denial / scan-findings / unarmed / incident),
1440×900 (incident stack), 390×844 (mobile stack).

- **P8-A security inventory (§20A) → IMPLEMENTED**: `docs/KAI_SECURITY_SOURCES.md` — every REAL/DERIVED/DEMO/UNAVAILABLE source across App A + App B, the "does not exist — do not fake" list (no runtime CVE/SAST/IDS; Phase 6 confirmed), and the honesty landmines (hard-coded `/api/security/status` fields, the `nx-h-security='CLEAR'` placeholder, the trading `alerts` decoy table).
- **P8-B alert doctrine model (§20/§21) → VERIFIED**: `kai-nexus-security.js`, 17 tests — canonical finding model; severity is `measured` only when the source carries one, else `inferred` by ONE documented rule (`inferGovernanceSeverity`) tagged as such, else `none`; `dedupeFindings` (exact dedupe + distinct-(scope,title) governance-denial correlation with a real count); `posture` (per-field provenance, never green unless real); `promoteToStoreAlert`; `summarize`.
- **P8-1 Security mode pane (§20) → VERIFIED**: posture rail (owner-gate / bridge / principal — REAL, else UNKNOWN) | governance & scan event stream | inspector with **EVENT FACT ↔ GOVERNANCE DECISION** separated (mirrors the intel fact/analysis split). Reuses the existing `store.alerts` strip + header counter — no parallel alert system. **Fixes the CSS `:not()` fall-through bug** (security mode was rendering the mission canvas) and the hard-coded header `CLEAR` placeholder.
- **Alert doctrine, enforced + shown (§21) → VERIFIED**: a **measured** critical (or an INERT owner gate) shows header/posture CRITICAL; an **inferred** severity never escalates past 'warning' and never drives the top-line posture. Screenshots confirm: governance-denial → header CLEAR + 2 inferred alerts; scan-findings (measured critical) → header CRITICAL; unarmed (INERT gate, 0 findings) → CRITICAL; incident → 2 correlated denials (`HIGH ×2`) + measured-critical reverse-shell.
- **P8-security untrusted-content (§20AE) → VERIFIED (model + render)**: every finding `untrusted:true`; title/detail/error/actor render via `textContent`/`escapeHtml` (inert `<script>`/`onerror`); "Ask KAI" places event text into the command bar as a user DATA message; `actor` surfaced but caveated as caller-supplied, not authenticated.
- **P8-Y live adapter (§20Y) → IMPLEMENTED (fail-soft)**: `bootSecurityLive()` reads App-A same-origin posture (`/admin/session/whoami`, `/admin/kai-bridge/health`, `/api/security/status`) as REAL; on-demand `runDefensiveScan()` → `/api/security/scan` (in-app only). App B governance-audit + host/ops-scanner + failures are **EXTERNAL_BLOCKED** (cross-app bridge allowlist + Docker) — surfaced UNAVAILABLE, never faked. `kai-nexus-security.js` added to `_NEXUS_APP_MIME`.
- **P8-X DEMO scenarios (§20X) → VERIFIED**: `?scenario=` security-nominal / governance-denial / scan-findings / unarmed / incident / source-down — all DEMO-tagged; source-down shows all-UNKNOWN posture + empty stream (no fabricated findings).

**Adversarial review (4-lens, refute-biased verify) → 13 confirmed, all FIXED + 7 tests added (24 total):** the sharpest was a **CRITICAL honesty inversion** — `/api/security/status.api_key_auth` is the STRING `'enabled'|'disabled — …'`, so `!!s.api_key_auth` was always true and reported an INERT owner gate as ARMED (fixed: parse `=== 'enabled'`). Also fixed: (2) `refreshSecurityAlerts` dropped the probe source fields, so a scan wiped a measured INERT-gate posture (re-attach `_apiKeyArmed/_bridge/_principal`); (3) partial/unmeasured posture painted green `CLEAR` (added a `probed` flag → CLEAR only when worst=info AND gate+bridge are REAL-confirmed); (4) the static HTML still shipped a green `CLEAR` placeholder (now `UNKNOWN`); (5) defensive-scan finding IDs collided on `(type, detail-length)` (now index+timestamp); (6) `dedupeFindings` correlation was non-idempotent (preserve count). New tests cover the incident invariant (measured-critical + inferred-high → critical), the partial-probe never-green case, `promoteToStoreAlert` boundaries, the remaining `inferGovernanceSeverity` branches, dedupe negatives, and idempotency.

**Phase 8 honest gaps:** App B governance/host-scan/failure feeds need the `/admin/kai/*` bridge allowlist expanded + App B running (Docker down) → live event stream is EXTERNAL_BLOCKED; severity for governance/auth/rate-limit events is inferred (no measured field exists); no runtime CVE/SAST/redaction-hit/auth-failure feed (those are ephemeral or non-existent — deliberately NOT surfaced as REAL); `POST /api/security/scan` is itself unauthenticated on App A (a pre-existing governance gap noted in the inventory, out of scope for this UI phase).

## Session 5 progress — 2026-08-25 (Phase 9: Memory Constellation — the KG ego-graph)
Evidence: a 5-reader memory-surface inventory (docs/KAI_MEMORY_SOURCES.md, D13) +
14 node tests (`test_nexus_memory.js`); screenshots reviewed at 3440×1440
(memory-graph + memory-unavailable), 1440×900 (memory-focus stack), 390×844 (mobile).

- **P9-A memory inventory (§22A) → IMPLEMENTED**: `docs/KAI_MEMORY_SOURCES.md` — the decisive finding is that exactly ONE real graph exists (App-B KG `data/kg/kg.db`: directed, typed, labeled property graph, named-relation edges, real adjacency + BFS); every other "memory" store (NarAI tiers, core.memory, Supabase notes, pgvector, twin/persona/relationship/journal/learning/failures) is FLAT records with no edges. The "does not exist — do not fake" list: no edge weights, no similarity/co-occurrence/tag edges, no stored recency/importance, no full-graph dump, no HTTP traverse, no cross-store IDs. Decision **D13**.
- **P9-B constellation model (§22) → VERIFIED**: `kai-nexus-memory.js`, 14 tests — entity/edge normalizers (canonical lowercased ids matching the KG NOCASE uniqueness; NO weight field), `buildEgoGraph` (keeps an edge only where both endpoints are present nodes; drops missing-endpoint edges + self-loops; never backfills), `dedupeEntities/Edges`, deterministic `layoutGraph` (degree-ranked, seed/highest-degree centered, no Math.random), `neighborsOf`, `summarize` (capped flag for the ≤500 `/stats` sample → "500+").
- **P9-1 Memory mode pane (§22) → VERIFIED**: facets rail (KG stats + entity-type filters + relation chips + search) | the **constellation** (directed, relation-labeled, type-colored SVG ego-graph with a legend; node radius by structural degree in the drawn set, NOT fabricated importance; uniform edges — no weights) | entity inspector (attributes + real in/out relations, Ask KAI / Focus, ego-graph caveat). Fixes the CSS `:not()` fall-through (memory mode was rendering the mission canvas, as security was pre-Phase-8).
- **Honesty enforced + shown (D13) → VERIFIED**: no fabricated edges (missing-endpoint edges dropped, screenshots show only real triples); no edge weights / recency-glow / importance-sizing; header shows "500+" at the sample cap; empty state ("teach a triple") and EXTERNAL_BLOCKED state ("bridge off — Nothing is fabricated") are honest.
- **P9-Y live adapter (§22Y) → IMPLEMENTED (fail-soft)**: `bootMemoryLive()` probes `/admin/kai-bridge/health`; bridge OFF (default) → `memProvenance=UNAVAILABLE`, honest empty state. When enabled, stitches a bounded ego-graph from `/admin/kai/kg/stats` + `/search` + per-seed `/neighbors` (no full dump exists) — labels URL-encoded. **EXTERNAL_BLOCKED** today (bridge off + Docker down + KG empty at rest). `kai-nexus-memory.js` added to `_NEXUS_APP_MIME`.
- **P9-X DEMO scenarios (§22X) → VERIFIED**: `?scenario=` memory-graph / memory-focus / memory-sparse / memory-empty / memory-unavailable — all DEMO-tagged; memory-empty shows the honest "graph is empty" state, memory-unavailable the EXTERNAL_BLOCKED state.

**Adversarial review (4-lens, refute-biased verify) → 7 confirmed (5 were one root bug), all FIXED + 3 tests added (17 total):** (1) the **"500+" cap was dead code** — `capped` required `drawn nodes.length ≥ 500`, but the ego-graph is bounded at ~60, so a real 800-entity KG rendered "60 entities" and the honest cap indicator never fired → fixed: `capped = !!statsCap` (the /stats signal alone), and the header/ENTITIES cell now show the **KG total from /stats** ("500+" at cap, else the count) with "N shown" for the ego sample; (2) **counts included undrawable edges** — summarize now runs over `buildEgoGraph(memNodes, memEdges)` so header/relation-chip counts match what's actually drawn; (3) **live-fetched graph didn't repaint on tab-open** — `bootMemoryLive` always repaints and the nav handler re-renders the revealed pane (also fixes the same latent gap for intel/security). New tests: cap fires from the /stats signal with a small sample, summarize excludes far-endpoint edges, and filtering a node drops its incident edge.

**Phase 9 honest gaps:** the live KG needs the governed bridge enabled + App B running + the operator to have hand-taught triples (no auto-population/NER exists) — until then the constellation is DEMO-fixtured and live is EXTERNAL_BLOCKED; only an ego-graph is drawable (no whole-graph dump endpoint — a thin `/admin/kg/graph` over the existing `traverse()` is the clean backend add); pgvector semantic memories, relationship, journal, learning, and failures are unreachable from the Nexus (not in the bridge allowlist / no read endpoint) and are deliberately NOT drawn.

## Session 6 progress — 2026-08-25 (Phase 10: Functional halo + safe activity/thinking viz)
Evidence: a 4-reader halo/§24 inventory (docs/KAI_HALO_SOURCES.md, D14) + 11 node tests
(`test_nexus_pulse.js`); browser-verified halo states + a live §24 leak check (a bus event
carrying a SECRET content field produced label "tool · Web", no leak). Also an independent
Phase 9 verify pass ran first (see below).

- **P10-A halo inventory (§23A) → IMPLEMENTED**: `docs/KAI_HALO_SOURCES.md` — the halo was half-functional (real `kaiState` machine from the governed SSE lifecycle, but decorative motion, 3/8 states styled, no env reaction, zero bus subscribers); agent/tool/step events are DEMO-only (no real backend feed); the one §24 leak vector is backend + config-dependent (`ollama_adapter` streams `<think>` verbatim if a reasoning model is configured; default is safe). Decision **D14**.
- **P10-2 §24 safety boundary → VERIFIED**: `kai-nexus-pulse.js`, 11 tests — `describeEvent(ev)` derives labels **structurally** from the event topic + a name/count allowlist and **never reads content fields** (a payload stuffed with reasoning/answer/prompt/args secrets yields only the topic label — unit-tested + live-verified); `stripReasoning` (client defense-in-depth: closed/variant/unclosed-trailing `<think>` blocks, no-op on normal answers) applied at the presence render + speak path; `activityLabel` maps every state to a safe word.
- **P10-1 functional halo (§23) → VERIFIED**: distinct CSS visuals for **every real `kaiState`** (researching/listening/alert added; pure CSS on the existing `data-state` contract); the halo now reacts to `data-env` (critical/warning/success — closes the "alert leaves the orb unchanged" gap); an **event-driven pulse** fires a one-shot ping on real bus events via the previously-unused `on('*')` seam (reduced-motion-guarded); a safe **activity indicator** ("what KAI is doing") shows labels only. `setKai` now routes through the one bus (`emit('kai.'+state)`) and the HOST bridge calls `setKai`, so the halo reacts to both live and scenario transitions. `?scenario=halo` cycles the states.
- **Honesty (§23/§39) → VERIFIED**: a "tools running"/agent-activity label appears only under `?scenario=` (DEMO banner); no fabricated halo states; the pulse binds to real events, not a fabricated busy loop. `kai-nexus-pulse.js` added to `_NEXUS_APP_MIME`.

**Adversarial review (4-lens incl. a dedicated §24-leak trace) → §24 boundary confirmed SOUND (no CoT/content reaches any halo surface, path-by-path); 2 confirmed defects FIXED (+2 tests, 13 total):** (1) `stripReasoning`'s unclosed-trailing strip could silently truncate a completed answer that legitimately contained a literal `<think>` (e.g. explaining tag syntax) → added a `finalized` flag: mid-stream still strips the partial scratchpad, but the final render/speak preserves a lone literal tag; also hardened the regex for attributed tags. (2) the `?scenario=halo` demo's `setInterval` leaked — it kept mutating global kaiState/env over other panes after nav-away → the tick now self-terminates when `store.mode !== 'command'` (browser-verified: timer clears one interval after leaving).

**Phase 10 honest gaps:** rich activity (tool/agent/step) is DEMO-only until a governed backend emits those events (D9); the halo's real live driver in production is the coarse `kaiState` lifecycle (thinking→speaking→done) — faithful but coarse. The §24 CoT leak is mitigated client-side (`stripReasoning` on the drawer) but the **proper fix is a backend strip at `ollama_adapter`/`brain.stream`** before emitting `{type:token}` — required before any reasoning model (deepseek-r1/qwq) is configured; the default model is non-reasoning and safe.

## Session 5b — Phase 9 independent verification (2026-08-25)
A 3-lens verify workflow confirmed all 7 Phase 9 fixes landed correctly (incl. edge cases
memStatsCount===0, DEMO null, capped) and found **2 low regressions the fixes introduced**,
both FIXED (commit 2befbb6): (1) `/stats`-ok but `/search`-fail advertised "500+ entities"
over an UNAVAILABLE pane; (2) a DEMO after a real boot bled the real `/stats` count into the
demo header. Root fix: the `/stats` total drives the header ONLY on a REAL connection
(`useStats = memProvenance === 'REAL'`); reset the stats fields in `_memScene` + each boot.
Browser-verified: DEMO+stale-stats → drawn count; UNAVAILABLE+stats → "0 entities".

## External blockers (§54)
- Live telemetry / real inference: App A + DB + providers must run (Docker daemon currently DOWN).
- Live news/intelligence source: the research digest (`/admin/research/latest`) is the ONE real primary source and is wired fail-soft (P6), but is unexercised until App B runs; no CVE/security feed exists; Perplexity needs `PERPLEXITY_API_KEY`.
- Live security event stream (P8): App B governance-audit (`data/governance/audit.jsonl`), Supreme host/ops scanner, and failure memory are cross-app → need the governed bridge `/admin/kai/*` allowlist expanded + App B running. App A posture (whoami/bridge/gate) is REAL and reachable now.
- Live knowledge graph (P9): the KG (`data/kg/kg.db`) is App-B, reachable only via the governed bridge `/admin/kai/kg/*` (`KAI_BRIDGE_ENABLED` default OFF) and is empty until the operator hand-teaches triples (no auto-extraction). A whole-graph render also wants a thin `/admin/kg/graph` endpoint over the existing `traverse()` (only stats/search/neighbors exist today).
- Avatar/voice asset upgrade: cinematic assets exist; provider-side TTS/viseme lip-sync pending (P12 milestone).
