// KAI Avatar — a REAL human face (photo-captured scan) rendered in Three.js.
//
// Loads a vendored GLB (facecap, a real face scan with 52 ARKit blendshapes +
// separate eye meshes) so KAI reads as a human, not a primitive robot. The
// scan's KTX2 photo-texture is stripped at build time (CSP blocks the basis
// worker); we apply a skin material + glowing blue eyes in code. Geometry +
// morphs (jawOpen / eyeBlink_* / eyeLook_* / mouth*) are real, driving genuine
// lip-sync, blinking, and eye darts.
//
// Self-contained / CSP-safe: three.module.js, GLTFLoader.js,
// meshopt_decoder.module.js and kai_face.glb are all vendored same-origin
// (no CDN, no import map, no basis worker).
//
// Public API (unchanged — command.js drives these):
//   new KaiAvatar(canvas); .start()/.stop(); .setSpeaking(b); .pulseMouth(s);
//   .setThinking(b); .setMood(name); .setState({securityScore,alerts,plansActive,mood}); .dispose()

import * as THREE from './three.module.js';
import { GLTFLoader } from './GLTFLoader.js';
import { MeshoptDecoder } from './meshopt_decoder.module.js';

const MOODS = {
  calm:     { eye: 0x35c6ff, aura: 0x2f7bff, energy: 0.55 },
  focused:  { eye: 0x2f8bff, aura: 0x2f7bff, energy: 0.85 },
  happy:    { eye: 0x22f0d6, aura: 0x18d6ff, energy: 1.0 },
  alert:    { eye: 0x8fb4ff, aura: 0xffb347, energy: 1.15 },
  critical: { eye: 0xff5d7a, aura: 0xff2d55, energy: 1.4 },
};
const lerp = (a, b, t) => a + (b - a) * t;
const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

export class KaiAvatar {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.opts = opts;
    this.running = false;
    this._raf = 0;
    this._t = 0;
    this._lastTs = 0;
    this.ready = false;

    this.speaking = false;
    this.thinking = false;
    this.mouthOpen = 0;
    this.mouthTarget = 0;
    this.blinkT = 2 + Math.random() * 3;
    this.blink = 0;
    this.energy = 0.6;
    this.energyTarget = 0.6;
    this.look = { x: 0, y: 0, tx: 0, ty: 0, idle: 0 };

    this.dict = null;       // morphTargetDictionary
    this.infl = null;       // morphTargetInfluences
    this.eyeMats = [];      // eyeball materials (tinted by mood)
    this.curEye = new THREE.Color(MOODS.calm.eye);
    this.tgtEye = new THREE.Color(MOODS.calm.eye);
    this.curAura = new THREE.Color(MOODS.calm.aura);
    this.tgtAura = new THREE.Color(MOODS.calm.aura);

    this._initRenderer();
    this._buildEnv();
    this._load();
    this._bindEvents();
    this._onResize();
  }

  _initRenderer() {
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: true, alpha: true, powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(28, 1, 0.01, 100);
    this.camera.position.set(0, 0, 3);
  }

  _buildEnv() {
    // 3-point lighting for lifelike skin (no env map needed).
    this.scene.add(new THREE.HemisphereLight(0xeaf2ff, 0x202634, 0.85));
    const key = new THREE.DirectionalLight(0xfff4e8, 2.0);
    key.position.set(1.5, 1.8, 2.2);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x9fc0ff, 0.9);
    fill.position.set(-2.2, 0.2, 1.2);
    this.scene.add(fill);
    const rim = new THREE.DirectionalLight(0x3f7bff, 1.6);
    rim.position.set(-0.5, 1.2, -2.5);
    this.scene.add(rim);

    // soft mood aura behind the head + ground glow
    this.haloMat = new THREE.MeshBasicMaterial({
      color: MOODS.calm.aura, transparent: true, opacity: 0.16,
      side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    this.halo = new THREE.Mesh(new THREE.SphereGeometry(2.4, 32, 32), this.haloMat);
    this.halo.position.set(0, 0, -1.2);
    this.scene.add(this.halo);
  }

  _load() {
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    const onLoad = (gltf) => {
      try { this._setup(gltf.scene); } catch (e) { console.error('[KAI avatar] setup failed', e); this._fallback = String(e); }
    };
    const onErr = (e) => { console.error('[KAI avatar] GLB load failed', e); this._fallback = 'load failed'; };
    const go = () => loader.load('./kai_face.glb', onLoad, undefined, onErr);
    // meshopt geometry needs the decoder ready first
    if (MeshoptDecoder && MeshoptDecoder.ready && typeof MeshoptDecoder.ready.then === 'function') {
      MeshoptDecoder.ready.then(go).catch(go);
    } else { go(); }
  }

  _setup(root) {
    this.model = root;

    root.traverse((o) => {
      if (o.isMesh || o.isSkinnedMesh) {
        // the GLB's eye meshes are unnamed — read up the node chain (eyeLeft /
        // grp_eyeLeft) so we can recolour just the eyes.
        const names = [];
        for (let p = o, i = 0; p && i < 3; p = p.parent, i++) if (p.name) names.push(p.name);
        const nm = names.join(' ').toLowerCase();
        if (o.morphTargetDictionary && o.morphTargetInfluences) {
          this.dict = o.morphTargetDictionary;
          this.infl = o.morphTargetInfluences;
        }
        if (nm.includes('eye') && !nm.includes('lash') && !nm.includes('brow')) {
          // glowing blue eyes (the scan has no separate iris, so the whole
          // eyeball reads as KAI's signature blue)
          const m = new THREE.MeshStandardMaterial({
            color: 0x0a2a55, emissive: new THREE.Color(MOODS.calm.eye),
            emissiveIntensity: 1.1, metalness: 0.1, roughness: 0.25,
          });
          o.material = m;
          this.eyeMats.push(m);
        } else if (nm.includes('teeth')) {
          o.material = new THREE.MeshStandardMaterial({ color: 0xeceff5, roughness: 0.5, metalness: 0 });
        } else {
          // skin: warm matte, slight translucency feel via low metalness
          o.material = new THREE.MeshStandardMaterial({
            color: 0xd8b39a, roughness: 0.62, metalness: 0.0,
          });
        }
      }
    });

    // center + frame the head
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    root.position.sub(center);                       // center at origin
    // Frame the head to fill ~80% of the viewport height.
    const fovRad = (this.camera.fov * Math.PI) / 180;
    const dist = (size.y / 2) / Math.tan(fovRad / 2) * 1.25;
    this.camera.position.set(0, 0, dist);
    this.camera.lookAt(0, 0, 0);
    this._baseY = root.position.y;

    this.scene.add(root);
    this.ready = true;
  }

  _setMorph(name, v) {
    if (!this.dict || !this.infl) return;
    const i = this.dict[name];
    if (i !== undefined) this.infl[i] = v;
  }

  _bindEvents() {
    this._onPointer = (e) => {
      const r = this.canvas.getBoundingClientRect();
      if (!r.width) return;
      this.look.tx = ((e.clientX - r.left) / r.width) * 2 - 1;
      this.look.ty = ((e.clientY - r.top) / r.height) * 2 - 1;
      this.look.idle = 0;
    };
    window.addEventListener('pointermove', this._onPointer, { passive: true });
    this._onResizeBound = () => this._onResize();
    window.addEventListener('resize', this._onResizeBound);
  }

  _onResize() {
    const w = this.canvas.clientWidth || this.canvas.parentElement?.clientWidth || 0;
    const h = this.canvas.clientHeight || this.canvas.parentElement?.clientHeight || 0;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  // ── public controls ─────────────────────────────────────────
  setSpeaking(on) { this.speaking = !!on; if (!on) this.mouthTarget = 0; }
  pulseMouth(s = 1) { this.mouthTarget = Math.max(this.mouthTarget, 0.5 + 0.5 * clamp01(s)); }
  setThinking(on) { this.thinking = !!on; }
  setMood(name) {
    const m = MOODS[name] || MOODS.calm;
    this.tgtEye.set(m.eye);
    this.tgtAura.set(m.aura);
    this.energyTarget = m.energy;
    this.mood = name;
  }
  setState({ securityScore = null, alerts = 0, plansActive = 0, mood = null } = {}) {
    if (mood && MOODS[mood]) { this.setMood(mood); return; }
    let name = 'calm';
    if (securityScore != null && securityScore < 40) name = 'critical';
    else if (alerts >= 3) name = 'alert';
    else if (alerts >= 1 || plansActive >= 1) name = 'focused';
    this.setMood(name);
    this.energyTarget += Math.min(alerts, 6) * 0.05;
  }

  // ── loop ─────────────────────────────────────────────────────
  start() {
    if (this.running) return;
    this.running = true;
    this._lastTs = performance.now();
    const loop = (ts) => {
      if (!this.running) return;
      this._raf = requestAnimationFrame(loop);
      const dt = Math.min((ts - this._lastTs) / 1000, 0.05);
      this._lastTs = ts;
      this._update(dt);
    };
    this._raf = requestAnimationFrame(loop);
  }
  stop() { this.running = false; if (this._raf) cancelAnimationFrame(this._raf); this._raf = 0; }

  _update(dt) {
    this._t += dt;
    const t = this._t;
    if (this.canvas.clientWidth &&
        Math.abs(this.canvas.width / (window.devicePixelRatio || 1) - this.canvas.clientWidth) > 2) {
      this._onResize();
    }
    if (!this.canvas.clientWidth) return;

    // mood colour lerp
    this.curEye.lerp(this.tgtEye, clamp01(dt * 2.5));
    this.curAura.lerp(this.tgtAura, clamp01(dt * 2.5));
    this.energy = lerp(this.energy, this.energyTarget, clamp01(dt * 2));
    for (const m of this.eyeMats) m.emissive.copy(this.curEye);
    if (this.haloMat) { this.haloMat.color.copy(this.curAura); this.haloMat.opacity = 0.12 + this.energy * 0.06; }

    if (this.ready && this.model) {
      // head-look (idle drift when no pointer)
      this.look.idle += dt;
      if (this.look.idle > 2.5) { this.look.tx = Math.sin(t * 0.35) * 0.55; this.look.ty = Math.sin(t * 0.27) * 0.3; }
      this.look.x = lerp(this.look.x, this.look.tx, clamp01(dt * 3));
      this.look.y = lerp(this.look.y, this.look.ty, clamp01(dt * 3));
      const nod = this.speaking ? Math.sin(t * 9) * 0.02 : 0;
      this.model.rotation.y = this.look.x * 0.42;
      this.model.rotation.x = -this.look.y * 0.26 + nod;
      // breathing
      this.model.position.y = this._baseY + Math.sin(t * 1.1) * 0.004;

      // eye darts via eyeLook morphs (subtle, follows gaze)
      const lx = clamp01(this.look.x), rx = clamp01(-this.look.x);
      this._setMorph('eyeLookOut_L', lx); this._setMorph('eyeLookIn_R', lx);
      this._setMorph('eyeLookOut_R', rx); this._setMorph('eyeLookIn_L', rx);

      // blink
      this.blinkT -= dt;
      if (this.blinkT <= 0) { this.blink = 1; this.blinkT = 2.5 + Math.random() * 4; }
      this.blink = Math.max(0, this.blink - dt * 9);
      this._setMorph('eyeBlink_L', this.blink);
      this._setMorph('eyeBlink_R', this.blink);

      // speaking → jaw + mouth shapes
      if (this.speaking) {
        this.mouthTarget = lerp(this.mouthTarget, 0.25 + Math.abs(Math.sin(t * 12)) * 0.6, clamp01(dt * 12));
      } else {
        this.mouthTarget = lerp(this.mouthTarget, 0, clamp01(dt * 7));
      }
      this.mouthOpen = lerp(this.mouthOpen, this.mouthTarget, clamp01(dt * 18));
      this._setMorph('jawOpen', this.mouthOpen * 0.7);
      this._setMorph('mouthFunnel', this.mouthOpen * 0.18);

      // thinking → tiny brow raise pulse
      const think = this.thinking ? (0.4 + Math.abs(Math.sin(t * 6)) * 0.4) : 0;
      this._setMorph('browInnerUp', think);
      for (const m of this.eyeMats) m.emissiveIntensity = 1.0 + (this.thinking ? Math.abs(Math.sin(t * 8)) * 0.8 : Math.sin(t * 2) * 0.15);
    }

    // aura pulse
    if (this.halo) this.halo.scale.setScalar(1 + Math.sin(t * 1.6) * 0.02 * this.energy);

    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.stop();
    window.removeEventListener('pointermove', this._onPointer);
    window.removeEventListener('resize', this._onResizeBound);
    this.scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
    });
    this.renderer.dispose();
  }
}
