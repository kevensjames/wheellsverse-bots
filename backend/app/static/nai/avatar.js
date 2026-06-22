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
          this.loaded = urls[i];
          // Give the loaded head a metallic android finish + glowing blue eyes so
          // KAI reads as a robot. (No ready-made robot head lip-syncs, so we chrome
          // a morph-capable human head.) Pass {keepMaterials:true} to skip.
          if (!this.opts.keepMaterials) this._robotize();
          this.ready = true;
        },
        undefined,
        () => attempt(i + 1),   // 404 / parse error → try the fallback face
      );
    };
    attempt(0);
  }

  // World-space bbox from raw vertex positions × world matrix. Unlike
  // Box3.setFromObject, this is correct for SKINNED meshes (whose head verts a
  // rig places far from the model origin) and for quantized meshes (facecap).
  _worldBox(obj) {
    obj.updateWorldMatrix(true, true);
    const min = new THREE.Vector3(1e9, 1e9, 1e9), max = new THREE.Vector3(-1e9, -1e9, -1e9);
    const v = new THREE.Vector3();
    obj.traverse((o) => {
      const p = o.isMesh && o.geometry && o.geometry.attributes.position;
      if (!p) return;
      const step = Math.max(1, Math.floor(p.count / 1500));
      for (let i = 0; i < p.count; i += step) { v.fromBufferAttribute(p, i).applyMatrix4(o.matrixWorld); min.min(v); max.max(v); }
    });
    return new THREE.Box3(min, max);
  }

  // Frame the HEAD as a portrait. Humanoid avatars (RPM/Avaturn) have a
  // 'Head'-named mesh — frame just that, so a full body / T-pose doesn't shrink
  // the face. A bare head (facecap, no 'head' name) frames the whole model.
  _frame(root) {
    let headObj = null;
    root.traverse((o) => { if (o.isMesh && !headObj && /head/i.test(o.name || '')) headObj = o; });
    const fitObj = headObj || root;
    const box = this._worldBox(fitObj);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    this._size = size.clone();
    root.position.sub(center);                              // head centered at origin
    const aspect = this.camera.aspect || 1;
    const margin = 1.22;                                    // tight portrait — crop neck/shoulders
    const halfH = Math.max(size.y, size.x / aspect) * 0.5 * margin;
    const dist = halfH / Math.tan((this.camera.fov * Math.PI / 180) / 2) + size.z * 0.6;
    this.camera.position.set(0, 0, dist);
    this.camera.lookAt(0, 0, 0);
  }

  // Turn a human head into a metallic android: chrome the skin/hair/body, and
  // make real eye meshes glow blue. Works for facecap (1 mesh → add eye spheres)
  // and for RPM/Avaturn (separate Wolf3D_Eye meshes → glow them in place).
  _robotize() {
    let foundEyes = false;
    const target = this.model || { traverse: (f) => this.meshes.forEach(f) };
    target.traverse((o) => {
      if (!o.isMesh) return;
      const n = (o.name || '').toLowerCase();
      const isEye = n.includes('eye') && !n.includes('eyelash') && !n.includes('brow');
      o.material = new THREE.MeshStandardMaterial(isEye
        ? { color: 0xbff0ff, emissive: 0x35c6ff, emissiveIntensity: 2.6, metalness: 0, roughness: 0.15 }
        : { color: 0x2b3a4d, metalness: 0.92, roughness: 0.36, emissive: 0x0c2742, emissiveIntensity: 0.4 });
      if (isEye) foundEyes = true;
    });
    if (foundEyes) return;     // real eye meshes glowing → no need for spheres
    const s = this._size || new THREE.Vector3(5, 7, 7);
    const r = Math.max(s.x, s.y) * 0.038;
    const geo = new THREE.SphereGeometry(r, 24, 24);
    const eyeMat = new THREE.MeshStandardMaterial({
      color: 0xbff0ff, emissive: 0x35c6ff, emissiveIntensity: 2.8, metalness: 0, roughness: 0.15,
    });
    this.eyes = [];
    for (const sx of [-1, 1]) {
      const e = new THREE.Mesh(geo, eyeMat);
      e.position.set(sx * s.x * 0.118, s.y * 0.045, s.z * 0.255);
      this.head.add(e); this.eyes.push(e);
    }
  }

  _setMorph(mesh, names, val) {
    const d = mesh.morphTargetDictionary, inf = mesh.morphTargetInfluences;
    for (const n of names) if (n in d) inf[d[n]] = val;
  }
  // Set ONLY the first available morph (avatars with both jawOpen + mouthOpen
  // would double-open the mouth into a gape if we set both).
  _setFirst(mesh, names, val) {
    const d = mesh.morphTargetDictionary, inf = mesh.morphTargetInfluences;
    for (const n of names) if (n in d) { inf[d[n]] = val; return; }
  }
  _applyMorphs() {
    const open = this.jaw;
    const smile = this.mood === 'happy' ? 0.26 + this.jaw * 0.12 : this.mood === 'calm' ? 0.08 : 0;
    for (const m of this.meshes) {
      this._setFirst(m, M_OPEN, open * 0.78);   // jaw drop tracks the voice
      this._setMorph(m, M_WIDE, open * 0.16);
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
