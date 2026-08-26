/* KAI Adaptive Mission Nexus — Authoritative Embodiment State Machine (Phase 12, §5)
 *
 * Pure UMD logic (browser + node), no DOM. ONE source of embodiment truth: every
 * consumer (face/eyes/halo/chest sigil/video/voice/subtitles/environment/command bar)
 * resolves from the SAME state via `resolve()` + reads the SAME per-state `spec()`.
 * This does NOT fork a second state machine — it maps the existing kaiState + env +
 * optional event hint onto the richer embodiment vocabulary and tells each consumer
 * what to do, so they can never drift out of sync (§5: "Do not create disconnected
 * state machines").
 *
 * Honest scope (docs/KAI_EMBODIMENT_SOURCES.md, D12): the production avatar is a VIDEO
 * (idle/speak clips) with no rig — so `spec().video` is a clip name, and `spec().face`
 * is an ADVISORY descriptor a rigged avatar would consume when one exists. Real
 * blink/gaze/viseme rendering is EXTERNAL_BLOCKED on a rigged asset; this module is the
 * state brain that is ready to drive it, and drives the video/halo/env/subtitle today.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.NexusEmbodiment = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STATES = ['sleep', 'idle', 'attentive', 'listening', 'understanding', 'thinking',
    'researching', 'executing', 'speaking', 'waiting', 'success', 'warning', 'critical', 'error'];

  // Per-state advisory spec. `halo` = the kaiState the Phase 10 halo already styles (reuse,
  // never rewrite). `env` = shell data-env overlay (null = leave as-is). `video` = clip.
  // `voice`/`subtitle` = whether KAI is vocalizing. `eyes` stays KAI-blue always (identity,
  // §7) — environment carries amber/crimson, never the eyes. `label` = §24-safe status word.
  var SPEC = {
    sleep:         { halo: 'offline',     env: null,       video: 'idle',  voice: false, subtitle: false, eyes: 'blue-dim',  label: 'Offline' },
    idle:          { halo: 'online',      env: 'idle',     video: 'idle',  voice: false, subtitle: false, eyes: 'blue',      label: 'Ready' },
    attentive:     { halo: 'online',      env: 'idle',     video: 'idle',  voice: false, subtitle: false, eyes: 'blue-focus', label: 'Attentive' },
    listening:     { halo: 'listening',   env: 'idle',     video: 'idle',  voice: false, subtitle: false, eyes: 'blue-focus', label: 'Listening…' },
    understanding: { halo: 'thinking',    env: 'idle',     video: 'idle',  voice: false, subtitle: false, eyes: 'blue-focus', label: 'Understanding…' },
    thinking:      { halo: 'thinking',    env: 'idle',     video: 'idle',  voice: false, subtitle: false, eyes: 'blue-energy', label: 'Thinking…' },
    researching:   { halo: 'researching', env: 'idle',     video: 'idle',  voice: false, subtitle: false, eyes: 'blue-scan',  label: 'Researching…' },
    executing:     { halo: 'thinking',    env: 'idle',     video: 'idle',  voice: false, subtitle: false, eyes: 'blue-energy', label: 'Working…' },
    speaking:      { halo: 'speaking',    env: null,       video: 'speak', voice: true,  subtitle: true,  eyes: 'blue',      label: 'Responding…' },
    waiting:       { halo: 'alert',       env: 'warning',  video: 'idle',  voice: false, subtitle: false, eyes: 'blue-focus', label: 'Awaiting you' },
    success:       { halo: 'online',      env: 'success',  video: 'idle',  voice: false, subtitle: false, eyes: 'blue',      label: 'Done' },
    warning:       { halo: 'alert',       env: 'warning',  video: 'idle',  voice: false, subtitle: false, eyes: 'blue',      label: 'Attention' },
    critical:      { halo: 'alert',       env: 'critical', video: 'idle',  voice: false, subtitle: false, eyes: 'blue',      label: 'Critical' },
    error:         { halo: 'alert',       env: 'critical', video: 'idle',  voice: false, subtitle: false, eyes: 'blue',      label: 'Error' },
  };

  function spec(state) { return SPEC[state] || SPEC.idle; }

  // Resolve the embodiment state from the live inputs. kaiState is the existing presence
  // state; env is the shell environment; hint is an optional event kind the caller knows
  // (executing/understanding/waiting/success/error) that kaiState alone can't express.
  // Precedence: an explicit outcome hint > kaiState lifecycle > env criticality overlay.
  // NOTE: env criticality does NOT override an active SPEAKING turn (KAI keeps talking; the
  // environment reddens around him — §7/§24), matching the directive's "eyes stay blue".
  function resolve(input) {
    input = input || {};
    var kai = String(input.kaiState || 'online').toLowerCase();
    var env = input.env ? String(input.env).toLowerCase() : 'idle';
    var hint = input.hint ? String(input.hint).toLowerCase() : '';

    if (kai === 'offline') return 'sleep';

    // explicit lifecycle hints the caller supplies
    if (hint === 'listening') return 'listening';
    if (hint === 'understanding') return 'understanding';
    if (hint === 'executing') return 'executing';
    if (hint === 'waiting') return 'waiting';

    // an active speaking turn wins over env overlays (keep talking; env reddens separately)
    if (kai === 'speaking') return 'speaking';
    if (kai === 'listening') return 'listening';
    if (kai === 'researching') return 'researching';
    if (kai === 'thinking') return 'thinking';

    // outcomes / environment (when not mid-utterance)
    if (hint === 'error' || kai === 'error') return 'error';
    if (env === 'critical') return 'critical';
    if (env === 'warning' || kai === 'alert') return 'warning';
    if (hint === 'success' || env === 'success') return 'success';

    if (hint === 'attentive') return 'attentive';
    return 'idle';
  }

  // Legal-transition guard (advisory): the machine is derived, not free-running, so most
  // transitions are legal; this documents the ones a renderer should animate through
  // rather than snap (e.g. speaking→idle passes through attentive). Returns the sequence
  // of intermediate states to ease through (may be empty).
  function easeThrough(from, to) {
    if (from === to) return [];
    if (from === 'speaking' && (to === 'idle' || to === 'sleep')) return ['attentive'];
    if (from === 'listening' && to === 'speaking') return ['understanding', 'thinking'];
    if (from === 'idle' && to === 'speaking') return ['thinking'];
    return [];
  }

  return { STATES: STATES, SPEC: SPEC, spec: spec, resolve: resolve, easeThrough: easeThrough };
});
