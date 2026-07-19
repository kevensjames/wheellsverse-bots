# SOL Motion System

Documents the **motion actually implemented** in the deployed SOL member app
(`frontend/sol/app.html` + `frontend/sol/sol-design-system.css`). Reviewed at
commit `6cd3d00`, production `https://wheellsverse.com/sol/app`.

> This doc is committed **with** the Increment-10 fixes and describes the
> **post-fix** state (e.g. the `openBankAdd` reduced-motion guard from MOT-01).

Motion in SOL is deliberately minimal. There is no motion library — every
animation is either a CSS `@keyframes`/`transition` or the one Canvas 2-D "SOL
Orb". Nothing pulses to create urgency, and no state is communicated by motion
alone.

## Principles

- **Motion supports a state change, never decorates money.** Entrances confirm
  "new content arrived"; a dialog scales in to confirm "a modal opened". No
  animation runs continuously on a financial figure.
- **No artificial urgency.** No countdowns, no slot-machine tallies, no pulsing
  "pay now" CTA, no confetti on payment.
- **Reduced motion is respected globally.** `sol-design-system.css` ships a
  blanket `@media (prefers-reduced-motion: reduce)` rule that collapses *every*
  animation and transition to `.001ms` (effectively off), and several components
  add a second explicit guard.
- **Motion is never required to understand state.** Every status also carries a
  text label + a shape/dot; turning motion off loses nothing semantic.

## Duration & easing tokens

Defined once in `sol-design-system.css:46`:

| Token | Value | Meaning |
|-------|-------|---------|
| `--dur` | `180ms` | base UI transition duration |
| `--ease` | `cubic-bezier(.2,.7,.2,1)` | standard "settle" easing (fast-out, soft-in) |

App-level components use short, hand-tuned durations rather than a strict scale.
Observed durations, from the source:

| Duration | Where | Property |
|----------|-------|----------|
| `.15s` | `.nav-item`, `.btn` (app.html inline) | color/background feedback |
| `180ms` (`--dur`) | `.premium-card`, `.circle-card`, `.field` (design-system) | transform / border |
| `.2s` | `.group-card`, `.more-sheet-backdrop` opacity, `.comm-guidelines` caret, `comm-in` | hover / fade |
| `.24s` | `.more-sheet` slide-up, `pay-card` (`circle-in`) entrance | sheet + card entrance |
| `.28s` | `.circle-card` (`circle-in`) entrance | card entrance |
| `.4s` | legacy `showGroup` cycle progress bar | width fill |
| `.5s` | `.pbar__fill` (goal/dashboard progress) | width fill |
| `.7s` | `.btn--loading::after` (`sol-spin`) | button spinner |
| `1s` | `.spinner` (`spin`) | page spinner |
| `1.3s` | `.sk` skeleton (`sk-shim`) | loading shimmer |
| `2.4s` | `.status--active.is-live::before` (`sol-breathe`) | live payout-slot breathe |

Easing is `--ease` (`cubic-bezier(.2,.7,.2,1)`) for entrances/transitions;
spinners and the skeleton use `linear`/`ease-in-out` as appropriate.

## Keyframes inventory

| `@keyframes` | Source | Used by | Nature |
|--------------|--------|---------|--------|
| `sol-spin` | design-system.css:90 | `.btn--loading::after` | one-shot-looped rotate (button spinner) |
| `sol-breathe` | design-system.css:166 | `.status--active.is-live::before` | opacity 1→.4→1, opacity-only — **defined but NOT currently applied** (the `is-live` class is not set anywhere in the member app, so this never runs in production; see below) |
| `spin` | app.html:82 | `.spinner` | page-load rotate |
| `sk-shim` | app.html:161 | `.sk` skeletons | background-position shimmer |
| `circle-in` | app.html:127 | `.circle-card`, `.pay-card` | translateY(6px)+fade entrance |
| `comm-in` | app.html:542 | `.comm-post` | opacity-only entrance (no transform — calmer feed) |

## Approved patterns (in use)

- **Short entrance** — cards fade/rise in once (`circle-in` 0.24–0.28 s,
  `comm-in` 0.2 s). Applied on render; not re-triggered continuously.
- **Dialog open/close** — the shared `.bank-modal` overlay toggles
  `.is-open` (`display:none`→`grid`); the backdrop fades. No bounce.
- **Sheet transition** — the mobile "More" sheet slides up
  (`transform:translateY(100%)`→`0`, 0.24 s) with a fading backdrop.
- **Card expansion** — the Community guidelines `<details>` rotates its caret
  (0.2 s); comment threads reveal instantly (no height animation, to avoid
  reflow jank on a long feed).
- **Read-state / progress reveal** — `.pbar__fill` animates its width (0.5 s)
  when a goal/dashboard progress value changes.
- **Filter / result transition** — feed re-renders swap content; the entrance
  keyframe provides a gentle fade. No cross-fade choreography.
- **Loading skeleton** — `.sk` shimmer (1.3 s) during fetches.
- **Focus scroll** — `commFocusComposer`, `premScrollManage`, and `openBankAdd`
  (guarded in Increment 10 — MOT-01) use
  `scrollIntoView({behavior: reduced ? 'auto' : 'smooth'})` — smooth only when
  motion is allowed.

## Restricted patterns (intentionally absent — verified not present)

Confetti · pulsing financial CTA · countdown/urgency timers · slot-machine number
motion · continuous decorative motion · alarm/shake animations · motion-only
status. **There is no perpetual animation on a populated screen.** A calm
opacity-only `sol-breathe` (2.4 s) is *defined* for a live payout slot
(`.status--active.is-live`), but the `is-live` class is **not applied anywhere
in the member app**, so it does not run in production (see MOT-02 in
`UX_AUDIT.md`); if ever enabled it is disabled under reduced motion.

## SOL Orb

The dashboard hero "orb" (`app.html:1552`, `SolOrb` IIFE; `<canvas id="solOrb">`
at 1425).

- **Canvas 2-D**, purely decorative, `aria-hidden="true"` — never announced,
  never conveys state a screen-reader user would miss.
- **Reduced motion:** `start()` bails immediately if `reduced()`
  (`matchMedia('(prefers-reduced-motion: reduce)')`). `render()` still calls
  `draw()` once, so reduced-motion users see a **single static orb frame**, not
  a blank canvas — motion off, meaning intact.
- **Visibility pause:** a `visibilitychange` listener calls `stop()` when the
  tab is hidden and resumes only if the dashboard is active — no rAF burns in a
  background tab.
- **Route pause:** `nav()` calls `SolOrb.resume()` only on `dashboard` and
  `SolOrb.stop()` on every other route, so the loop never runs off-screen.
- **Pointer parallax:** a `mousemove` handler nudges the light source, but only
  when the pointer is **not** coarse (`matchMedia('(pointer: coarse)')`) — touch
  devices get no parallax and no mouse listener.
- **Fallback frame:** if `#solOrb` or `getContext('2d')` is missing, `render()`
  returns early — no orb, no error.
- **Progress ring:** when `opts.progress > 0`, an arc is drawn around the orb
  (contribution/next-payout progress); it's a static arc per frame, not an
  independent animation.

## Reduced-motion matrix

Global rule (`design-system.css:190`) forces `animation-duration` and
`transition-duration` to `.001ms` for `*`, so **everything below is disabled by
default under reduced motion**. Components with an *additional* explicit guard:

| Component | Motion | Under `prefers-reduced-motion: reduce` |
|-----------|--------|----------------------------------------|
| SOL Orb | rAF Canvas loop | JS-gated off → single static frame (`start()` bails) |
| `.status--active.is-live` breathe | opacity loop | off (global rule) |
| `.circle-card` / `.pay-card` entrance | `circle-in` | off (global + local `.pay-card` guard at app.html:631) |
| `.comm-post` entrance | `comm-in` | off (global + local guard at app.html:588) |
| `.comm-guidelines` caret | transform | off (local guard at app.html:588) |
| `.premium-card:hover` | transform | off (local guard at app.html:598) |
| skeletons / spinners | shimmer / spin | off (global rule) |
| smooth scroll (`commFocusComposer`, `premScrollManage`, `openBankAdd`) | `scrollIntoView` | JS-gated to `behavior:'auto'` |
| `.pbar__fill` width | transition | off (global rule) — value still updates instantly |

**Result:** with reduced motion enabled, the app renders fully with no
animation and no loss of state or content.

## Notes & limitations

- Durations are hand-tuned per component rather than snapped to a strict token
  scale; a future consolidation could map them to 2–3 named steps
  (`--dur-fast`/`--dur`/`--dur-slow`). Documented, not a defect.
- `app.html` redefines `.btn` (inline, `transition:.15s`) separately from the
  design-system `.btn` (`transform var(--dur)`); the app markup uses the inline
  variant. See `DESIGN_SYSTEM.md` for the button-class provenance.
