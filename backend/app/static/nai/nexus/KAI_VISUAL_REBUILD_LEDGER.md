# KAI Visual Rebuild Ledger (§27)

Status legend: NOT_STARTED · IN_PROGRESS · IMPLEMENTED · VERIFIED (screenshot) · EXTERNAL_BLOCKED

Baseline (start of rebuild): commit `9691632` — canvas synthetic-human avatar, judged
"toy/mannequin, too small, empty center". Rebuild target: cinematic AI command center.

| ID | Requirement (P) | Status | Verification | Blocker |
|----|-----------------|--------|--------------|---------|
| C1 | Composition: KAI dominates 40–60% center, no huge empty space (P0) | VERIFIED | desktop+mobile screenshots | — |
| C2 | Rails substantial + stronger command bar (P0/P1) | VERIFIED | dock 56px + accent glow | — |
| K1 | KAI hero: semi-photoreal, adult, head+neck+shoulders (P0) | VERIFIED | generated portrait hero, both viewports | photoreal *rigged* GLB still external |
| K2 | Real visual asset pipeline (§21) — generated image presence | VERIFIED | Higgsfield soul_2 → assets/kai.jpg + portrait.js | — |
| E1 | Luminous layered eyes (not flat disks) (P0) | VERIFIED | portrait iris+glow + fx eye-energy | — |
| L1 | Cinematic lighting: key + rim + eye + core + separation (P0) | VERIFIED | portrait rim + halo/core glow | — |
| A1 | Alive: breathing/blink/saccade/gaze, non-looping (P1) | IMPLEMENTED (v2) | prior | — |
| A2 | Cursor/user awareness gaze (P1) | NOT_STARTED | — | — |
| CB | Command bar rebuild + state energy (P1) | NOT_STARTED | — | — |
| N1 | Intelligence terminal + detail drawer + provenance (P1) | IN_PROGRESS | badges done | live feed = APIs |
| AG | Agent constellation w/ packet animation (P1) | IMPLEMENTED (panel) | — | — |
| M1 | Memory constellation illuminates on access (P1) | IMPLEMENTED (panel) | — | — |
| ENV| Environmental reactions to state (P2) | IMPLEMENTED (rim/halo) | — | — |
| BG | Subtle depth background (P2) | IMPLEMENTED (particles) | — | — |
| RSP| Mobile as distinct composition (P0) | IN_PROGRESS | — | — |
| PERF| Adaptive perf 60/45/30 + pause hidden (P2) | IMPLEMENTED (v2) | — | — |

K-note (§21): a photoreal rigged GLB cannot be fetched/generated in this sandbox
(no model repo access, CSP-inlined artifact). Strategy: generate a semi-photoreal KAI
PORTRAIT as the hero face (image-presence, the directive's endorsed fallback), overlaid
with a canvas for halo/eyes-glow/particles/state so KAI stays alive. The portrait/GLB is
ONE replaceable component behind the existing avatar controller API.
