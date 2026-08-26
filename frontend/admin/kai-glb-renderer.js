/* KAI — GLB Renderer (Phase 12, §19/§20, D14 plain Three.js). UMD.
 *
 * The single rendering boundary for the digital-human GLB. Three.js is INJECTED
 * ({THREE, GLTFLoader}) so this core is testable with mocks and so the buildless
 * admin app owns exactly one place that touches Three.js. RUNTIME is EXTERNAL_BLOCKED
 * until the operator vendors a pinned Three.js build + a rigged GLB (D14) — but the
 * load-state machine, disposal accounting, WebGL-context-loss fallback, and the
 * velocity-limited head/eye control are all real, tested logic NOW.
 *
 * Load states: UNINITIALIZED → LOADING → READY | FAILED, and DISPOSED terminal.
 * READY is set ONLY after the GLB parses AND a SkinnedMesh with a morph dictionary
 * binds through MorphTargetRegistry — never optimistically (no fake READY, §8).
 * The SAME viseme-engine coefficient frames that drive LabAvatarDriver drive this
 * renderer via applyCoeffs() → MorphTargetRegistry (the §11 single-source invariant).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./kai-morph-registry.js'));
  else root.KaiGLBRenderer = factory(root.KaiMorphRegistry);
})(typeof self !== 'undefined' ? self : this, function (MR) {
  'use strict';

  var STATES = ['UNINITIALIZED', 'LOADING', 'READY', 'FAILED', 'DISPOSED'];
  // head yaw/pitch + eye gaze are clamped to human-plausible ranges and rate-limited
  var LIMITS = { headYaw: 0.6, headPitch: 0.4, gazeX: 1, gazeY: 1 };            // radians / normalized
  var RATE = { head: 2.5, gaze: 8.0 };                                          // units per second (velocity cap)

  function _clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  // move `cur` toward `target` by at most rate*dt — the velocity limit that stops head/eye snapping
  function approach(cur, target, rate, dtSec) {
    var maxStep = rate * dtSec, d = target - cur;
    if (d > maxStep) return cur + maxStep;
    if (d < -maxStep) return cur - maxStep;
    return target;
  }

  function KaiGLBRenderer(opts) {
    opts = opts || {};
    this.THREE = opts.THREE || null;
    this.GLTFLoader = opts.GLTFLoader || null;
    this.canvas = opts.canvas || null;
    this.quality = opts.quality || 'high';
    this.onFallback = typeof opts.onFallback === 'function' ? opts.onFallback : function () {};
    this.state = 'UNINITIALIZED';
    this.error = null;
    this.mesh = null;            // the SkinnedMesh carrying morphTargetInfluences
    this.morphRegistry = null;
    this.boneRegistry = null;
    this._root = null;           // the added gltf.scene root (removed on dispose)
    this._disposables = [];      // {dispose()} geometries/materials/textures/renderer we own
    this._trackedSet = (typeof Set !== 'undefined') ? new Set() : null;   // dedupe shared textures/materials
    this._disposedCount = 0;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this._pose = { headYaw: 0, headPitch: 0, gazeX: 0, gazeY: 0 };
    this._target = { headYaw: 0, headPitch: 0, gazeX: 0, gazeY: 0 };
    this._contextLost = false;
  }
  var P = KaiGLBRenderer.prototype;

  // texture-bearing PBR material slots — ALL leak on dispose if only .map is released
  var TEX_KEYS = ['map', 'normalMap', 'bumpMap', 'roughnessMap', 'metalnessMap', 'emissiveMap', 'aoMap',
    'displacementMap', 'alphaMap', 'envMap', 'lightMap', 'clearcoatMap', 'clearcoatNormalMap',
    'clearcoatRoughnessMap', 'sheenColorMap', 'specularMap', 'transmissionMap', 'thicknessMap'];

  P._track = function (obj) {
    if (!obj || typeof obj.dispose !== 'function') return obj;
    if (this._trackedSet) { if (this._trackedSet.has(obj)) return obj; this._trackedSet.add(obj); }  // dedupe shared handles
    this._disposables.push(obj);
    return obj;
  };
  // track a material and EVERY texture map it references (not just .map)
  P._trackMaterial = function (mat) {
    if (!mat) return;
    this._track(mat);
    for (var i = 0; i < TEX_KEYS.length; i++) { var t = mat[TEX_KEYS[i]]; if (t) this._track(t); }
  };
  // track a mesh's geometry + all its materials' textures
  P._trackMesh = function (mesh) {
    if (!mesh) return;
    this._track(mesh.geometry);
    var mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (var i = 0; i < mats.length; i++) this._trackMaterial(mats[i]);
  };

  // build the WebGL renderer/scene/camera/lights and arm the context-loss listener.
  // No GLB yet → state stays UNINITIALIZED (a scene without an avatar is NOT READY).
  P.init = function () {
    if (this.state === 'DISPOSED') return this;
    if (!this.THREE || !this.canvas) { this.state = 'FAILED'; this.error = 'three_or_canvas_missing'; return this; }
    var T = this.THREE, self = this;
    this.renderer = this._track(new T.WebGLRenderer({ canvas: this.canvas, antialias: this.quality !== 'low' }));
    this.scene = new T.Scene();
    this.camera = new T.PerspectiveCamera(28, 1, 0.1, 100);
    if (this.camera.position && this.camera.position.set) this.camera.position.set(0, 1.6, 1.4);   // head-and-shoulders framing
    var key = new T.DirectionalLight(0xffffff, 1.0); if (key.position && key.position.set) key.position.set(1, 2, 2);
    var fill = new T.AmbientLight(0x8090ff, 0.35);   // faint KAI-blue ambient
    this.scene.add(key); this.scene.add(fill);
    if (this.canvas.addEventListener) {
      // keep the bound ref so dispose() can removeEventListener (no retained renderer / cross-instance fire)
      this._ctxLostListener = function (e) { if (e && e.preventDefault) e.preventDefault(); self._onContextLost(); };
      this.canvas.addEventListener('webglcontextlost', this._ctxLostListener);
    }
    return this;
  };

  P._onContextLost = function () {
    if (this.state === 'DISPOSED') return;   // a disposed renderer never fires fallback
    if (this._contextLost) return;
    this._contextLost = true;
    this.error = 'webgl_context_lost';
    // truthfully fall back to the video avatar rather than showing a frozen/black GLB
    this.onFallback('webgl_context_lost');
  };

  // async load. onLoad(gltf)=success ONLY when a morph-bearing SkinnedMesh binds; onError → FAILED.
  P.load = function (url) {
    var self = this;
    if (this.state === 'DISPOSED') return Promise.reject(new Error('disposed'));
    if (!this.GLTFLoader) { this.state = 'FAILED'; this.error = 'loader_missing'; return Promise.reject(new Error('loader_missing')); }
    this.state = 'LOADING'; this.error = null;
    var loader = new this.GLTFLoader();
    return new Promise(function (resolve, reject) {
      loader.load(url,
        function (gltf) {
          // dispose() may have run while the loader was in flight — DISPOSED is terminal: bind,
          // dispose whatever it just created, and DO NOT resurrect state (no leak, no fake READY).
          if (self.state === 'DISPOSED') { try { self._bind(gltf); } catch (e) { /* ignore */ } self._disposeTracked(); return reject(new Error('disposed')); }
          try {
            self._bind(gltf);
            self.state = 'READY';                 // set READY only after a successful bind
            resolve(self);
          } catch (err) {
            self.state = 'FAILED'; self.error = String(err && err.message || err);
            reject(err);
          }
        },
        function () {},                            // progress (ignored)
        function (err) {
          if (self.state === 'DISPOSED') return reject(new Error('disposed'));   // don't rewrite DISPOSED → FAILED
          self.state = 'FAILED'; self.error = 'load_error'; reject(err || new Error('load_error'));
        }
      );
    });
  };

  // bind the registries + add to scene, tracking EVERY mesh's resources. Throws if the rig is
  // unusable so READY is NEVER set on a degenerate asset (§8 — no fake READY).
  P._bind = function (gltf) {
    var root = gltf && gltf.scene;
    if (!root) throw new Error('no_scene');
    var candidates = [], meshes = [], boneNames = [];
    root.traverse(function (o) {
      // a real morph mesh needs a NON-EMPTY dictionary + an influences array ({} and [] are both truthy)
      if (o.morphTargetDictionary && o.morphTargetInfluences && Object.keys(o.morphTargetDictionary).length > 0) candidates.push(o);
      if (o.geometry) meshes.push(o);
      if (o.isBone || o.type === 'Bone') boneNames.push(o.name);
    });
    if (!candidates.length) throw new Error('no_morph_mesh');   // no blendshapes → cannot lip-sync — refuse

    // choose the candidate that binds the MOST critical morphs (the real face, not a teeth/eyelash morph mesh)
    var best = null, bestReg = null, bestScore = -1;
    for (var i = 0; i < candidates.length; i++) {
      var reg = MR.buildMorphRegistry(candidates[i].morphTargetDictionary);
      var score = MR.CRITICAL_MORPHS.length - reg.missingCritical.length;
      if (score > bestScore) { bestScore = score; best = candidates[i]; bestReg = reg; }
    }
    if (bestScore <= 0) throw new Error('no_critical_morphs');   // binds no jaw/blink/mouth → not a usable face

    this.mesh = best;
    this.morphRegistry = bestReg;
    this.boneRegistry = MR.buildBoneRegistry(boneNames);
    if (this.scene && this.scene.add) { this.scene.add(root); this._root = root; }
    for (var j = 0; j < meshes.length; j++) this._trackMesh(meshes[j]);   // track ALL meshes, not just the face
  };

  // §11 invariant: the same coefficient frame the Lab uses drives the GLB morph influences.
  P.applyCoeffs = function (coeffs) {
    if (this.state !== 'READY' || !this.mesh) return false;   // truthful: no influence before a real bind
    MR.applyCoeffs(this.morphRegistry, coeffs || {}, this.mesh.morphTargetInfluences);
    return true;
  };

  // request a head pose / gaze target (clamped to plausible ranges); tick() eases toward it.
  P.setHeadTarget = function (yaw, pitch) {
    this._target.headYaw = _clamp(yaw || 0, -LIMITS.headYaw, LIMITS.headYaw);
    this._target.headPitch = _clamp(pitch || 0, -LIMITS.headPitch, LIMITS.headPitch);
  };
  P.setGazeTarget = function (x, y) {
    this._target.gazeX = _clamp(x || 0, -LIMITS.gazeX, LIMITS.gazeX);
    this._target.gazeY = _clamp(y || 0, -LIMITS.gazeY, LIMITS.gazeY);
  };

  // advance pose toward target under the velocity cap (no snapping); returns the eased pose.
  P.tick = function (dtMs) {
    var dt = Math.max(0, (dtMs || 0) / 1000);
    var p = this._pose, t = this._target;
    p.headYaw = approach(p.headYaw, t.headYaw, RATE.head, dt);
    p.headPitch = approach(p.headPitch, t.headPitch, RATE.head, dt);
    p.gazeX = approach(p.gazeX, t.gazeX, RATE.gaze, dt);
    p.gazeY = approach(p.gazeY, t.gazeY, RATE.gaze, dt);
    return { headYaw: p.headYaw, headPitch: p.headPitch, gazeX: p.gazeX, gazeY: p.gazeY };
  };

  P.getState = function () { return { state: this.state, error: this.error, morphsBound: this.morphRegistry ? this.morphRegistry.boundCount : 0, disposed: this._disposedCount, contextLost: this._contextLost }; };

  // dispose every tracked GPU resource exactly once + detach the scene root. Reused by the
  // dispose-during-load path, so it never changes state itself.
  P._disposeTracked = function () {
    for (var i = 0; i < this._disposables.length; i++) {
      try { this._disposables[i].dispose(); this._disposedCount++; } catch (e) { /* keep disposing the rest */ }
    }
    this._disposables = [];
    if (this._trackedSet) this._trackedSet.clear();
    if (this._root && this.scene && this.scene.remove) { try { this.scene.remove(this._root); } catch (e) { /* ignore */ } }
    this._root = null;
    return this._disposedCount;
  };

  // dispose every tracked GPU resource exactly once and go terminal.
  P.dispose = function () {
    if (this.state === 'DISPOSED') return this._disposedCount;
    this._disposeTracked();
    if (this._ctxLostListener && this.canvas && this.canvas.removeEventListener) {
      this.canvas.removeEventListener('webglcontextlost', this._ctxLostListener);   // no retained renderer / cross-instance fire
    }
    this._ctxLostListener = null;
    this.mesh = null; this.scene = null; this.camera = null; this.renderer = null; this.canvas = null;
    this.state = 'DISPOSED';
    return this._disposedCount;
  };

  return { KaiGLBRenderer: KaiGLBRenderer, STATES: STATES, LIMITS: LIMITS, RATE: RATE, approach: approach };
});
