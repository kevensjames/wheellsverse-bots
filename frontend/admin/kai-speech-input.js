/* KAI — Speech Input Provider (Phase 12, §12/§13). Pure UMD, no DOM.
 *
 * Wraps browser speech input (SpeechRecognition / mic) behind ONE provider that reports its
 * real capabilities TRUTHFULLY. Mic/recognition is BROWSER_LIMITED and this module says so:
 * Web Speech recognition is Chrome/webkit-only, permission-gated, and often network-backed —
 * it is NEVER asserted as universally available. All browser APIs are INJECTED
 * ({SpeechRecognition, getUserMedia}) so the state machine + the input-side barge-in trigger
 * are deterministically testable without a real microphone.
 *
 * Input-side barge-in (P0, §13): while KAI is SPEAKING and listening is armed, the FIRST
 * detected speech onset fires onSpeechStart() → the caller routes it to the ONE
 * KaiSpeechCancellationController.bargeIn() (no separate stop semantics, §14).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiSpeechInput = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STATES = ['IDLE', 'LISTENING', 'STOPPED', 'ERROR'];

  function KaiSpeechInputProvider(opts) {
    opts = opts || {};
    this.SR = opts.SpeechRecognition || null;     // window.SpeechRecognition || webkitSpeechRecognition (injected)
    this.getUserMedia = opts.getUserMedia || null;
    this.onSpeechStart = typeof opts.onSpeechStart === 'function' ? opts.onSpeechStart : function () {};
    this.onResult = typeof opts.onResult === 'function' ? opts.onResult : function () {};
    this.onError = typeof opts.onError === 'function' ? opts.onError : function () {};
    this.onEnd = typeof opts.onEnd === 'function' ? opts.onEnd : function () {};
    this.now = opts.now || function () { return 0; };
    this.state = 'IDLE';
    this.error = null;
    this._rec = null;
    this._armed = false;       // barge-in armed (KAI is speaking)
    this._firedOnset = false;  // onset fires ONCE per listening session
  }
  var P = KaiSpeechInputProvider.prototype;

  // TRUTHFUL capability report — presence of the injected APIs, never an optimistic claim.
  P.getCapabilities = function () {
    return {
      recognition: !!this.SR,
      microphone: !!this.getUserMedia,
      status: this.SR ? 'BROWSER_LIMITED' : 'UNAVAILABLE',
      note: 'Web Speech recognition is Chrome/webkit-only, permission-gated, and often network-backed.',
      continuous: !!this.SR,
      interim_results: !!this.SR,
    };
  };
  P.availability = function () {
    if (!this.SR) return { available: false, reason: 'no_speech_recognition_api' };
    return { available: true, reason: 'BROWSER_LIMITED' };   // present ≠ guaranteed; caller must handle permission denial
  };

  // arm/disarm the input-side barge-in (caller sets armed=true while KAI is SPEAKING)
  P.armBargeIn = function (on) { this._armed = !!on; };

  P.start = function (config) {
    if (!this.SR) { this.state = 'ERROR'; this.error = 'no_speech_recognition_api'; return { started: false, reason: this.error }; }
    if (this.state === 'LISTENING') return { started: true, reason: 'already_listening' };
    var self = this;
    this._firedOnset = false;
    var rec = new this.SR();
    rec.continuous = config && config.continuous != null ? config.continuous : true;
    rec.interimResults = config && config.interim != null ? config.interim : true;
    rec.lang = (config && config.lang) || 'en-US';
    rec.onspeechstart = function () { self._onset(); };
    rec.onaudiostart = function () { /* audio captured; onset waits for speech to avoid false triggers */ };
    rec.onresult = function (ev) {
      // onset can also be inferred from the first (even interim) result, in case onspeechstart is absent
      self._onset();
      self.onResult(self._extract(ev));
    };
    rec.onerror = function (ev) { self.state = 'ERROR'; self.error = (ev && ev.error) || 'recognition_error'; self.onError(self.error); };
    rec.onend = function () { if (self.state === 'LISTENING') self.state = 'STOPPED'; self.onEnd(); };
    this._rec = rec;
    this.state = 'LISTENING';
    this.error = null;
    try { rec.start(); } catch (e) { this.state = 'ERROR'; this.error = String(e && e.message || e); return { started: false, reason: this.error }; }
    return { started: true };
  };

  // fire the barge-in onset exactly once per listening session, only when armed
  P._onset = function () {
    if (this._firedOnset) return;
    this._firedOnset = true;
    var at = this.now();
    if (this._armed) this.onSpeechStart({ detected_at: at });   // → caller calls controller.bargeIn()
  };

  P._extract = function (ev) {
    try {
      var r = ev && ev.results && ev.results[ev.results.length - 1];
      var alt = r && r[0];
      return { transcript: (alt && alt.transcript) || '', isFinal: !!(r && r.isFinal), confidence: (alt && alt.confidence) || 0 };
    } catch (e) { return { transcript: '', isFinal: false, confidence: 0 }; }
  };

  P.stop = function () {
    if (this._rec) { try { this._rec.abort ? this._rec.abort() : this._rec.stop(); } catch (e) { /* ignore */ } }
    this._rec = null;
    if (this.state === 'LISTENING') this.state = 'STOPPED';
    return this.state;
  };

  P.getState = function () { return { state: this.state, error: this.error, armed: this._armed, firedOnset: this._firedOnset }; };

  return { KaiSpeechInputProvider: KaiSpeechInputProvider, STATES: STATES };
});
