// KAI Avatar — a real-time 3D head with AUDIO-DRIVEN LIP-SYNC.
//
// Unlike a pre-rendered video, a 3D head has morph targets (blendshapes) we can
// move every frame. The live TTS amplitude (fed via setVoiceLevel) drives the
// `jawOpen` morph, so the mouth physically opens on loud syllables and closes on
// pauses — genuine real-time lip-sync, no per-reply render, no delay.
//
// Loads ./kai_human.glb (your Ready Player Me avatar) if present, else falls back
// to ./kai_face.glb (a 52-blendshape ARKit demo head) so the engine always works.
// Morph names are matched across BOTH facecap (ARKit) and Ready Player Me.
//
// Public API (unchanged so command.js / kai-preview.js keep working):
//   new KaiAvatar(canvas[, {src}]); .start()/.stop(); .setSpeaking(b);
//   .setVoiceLevel(0..1); .pulseMouth(s); .setThinking(b); .setMood(name);
//   .setState({...}); .dispose()

import * as THREE from './three.module.js';
import { GLTFLoader } from './GLTFLoader.js';

const MOODS = {
  calm: '#35c6ff', focused: '#2f8bff', happy: '#22f0d6', alert: '#ffb347', critical: '#ff4d6d',
};

// Morph-target candidates — first match per mesh wins. Covers facecap's ARKit
// names AND Ready Player Me's ARKit/Oculus-viseme names.
const M_OPEN  = ['jawOpen', 'mouthOpen', 'viseme_aa', 'viseme_O', 'mouthFunnel'];
const M_WIDE  = ['mouthStretchLeft', 'mouthStretchRight', 'mouthStretch_L', 'mouthStretch_R', 'viseme_I'];
const M_SMILE = ['mouthSmileLeft', 'mouthSmileRight', 'mouthSmile_L', 'mouthSmile_R', 'mouthSmile', 'viseme_E'];
const M_BLINK = ['eyeBlinkLeft', 'eyeBlinkRight', 'eyeBlink_L', 'eyeBlink_R', 'eyesClosed'];

export class KaiAvatar {
  constructor(canvas, opts = {}) {
    this.canvas = canvas; this.opts = opts;
    this.running = false; this.ready = false;
    this.mood = 'calm'; this.speaking = false; this.thinking = false;
    this.voice = 0; this.jaw = 0;          // smoothed mouth opening
    this.blink = 0; this.blinkTimer = 1.5; this.blinkClose = 0;
    this.t = 0; this.look = { x: 0, y: 0 };
    this.meshes = [];                       // morph-capable meshes

    this.stage = (canvas && canvas.parentElement) || document.body;
    if (canvas) { canvas.style.display = 'block'; canvas.style.width = '100%'; canvas.style.height = '100%'; }

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(26, 1, 0.01, 100);
    this.camera.position.set(0, 0.02, 1.1);

    // Electric-blue key + cyan rim + warm fill — matches the dark-bright theme.
    this.scene.add(new THREE.AmbientLight(0x6c86c8, 0.75));
    this.key = new THREE.DirectionalLight(0xcfeaff, 2.1); this.key.position.set(0.7, 0.9, 1.5); this.scene.add(this.key);
    this.rim = new THREE.DirectionalLight(0x35c6ff, 1.6); this.rim.position.set(-1.1, 0.4, -0.9); this.scene.add(this.rim);
    this.fill = new THREE.PointLight(0x2f8bff, 7, 9); this.fill.position.set(0, -0.4, 1.3); this.scene.add(this.fill);

    this.head = new THREE.Group(); this.scene.add(this.head);

    this._load();
    this._onResize = () => this._resize(); window.addEventListener('resize', this._onResize, { passive: true });
    this._onPointer = (e) => {
      const r = this.stage.getBoundingClientRect(); if (!r.width) return;
      this.look.x = (e.clientX - r.left) / r.width - 0.5;
      this.look.y = (e.clientY - r.top) / r.height - 0.5;
    };
    window.addEventListener('pointermove', this._onPointer, { passive: true });
    this._resize();
    this.setMood('happy');   // newborn KAI — curious + happy by default
  }

  _load() {
    const loader = new GLTFLoader();
    const urls = [this.opts.src || './kai_human.glb', './kai_face.glb'];
    const attempt = (i) => {
      if (i >= urls.length) { this._fail(); return; }
      loader.load(urls[i],
        (gltf) => {
          const root = gltf.scene; this.head.add(root); this.model = root;
          root.traverse((o) => {
            if (o.isMesh) {
              o.frustumCulled = false;
              if (o.morphTargetDictionary && o.morphTargetInfluences) this.meshes.push(o);
              if (o.material) { o.material.envMapIntensity = 0.6; }
            }
          });
          this._frame(root);
          this.ready = true;
          this.loaded = urls[i];
        },
        undefined,
        () => attempt(i + 1),   // 404 / parse error → try the fallback face
      );
    };
    attempt(0);
  }

  // Center the model's bounding box at the origin, then frame a face-height
  // window. "Tall body" (a standing RPM export) is detected by ASPECT RATIO, not
  // absolute size — facecap is quantized to ~5×7 world units, so a size threshold
  // misfires. For a body we frame the top ~20% (the head); for a head/bust the
  // whole thing.
  _frame(root) {
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    root.position.sub(center);                              // bbox centered at origin
    const tallBody = size.y / Math.max(1e-4, size.x) > 1.7; // standing body vs. head/bust
    const faceH = tallBody ? size.y * 0.20 : size.y;
    const faceCenterY = tallBody ? size.y * 0.5 - faceH * 0.5 : 0;
    root.position.y -= faceCenterY;                         // bring the face to the origin
    const aspect = this.camera.aspect || 1;
    const winW = tallBody ? faceH * 0.8 : size.x;
    const halfH = Math.max(faceH, winW / aspect) * 0.5;
    const dist = halfH / Math.tan((this.camera.fov * Math.PI / 180) / 2) * 1.12 + size.z * 0.6;
    this.camera.position.set(0, 0, dist);
    this.camera.lookAt(0, 0, 0);
  }

  _setMorph(mesh, names, val) {
    const d = mesh.morphTargetDictionary, inf = mesh.morphTargetInfluences;
    for (const n of names) if (n in d) inf[d[n]] = val;
  }
  _applyMorphs() {
    const open = this.jaw;
    const smile = this.mood === 'happy' ? 0.30 + this.jaw * 0.15 : this.mood === 'calm' ? 0.10 : 0;
    for (const m of this.meshes) {
      this._setMorph(m, M_OPEN, open * 0.95);
      this._setMorph(m, M_WIDE, open * 0.22);
      this._setMorph(m, M_SMILE, smile);
      this._setMorph(m, M_BLINK, this.blink);
    }
  }

  _resize() {
    const w = this.stage.clientWidth || 640, h = this.stage.clientHeight || 480;
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  start() { if (this.running) return; this.running = true; this._loop(); }
  stop() { this.running = false; if (this._raf) cancelAnimationFrame(this._raf); }

  _loop() {
    if (!this.running) return;
    this._raf = requestAnimationFrame(() => this._loop());
    const dt = 0.016; this.t += dt;

    // Mouth: smooth the jaw toward the live voice level (snappy open, soft close).
    const targetJaw = this.speaking ? this.voice : 0;
    this.jaw += (targetJaw - this.jaw) * (targetJaw > this.jaw ? 0.6 : 0.35);

    // Blink: quick 0→1→0 envelope every few seconds.
    if (this.blinkClose > 0) {
      this.blinkClose -= dt;
      this.blink = Math.sin((1 - Math.max(0, this.blinkClose / 0.16)) * Math.PI);
      if (this.blinkClose <= 0) this.blink = 0;
    } else {
      this.blinkTimer -= dt;
      if (this.blinkTimer <= 0) { this.blinkClose = 0.16; this.blinkTimer = 2.4 + Math.random() * 3.4; }
    }

    // Head: idle sway + lean toward the cursor (KAI "looks at" you), gentle bob.
    if (this.model || this.meshes.length) {
      const idle = Math.sin(this.t * 0.8) * 0.05;
      const ty = this.look.x * 0.55 + idle;
      const tx = this.look.y * 0.32 + (this.thinking ? 0.06 : 0);
      this.head.rotation.y += (ty - this.head.rotation.y) * 0.06;
      this.head.rotation.x += (tx - this.head.rotation.x) * 0.06;
      this.head.position.y = Math.sin(this.t * 1.6) * 0.004;
    }

    this._applyMorphs();
    this.renderer.render(this.scene, this.camera);
  }

  setSpeaking(on) { this.speaking = !!on; if (!on) this.voice = 0; }
  setVoiceLevel(level) { this.voice = Math.max(0, Math.min(1, level || 0)); }
  pulseMouth(s) { this.voice = Math.max(this.voice, Math.min(1, s || 0.6)); }
  setThinking(on) { this.thinking = !!on; }
  setMood(name) {
    const c = MOODS[name] || MOODS.calm; this.mood = name;
    const col = new THREE.Color(c);
    if (this.rim) this.rim.color = col;
    if (this.fill) this.fill.color = col;
  }
  setState({ securityScore = null, alerts = 0, plansActive = 0, mood = null } = {}) {
    if (mood && MOODS[mood]) { this.setMood(mood); return; }
    let n = 'happy';
    if (securityScore != null && securityScore < 40) n = 'critical';
    else if (alerts >= 3) n = 'alert';
    else if (alerts >= 1 || plansActive >= 1) n = 'focused';
    this.setMood(n);
  }

  _fail() {
    const s = this.stage; if (!s) return;
    const d = document.createElement('div');
    d.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#8295bf;text-align:center;padding:24px;font-size:14px;line-height:1.5;';
    d.textContent = 'Avatar model failed to load. (WebGL or the .glb is unavailable.) Voice + dashboard still work.';
    s.appendChild(d);
  }
  dispose() {
    this.stop();
    window.removeEventListener('resize', this._onResize);
    window.removeEventListener('pointermove', this._onPointer);
    try { this.renderer.dispose(); } catch (_) {}
  }
}
