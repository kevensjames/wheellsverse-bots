// KAI Avatar — a procedural HUMANOID android "body" rendered in Three.js.
//
// A robot that reads as human: a sculpted head (cranium, brow, nose, cheeks,
// lips), real eyes (white sclera + glowing blue iris + pupil) that blink, and a
// hinged jaw that opens while speaking. Android styling — light face panels,
// dark under-structure, temple sensors, a glowing chest core.
//
// Self-contained: imports a vendored three.module.js by relative path (no CDN,
// no addons, no import map) so it satisfies the daemon's CSP (script-src 'self')
// and works offline. Core primitives only.
//
// Public API (called by command.js):
//   new KaiAvatar(canvasEl); .start()/.stop(); .setSpeaking(b); .pulseMouth(s);
//   .setThinking(b); .setMood(name); .setState({securityScore,alerts,plansActive,mood}); .dispose()

import * as THREE from './three.module.js';

// Mood → palette (drives the iris, chest core, aura, particles).
const MOODS = {
  calm:     { primary: 0x35c6ff, accent: 0x2f7bff, energy: 0.55 },
  focused:  { primary: 0x2f8bff, accent: 0x2f7bff, energy: 0.85 },
  happy:    { primary: 0x22f0d6, accent: 0x18d6ff, energy: 1.0 },
  alert:    { primary: 0xffb347, accent: 0xff7b3d, energy: 1.15 },
  critical: { primary: 0xff4d6d, accent: 0xff2d55, energy: 1.4 },
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

    this.speaking = false;
    this.thinking = false;
    this.mouthOpen = 0;
    this.mouthTarget = 0;
    this.blinkT = 2 + Math.random() * 3;
    this.blink = 0;
    this.energy = 0.6;
    this.energyTarget = 0.6;

    this.look = { x: 0, y: 0, tx: 0, ty: 0, idle: 0 };

    this.curColor = new THREE.Color(MOODS.calm.primary);
    this.targetColor = new THREE.Color(MOODS.calm.primary);
    this.curAccent = new THREE.Color(MOODS.calm.accent);
    this.targetAccent = new THREE.Color(MOODS.calm.accent);

    this._initRenderer();
    this._buildScene();
    this._bindEvents();
    this._onResize();
  }

  _initRenderer() {
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: true, alpha: true, powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
    this.camera.position.set(0, 0.02, 5.6);   // framed on the face
    this.camera.lookAt(0, 0.02, 0);
  }

  _glow(color, size, opacity = 0.5) {
    return new THREE.Mesh(
      new THREE.CircleGeometry(size, 32),
      new THREE.MeshBasicMaterial({
        color, transparent: true, opacity,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }),
    );
  }

  _buildScene() {
    const scene = this.scene;

    // ── Lighting (bright enough that the FACE reads) ─────────
    scene.add(new THREE.HemisphereLight(0xdfeaff, 0x141822, 0.95));
    const key = new THREE.DirectionalLight(0xffffff, 1.55);
    key.position.set(2.2, 2.6, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xa9c4ff, 0.8);
    fill.position.set(-3, 0.5, 2.5);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0x2f6bff, 1.5);
    rim.position.set(-2, 1.5, -3);
    scene.add(rim);
    this.eyeLightL = new THREE.PointLight(MOODS.calm.primary, 1.3, 4);
    this.eyeLightR = new THREE.PointLight(MOODS.calm.primary, 1.3, 4);
    scene.add(this.eyeLightL, this.eyeLightR);

    // ── Materials ────────────────────────────────────────────
    this.skinMat = new THREE.MeshStandardMaterial({ color: 0xc7d2e6, metalness: 0.1, roughness: 0.72 });
    const panelMat = new THREE.MeshStandardMaterial({ color: 0x8d9bb8, metalness: 0.6, roughness: 0.45 });
    const darkMat = new THREE.MeshStandardMaterial({ color: 0x121a2c, metalness: 0.85, roughness: 0.4 });
    const lipMat = new THREE.MeshStandardMaterial({ color: 0x9aa6c0, metalness: 0.4, roughness: 0.5 });
    const scleraMat = new THREE.MeshStandardMaterial({ color: 0xf2f6ff, metalness: 0.0, roughness: 0.3 });
    this.irisMat = new THREE.MeshStandardMaterial({
      color: 0x0a1422, emissive: new THREE.Color(MOODS.calm.primary), emissiveIntensity: 3.2,
      metalness: 0.2, roughness: 0.25,
    });
    const pupilMat = new THREE.MeshBasicMaterial({ color: 0x04070d });
    this.chestMat = new THREE.MeshStandardMaterial({
      color: 0x0a0f1a, emissive: new THREE.Color(MOODS.calm.accent), emissiveIntensity: 2.8,
      metalness: 0.4, roughness: 0.3,
    });
    this.seamMat = new THREE.MeshStandardMaterial({
      color: 0x0a0f1a, emissive: new THREE.Color(MOODS.calm.accent), emissiveIntensity: 1.2,
    });

    this.robot = new THREE.Group();
    scene.add(this.robot);

    // ── Head group (turns toward the user) ───────────────────
    this.head = new THREE.Group();
    this.robot.add(this.head);

    // cranium / face — an egg-shaped skull (human proportions)
    const skull = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 40), this.skinMat);
    skull.scale.set(0.82, 0.96, 0.9);
    this.head.add(skull);
    // narrower lower face / cheeks → jaw taper
    const midFace = new THREE.Mesh(new THREE.SphereGeometry(1, 40, 32), this.skinMat);
    midFace.scale.set(0.7, 0.55, 0.82);
    midFace.position.y = -0.42;
    this.head.add(midFace);

    // scalp / helmet panel (reads as "robot")
    const scalp = new THREE.Mesh(new THREE.SphereGeometry(1.0, 40, 32, 0, Math.PI * 2, 0, Math.PI * 0.55), panelMat);
    scalp.scale.set(0.86, 0.98, 0.94);
    scalp.position.y = 0.06;
    this.head.add(scalp);
    // forehead sensor seam
    const browSeam = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.025, 0.03), this.seamMat);
    browSeam.position.set(0, 0.34, 0.84);
    this.head.add(browSeam);

    // brow ridge
    const brow = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.1, 0.22), this.skinMat);
    brow.position.set(0, 0.2, 0.7);
    brow.rotation.x = -0.12;
    this.head.add(brow);

    // ── Eyes (sclera + glowing blue iris + pupil), blink-able ─
    this.eyeGroups = [];
    this.eyeGlows = [];
    for (const ex of [-0.3, 0.3]) {
      const g = new THREE.Group();
      g.position.set(ex, 0.12, 0.6);
      const sclera = new THREE.Mesh(new THREE.SphereGeometry(0.17, 28, 24), scleraMat);
      sclera.scale.set(1, 0.78, 0.8);
      g.add(sclera);
      const iris = new THREE.Mesh(new THREE.SphereGeometry(0.085, 24, 20), this.irisMat);
      iris.position.set(0, 0, 0.12);
      g.add(iris);
      const pupil = new THREE.Mesh(new THREE.CircleGeometry(0.035, 20), pupilMat);
      pupil.position.set(0, 0, 0.2);
      g.add(pupil);
      const glow = this._glow(MOODS.calm.primary, 0.16, 0.4);
      glow.position.set(0, 0, 0.16);
      g.add(glow);
      this.eyeGlows.push(glow);
      // upper lid (skin) that drops on blink
      const lid = new THREE.Mesh(new THREE.SphereGeometry(0.185, 24, 16, 0, Math.PI * 2, 0, Math.PI * 0.5), this.skinMat);
      lid.scale.set(1, 0.8, 0.85);
      lid.position.set(0, 0.02, 0);
      g.add(lid);
      this.head.add(g);
      this.eyeGroups.push({ g, lid });
    }
    this.eyeLightL.position.set(-0.3, 0.12, 0.9);
    this.eyeLightR.position.set(0.3, 0.12, 0.9);

    // ── Nose (bridge + tip) ──────────────────────────────────
    const noseBridge = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.34, 0.16), this.skinMat);
    noseBridge.position.set(0, 0.0, 0.76);
    noseBridge.rotation.x = 0.2;
    this.head.add(noseBridge);
    const noseTip = new THREE.Mesh(new THREE.SphereGeometry(0.085, 20, 16), this.skinMat);
    noseTip.scale.set(1, 0.8, 0.9);
    noseTip.position.set(0, -0.16, 0.86);
    this.head.add(noseTip);

    // ── Mouth: fixed upper lip + hinged JAW (opens to speak) ──
    const mouthCavity = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.22, 0.12), darkMat);
    mouthCavity.position.set(0, -0.46, 0.66);
    this.head.add(mouthCavity);
    const upperLip = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.06, 0.12), lipMat);
    upperLip.position.set(0, -0.4, 0.76);
    this.head.add(upperLip);

    this.jaw = new THREE.Group();
    this.jaw.position.set(0, -0.3, -0.1);     // hinge near the ears
    this.head.add(this.jaw);
    const chin = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 24), this.skinMat);
    chin.scale.set(0.6, 0.36, 0.62);
    chin.position.set(0, -0.34, 0.28);
    this.jaw.add(chin);
    const lowerLip = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.07, 0.12), lipMat);
    lowerLip.position.set(0, -0.2, 0.86);
    this.jaw.add(lowerLip);

    // ── Cheeks (soft volume) ─────────────────────────────────
    for (const cx of [-0.42, 0.42]) {
      const cheek = new THREE.Mesh(new THREE.SphereGeometry(0.26, 20, 16), this.skinMat);
      cheek.scale.set(0.9, 0.7, 0.6);
      cheek.position.set(cx, -0.12, 0.62);
      this.head.add(cheek);
    }

    // ── Ears + temple sensors (the "robot" tell) ─────────────
    for (const ex of [-0.82, 0.82]) {
      const ear = new THREE.Mesh(new THREE.SphereGeometry(0.16, 18, 14), panelMat);
      ear.scale.set(0.5, 0.9, 0.7);
      ear.position.set(ex, -0.02, 0.06);
      this.head.add(ear);
      const temple = new THREE.Mesh(new THREE.TorusGeometry(0.07, 0.022, 12, 20), this.seamMat);
      temple.position.set(ex * 0.92, 0.16, 0.34);
      temple.rotation.y = ex < 0 ? -0.5 : 0.5;
      this.head.add(temple);
    }

    // ── Neck ─────────────────────────────────────────────────
    const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.34, 0.6, 24), panelMat);
    neck.position.y = -1.02;
    this.robot.add(neck);
    const collar = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.5, 0.18, 24), darkMat);
    collar.position.y = -1.28;
    this.robot.add(collar);

    // ── Torso / shoulders + glowing chest core ───────────────
    const torso = new THREE.Group();
    torso.position.y = -2.05;
    this.robot.add(torso);
    const chestPlate = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 24), panelMat);
    chestPlate.scale.set(1.25, 0.85, 0.7);
    chestPlate.position.y = 0.2;
    torso.add(chestPlate);
    for (const sx of [-1.15, 1.15]) {
      const sh = new THREE.Mesh(new THREE.SphereGeometry(0.5, 22, 18), panelMat);
      sh.scale.set(1, 0.8, 0.9);
      sh.position.set(sx, 0.42, 0);
      torso.add(sh);
    }
    const coreRing = new THREE.Mesh(new THREE.TorusGeometry(0.3, 0.06, 16, 40), this.chestMat);
    coreRing.position.set(0, 0.22, 0.52);
    torso.add(coreRing);
    this.chestCore = new THREE.Mesh(new THREE.CircleGeometry(0.22, 36), this.chestMat);
    this.chestCore.position.set(0, 0.22, 0.53);
    torso.add(this.chestCore);
    this.chestGlow = this._glow(MOODS.calm.accent, 0.45, 0.4);
    this.chestGlow.position.set(0, 0.22, 0.48);
    torso.add(this.chestGlow);

    // ── Aura: halo shell + floor glow + particle field ───────
    this.haloMat = new THREE.MeshBasicMaterial({
      color: MOODS.calm.primary, transparent: true, opacity: 0.05,
      side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    this.halo = new THREE.Mesh(new THREE.SphereGeometry(3.1, 32, 32), this.haloMat);
    scene.add(this.halo);
    this.glowDisc = new THREE.Mesh(
      new THREE.CircleGeometry(2.6, 48),
      new THREE.MeshBasicMaterial({
        color: MOODS.calm.accent, transparent: true, opacity: 0.07,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }),
    );
    this.glowDisc.position.set(0, -0.2, -1.6);
    scene.add(this.glowDisc);
    this._buildParticles();
  }

  _buildParticles() {
    const N = 280;
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      const r = 2.2 + Math.random() * 1.6;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
      pos[i * 3 + 1] = r * Math.cos(ph) * 0.85;
      pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th) - 0.5;
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.particleMat = new THREE.PointsMaterial({
      color: MOODS.calm.primary, size: 0.034, transparent: true, opacity: 0.7,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    this.particles = new THREE.Points(geo, this.particleMat);
    this.scene.add(this.particles);
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

  // ── expressive controls ────────────────────────────────────
  setSpeaking(on) { this.speaking = !!on; if (!on) this.mouthTarget = 0; }
  pulseMouth(strength = 1) { this.mouthTarget = Math.max(this.mouthTarget, 0.5 + 0.5 * clamp01(strength)); }
  setThinking(on) { this.thinking = !!on; }

  setMood(name) {
    const m = MOODS[name] || MOODS.calm;
    this.targetColor.set(m.primary);
    this.targetAccent.set(m.accent);
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

  // ── render loop ────────────────────────────────────────────
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

    // colour lerp (mood)
    this.curColor.lerp(this.targetColor, clamp01(dt * 2.5));
    this.curAccent.lerp(this.targetAccent, clamp01(dt * 2.5));
    this.energy = lerp(this.energy, this.energyTarget, clamp01(dt * 2));
    this.irisMat.emissive.copy(this.curColor);
    this.chestMat.emissive.copy(this.curAccent);
    this.seamMat.emissive.copy(this.curAccent);
    this.eyeLightL.color.copy(this.curColor);
    this.eyeLightR.color.copy(this.curColor);
    this.haloMat.color.copy(this.curColor);
    this.particleMat.color.copy(this.curColor);
    for (const g of this.eyeGlows) g.material.color.copy(this.curColor);
    this.chestGlow.material.color.copy(this.curAccent);

    // breathing + sway
    this.robot.position.y = Math.sin(t * 1.1) * 0.03;
    this.robot.rotation.z = Math.sin(t * 0.5) * 0.01;

    // head-look (idle drift when no pointer)
    this.look.idle += dt;
    if (this.look.idle > 2.5) {
      this.look.tx = Math.sin(t * 0.35) * 0.5;
      this.look.ty = Math.sin(t * 0.27) * 0.25;
    }
    this.look.x = lerp(this.look.x, this.look.tx, clamp01(dt * 3));
    this.look.y = lerp(this.look.y, this.look.ty, clamp01(dt * 3));
    const nod = this.speaking ? Math.sin(t * 9) * 0.025 : 0;
    this.head.rotation.y = this.look.x * 0.45;
    this.head.rotation.x = this.look.y * 0.28 + nod;

    // blink (drop the lids + squash the eyes)
    this.blinkT -= dt;
    if (this.blinkT <= 0) { this.blink = 1; this.blinkT = 2.5 + Math.random() * 4; }
    this.blink = Math.max(0, this.blink - dt * 8);
    for (const { g, lid } of this.eyeGroups) {
      g.scale.y = 1 - this.blink * 0.85;
      lid.rotation.x = this.blink * 1.2;
    }

    // iris brightness (spikes while thinking)
    const think = this.thinking ? (1.4 + Math.sin(t * 12) * 0.6) : 1;
    this.irisMat.emissiveIntensity = (2.8 + Math.sin(t * 2) * 0.4) * think;
    this.eyeLightL.intensity = this.eyeLightR.intensity = 1.1 * think;
    for (const g of this.eyeGlows) g.material.opacity = (0.32 + Math.sin(t * 2) * 0.08) * think;

    // mouth → JAW open
    if (this.speaking) {
      this.mouthTarget = lerp(this.mouthTarget, 0.35 + Math.abs(Math.sin(t * 12)) * 0.55, clamp01(dt * 10));
    } else {
      this.mouthTarget = lerp(this.mouthTarget, 0, clamp01(dt * 6));
    }
    this.mouthOpen = lerp(this.mouthOpen, this.mouthTarget, clamp01(dt * 16));
    this.jaw.rotation.x = this.mouthOpen * 0.42;

    // chest core + aura
    const pulse = 0.7 + Math.sin(t * 2.2) * 0.3 * this.energy;
    this.chestMat.emissiveIntensity = 2.0 + pulse * 1.4;
    this.chestCore.scale.setScalar(0.96 + pulse * 0.08);
    this.chestGlow.material.opacity = 0.3 + pulse * 0.18;
    this.chestGlow.scale.setScalar(0.96 + pulse * 0.12);
    this.haloMat.opacity = 0.04 + this.energy * 0.05;
    this.halo.scale.setScalar(1 + Math.sin(t * 1.6) * 0.015 * this.energy);
    this.particles.rotation.y += dt * (0.05 + this.energy * 0.12);
    this.particles.rotation.x = Math.sin(t * 0.2) * 0.1;
    this.particleMat.opacity = 0.4 + this.energy * 0.35;

    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.stop();
    window.removeEventListener('pointermove', this._onPointer);
    window.removeEventListener('resize', this._onResizeBound);
    this.scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => m.dispose());
      }
    });
    this.renderer.dispose();
  }
}
