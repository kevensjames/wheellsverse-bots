# KAI Presence in Admin — Integration Design (P11–P15)

> **Status: PREPARED, not wired.** The directive gates presence on staging
> certification of the identity/bridge/command spine (Gates 1–3), which is
> blocked on an isolated staging environment that does not yet exist. This is the
> credential-free design deliverable; wiring begins once the spine is staging-green.
> Everything here reuses the governed session (P2), the same-origin bridge (P3),
> and the context envelope (P7) — no new identity, no new brain, no third dashboard.

## The load-bearing constraint: the admin is a MULTI-PAGE static app

`dashboard/ceo.html`, `frontend/admin/*.html`, the legacy dashboard — each is a
full page load, not an SPA route. So "conversation persists across navigation"
(the acceptance criterion) **cannot** rely on in-memory JS state. The design:

- **Conversation lives server-side** in App B, keyed to the session principal +
  a `conversation_id`. The client stores only that id (localStorage + the
  governed session).
- Every admin page **rehydrates** the presence UI on load: `GET /admin/kai/conversation/current` (via the bridge) → last N turns + KAI state.
- Entering/leaving Nexus is just another page/route that rehydrates the same
  conversation. Nothing resets because nothing important lived in the page.

## P14 first — the one provider (`frontend/admin/kai-presence.js`)

A single ES module, imported by the orb, drawer, Nexus shell, command bar, and
contextual action buttons. It is the only KAI state store (§26). Canonical state:

```
principal        // from GET /admin/session/whoami (role + scopes) — server truth
session          // active? (wv_session_active hint) + whoami source
conversation     // {id, turns[]} rehydrated from server on load
kaiState         // reuse the Nexus state machine: idle/listening/thinking/speaking/…
route            // location.pathname
context          // buildKaiContext() — descriptive-only envelope (P7)
pendingApprovals // from the governed approval surface (future)
notifications
voiceState       // idle/recording/speaking
presenceMode     // 'minimized' | 'assistant' | 'nexus'
```

Rules: no separate stores for drawer/Nexus/command-bar/orb — they all read this
one. Never infer privilege from client state; `principal.scopes` is display-only,
authorization is always re-checked server-side at the bridge.

Reuse: the Nexus already ships a state machine + bus (`static/nai/nexus/js/state.js`,
11 states) and an avatar/voice stack. `kai-presence.js` wraps that machine so the
orb, drawer bust, and full Nexus share **one** state object.

## P11 — MINIMIZED (the orb)

A tiny fixed indicator injected into the shared admin header/shell: `[KAI ●]`.
Subscribes to `kaiState`; the dot color/animation reflects online / listening /
thinking / alert. Lightweight (no avatar render). Click → opens the drawer.
Rendering is paused when not visible (perf).

## P12 — ASSISTANT (the drawer)

Persistent contextual drawer, 440–520px desktop. Contents: animated KAI bust
(the Nexus avatar at drawer scale, not the full cinematic stage), current KAI
state, current-page context chip, conversation, suggested actions, voice, command
input. It uses the **same governed session**: messages POST to
`/admin/kai/kai-chat` (bridge → App B) with `credentials:'include'` and the
`buildKaiContext()` envelope; streaming via SSE (bridge preserves it). Voice reuses
the real `/kai/tts` + `/kai/transcribe` (App B) through the bridge. No separate
chatbot, no second identity.

## P13 — NEXUS inside admin (`/admin/kai`)

Mount the existing Command Nexus (`static/nai/nexus/`) at the canonical route
`/admin/kai`, served same-origin (App A route that loads the Nexus assets via the
bridge, or App A serves a thin shell that boots the Nexus against App B through
the bridge). It boots `kai-presence.js` — so it shares session, conversation,
context, agent registry, memory, and governance with the drawer. Entering Nexus
rehydrates the same `conversation_id`; leaving returns to the drawer with the same
conversation. The cinematic embodiment work already on `feat/kai-nexus` is the
Nexus mode — do not rebuild it.

## P15 — contextual actions (per-page adapters)

Small, non-intrusive KAI actions on existing pages. Each page provides an adapter
that fills `context.entity_type` / `entity_id` and offers buttons that open the
drawer with a governed, pre-filled prompt:

| Page | entity | Actions |
|---|---|---|
| Security (finding) | finding id | Explain · Investigate · Prepare fix |
| Agents (agent) | agent id | Explain state · Summarize · Investigate blocker |
| Deployments | deployment id | Diagnose · Compare release · Prepare rollback |
| SOL (circle/payment) | entity id | Explain state · Investigate payment · Review reconciliation |

All writes stay governed: the button only *opens a prompt*; execution goes through
`/admin/kai/*` where scope + approval are enforced. Owner-only actions require
`kai.ultra`; financial/destructive still hit their existing confirmation/approval
layers — the presence layer never bypasses them (§12/§13).

## Presence acceptance (from the directive)

From `/admin`: orb visible → click → drawer opens → ask → the **same governed KAI**
answers → navigate to another admin page → conversation persists (server rehydrate)
→ context updates to the new page → enter Nexus → same conversation continues →
exit Nexus → same conversation remains. One identity throughout.

## Build order (once staging-green)

1. `kai-presence.js` provider + `GET /admin/kai/conversation/current` (App B, via bridge).
2. Orb (inert until `whoami` shows a session).
3. Drawer (governed chat + context + voice).
4. `/admin/kai` Nexus mount reusing the provider.
5. Per-page contextual-action adapters.
6. Extract the shared shell/header so the orb rides every `frontend/admin/*.html`
   page (replaces the single-page Cmd+K drawer already in `index.html`).

Each step is additive and flag-gated (`KAI_PRESENCE_ENABLED`, default OFF); the
existing pages keep working untouched until presence is verified.
