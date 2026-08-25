# KAI Halo / Activity Signal Inventory (Phase 10A)

Ground truth for the **Functional Halo (§23)** + **Safe workflow/thinking viz (§24)**.
Built from a 4-reader audit of the halo, the event bus, the governed SSE stream, and
the §24 chain-of-thought surface. Provenance: `REAL` · `DERIVED` · `DEMO` · `UNAVAILABLE`.

## The one REAL driver (before Phase 10)
The halo binds to `kaiState` via `HOST.on('kaiState')` (`kai-nexus.js:40`) → `paintKai()`
→ `#nx-halo[data-state]`. `kaiState` (offline/online/listening/thinking/speaking/alert)
is driven by the **governed SSE lifecycle** (`kai-presence.js:388-397`: `status:thinking`
→ first `token`→speaking → `done`→online; `error`→alert) and TTS start/end. REAL in-app.

**Half-functional before this phase:** the state machine is real, but (a) only 3 of 8
states had distinct CSS (thinking/speaking/offline), (b) motion was a fixed decorative
loop bound to nothing, (c) `setEnv` (alert/critical) recolored the shell but never the
halo, and (d) the event bus had **zero subscribers** — the previously-unused seam.

## REAL, CoT-safe signals a functional halo may use
| Signal | Location | Provenance |
|---|---|---|
| `kaiState` transitions | `kai-presence.js:68`, mirrored `kai-nexus.js:40` → `emit('kai.'+s)` | REAL (in-app) |
| Governed SSE `status`/`token`-cadence/`done`/`error` | `kai-presence.js:388-397` | REAL |
| `connectionState` idle/streaming | `kai-presence.js:60` | REAL |
| Activity log (`logActivity`) | `kai-nexus.js:182` | REAL (safe labels) |
| `setEnv` → `.nx-shell[data-env]` (from real probes in live boot) | `kai-nexus.js:73` | DERIVED |

## DEMO-only (must stay behind ?scenario=)
Agent/tool events (`agent.tool.started`, …), procedure/approval steps, mission tools[]
— the **topic vocabulary is real code** but every caller is a DEMO scenario; live agent
runtime is UNAVAILABLE (D9) and no backend emits tool/step events. A "tools running"
indicator in production would fabricate a busy signal → DEMO-gated only.

## §24 — chain-of-thought safety
**Safe to show:** kaiState labels, SSE frame *types*, stream active/idle, token *cadence*
(count, never text), tool NAME / step title / agent status labels, the activity feed,
env level, opaque correlation/conversation ids.

**Must NEVER show:** the assembled system prompt (`brain.py:272-282`), raw model reasoning /
chain-of-thought, self-correction critique (`self_correction/loop.py:69`), tool arguments.

**The one real leak vector (config-dependent, backend):** `ollama_adapter.py:75-102` yields
`message.content` **verbatim with no `<think>`-tag stripping**; `router.stream`→`brain.stream`
pass it straight through as `{type:token}` → the visible answer + TTS. The **default model
(llama3.1:8b) is non-reasoning → safe**, but if `OLLAMA_MODEL` is set to a reasoning model
(deepseek-r1/qwq) its inline `<think>…</think>` scratchpad would stream raw into the answer.
There is **no reasoning filter in the token path** — the *proper* fix is a strip at the
adapter/`brain.stream` boundary before emitting `{type:token}` (backend, out of this UI
phase's scope; documented here as required).

## What Phase 10 built (all §24-clean)
- Completed the halo state visuals for every real `kaiState` (alert/researching/listening/
  online/idle) — pure CSS on the existing `data-state` contract; reduced-motion honored.
- The halo reacts to `data-env` (critical/warning/success) — closes the "alert leaves the
  orb unchanged" gap.
- An **event-driven pulse**: a one-shot ping on any REAL bus event (`on('*')` — the unused
  seam), reduced-motion-guarded.
- A safe **activity indicator** ("what KAI is doing") driven by `NexusPulse.describeEvent`,
  which derives its label **structurally from the event topic + an allowlist of name/count
  fields** and never reads `text/reasoning/args/prompt/…` — so it cannot leak CoT (unit-tested).
- `NexusPulse.stripReasoning` — a client-side defense-in-depth applied at the presence
  render/speak path (`kai-presence.js`), a no-op on normal answers, that hides an inline
  `<think>` scratchpad if a reasoning model is ever configured. (The adapter-level strip
  remains the proper backend fix.)
