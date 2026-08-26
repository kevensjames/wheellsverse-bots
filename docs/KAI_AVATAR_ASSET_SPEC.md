# KAI Avatar Asset Contract (Phase 12, §2)

The production embodiment is `D12_AVATAR_ARCHITECTURE = GLB_ARKit_BLENDSHAPE_DIGITAL_HUMAN`.
This is the contract the external rigged asset MUST satisfy so it is **plug-and-play** into
the already-built engine (viseme mapper/engine, idle-life, driver abstraction). The current
MP4 is `FALLBACK_VIDEO` only. **Do not fake lip-sync by warping the MP4.**

## File
`kai-avatar-v1.glb` — glTF 2.0 binary (GLB). Place under `frontend/admin/nexus-assets/`.

## Geometry (required)
head · neck · shoulders · upper torso. (Optional later: arms/hands/full body.)

## Skeleton (humanoid upper body, min controllable)
`root · spine · chest · neck · head` (optional: shoulders/clavicles/arms). Used by the
idle-life engine for head drift + breathing (chest/shoulder).

## Eyes (identity signature — §7/§23)
Separate L/R eyeball rotation; visible pupil/iris; **independent L/R blink** + eyelid
deformation. Detailed **blue** iris + catchlight. Eyes stay blue in EVERY state (the
environment carries amber/crimson, never the eyes).

## Facial rig — ARKit-compatible blendshapes (min set, §3)
The engine drives these exact coefficient names (0..1). The asset must expose them as morph
targets, OR the GLB driver must map them to the asset's own morphs:
```
eyeBlinkLeft eyeBlinkRight
eyeLookUp/Down/In/Out Left|Right
browInnerUp browDownLeft browDownRight browOuterUpLeft browOuterUpRight
jawOpen jawLeft jawRight
mouthClose mouthFunnel mouthPucker
mouthSmileLeft mouthSmileRight mouthFrownLeft mouthFrownRight
mouthStretchLeft mouthStretchRight mouthPressLeft mouthPressRight
mouthUpperUpLeft mouthUpperUpRight mouthLowerDownLeft mouthLowerDownRight
mouthRollLower mouthRollUpper mouthShrugUpper mouthShrugLower
cheekPuff cheekSquintLeft cheekSquintRight noseSneerLeft noseSneerRight
```
(All are standard ARKit blendshapes; the mapper currently emits a subset incl. `mouthShrugUpper`.)
Additional supported shapes should be retained.

## Speech / viseme contract (§4)
The engine emits the 14 conceptual visemes REST · A_AH · E · I · O · U · MBP · FV · TH · L ·
R · SZ · SH_CH_J · W_Q and (via `kai-viseme-mapper.js`) **already converts each to weighted
ARKit mouth coefficients** — so the asset needs NO dedicated viseme morphs; the mapper's
weighted-blendshape output plus the coarticulation engine (`kai-viseme-engine.js`) produce
natural speech. Physical requirements the mapped coefficients assume: MBP visibly closes the
lips (jaw shut), FV tucks the lower lip toward the upper teeth, O/U round the lips, A/AH
opens the jaw, REST rests the mouth closed.

## Identity (§23) — must preserve
adult male · consistent KAI face · realistic human proportions · calm neutral default ·
**blue detailed irises** · dark premium futuristic clothing · subtle chest sigil · NO robot
helmet / exposed skull / superhero armor / cartoon proportions / exaggerated muscles / any
copyrighted-character resemblance. Technology reads through eyes/halo/lighting, not plating.

## Materials / performance (§24-27)
PBR (base color / normal / roughness; metallic only where appropriate). Skin must NOT glow —
only KAI energy effects glow. Textures: 4K (HIGH) / 2K (BALANCED) / 1K-2K (mobile). Hair as
optimized cards/lightweight geometry (no browser-hostile strand groom). Polygon/perf budget
is set after profiling (HIGH/BALANCED/SAVER) — communication motion (mouth/eyes/blink/gaze/
head/voice) is preserved before decoration under load (§31).

## Acceptance gate (§21/§22) — the GLB capability inspector runs on load
Reject for production if: no facial morph targets · no independent blink · no jaw control ·
eyes cannot rotate · mouth cannot form meaningful speech shapes · head cannot move · texture/
material quality destroys KAI identity. May be accepted PARTIAL for development. On arrival:
load through `KaiAvatarDriver` (`kind:'glb'`) — no rewrite — then certify blink · gaze ·
breathing · head · expressions · all visemes · voice · lip-sync · subtitles · barge-in ·
return-to-REST · performance · mobile fallback.

## What is already built (engine ready, §28)
`kai-viseme-mapper.js` · `kai-viseme-engine.js` (coarticulation) · `kai-idle-life.js`
(blink/breathing/saccade/gaze/head/expression) · `kai-avatar-driver.js` (GLB/VIDEO/LAB, with
GLB reporting ASSET_UNAVAILABLE until this file exists) · `kai-nexus-embodiment.js` (state
machine). 29 + 9 pure tests. **EXTERNAL_BLOCKED (this asset):** final avatar rendering +
production visual certification only — every engine above is done and asset-independent.
