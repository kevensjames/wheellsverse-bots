/* KAI — Semantic Speech Chunker (Phase 12, §10). Pure UMD, no DOM.
 *
 * Turns INCREMENTAL sanitized assistant text into speakable phrase chunks so TTS can
 * begin before the whole answer arrives, WITHOUT sending one token per call. Prefers
 * sentence / strong-clause boundaries; falls back to a bounded buffer at a word boundary.
 * Never breaks inside an abbreviation (Dr., e.g., p.m.), a decimal (3.14), or a URL, and
 * treats an ellipsis as one pause. Input is assumed already reasoning-sanitized upstream.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiSpeechChunker = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DEFAULT = { minChars: 12, maxChars: 200 };
  // words that end in '.' but do NOT end a sentence (lowercased, no trailing dot)
  var ABBREV = {};
  ['mr', 'mrs', 'ms', 'dr', 'prof', 'st', 'vs', 'etc', 'eg', 'ie', 'no', 'inc', 'ltd', 'jr', 'sr',
    'fig', 'approx', 'dept', 'gen', 'sen', 'gov', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug',
    'sep', 'sept', 'oct', 'nov', 'dec', 'am', 'pm', 'ph', 'ds', 'us', 'uk'].forEach(function (w) { ABBREV[w] = true; });

  function _isDigit(c) { return c >= '0' && c <= '9'; }
  function _lastWord(s, endExclusive) {
    var i = endExclusive - 1, w = '';
    while (i >= 0 && /[A-Za-z.]/.test(s[i])) { w = s[i] + w; i--; }
    return w.replace(/\.+$/, '').replace(/^.*\./, '').toLowerCase();   // strip dots (handles "e.g" → "g"? keep last segment)
  }
  function _abbrevAt(s, dotIdx) {
    // scan back over letters AND internal dots so "p.m.", "e.g.", "U.S." are recognized
    var i = dotIdx - 1, w = '';
    while (i >= 0 && /[A-Za-z.]/.test(s[i])) { w = s[i] + w; i--; }
    return !!ABBREV[w.replace(/\./g, '').toLowerCase()];
  }
  function _looksUrl(s, dotIdx) {
    // a '.' inside a URL/host: preceded by non-space and followed by a non-space letter/digit
    var next = s[dotIdx + 1];
    if (next == null || /\s/.test(next)) return false;
    // scan back to whitespace; if the token contains '://' or starts with www or has no space and a following letter, treat as inline
    var i = dotIdx, tok = '';
    while (i >= 0 && !/\s/.test(s[i])) { tok = s[i] + tok; i--; }
    return tok.indexOf('://') !== -1 || /^www\./i.test(tok) || /[A-Za-z]/.test(next);
  }

  // find the end index (inclusive) of the first valid speakable boundary in buf, or -1
  function _boundary(buf, cfg, chunkStart) {
    for (var i = 0; i < buf.length; i++) {
      var c = buf[i];
      if (c === '.' || c === '!' || c === '?' || c === ';' || c === ':') {
        // consume an ellipsis run as one boundary
        if (c === '.' && buf[i + 1] === '.' ) {
          var j = i; while (buf[j + 1] === '.') j++;
          if ((i - chunkStart) >= cfg.minChars) return j;   // break after the ellipsis
          i = j; continue;
        }
        if (c === '.') {
          if (_isDigit(buf[i - 1]) && _isDigit(buf[i + 1])) continue;   // decimal
          if (_abbrevAt(buf, i)) continue;                               // abbreviation
          if (_looksUrl(buf, i)) continue;                               // URL/host
        }
        var after = buf[i + 1];
        var atEnd = after == null;
        if (!atEnd && !/\s/.test(after)) continue;   // sentence break needs whitespace/end after
        if ((i - chunkStart + 1) >= cfg.minChars) return i;   // valid boundary of a long-enough chunk
      }
    }
    // no punctuation boundary: fall back to a bounded buffer at a word boundary
    if (buf.length - chunkStart >= cfg.maxChars) {
      var k = chunkStart + cfg.maxChars;
      while (k > chunkStart && !/\s/.test(buf[k])) k--;
      if (k > chunkStart) return k - 1;
    }
    return -1;
  }

  function KaiSpeechChunker(opts) {
    this.cfg = Object.assign({}, DEFAULT, opts || {});
    this.buf = '';
  }
  KaiSpeechChunker.prototype.push = function (text) {
    if (text) this.buf += text;
    var out = [];
    for (;;) {
      var b = _boundary(this.buf, this.cfg, 0);
      if (b < 0) break;
      var chunk = this.buf.slice(0, b + 1).trim();
      this.buf = this.buf.slice(b + 1);
      if (chunk) out.push(chunk);
    }
    return out;
  };
  KaiSpeechChunker.prototype.flush = function () {
    var chunk = this.buf.trim(); this.buf = '';
    return chunk ? [chunk] : [];
  };
  KaiSpeechChunker.prototype.reset = function () { this.buf = ''; };

  // convenience: chunk a whole (already complete) string
  function chunkAll(text, opts) {
    var c = new KaiSpeechChunker(opts);
    return c.push(text || '').concat(c.flush());
  }

  return { KaiSpeechChunker: KaiSpeechChunker, chunkAll: chunkAll, DEFAULT: DEFAULT, ABBREV: ABBREV };
});
