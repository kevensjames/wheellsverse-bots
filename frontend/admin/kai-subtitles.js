/* KAI — Governed Subtitle Buffer (Phase 12, §23–27). Pure UMD, no DOM.
 *
 * Accumulates the PROGRESSIVE assistant answer from the governed stream (App B sanitized
 * SSE → bridge → here) into a bounded, display-ready subtitle window. Two honesty rules:
 *  (§24) ONLY reasoning-sanitized text is ever visible. The buffer keeps RAW deltas and
 *        sanitizes ON READ through the authoritative NexusPulse.stripReasoning boundary —
 *        the DEFAULT is FAIL-CLOSED (a `<think>` that slips the backend is stripped even if
 *        the caller injects nothing), so subtitles can never leak chain-of-thought.
 *  (§14/§27) INTERRUPTION CONSISTENCY — when STOP/barge-in fires, subtitles FREEZE exactly
 *        where the voice stopped; a late SSE delta for the interrupted utterance is dropped
 *        (epoch-guarded), so there is never "ghost" text advancing after KAI went silent.
 *
 * State: EMPTY → STREAMING → SETTLED, or → INTERRUPTED (terminal for that utterance).
 * The renderer/DOM lives at the call site; visible() returns the bounded string to paint.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./kai-nexus-pulse.js'));
  else root.KaiSubtitles = factory(root.NexusPulse);
})(typeof self !== 'undefined' ? self : this, function (Pulse) {
  'use strict';

  var DEFAULT = { maxChars: 240 };                 // rolling window; subtitles show the tail
  var _TAGS = 'think|thinking|reasoning|scratchpad|reflection';
  var _CLOSED = new RegExp('<(' + _TAGS + ')(?:\\s[^>]*)?>[\\s\\S]*?<\\/\\1>', 'gi');
  var _OPEN_TRAILING = new RegExp('<(' + _TAGS + ')(?:\\s[^>]*)?>[\\s\\S]*$', 'i');

  // FAIL-CLOSED §24 default: reuse the authoritative boundary when present, else an identical
  // inline strip (closed blocks always removed; unclosed-trailing removed mid-stream, kept on
  // finalize). NEVER a verbatim pass-through — a missing sanitizer must not expose reasoning.
  function defaultSanitize(raw, finalized) {
    if (Pulse && Pulse.stripReasoning) return Pulse.stripReasoning(raw, { finalized: !!finalized });
    var out = String(raw == null ? '' : raw).replace(_CLOSED, '');
    if (!finalized) out = out.replace(_OPEN_TRAILING, '');
    return out;
  }

  // last `max` chars, trimmed to a word boundary so the window never cuts mid-word
  function windowTail(s, max) {
    if (s.length <= max) return s;
    var start = s.length - max, sp = s.indexOf(' ', start);
    return (sp === -1 ? s.slice(start) : s.slice(sp + 1)).replace(/^\s+/, '');
  }

  function KaiSubtitleBuffer(opts) {
    this.cfg = Object.assign({}, DEFAULT, opts || {});
    // opts.sanitize(raw, finalized) -> safe text. Defaults FAIL-CLOSED (strips reasoning).
    this.sanitize = (opts && typeof opts.sanitize === 'function') ? opts.sanitize : defaultSanitize;
    this._raw = '';
    this._finalized = false;
    this.state = 'EMPTY';
    this._epoch = 0;      // increments per utterance; a delta tagged with a stale epoch is ignored
    this._frozen = false;
  }
  var P = KaiSubtitleBuffer.prototype;

  // start a new utterance: fresh epoch, cleared buffer. Returns the epoch the caller must
  // stamp onto this utterance's deltas.
  P.begin = function () {
    this._epoch++; this._raw = ''; this._finalized = false; this._frozen = false; this.state = 'EMPTY';
    return this._epoch;
  };

  // append a streamed delta. `epoch` (optional) guards against late frames from a prior,
  // interrupted utterance — pass the value begin() returned. Returns the visible window.
  P.push = function (delta, epoch) {
    if (this._frozen) return this.visible();                       // interrupted → drop further text (§27)
    if (epoch != null && epoch !== this._epoch) return this.visible();   // stale utterance → ignore
    this._raw += (delta || '');
    if (this.visible()) this.state = 'STREAMING';
    return this.visible();
  };

  // end of stream: sanitize in finalized mode (a genuinely-closed reasoning block stays
  // stripped; a lone literal <think> in a finished answer is preserved) and settle.
  P.finalize = function () {
    if (this._frozen) return this.visible();
    this._finalized = true;
    this.state = this.visible() ? 'SETTLED' : 'EMPTY';
    return this.visible();
  };

  // STOP / barge-in: freeze subtitles where the voice stopped. Idempotent.
  P.interrupt = function () {
    if (this.state !== 'EMPTY') this.state = 'INTERRUPTED';
    this._frozen = true;
    return this.visible();
  };

  // §24: sanitize the RAW accumulation on every read — reasoning is never stored as "visible".
  P.fullText = function () { return this.sanitize(this._raw, this._finalized); };
  P.visible = function () { return windowTail(this.fullText(), this.cfg.maxChars); };
  P.getState = function () { return this.state; };

  return { KaiSubtitleBuffer: KaiSubtitleBuffer, windowTail: windowTail, defaultSanitize: defaultSanitize, DEFAULT: DEFAULT };
});
