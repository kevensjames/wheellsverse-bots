# KAI · Command Nexus

A buildless, static, real-time command dashboard that makes **KAI the center of the
operating system** — presence, conversation, intelligence, actions, world state.

Isolated frontend program (branch `feat/kai-nexus`), independent of the
`v1.0.0-foundation` backend release. No build step required to run.

## Run
```
cd backend/app/static/nai/nexus
python3 -m http.server 8899        # then open http://127.0.0.1:8899/index.html
```
Served in prod wherever `app/static/nai/` is (e.g. `/static/nai/nexus/`).

## Single-file preview
`nexus.preview.html` is a self-contained build (all CSS + JS inlined, zero external
requests) — open it directly, no server. Regenerate after edits:
```
npx esbuild js/app.js --bundle --format=esm --minify --outfile=/tmp/nexus.bundle.js
node build_preview.mjs
```

## Architecture (buildless ES modules)
```
index.html            Command Nexus shell (SYSTEM · KAI · LIVE INTELLIGENCE)
css/tokens.css        Design system — colour/type/space/glass/depth/motion + STATE-driven --accent
css/nexus.css         Layout, glass components, dock, tabs, workspace, responsive/mobile
js/state.js           KAI state machine (9 states) + event bus  →  <html data-kai="…">
js/avatar.js          Canvas presence: layered luminous eyes, micro-motion, neural halo, wings, presence mode
js/particles.js       Ambient data-particle field (adaptive density)
js/sound.js           WebAudio cues · Silent/Ambient/Cinematic
js/voice.js           SpeechRecognition intents → panel routing (gated actions never auto-run)
js/transitions.js     Cinematic workspace overlay (one environment transforming around KAI)
js/data.js            Living-system engine: simulated real-time + REAL /readyz seam
js/app.js             Bootstrap: conversation flow, tabs, settings, mobile KPIs, adaptive quality
js/panels/*.js        system · intelligence(news) · thinking · activity · agents(constellation) ·
                      mission · memory · tools · infrastructure · security · market · world(globe)
```
Every panel implements `create(ctx)` and subscribes to `data:<domain>` events.
DOM is built with `textContent` (no data → innerHTML): XSS-safe by construction.

## Vision map — build order status
Done (buildless-appropriate): 1 design system · 2 shell · 3 avatar micro-motion ·
5 states · 6 wings · 7 neural halo · 8 thinking viz · 9 agent constellation ·
10 activity stream · 11 news intelligence · 12 world pulse · 13 market · 14 memory graph ·
15 security center · 16 infrastructure · 17 mission control · 18 voice · 19 transitions ·
23 ambient · 24 sound · 25 mobile · 26 presence · 27 identity direction.

## Seams (need external assets/services — built as clean swap points, not faked)
- **#2 photoreal avatar** — replace the canvas presence in `avatar.js` with a rigged
  GLB/VRM head in WebGL; drive the SAME controller API (gaze/state/halo).
- **#21 lip-sync** — feed TTS viseme timings into avatar mouth blendshapes.
- **#22 eye-contact** — webcam + facemesh to set the gaze target.
- **#11/#12/#13 live feeds** — swap the simulated `data.js` domains for real news / market /
  geo APIs + a KAI impact-scoring service. `data.js` `tryReal()` shows the `/readyz` pattern.
