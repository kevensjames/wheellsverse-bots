/* KAI — TTS Provider abstraction + voice ranking (Phase 12, §6/§7). Pure UMD (browser
 * APIs injected). Nexus never touches speechSynthesis directly — all voice goes through a
 * KaiTTSProvider. `rankVoices`/`pickVoice` are pure so the masculine-preference logic is
 * testable; the actual synth/utterance are injected (real in the browser, mocked in tests).
 *
 * Honest capability truth (§16): Web Speech has NO viseme timing and only coarse word
 * boundaries — the provider reports that, so nothing downstream claims "real phoneme sync".
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiTTSProvider = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var MALE_HINTS = ['david', 'mark', 'daniel', 'alex', 'fred', 'george', 'james', 'thomas', 'ryan',
    'guy', 'male', 'arthur', 'oliver', 'aaron', 'eric', 'christopher', 'matthew', 'gordon', 'lee', 'liam'];
  var FEMALE_HINTS = ['samantha', 'victoria', 'karen', 'moira', 'tessa', 'fiona', 'female', 'zira',
    'susan', 'anna', 'amy', 'lessac', 'allison', 'ava', 'serena', 'kate', 'catherine', 'zoe', 'sara', 'joana', 'nicky'];
  var QUALITY_HINTS = ['natural', 'premium', 'enhanced', 'neural'];

  function _has(name, list) { var n = String(name || '').toLowerCase(); for (var i = 0; i < list.length; i++) if (n.indexOf(list[i]) !== -1) return true; return false; }

  // Score a voice for KAI: English + masculine + quality. Returns {voice, score, masculine, reasons}.
  function scoreVoice(v) {
    var name = v.name || '', lang = String(v.lang || '').toLowerCase(), s = 0, reasons = [];
    var male = _has(name, MALE_HINTS), female = _has(name, FEMALE_HINTS);
    if (male && !female) { s += 100; reasons.push('masculine-name'); }
    if (female) { s -= 120; reasons.push('female-name'); }
    if (lang.indexOf('en') === 0) { s += 40; reasons.push('english'); }
    if (lang === 'en-us' || lang === 'en_us') { s += 15; reasons.push('en-US'); }
    if (v.localService) { s += 10; reasons.push('local'); }
    if (v.default) { s += 5; reasons.push('default'); }
    if (_has(name, QUALITY_HINTS)) { s += 12; reasons.push('quality'); }
    return { voice: v, score: s, masculine: male && !female, reasons: reasons };
  }

  function rankVoices(voices) {
    var scored = (voices || []).map(scoreVoice);
    // stable sort by score desc, then name for determinism
    scored.sort(function (a, b) { return (b.score - a.score) || String(a.voice.name).localeCompare(String(b.voice.name)); });
    return scored;
  }
  function pickVoice(voices) { var r = rankVoices(voices); return r.length ? r[0].voice : null; }

  // ── Web Speech provider (browser). synth + makeUtterance injected for testability. ──
  function webSpeechProvider(opts) {
    opts = opts || {};
    var synth = opts.synth || (typeof window !== 'undefined' ? window.speechSynthesis : null);
    var makeUtterance = opts.makeUtterance || (typeof window !== 'undefined' && window.SpeechSynthesisUtterance
      ? function (t) { return new window.SpeechSynthesisUtterance(t); } : null);
    var preferredName = opts.preferredVoiceName || null;
    var diag = { id: 'web-speech', speaking: false, lastError: null };

    function listVoices() { try { return (synth && synth.getVoices && synth.getVoices()) || []; } catch (e) { return []; } }
    function resolveVoice() {
      var vs = listVoices();
      if (preferredName) { for (var i = 0; i < vs.length; i++) if (vs[i].name === preferredName) return vs[i]; }
      return pickVoice(vs);
    }
    return {
      id: 'web-speech',
      getCapabilities: function () {
        return { provider_id: 'web-speech', voices: true, streaming: false, viseme_timestamps: false, word_timestamps: true, cancel: true };
      },
      availability: function () { return { available: !!(synth && makeUtterance), reason: (synth && makeUtterance) ? null : 'speechSynthesis unavailable' }; },
      listVoices: listVoices,
      rankVoices: function () { return rankVoices(listVoices()); },
      setPreferredVoice: function (name) { preferredName = name || null; },
      speak: function (text, o) {
        o = o || {};
        if (!synth || !makeUtterance) { diag.lastError = 'unavailable'; if (o.onerror) o.onerror('unavailable'); return null; }
        var u = makeUtterance(String(text || ''));
        var v = resolveVoice(); if (v) u.voice = v;
        u.rate = o.rate != null ? o.rate : 1.0; u.pitch = o.pitch != null ? o.pitch : 1.0;
        u.onstart = function () { diag.speaking = true; if (o.onstart) o.onstart(); };
        u.onend = function () { diag.speaking = false; if (o.onend) o.onend(); };
        u.onerror = function (e) { diag.speaking = false; diag.lastError = (e && e.error) || 'error'; if (o.onerror) o.onerror(diag.lastError); };
        if (o.onboundary && 'onboundary' in u) u.onboundary = function (e) { o.onboundary(e); };   // coarse word timing only
        synth.speak(u);
        return u;
      },
      cancel: function () { try { if (synth && synth.cancel) synth.cancel(); } catch (e) {} diag.speaking = false; },
      getDiagnostics: function () { return Object.assign({}, diag, { preferredVoiceName: preferredName }); },
    };
  }

  function createProvider(kind, opts) {
    switch (String(kind || 'web-speech').toLowerCase()) {
      case 'web-speech': default: return webSpeechProvider(opts);
    }
  }

  return { MALE_HINTS: MALE_HINTS, FEMALE_HINTS: FEMALE_HINTS, scoreVoice: scoreVoice, rankVoices: rankVoices, pickVoice: pickVoice, webSpeechProvider: webSpeechProvider, createProvider: createProvider };
});
