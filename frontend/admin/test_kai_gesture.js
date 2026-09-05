/* Node tests for kai-gesture.js (+ the kai-presence.js wiring, statically) — camera OFF by default, explicit-activation-
 * only start, local-only, no frame reads, the backend's closed non-consequential vocabulary, session flag never persisted.
 * Run: node test_kai_gesture.js */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const G = require('./kai-gesture.js');

let pass = 0;
const tests = [];
function test(name, fn) { tests.push([name, fn]); }
// line comments first (a `/*` inside a `// …` line must not open a block), then block comments
const stripComments = src => src.replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/[^\n]*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
const readAdmin = f => fs.readFileSync(path.join(__dirname, f), 'utf8');

// ── fakes (no DOM, no camera) ─────────────────────────────────────────────────
function fakeEl() {
  return { hidden: false, textContent: '', className: '', attrs: {}, kids: [], handlers: {},
    setAttribute(k, v) { this.attrs[k] = v; }, appendChild(c) { this.kids.push(c); return c; }, addEventListener(t, f) { this.handlers[t] = f; } };
}
function fakeDoc() { const d = { hidden: false, handlers: {}, body: fakeEl(), createElement: () => fakeEl(), addEventListener(t, f) { d.handlers[t] = f; }, removeEventListener(t) { delete d.handlers[t]; } }; return d; }
function fakeWin() { const w = { handlers: {}, addEventListener(t, f) { w.handlers[t] = f; }, removeEventListener(t) { delete w.handlers[t]; } }; return w; }
// Any property access other than getTracks()/then counts as a "frame read" — the module must never touch one.
function fakeStream() {
  const s = { stopped: 0, reads: 0, getTracks() { return [{ stop: () => { s.stopped++; } }]; } };
  return new Proxy(s, { get(t, k) { if (!(k in t) && k !== 'then') t.reads++; return t[k]; } });
}
function fakeMedia(impl) {
  const md = { calls: 0, args: null, streams: [], getUserMedia(c) { md.calls++; md.args = c; if (impl) return impl(); const s = fakeStream(); md.streams.push(s); return Promise.resolve(s); } };
  return md;
}
const CONSEQUENTIAL = ['approve', 'confirm', 'execute', 'spend', 'authorize', 'yes', 'ask', 'holdingCommand', 'postConfirm', 'enable', 'merge', 'deploy', 'policy'];
function mk(o) {
  const doc = fakeDoc(), win = fakeWin(), md = fakeMedia(), calls = [], changes = [];
  const actions = {};
  for (const a of G.ACTIONS) actions[a] = () => calls.push(a);
  for (const c of CONSEQUENTIAL) actions[c] = () => calls.push('!!' + c);   // present on the object; must NEVER be invoked
  const s = new G.KaiCameraSession(Object.assign({ document: doc, window: win, mediaDevices: md, userActivation: { isActive: true },
    allowed: () => ({ ok: true, code: 'AVAILABLE_SESSION' }), actions, onChange: ev => changes.push(ev) }, o || {}));
  return { s, doc, win, md, calls, changes };
}
const ev = (gesture, confidence, ts) => ({ gesture, confidence: confidence == null ? 0.95 : confidence, ts: ts == null ? 1000 : ts });

// ── OFF by default; start() refusals never reach the camera API ──────────────
test('default: camera OFF, recognizer RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED, authority NONE, not persisted', () => {
  const { s } = mk();
  const st = s.status();
  assert.strictEqual(st.camera, 'OFF');
  assert.strictEqual(st.recognizer, 'RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED');
  assert.strictEqual(st.authority, 'NONE'); assert.strictEqual(st.persisted, false); assert.strictEqual(st.inference, 'LOCAL_ONLY'); assert.strictEqual(st.biometrics, 'NONE');
});
test('start() without a live user activation → refused, getUserMedia never called', async () => {
  const { s, md } = mk({ userActivation: { isActive: false } });
  const r = await s.start('owner-click');
  assert.strictEqual(r.started, false); assert.strictEqual(r.code, 'NO_USER_ACTIVATION');
  assert.strictEqual(md.calls, 0); assert.strictEqual(s.status().camera, 'OFF');
  const noApi = mk({ userActivation: null });
  assert.strictEqual((await noApi.s.start('owner-click')).code, 'NO_USER_ACTIVATION'); assert.strictEqual(noApi.md.calls, 0);
});
test('start() from anything but the explicit owner control → refused (api / boot / undefined)', async () => {
  const { s, md } = mk();
  for (const t of ['api', 'boot', 'auto', undefined, '']) { const r = await s.start(t); assert.strictEqual(r.started, false); assert.strictEqual(r.code, 'NOT_EXPLICIT'); }
  assert.strictEqual(md.calls, 0);
});
test('policy gate not ok (backend not AVAILABLE_SESSION) → refused with its reason; no gate at all → fail closed', async () => {
  const { s, md } = mk({ allowed: () => ({ ok: false, code: 'FLAG_OFF', reason: 'KAI_CAMERA_ENABLED is off' }) });
  const r = await s.start('owner-click');
  assert.deepStrictEqual([r.started, r.code, r.reason], [false, 'FLAG_OFF', 'KAI_CAMERA_ENABLED is off']); assert.strictEqual(md.calls, 0);
  const bare = new G.KaiCameraSession({ document: fakeDoc(), window: fakeWin(), mediaDevices: fakeMedia(), userActivation: { isActive: true } });
  assert.strictEqual((await bare.start('owner-click')).code, 'NO_POLICY_GATE');
});
test('no document for the mandatory indicator → refused, camera never opened', async () => {
  const { s, md } = mk({ document: null });
  assert.strictEqual((await s.start('owner-click')).code, 'INDICATOR_UNAVAILABLE'); assert.strictEqual(md.calls, 0);
});

// ── the ONE capture call: explicit click + activation + gate ─────────────────
test('explicit owner click → exactly one getUserMedia({video:true, audio:false}); ON_SESSION; banner shown', async () => {
  const { s, md, doc, changes } = mk();
  const r = await s.start('owner-click');
  assert.strictEqual(r.started, true); assert.strictEqual(r.code, 'ON_SESSION');
  assert.strictEqual(md.calls, 1); assert.deepStrictEqual(md.args, { video: true, audio: false });
  assert.strictEqual(s.status().camera, 'ON_SESSION');
  const banner = doc.body.kids[0];
  assert.strictEqual(banner.className, 'kaip-cam-banner'); assert.strictEqual(banner.attrs.role, 'status'); assert.strictEqual(banner.attrs['aria-live'], 'assertive'); assert.strictEqual(banner.hidden, false);
  assert.ok(banner.kids.some(k => k.textContent === 'CAMERA ON — local only, nothing leaves this device'));
  assert.ok(banner.kids.some(k => /no frames read · recognizer RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED/.test(k.textContent)));
  assert.deepStrictEqual(changes, [{ on: true, reason: 'owner-click' }]);
  const again = await s.start('owner-click');
  assert.strictEqual(again.code, 'ALREADY_ON'); assert.strictEqual(md.calls, 1, 'a second start never re-requests the camera');
});
test('permission denied → PERMISSION_DENIED, camera stays OFF, no banner', async () => {
  const md = fakeMedia(() => Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' })));
  const { s, doc } = mk({ mediaDevices: md });
  const r = await s.start('owner-click');
  assert.strictEqual(r.code, 'PERMISSION_DENIED'); assert.strictEqual(s.status().camera, 'OFF'); assert.strictEqual(doc.body.kids.length, 0);
});

// ── no recognizer → zero frame reads; nothing in this file can read one ───────
test('no recognizer registered → status UNAVAILABLE and ZERO frame reads while open', async () => {
  const { s, md } = mk();
  await s.start('owner-click');
  assert.strictEqual(s.status().recognizer, 'RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED');
  assert.strictEqual(s.status().frames_read_by_this_module, 0);
  assert.strictEqual(md.streams[0].reads, 0, 'the stream was never asked for anything');
  s.stop('user-stop');
  assert.strictEqual(md.streams[0].reads, 0); assert.strictEqual(md.streams[0].stopped, 1);
});
test('static: kai-gesture.js has exactly ONE getUserMedia call and no frame / network / storage API', () => {
  const src = stripComments(readAdmin('kai-gesture.js'));
  assert.strictEqual((src.match(/getUserMedia\(/g) || []).length, 1, 'exactly one capture call site');
  for (const bad of ['ImageCapture', 'grabFrame', 'canvas', 'drawImage', 'toDataURL', 'toBlob', 'createImageBitmap', 'requestVideoFrameCallback', 'srcObject', 'getVideoTracks', 'MediaRecorder',
    'fetch(', 'XMLHttpRequest', 'WebSocket', 'sendBeacon', 'EventSource', 'localStorage', 'sessionStorage', 'indexedDB', 'cookie', 'holdingCommand', 'postConfirm', 'ask(']) {
    assert.ok(!src.includes(bad), 'forbidden token present: ' + bad);
  }
});
test('static: across the WHOLE admin frontend the ONLY getUserMedia call site is kai-gesture.js (kai-presence.js: none)', () => {
  const hits = {};
  for (const f of fs.readdirSync(__dirname)) {
    if (!f.endsWith('.js') || f.startsWith('test_')) continue;
    const n = (stripComments(readAdmin(f)).match(/getUserMedia\(/g) || []).length;
    if (n) hits[f] = n;
  }
  assert.deepStrictEqual(hits, { 'kai-gesture.js': 1 }, 'getUserMedia( call sites: ' + JSON.stringify(hits));
});

// ── typed events: the backend's closed vocabulary, never consequential ────────
test('vocabulary + threshold are IDENTICAL to backend gesture_policy.py (GESTURE_ACTIONS, CONFIDENCE_THRESHOLD)', () => {
  const py = fs.readFileSync(path.join(__dirname, '../../backend/app/services/holding/gesture_policy.py'), 'utf8');
  const backend = {}; for (const m of py.matchAll(/Gesture\.(\w+):\s*"(\w+)"/g)) backend[m[1]] = m[2];
  assert.ok(Object.keys(backend).length >= 5, 'parsed the backend map');
  assert.deepStrictEqual({ ...G.VOCABULARY }, backend);
  assert.strictEqual(G.MIN_CONFIDENCE, Number(py.match(/CONFIDENCE_THRESHOLD\s*=\s*([\d.]+)/)[1]));
  const consequential = py.match(/CONSEQUENTIAL_ACTIONS\s*=\s*frozenset\(\{([^}]*)\}\)/)[1].match(/"(\w+)"/g).map(x => x.replace(/"/g, ''));
  assert.ok(!G.ACTIONS.some(a => consequential.includes(a)), 'no frontend action is backend-consequential');
});
test('mapping: every vocabulary gesture calls only its non-consequential helper; consequential handlers never run', async () => {
  const { s, calls } = mk();
  await s.start('owner-click');
  for (const [g, a] of Object.entries(G.VOCABULARY)) { const r = s.handleEvent(ev(g)); assert.strictEqual(r.status, 'APPLIED'); assert.strictEqual(r.action, a); assert.strictEqual(r.authority, 'NONE'); assert.strictEqual(r.channel, 'gesture'); }
  assert.deepStrictEqual(calls, [...G.ACTIONS]);
  assert.strictEqual(s.handleEvent(ev(' open_palm ')).action, 'stop', 'same normalization as the backend (trim + upper)');
  for (const c of CONSEQUENTIAL) { const r = s.handleEvent(ev(c, 1)); assert.strictEqual(r.status, 'REFUSED'); assert.strictEqual(r.code, 'UNKNOWN_GESTURE'); }
  for (const c of ['stop', 'next', 'open_drawer', 'THUMBS_UP', 'OK_SIGN', 'NOD', 'WAVE', 'approve stop', 'OPEN_PALM APPROVE', 'constructor', '__proto__']) assert.strictEqual(s.handleEvent(ev(c, 1)).code, 'UNKNOWN_GESTURE', c);
  assert.ok(!calls.some(c => c.startsWith('!!')), 'no consequential handler was ever invoked: ' + calls);
  assert.ok(!G.ACTIONS.some(a => /approve|confirm|execute|spend|authori|pay|buy|send|delete|deploy|merge|enable|policy/i.test(a)), 'actions are non-consequential by construction');
});
test('low confidence and malformed events are refused', async () => {
  const { s, calls } = mk();
  await s.start('owner-click');
  assert.strictEqual(s.handleEvent(ev('OPEN_PALM', 0.5)).code, 'LOW_CONFIDENCE');
  assert.strictEqual(s.handleEvent(ev('OPEN_PALM', 0.79)).code, 'LOW_CONFIDENCE');
  assert.strictEqual(s.handleEvent(ev('OPEN_PALM', NaN)).code, 'MALFORMED');
  assert.strictEqual(s.handleEvent({ gesture: 'OPEN_PALM', confidence: '0.99', ts: 1 }).code, 'MALFORMED');
  assert.strictEqual(s.handleEvent({ gesture: 'OPEN_PALM', confidence: 0.99 }).code, 'MALFORMED');
  assert.strictEqual(s.handleEvent(null).code, 'MALFORMED');
  assert.strictEqual(s.handleEvent({ gesture: ['OPEN_PALM'], confidence: 0.99, ts: 1 }).code, 'MALFORMED');
  assert.deepStrictEqual(calls, []);
});
test('events while the camera is OFF are refused even when well-formed', () => {
  const { s, calls } = mk();
  assert.strictEqual(s.handleEvent(ev('OPEN_PALM')).code, 'CAMERA_OFF'); assert.deepStrictEqual(calls, []);
});

// ── stop paths; never auto-restart; never persisted ──────────────────────────
test('tab hidden → stop (tracks closed, banner hidden); becoming visible again NEVER re-opens', async () => {
  const { s, md, doc, changes } = mk();
  await s.start('owner-click');
  doc.hidden = true; doc.handlers.visibilitychange();
  assert.strictEqual(s.status().camera, 'OFF'); assert.strictEqual(md.streams[0].stopped, 1); assert.strictEqual(doc.body.kids[0].hidden, true);
  assert.deepStrictEqual(changes[1], { on: false, reason: 'hidden' });
  doc.hidden = false; if (doc.handlers.visibilitychange) doc.handlers.visibilitychange();
  assert.strictEqual(s.status().camera, 'OFF'); assert.strictEqual(md.calls, 1, 'no auto-restart');
  assert.strictEqual(doc.handlers.visibilitychange, undefined, 'listener removed with the session');
});
test('pagehide → stop; the banner Stop button → stop', async () => {
  const a = mk(); await a.s.start('owner-click'); a.win.handlers.pagehide();
  assert.strictEqual(a.s.status().camera, 'OFF'); assert.strictEqual(a.md.streams[0].stopped, 1);
  const b = mk(); await b.s.start('owner-click');
  b.doc.body.kids[0].kids.find(k => k.className === 'kaip-cam-stop').handlers.click();
  assert.strictEqual(b.s.status().camera, 'OFF'); assert.deepStrictEqual(b.changes[1], { on: false, reason: 'user-stop' });
});
test('stop() while the camera is still opening closes the late stream immediately and stays OFF', async () => {
  let resolve; const md = fakeMedia(() => new Promise(r => { resolve = r; }));
  const { s } = mk({ mediaDevices: md });
  const pending = s.start('owner-click');
  s.stop('user-stop');
  const late = fakeStream(); resolve(late);
  const r = await pending;
  assert.strictEqual(r.code, 'STOPPED_DURING_START'); assert.strictEqual(late.stopped, 1); assert.strictEqual(s.status().camera, 'OFF');
});
test('session flag is memory-only: a fresh session is OFF after another was ON; status.persisted === false', async () => {
  const a = mk(); await a.s.start('owner-click'); assert.strictEqual(a.s.status().camera, 'ON_SESSION');
  const b = mk(); assert.strictEqual(b.s.status().camera, 'OFF'); assert.strictEqual(b.s.status().persisted, false);
});

// ── the seam ──────────────────────────────────────────────────────────────────
test('registerRecognizer(fn): attached with the stream + emit, typed events flow through the same mapping, disposed on stop', async () => {
  const { s, md, calls, doc } = mk();
  await s.start('owner-click');
  let got = null, disposed = 0;
  assert.strictEqual(s.registerRecognizer('not a function'), false);
  s.registerRecognizer((stream, emit) => { got = { stream, emit }; return () => { disposed++; }; });
  assert.strictEqual(s.status().recognizer, 'REGISTERED');
  assert.strictEqual(got.stream, md.streams[0]);
  assert.ok(/recognizer registered/.test(doc.body.kids[0].kids.find(k => k.className === 'kaip-cam-sub').textContent));
  assert.strictEqual(got.emit(ev('SWIPE_LEFT')).status, 'APPLIED'); assert.strictEqual(got.emit(ev('approve', 1)).code, 'UNKNOWN_GESTURE');
  assert.deepStrictEqual(calls, ['next']);
  s.stop('user-stop'); assert.strictEqual(disposed, 1);
});

// ── kai-presence.js wiring (static — the module needs a DOM; these pin the contract) ──
test('static: kai-presence.js opens the camera ONLY from the #ks-camera_enabled control (owner-click); the API start is "api"; settings never persist camera on', () => {
  const src = stripComments(readAdmin('kai-presence.js'));
  const explicit = src.match(/startCamera\('owner-click'\)/g) || [];
  assert.strictEqual(explicit.length, 1, 'exactly one explicit-trigger call site');
  const line = src.split('\n').find(l => l.includes("startCamera('owner-click')"));
  assert.ok(line.includes("q('ks-camera_enabled').addEventListener('change'"), 'the explicit trigger lives in the settings control handler: ' + line);
  assert.ok(src.includes("start: () => startCamera('api')"), 'KAI.gesture.start passes the non-explicit trigger (refused by the module)');
  assert.ok(src.includes('s.camera_enabled = false'), 'loadSettings forces camera_enabled=false (never persisted as on)');
  assert.ok(!/camera_enabled\s*=\s*true/.test(src), 'nothing sets camera_enabled=true');
  for (const hook of ["stopCamera(r || 'user-stop')", "stopCamera('logout')", "stopCamera('settings-off')", "stopCamera('reset')"]) assert.ok(src.includes(hook), 'stop hook present: ' + hook);
  assert.ok(src.includes("if (state.settings.muted) KAI.stop('user-stop')") && src.includes("if (b) KAI.stop('user-stop')"), 'mute stops everything (camera included) on both the UI and API paths');
});
test('static: the gesture actions injected by kai-presence.js are exactly the vocabulary actions and never a consequential helper', () => {
  const src = stripComments(readAdmin('kai-presence.js'));
  const m = src.match(/actions:\s*\{([^}]*)\}/);
  assert.ok(m, 'actions literal found');
  const keys = [...m[1].matchAll(/(\w+):\s*\(\)\s*=>/g)].map(x => x[1]).sort();
  assert.deepStrictEqual(keys, [...G.ACTIONS].sort());
  for (const bad of ['ask', 'holdingCommand', 'postConfirm', 'confirm', 'fetch', 'submit', 'login', 'approve', 'speak', 'startListening', 'startCamera']) assert.ok(!new RegExp('\\b' + bad + '\\b').test(m[1]), 'forbidden helper in gesture actions: ' + bad);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  ok  ' + name); pass++; }
    catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; }
  }
  console.log('\n' + pass + ' passed');
})();
