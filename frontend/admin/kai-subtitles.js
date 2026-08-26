/* KAI — Governed Subtitle Buffer (Phase 12, §23–27). Pure UMD, no DOM.
 *
 * Accumulates the PROGRESSIVE assistant answer from the governed stream (App B sanitized
 * SSE → bridge → here) into a bounded, display-ready subtitle window. Two honesty rules:
 *  (§24) ONLY reasoning-sanitized text is ever visible — an injected streaming sanitizer
 *        ({push(delta)->safe, flush()->tail}) runs defense-in-depth over every delta, so a
 *        `<think>` that slips through the backend still never reaches the screen or TTS.
 *  (§14/§27) INTERRUPTION CONSISTENCY — when STOP/barge-in fires, subtitles FREEZE exactly
 *        where the voice stopped; a late SSE delta for the interrupted utterance is dropped
 *        (epoch-guarded), so there is never "ghost" text advancing after KAI went silent.
 *
 * State: EMPTY → STREAMING → SETTLED, or → INTERRUPTED (terminal for that utterance).
 * The renderer/DOM lives at the call site; visible() returns the bounded string to paint.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiSubtitles = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DEFAULT = { maxChars: 240 };                 // rolling window; subtitles show the tail
  var PASSTHROUGH = { push: function (d) { return d || ''; }, flush: function () { return ''; } };

  // last `max` chars, trimmed to a word boundary so the window never cuts mid-word
  function windowTail(s, max) {
    if (s.length <= max) return s;
    var start = s.length - max, sp = s.indexOf(' ', start);
    return (sp === -1 ? s.slice(start) : s.slice(sp + 1)).replace(/^\s+/, '');
  }

  function KaiSubtitleBuffer(opts) {
    this.cfg = Object.assign({}, DEFAULT, opts || {});
    this.sanitizer = (opts && opts.sanitizer) || PASSTHROUGH;   // MUST be the §24 streaming sanitizer in prod
    this._full = '';
    this.state = 'EMPTY';
    this._epoch = 0;      // increments per utterance; a delta tagged with a stale epoch is ignored
    this._frozen = false;
  }
  var P = KaiSubtitleBuffer.prototype;

  // start a new utterance: fresh epoch, cleared buffer, sanitizer reset. Returns the epoch
  // the caller must stamp onto this utterance's deltas.
  P.begin = function () {
    this._epoch++; this._full = ''; this._frozen = false; this.state = 'EMPTY';
    if (this.sanitizer.reset) this.sanitizer.reset();
    return this._epoch;
  };

  // append a streamed delta. `epoch` (optional) guards against late frames from a prior,
  // interrupted utterance — pass the value begin() returned. Returns the visible window.
  P.push = function (delta, epoch) {
    if (this._frozen) return this.visible();                       // interrupted → drop further text (§27)
    if (epoch != null && epoch !== this._epoch) return this.visible();   // stale utterance → ignore
    var safe = this.sanitizer.push(delta || '');                  // §24: sanitized before it can ever be shown
    if (safe) this._full += safe;
    if (this._full) this.state = 'STREAMING';
    return this.visible();
  };

  // end of stream: flush the sanitizer tail (preserves the final answer; a genuinely-closed
  // reasoning block stays stripped) and settle.
  P.finalize = function () {
    if (this._frozen) return this.visible();
    var tail = this.sanitizer.flush ? this.sanitizer.flush() : '';
    if (tail) this._full += tail;
    this.state = this._full ? 'SETTLED' : 'EMPTY';
    return this.visible();
  };

  // STOP / barge-in: freeze subtitles where the voice stopped. Idempotent.
  P.interrupt = function () {
    if (this.state !== 'EMPTY') this.state = 'INTERRUPTED';
    this._frozen = true;
    return this.visible();
  };

  P.visible = function () { return windowTail(this._full, this.cfg.maxChars); };
  P.fullText = function () { return this._full; };
  P.getState = function () { return this.state; };

  return { KaiSubtitleBuffer: KaiSubtitleBuffer, windowTail: windowTail, DEFAULT: DEFAULT };
});
