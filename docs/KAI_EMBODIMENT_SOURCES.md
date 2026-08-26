# KAI Embodiment / Voice Source Inventory (Phase 12A)

Ground truth from a 4-reader audit (reasoning boundary, avatar, TTS/voice, stream/
barge-in). Provenance: `REAL` · `DERIVED` · `DEMO` · `UNAVAILABLE`. Environment:
**Docker DOWN + governed bridge default OFF** → every live speak/stream/avatar path is
**unexercisable end-to-end here** (validate by unit test, not live run).

## 1. Backend reasoning boundary (P0) — the one fully-buildable, non-blocked win
**Before:** NO backend `<think>`/reasoning strip existed anywhere in `backend/app` — the
frontend regex (`kai-nexus-pulse.js` / `kai-presence.js`) was the ONLY defense. Raw
provider output crossed SSE, DB persistence, usage accounting, and TTS.
**Sinks (all now covered):** admin governed SSE (`admin_chat.py` → `brain.stream`),
public SSE (`nai.py:111` → `brain.stream`), both buffered paths (`brain.chat`), DB
persistence (brain saves sanitized), the self-correction/reviser override
(`admin_chat.py:434` — bypasses Router), and `/kai/tts` (`services/tts.py`).
**Fix (this phase):** `backend/app/services/reasoning_sanitizer.py` — a stateless
`strip_reasoning(text, finalized=True)` + a stateful `StreamingReasoningSanitizer`
(chunk-boundary-safe: a `<think>` split across SSE frames is buffered). Matches the
frontend semantic exactly (closed block always removed; unclosed-trailing suppressed
mid-stream, preserved on finalize). 26 pure tests incl. an **exhaustive** property
(streaming output == stateless result for every split of 14 cases). Frontend strip stays
as defense-in-depth. **VERIFIED (unit).**

## 2. Avatar — CURRENT_AVATAR_TYPE = VIDEO (canned loops)
`frontend/admin/kai-presence.js` mounts two looping `<video>` (`kai-idle.mp4` /
`kai-speak.mp4` under `nexus-assets/`) + a poster jpg, swapped by a single boolean
(`kaiState==='speaking'`) via CSS mix-blend. **No rig, no bones, no morph targets/
blendshapes, no viseme feed.** Honest label: **DEMO-grade idle↔speak video swap.**
- **Real facial life (blink / gaze / visemes / micro-expression) is IMPOSSIBLE on a
  pre-rendered video** — the video *is* the face; you cannot morph its mouth to phonemes.

## 3. Voice / TTS
- **Avatar voice = browser Web Speech API** (`speechSynthesis`), `_pickVoice`
  **already prefers masculine** (a male-name list, then any `en-*` not matching a female
  regex). Availability depends on OS-installed voices. **The avatar is NOT female.**
- Server paths (separate "read-aloud", NOT the avatar): Piper `en_US-lessac-medium`
  (female) → OpenAI `alloy`. A **male Piper model `en_US-ryan-high.onnx` exists on disk,
  unused** — pointing `PIPER_MODEL_PATH` at it makes the server voice male (1 env change).
- **No streaming TTS** (Web Speech speaks the final answer once). **No viseme/phoneme
  timing anywhere** (Web Speech exposes only `onboundary` word events, unused).

## 4. Stream / state / barge-in
- `kaiState` enum: offline/online/listening/thinking/speaking/alert. **`listening` is
  declared but NEVER entered** — the exact slot a mic/embodiment state plugs into.
- Governed SSE (`POST /admin/kai/kai-chat/stream`) + `AbortController` cancellation is
  **REAL and wired end-to-end** (client abort → `request.is_disconnected()` →
  GeneratorExit → ollama `client.stream()` closes).
- **Barge-in: output-side EXISTS** (new question / STOP aborts stream+TTS). **Input-side
  ABSENT** — no mic, no VAD, no `SpeechRecognition`/`getUserMedia` anywhere in admin KAI.
  "Interrupt KAI by speaking" cannot exist without a mic capture path.

## Does NOT exist — cannot be fabricated
- A rigged 2D/3D avatar (Live2D/GLB/VRM) with morph targets — **art/rigging-pipeline
  asset; not in repo; cannot be generated here.**
- A viseme/phoneme feed — needs Azure Speech visemes (key+network, UNAVAILABLE) or
  client audio-energy inference (needs an `<audio>` element AND a rigged mouth to drive).
- Microphone / VAD / speech-to-interrupt.
- Streaming/incremental TTS; a guaranteed cross-OS male Web Speech voice.

## Consequence for Phase 12 (honest scope)
Real, buildable NOW (no asset/infra): the **backend sanitizer (done)**, the
**authoritative embodiment state machine**, masculine-voice hardening + audition, the
**viseme/coarticulation engine as pure tested logic** (ready to drive a rig when one
exists; demonstrated against a 2D placeholder in an Avatar Lab), idle-life *schedulers*
(timing logic), and state→halo/env/subtitle sync (extends Phase 10/11 — no rewrite).
**EXTERNAL_BLOCKED (needs assets/infra, must NOT be faked):** photoreal rigged avatar,
real audio-driven viseme lip-sync, microphone barge-in, streaming TTS with viseme timing.
Per §40, Phase 12 is **NOT** complete while KAI is a video with audio over it.
