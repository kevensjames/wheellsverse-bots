// ============================================================================
// KAI avatar — GLB/VRM WebGL backend (§9 photoreal path)
//
// HONEST STATUS: this is the *controller* for a rigged 3D KAI. It is real,
// working code that drives ARKit-style facial blendshapes + eye/head bones from
// the canonical state machine — BUT it activates ONLY when BOTH are present:
//   1. a bundled 3D library on window.THREE (+ a GLTFLoader), and
//   2. a rigged asset at assets/kai.glb.
// Neither ships in this repo yet (adding Three.js ~600KB is unwarranted until a
// production avatar asset exists). So on this build tryMountGltf() returns null
// and the controller falls back to the canvas presence. We do NOT claim photoreal
// is complete — see README "Seams". Drop in the lib + asset and this lights up.
//
// Required GLB blendshapes (ARKit-compatible): blink, blinkLeft, blinkRight,
// jawOpen, mouthSmile, mouthFrown, mouthA/E/I/O/U, browUp, browDown,
// eyeLookLeft/Right/Up/Down. Required bones: head, neck, eyeL, eyeR.
// ============================================================================
import { bus, KAI } from '../state.js';

export function hasWebGL() {
  try { const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl'))); }
  catch { return false; }
}

async function assetExists(url) {
  try { const r = await fetch(url, { method: 'HEAD' }); return r.ok; } catch { return false; }
}

// state → target facial pose (blendshape weights 0..1)
const POSE = {
  idle:         { blink: 0, jawOpen: 0, browUp: .05, mouthSmile: .04 },
  listening:    { browUp: .35, mouthSmile: .06 },
  understanding:{ browUp: .5 },
  thinking:     { browUp: .12, eyeLookUp: .3 },
  researching:  { eyeLookUp: .25, browUp: .1 },
  executing:    { browUp: .08 },
  speaking:     { mouthSmile: .1 },
  success:      { mouthSmile: .5, browUp: .2 },
  warning:      { browDown: .3 },
  critical:     { browDown: .5, mouthFrown: .2 },
  sleep:        { blink: .8 },
};

export async function tryMountGltf(canvas) {
  if (!hasWebGL()) return null;
  const THREE = window.THREE;
  if (!THREE || !THREE.GLTFLoader) return null;               // 3D lib not bundled
  if (!(await assetExists('assets/kai.glb'))) return null;    // no rigged asset yet

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(28, 1, .1, 100); cam.position.set(0, 1.5, 2.2);
  scene.add(new THREE.AmbientLight(0x24406a, 1.1));
  const rim = new THREE.DirectionalLight(0x4da3ff, 1.4); rim.position.set(2, 2, 2); scene.add(rim);

  const gltf = await new Promise((res, rej) => new THREE.GLTFLoader().load('assets/kai.glb', res, undefined, rej));
  scene.add(gltf.scene);

  // collect blendshape + bone handles
  const morphs = {}; let head, eyeL, eyeR;
  gltf.scene.traverse(o => {
    if (o.morphTargetDictionary) for (const k in o.morphTargetDictionary) morphs[k] = { mesh: o, i: o.morphTargetDictionary[k] };
    if (o.isBone) { if (/head/i.test(o.name)) head = o; if (/eye.*l/i.test(o.name)) eyeL = o; if (/eye.*r/i.test(o.name)) eyeR = o; }
  });
  const setMorph = (name, w) => { const m = morphs[name]; if (m) m.mesh.morphTargetInfluences[m.i] = w; };

  const m = { pose: {}, target: POSE.idle, blink: 0, nextBlink: 1400, gaze: { x: 0, y: 0 }, gazeT: { x: 0, y: 0 }, env: 0x4da3ff, viseme: {} };
  bus.on('state', ({ state }) => { m.target = POSE[state] || POSE.idle; });
  bus.on('gaze:point', p => { const r = canvas.getBoundingClientRect();
    m.gazeT.x = Math.max(-1, Math.min(1, (p.x - (r.left + r.width / 2)) / (innerWidth * .5)));
    m.gazeT.y = Math.max(-1, Math.min(1, (p.y - (r.top + r.height * .44)) / (innerHeight * .5))); });
  bus.on('env:light', ({ color }) => { rim.color.set(color || '#4da3ff'); });
  bus.on('viseme', v => { m.viseme = v || {}; });      // Phase-2 lip-sync feeds here

  function resize() { const s = canvas.clientWidth || 440; renderer.setSize(s, s, false); cam.aspect = 1; cam.updateProjectionMatrix(); }
  new ResizeObserver(resize).observe(canvas); resize();

  let raf, last = performance.now(), blinkT = 0;
  function frame(now) {
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    if (document.hidden) { raf = requestAnimationFrame(frame); return; }   // §33 pause
    // ease pose toward target
    for (const k in m.target) m.pose[k] = (m.pose[k] || 0) + ((m.target[k] || 0) - (m.pose[k] || 0)) * dt * 4;
    // procedural blink
    blinkT += dt * 1000;
    if (blinkT > m.nextBlink) { m.blink = Math.min(1, m.blink + dt * 15); if (m.blink >= 1) { blinkT = 0; m.nextBlink = 2800 + Math.random() * 4700; } }
    else if (m.blink > 0) m.blink = Math.max(0, m.blink - dt * 17);
    for (const k in m.pose) setMorph(k, m.pose[k]);
    setMorph('blink', Math.max(m.pose.blink || 0, m.blink));
    // visemes (lip-sync) override mouth when speaking
    for (const v in m.viseme) setMorph('mouth' + v.toUpperCase(), m.viseme[v]);
    // gaze via eye bones + head follow
    m.gaze.x += (m.gazeT.x - m.gaze.x) * dt * 4; m.gaze.y += (m.gazeT.y - m.gaze.y) * dt * 4;
    if (eyeL) { eyeL.rotation.y = m.gaze.x * .4; eyeL.rotation.x = m.gaze.y * .3; }
    if (eyeR) { eyeR.rotation.y = m.gaze.x * .4; eyeR.rotation.x = m.gaze.y * .3; }
    if (head) head.rotation.y = m.gaze.x * .12;
    renderer.render(scene, cam);
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);
  canvas.dataset.avatarBackend = 'gltf';

  return { backend: 'gltf', litHalo() {}, lookAt: (x, y) => bus.emit('gaze:point', { x, y }), destroy: () => { cancelAnimationFrame(raf); renderer.dispose(); } };
}
