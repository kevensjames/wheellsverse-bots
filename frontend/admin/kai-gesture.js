/* KAI — Camera session + gesture SEAM (Phase 8, §8/§94). Same-origin UMD, fully injectable, reads NO frames.
 *
 * NON-NEGOTIABLES — enforced by this code, not by convention:
 *   • Camera OFF by default. start() opens it ONLY for the explicit owner control ('owner-click') inside a
 *     live user activation, and ONLY when the injected policy gate says ok (backend KAI_CAMERA_ENABLED →
 *     AVAILABLE_SESSION, owner, bridge). The ON flag lives in this object's memory only — never in storage.
 *   • The ONE capture call in the whole admin frontend is inside start() below (video only, audio never
 *     requested). grep it. No preview element, no stream attachment, no bitmap/frame API, no network API:
 *     THIS MODULE NEVER READS A FRAME (test_kai_gesture.js scans the source for every such token).
 *   • A recognizer is an injectable SEAM (registerRecognizer). NONE is shipped — no dependency, no CDN script,
 *     no model download — status RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED: a hand-tracking library is third-party
 *     supply chain and must first pass capability/manifest certification. Registering does not certify.
 *   • If a recognizer is ever registered, inference is LOCAL-ONLY by contract, and NO biometric / identity /
 *     emotion inference exists here: the vocabulary is closed and non-consequential.
 *   • A mandatory fixed "CAMERA ON — local only, nothing leaves this device" banner (role=status, aria-live)
 *     is shown for as long as the camera is open; start() refuses if it cannot be mounted.
 *   • stop() on: the banner's Stop, tab hidden, pagehide, and every presence-level stop (KAI.stop, logout,
 *     mute, settings toggle off, reset). NEVER auto-restarts.
 *   • Gesture events are TYPED {gesture, confidence, ts}. The closed vocabulary is the SAME map as the backend
 *     (gesture_policy.GESTURE_ACTIONS — test_kai_gesture.js diffs the two) and maps ONLY to non-consequential
 *     UI helpers injected by the presence layer; a gesture can never approve / confirm / execute / spend /
 *     change authority — the backend refuses channel 'gesture' (REFUSED_CHANNEL, §75) exactly like voice, and
 *     this module never even holds a handle to holdingCommand / confirm / ask.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiGesture = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var RECOGNIZER_STATUS = 'RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED';
  // Closed vocabulary — MUST stay identical to backend gesture_policy.GESTURE_ACTIONS. Non-consequential UI only.
  var VOCABULARY = Object.freeze({ OPEN_PALM: 'stop', SWIPE_LEFT: 'next', SWIPE_RIGHT: 'previous', THUMBS_DOWN: 'dismiss', POINT_UP: 'open_drawer' });
  var ACTIONS = Object.freeze(Object.keys(VOCABULARY).map(function (k) { return VOCABULARY[k]; }));
  var MIN_CONFIDENCE = 0.8;
  var EXPLICIT_TRIGGER = 'owner-click';

  function KaiCameraSession(opts) {
    opts = opts || {};
    var g = typeof globalThis !== 'undefined' ? globalThis : {};
    var nav = g.navigator || null;
    this.doc = opts.document !== undefined ? opts.document : (g.document || null);
    this.win = opts.window !== undefined ? opts.window : (g.window || null);
    this.mediaDevices = opts.mediaDevices !== undefined ? opts.mediaDevices : (nav && nav.mediaDevices) || null;
    this.userActivation = opts.userActivation !== undefined ? opts.userActivation : (nav && nav.userActivation) || null;
    // Policy gate (presence: backend AVAILABLE_SESSION + owner + bridge + not muted). Missing gate = fail closed.
    this.allowed = typeof opts.allowed === 'function' ? opts.allowed : function () { return { ok: false, code: 'NO_POLICY_GATE', reason: 'no policy gate injected — camera stays OFF' }; };
    this.actions = opts.actions || {};                 // action → non-consequential helper (KAI.stop, drawer, chip focus)
    this.onChange = typeof opts.onChange === 'function' ? opts.onChange : function () {};
    this.on = false;          // in memory ONLY — never persisted (the test proves no storage API is referenced)
    this.stream = null;
    this.recognizer = null;
    this.last = null;         // last gesture decision (for the dashboard)
    this._epoch = 0;          // bumped by stop(): a start() resolving after a stop() is discarded, tracks closed
    this._starting = false;
    this._banner = null; this._bannerSub = null;
    this._onVis = null; this._onHide = null; this._disposeRec = null;
  }
  var P = KaiCameraSession.prototype;

  P.status = function () {
    return {
      camera: this.on ? 'ON_SESSION' : 'OFF',
      recognizer: this.recognizer ? 'REGISTERED' : RECOGNIZER_STATUS,
      frames_read_by_this_module: 0,    // structural: this file has no frame API at all
      inference: 'LOCAL_ONLY', biometrics: 'NONE', authority: 'NONE', persisted: false,
      vocabulary: VOCABULARY, min_confidence: MIN_CONFIDENCE, last: this.last,
    };
  };

  function no(code, reason) { return Promise.resolve({ started: false, code: code, reason: reason }); }
  function stopTracks(stream) {
    try { (stream && stream.getTracks ? stream.getTracks() : []).forEach(function (t) { try { t.stop(); } catch (e) { /* ignore */ } }); } catch (e) { /* ignore */ }
  }

  // Fail-closed order: already on → policy gate → explicit trigger → live user activation → indicator → browser API.
  P.start = function (trigger) {
    if (this.on) return Promise.resolve({ started: true, code: 'ALREADY_ON', reason: 'camera already open for this session' });
    if (this._starting) return no('ALREADY_STARTING', 'camera is already opening');
    var gate = this.allowed() || {};
    if (!gate.ok) return no(gate.code || 'NOT_ALLOWED', gate.reason || 'camera not permitted');
    if (trigger !== EXPLICIT_TRIGGER) return no('NOT_EXPLICIT', 'the camera opens only from the explicit owner control');
    var ua = this.userActivation;
    if (!ua || !ua.isActive) return no('NO_USER_ACTIVATION', 'the camera requires a live user activation — click the control');
    if (!this.doc || !this.doc.body) return no('INDICATOR_UNAVAILABLE', 'no document to mount the mandatory CAMERA ON indicator');
    var md = this.mediaDevices;
    if (!md || typeof md.getUserMedia !== 'function') return no('BROWSER_UNAVAILABLE', 'this browser exposes no camera API');
    var self = this, epoch = this._epoch, p;
    this._starting = true;
    try { p = md.getUserMedia({ video: true, audio: false }); }   // THE ONE capture call — audio is never requested
    catch (e) { this._starting = false; return no('CAPTURE_FAILED', String(e && e.message || e)); }
    return Promise.resolve(p).then(function (stream) {
      self._starting = false;
      if (epoch !== self._epoch || self.on) { stopTracks(stream); return { started: false, code: 'STOPPED_DURING_START', reason: 'stop() was called while the camera was opening' }; }
      self.stream = stream; self.on = true;
      self._bind(); self._showBanner(); self._attachRecognizer();
      self.onChange({ on: true, reason: trigger });
      return { started: true, code: 'ON_SESSION', reason: 'camera open for this session only — local only, nothing leaves this device' };
    }, function (err) {
      self._starting = false;
      var n = (err && err.name) || String(err);
      return { started: false, code: n === 'NotAllowedError' || n === 'SecurityError' ? 'PERMISSION_DENIED' : n === 'NotFoundError' ? 'NO_CAMERA' : 'CAPTURE_FAILED', reason: n };
    });
  };

  P.stop = function (reason) {
    reason = reason || 'stop';
    this._epoch++; this._starting = false;
    var was = this.on;
    if (this._disposeRec) { try { this._disposeRec(); } catch (e) { /* ignore */ } this._disposeRec = null; }
    if (this.stream) { stopTracks(this.stream); this.stream = null; }
    this.on = false;
    this._unbind(); this._hideBanner();
    if (was) this.onChange({ on: false, reason: reason });
    return { on: false, reason: reason };
  };

  // A hidden tab never keeps the camera; leaving the page closes it. Becoming visible again NEVER re-opens it.
  P._bind = function () {
    var self = this;
    this._onVis = function () { if (self.doc.hidden) self.stop('hidden'); };
    this._onHide = function () { self.stop('pagehide'); };
    this.doc.addEventListener('visibilitychange', this._onVis);
    if (this.win && this.win.addEventListener) this.win.addEventListener('pagehide', this._onHide);
  };
  P._unbind = function () {
    if (this._onVis && this.doc && this.doc.removeEventListener) this.doc.removeEventListener('visibilitychange', this._onVis);
    if (this._onHide && this.win && this.win.removeEventListener) this.win.removeEventListener('pagehide', this._onHide);
    this._onVis = this._onHide = null;
  };

  // Mandatory indicator — created next to the capture call so no caller can open the camera without it.
  P._showBanner = function () {
    var d = this.doc, self = this;
    if (!this._banner) {
      var b = d.createElement('div'); b.className = 'kaip-cam-banner';
      b.setAttribute('role', 'status'); b.setAttribute('aria-live', 'assertive');
      var dot = d.createElement('span'); dot.className = 'kaip-cam-dot'; dot.setAttribute('aria-hidden', 'true');
      var text = d.createElement('span'); text.className = 'kaip-cam-text'; text.textContent = 'CAMERA ON — local only, nothing leaves this device';
      var sub = d.createElement('span'); sub.className = 'kaip-cam-sub';
      var btn = d.createElement('button'); btn.type = 'button'; btn.className = 'kaip-cam-stop'; btn.textContent = 'Stop camera'; btn.setAttribute('aria-label', 'Turn the camera off');
      btn.addEventListener('click', function () { self.stop('user-stop'); });
      b.appendChild(dot); b.appendChild(text); b.appendChild(sub); b.appendChild(btn);
      d.body.appendChild(b); this._banner = b; this._bannerSub = sub;
    }
    this._bannerSub.textContent = this.recognizer ? 'recognizer registered · frames processed on this device only' : 'no frames read · recognizer ' + RECOGNIZER_STATUS;
    this._banner.hidden = false;
  };
  P._hideBanner = function () { if (this._banner) this._banner.hidden = true; };

  // THE SEAM. fn(stream, emit) → optional dispose(). Nothing is shipped behind it.
  P.registerRecognizer = function (fn) {
    if (typeof fn !== 'function') return false;
    this.recognizer = fn;
    if (this.on) { this._attachRecognizer(); this._showBanner(); }
    return true;
  };
  P._attachRecognizer = function () {
    if (!this.recognizer || !this.on || this._disposeRec) return;
    var self = this;
    var d = this.recognizer(this.stream, function (ev) { return self.handleEvent(ev); });
    this._disposeRec = typeof d === 'function' ? d : function () {};
  };

  // Typed event → closed vocabulary (same normalization as the backend: trim + upper) → injected non-consequential
  // helper. Only VOCABULARY actions are ever looked up, so an injected 'approve'/'confirm'/'execute' handler (or a
  // gesture named like one) can never run.
  P.handleEvent = function (ev) {
    var out = { channel: 'gesture', authority: 'NONE', status: 'REFUSED', code: '', gesture: ev && ev.gesture, action: null };
    var malformed = !ev || typeof ev.gesture !== 'string' || typeof ev.confidence !== 'number' || ev.confidence !== ev.confidence || typeof ev.ts !== 'number';
    var name = malformed ? '' : ev.gesture.trim().toUpperCase();
    var action = Object.prototype.hasOwnProperty.call(VOCABULARY, name) ? VOCABULARY[name] : null;
    if (malformed) out.code = 'MALFORMED';
    else if (!this.on) out.code = 'CAMERA_OFF';
    else if (!action) out.code = 'UNKNOWN_GESTURE';
    else if (ev.confidence < MIN_CONFIDENCE) out.code = 'LOW_CONFIDENCE';
    else if (typeof this.actions[action] !== 'function') out.code = 'NO_HANDLER';
    else {
      try { this.actions[action](); out.status = 'APPLIED'; out.code = 'APPLIED'; out.action = action; }
      catch (e) { out.code = 'HANDLER_ERROR'; }
    }
    this.last = out;
    return out;
  };

  return { KaiCameraSession: KaiCameraSession, VOCABULARY: VOCABULARY, ACTIONS: ACTIONS, RECOGNIZER_STATUS: RECOGNIZER_STATUS, MIN_CONFIDENCE: MIN_CONFIDENCE, EXPLICIT_TRIGGER: EXPLICIT_TRIGGER };
});
