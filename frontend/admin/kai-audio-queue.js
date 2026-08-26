/* KAI — Bounded Speech Audio Queue (Phase 12, §15). Pure UMD, no DOM.
 *
 * Ordered, bounded queue of speakable chunks with an explicit lifecycle. On interruption
 * (barge-in / STOP) the active item is cancelled and all future items cleared. No
 * unbounded growth. Timestamps come from an injected clock (deterministic in tests);
 * the actual TTS synth/playback lives in the driver/provider — this is pure state.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiAudioQueue = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STATES = ['QUEUED', 'SYNTHESIZING', 'PLAYING', 'COMPLETE', 'CANCELLED', 'FAILED'];
  var ACTIVE = { SYNTHESIZING: 1, PLAYING: 1 };
  var TERMINAL = { COMPLETE: 1, CANCELLED: 1, FAILED: 1 };

  function KaiAudioQueue(opts) {
    opts = opts || {};
    this.maxLen = opts.maxLen || 24;         // bounded (§15)
    this.now = opts.now || function () { return 0; };
    this.items = [];
    this._seq = 0;
  }
  var P = KaiAudioQueue.prototype;

  P.enqueue = function (text, provider) {
    if (this.pending() >= this.maxLen) return null;   // reject rather than grow unbounded
    var item = {
      id: 'spk-' + (++this._seq), text: text, sequence: this._seq, provider: provider || null,
      status: 'QUEUED', created_at: this.now(), started_at: null, completed_at: null, viseme_timeline: null,
    };
    this.items.push(item);
    return item;
  };

  P._byId = function (id) { for (var i = 0; i < this.items.length; i++) if (this.items[i].id === id) return this.items[i]; return null; };

  // the next QUEUED item in sequence order (FIFO)
  P.next = function () {
    for (var i = 0; i < this.items.length; i++) if (this.items[i].status === 'QUEUED') return this.items[i];
    return null;
  };
  P._set = function (id, status, stamp) {
    var it = this._byId(id); if (!it) return null;
    if (TERMINAL[it.status]) return null;   // a CANCELLED/COMPLETE/FAILED item is immutable — a late onend can't resurrect it
    it.status = status;
    if (stamp === 'start') it.started_at = this.now();
    if (stamp === 'end') it.completed_at = this.now();
    return it;
  };
  P.markSynthesizing = function (id) { return this._set(id, 'SYNTHESIZING'); };
  P.markPlaying = function (id, timeline) { var it = this._set(id, 'PLAYING', 'start'); if (it && timeline) it.viseme_timeline = timeline; return it; };
  P.markComplete = function (id) { return this._set(id, 'COMPLETE', 'end'); };
  P.markFailed = function (id) { return this._set(id, 'FAILED', 'end'); };

  P.active = function () { for (var i = 0; i < this.items.length; i++) if (ACTIVE[this.items[i].status]) return this.items[i]; return null; };
  P.pending = function () { var n = 0; for (var i = 0; i < this.items.length; i++) if (this.items[i].status === 'QUEUED') n++; return n; };

  // Interruption: cancel the active item + clear every not-yet-terminal future item.
  P.cancelAll = function () {
    var cancelled = 0;
    for (var i = 0; i < this.items.length; i++) {
      var it = this.items[i];
      if (!TERMINAL[it.status]) { it.status = 'CANCELLED'; it.completed_at = this.now(); cancelled++; }
    }
    return cancelled;
  };

  // Drop terminal items (housekeeping) so the array does not grow across a long session.
  P.prune = function () { this.items = this.items.filter(function (it) { return !TERMINAL[it.status]; }); return this.items.length; };
  P.size = function () { return this.items.length; };

  return { KaiAudioQueue: KaiAudioQueue, STATES: STATES };
});
