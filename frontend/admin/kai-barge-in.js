/* KAI — Speech Cancellation Controller + Barge-in (Phase 12, §13/§14). Pure UMD, no DOM.
 *
 * ONE cancellation path used by BOTH the STOP control and input-side barge-in (§14 — no
 * divergent stop semantics). All effects are injected (cancel TTS, clear queue, clear
 * viseme timeline, mouth→REST, cancel LLM/SSE, set state) so the orchestration is
 * deterministically testable; timing marks come from an injected clock. Barge-in is P0:
 * when the user speaks while KAI is SPEAKING, everything stops and state → LISTENING,
 * with the reaction latency measured honestly.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiBargeIn = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function KaiSpeechCancellationController(deps) {
    deps = deps || {};
    this.d = deps;
    this.now = deps.now || function () { return 0; };
    this.marks = {};
  }
  var P = KaiSpeechCancellationController.prototype;

  // The single stop routine. reason: 'user-stop' | 'barge-in' | 'error' | 'route-change' | 'nav'.
  // Order matters: silence audio FIRST, then clear queued/visemes, relax the mouth, cancel upstream.
  P.stop = function (reason) {
    var m = { reason: reason || 'user-stop', started_at: this.now() };
    if (this.d.cancelTTS) this.d.cancelTTS();
    m.audio_stopped_at = this.now();
    if (this.d.clearQueue) this.d.clearQueue();
    if (this.d.clearVisemes) this.d.clearVisemes();
    m.viseme_stopped_at = this.now();
    if (this.d.mouthToRest) this.d.mouthToRest();
    if (this.d.cancelLLM) this.d.cancelLLM();     // abort the governed SSE where supported
    m.done_at = this.now();
    this.marks = m;
    return m;
  };

  // Output-side STOP (existing control): stop + settle to a non-listening state.
  P.userStop = function () {
    var m = this.stop('user-stop');
    if (this.d.setState) this.d.setState('online');
    m.state = 'online';
    return m;
  };

  // Input-side barge-in (P0, §13): user spoke while KAI was speaking → stop + LISTENING.
  P.bargeIn = function () {
    var detected = this.now();
    var m = this.stop('barge-in');
    m.barge_in_detected_at = detected;
    if (this.d.setState) this.d.setState('listening');
    m.listening_at = this.now();
    m.state = 'listening';
    m.reaction_ms = m.listening_at - detected;   // BARGE_IN_REACTION_MS (honest local latency)
    this.marks = m;
    return m;
  };

  // Lifecycle cleanup (route change / nav): stop without forcing listening.
  P.teardown = function (reason) {
    var m = this.stop(reason || 'route-change');
    if (this.d.stopMic) this.d.stopMic();
    if (this.d.disposeTimers) this.d.disposeTimers();
    if (this.d.setState) this.d.setState('idle');
    m.state = 'idle';
    return m;
  };

  return { KaiSpeechCancellationController: KaiSpeechCancellationController };
});
