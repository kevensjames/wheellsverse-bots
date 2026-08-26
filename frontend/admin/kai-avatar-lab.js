/* KAI Avatar Lab controller (Phase 12, §1-8/§32). DEV TOOL — drives the REAL engines
 * (viseme mapper/engine, idle-life, embodiment state machine, chunker, audio queue, TTS,
 * barge-in) through a LabAvatarDriver rendering a 2D SVG face. NOT the production asset. */
(function () {
  'use strict';
  var VM = window.KaiVisemeMapper, VE = window.KaiVisemeEngine, IL = window.KaiIdleLife,
    AD = window.KaiAvatarDriver, EMB = window.NexusEmbodiment, CH = window.KaiSpeechChunker,
    AQ = window.KaiAudioQueue, TTS = window.KaiTTSProvider, BI = window.KaiBargeIn;
  var NS = 'http://www.w3.org/2000/svg';
  var REDUCE = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var el = function (id) { return document.getElementById(id); };
  var now = function () { return (window.performance && performance.now()) ? performance.now() : Date.now(); };

  // ── face state (what the driver applies) ──────────────────────────────────
  var face = { coeffs: {}, gaze: { yaw: 0, pitch: 0 }, head: { yaw: 0, pitch: 0, roll: 0 }, blink: 0, expr: {} };
  var svg = {};   // named SVG nodes

  function buildFace() {
    var s = document.createElementNS(NS, 'svg'); s.setAttribute('viewBox', '0 0 200 224'); s.setAttribute('role', 'img'); s.setAttribute('aria-label', 'KAI dev avatar');
    var defs = document.createElementNS(NS, 'defs');
    var g = document.createElementNS(NS, 'radialGradient'); g.setAttribute('id', 'kf-iris-grad');
    [['0%', '#8fe6ff'], ['55%', '#2f9bff'], ['100%', '#0a2a66']].forEach(function (p) { var st = document.createElementNS(NS, 'stop'); st.setAttribute('offset', p[0]); st.setAttribute('stop-color', p[1]); g.appendChild(st); });
    defs.appendChild(g); s.appendChild(defs);
    var head = mk('g', { id: 'kf-head' }); svg.head = head; s.appendChild(head);
    head.appendChild(mk('ellipse', { class: 'kf-skin', cx: 100, cy: 108, rx: 62, ry: 78 }));
    // brows
    svg.browL = mk('path', { class: 'kf-brow', d: '' }); svg.browR = mk('path', { class: 'kf-brow', d: '' });
    head.appendChild(svg.browL); head.appendChild(svg.browR);
    // eyes (white, iris, pupil, catchlight, lid)
    ['L', 'R'].forEach(function (side) {
      var ex = side === 'L' ? 74 : 126;
      head.appendChild(mk('ellipse', { class: 'kf-eye-white', cx: ex, cy: 92, rx: 16, ry: 10 }));
      svg['iris' + side] = mk('circle', { class: 'kf-iris', cx: ex, cy: 92, r: 7.5 });
      svg['pupil' + side] = mk('circle', { class: 'kf-pupil', cx: ex, cy: 92, r: 3.4 });
      svg['catch' + side] = mk('circle', { class: 'kf-catch', cx: ex + 2, cy: 89, r: 1.4 });
      svg['lid' + side] = mk('rect', { class: 'kf-lid', x: ex - 17, y: 78, width: 34, height: 0, rx: 6 });
      head.appendChild(svg['iris' + side]); head.appendChild(svg['pupil' + side]); head.appendChild(svg['catch' + side]); head.appendChild(svg['lid' + side]);
    });
    head.appendChild(mk('path', { class: 'kf-lip', d: 'M92 118 Q100 124 108 118', style: 'stroke:#33456b;stroke-width:3' })); // nose
    // mouth
    svg.mouthIn = mk('ellipse', { class: 'kf-mouth-in', cx: 100, cy: 156, rx: 22, ry: 3 });
    svg.teeth = mk('rect', { class: 'kf-teeth', x: 86, y: 150, width: 28, height: 0, rx: 1 });
    svg.lipU = mk('path', { class: 'kf-lip', d: '' }); svg.lipL = mk('path', { class: 'kf-lip', d: '' });
    head.appendChild(svg.mouthIn); head.appendChild(svg.teeth); head.appendChild(svg.lipU); head.appendChild(svg.lipL);
    el('lab-face-wrap').replaceChildren(s);
    drawFace();
  }
  function mk(tag, attrs) { var n = document.createElementNS(NS, tag); for (var k in attrs) n.setAttribute(k, attrs[k]); return n; }
  var C = function (k) { return +(face.coeffs[k] || 0) + (+(face.expr[k] || 0)); };

  function drawFace() {
    // head pose (subtle)
    svg.head.setAttribute('transform', 'translate(' + (face.head.yaw * 1.4).toFixed(2) + ',' + (-face.head.pitch * 1.4).toFixed(2) + ') rotate(' + (face.head.roll).toFixed(2) + ' 100 112)');
    // brows
    var bi = C('browInnerUp'), bdL = C('browDownLeft'), bdR = C('browDownRight'), boL = C('browOuterUpLeft'), boR = C('browOuterUpRight');
    svg.browL.setAttribute('d', brow(60, 88, bi, bdL, boL, 1));
    svg.browR.setAttribute('d', brow(114, 88, bi, bdR, boR, -1));
    // eyes: gaze offset + blink lid height
    ['L', 'R'].forEach(function (side) {
      var ex = side === 'L' ? 74 : 126;
      var gx = ex + face.gaze.yaw * 5, gy = 92 - face.gaze.pitch * 4;
      svg['iris' + side].setAttribute('cx', gx.toFixed(2)); svg['iris' + side].setAttribute('cy', gy.toFixed(2));
      svg['pupil' + side].setAttribute('cx', gx.toFixed(2)); svg['pupil' + side].setAttribute('cy', gy.toFixed(2));
      svg['catch' + side].setAttribute('cx', (gx + 2).toFixed(2)); svg['catch' + side].setAttribute('cy', (gy - 3).toFixed(2));
      var lidH = Math.max(0, Math.min(1, face.blink)) * 20;   // 0..20
      svg['lid' + side].setAttribute('height', lidH.toFixed(2));
    });
    // mouth from coefficients
    var j = C('jawOpen'), close = C('mouthClose'), pk = C('mouthPucker'), fn = C('mouthFunnel'),
      st = C('mouthStretchLeft'), sm = C('mouthSmileLeft'), ld = C('mouthLowerDownLeft'), rl = C('mouthRollLower'), uu = C('mouthUpperUpLeft');
    var cy = 156;
    var openH = Math.max(1.5, (3 + j * 34) * (1 - 0.85 * close));
    var width = Math.max(20, Math.min(64, 44 * (1 + st * 0.55 - (pk + fn) * 0.35)));
    var corner = -sm * 9;
    var lx = 100 - width / 2, rx = 100 + width / 2;
    svg.mouthIn.setAttribute('cx', 100); svg.mouthIn.setAttribute('cy', cy);
    svg.mouthIn.setAttribute('rx', (width / 2).toFixed(2)); svg.mouthIn.setAttribute('ry', (openH / 2).toFixed(2));
    var topMidY = cy - openH / 2 - uu * 4;
    var botMidY = cy + openH / 2 - rl * 6 + 2;   // rollLower raises the lower lip (FV)
    svg.lipU.setAttribute('d', 'M' + lx + ' ' + (cy + corner) + ' Q100 ' + topMidY.toFixed(1) + ' ' + rx + ' ' + (cy + corner));
    svg.lipL.setAttribute('d', 'M' + rx + ' ' + (cy + corner) + ' Q100 ' + botMidY.toFixed(1) + ' ' + lx + ' ' + (cy + corner));
    var showTeeth = (rl > 0.4 && ld > 0.2) ? 5 : 0;   // FV: lower lip to upper teeth
    svg.teeth.setAttribute('height', showTeeth); svg.teeth.setAttribute('y', (cy - openH / 2 - 1).toFixed(1)); svg.teeth.setAttribute('width', Math.min(28, width - 6));
    svg.teeth.setAttribute('x', (100 - Math.min(28, width - 6) / 2).toFixed(1));
  }
  function brow(x, y, inner, down, outer, dir) {
    var lift = inner * 6 + outer * 5 - down * 5;
    var x2 = x + 40 * 1;   // width
    return 'M' + x + ' ' + (y - (dir > 0 ? outer * 3 : inner * 3)) + ' Q' + (x + 20) + ' ' + (y - lift) + ' ' + x2 + ' ' + (y - (dir > 0 ? inner * 3 : outer * 3));
  }

  // ── driver ────────────────────────────────────────────────────────────────
  var driver = AD.createDriver('lab', { apply: function (coeffs) { face.coeffs = coeffs || {}; drawFace(); } });
  driver.load();
  el('lab-avatar-diag').textContent = 'driver: ' + driver.kind + ' · ' + driver.getDiagnostics().label + ' · visemes=' + driver.getCapabilities().visemes;

  function setCoeffs(coeffs) { face.coeffs = coeffs || {}; drawFace(); showCoeffs(coeffs); }
  function showCoeffs(coeffs) {
    var box = el('lab-coeffs'); if (!box) return; box.replaceChildren();
    (VM.COEFF_KEYS).forEach(function (k) {
      var v = +(coeffs[k] || 0); var kk = document.createElement('span'); kk.className = 'k'; kk.textContent = k;
      var vv = document.createElement('span'); vv.className = 'v' + (v === 0 ? ' z' : ''); vv.textContent = v.toFixed(2); box.append(kk, vv);
    });
  }

  // ── viseme lab ──────────────────────────────────────────────────────────────
  var visBtns = el('lab-viseme-btns');
  VM.VISEMES.forEach(function (v) {
    var b = document.createElement('button'); b.className = 'lab-btn'; b.textContent = v.replace('_', '/'); b.type = 'button';
    b.addEventListener('click', function () { stopLoops(); el('lab-viseme-name').textContent = v; var c = VM.visemeToCoefficients(v); driver.setViseme(v, 1); face.coeffs = c; drawFace(); showCoeffs(c); });
    visBtns.appendChild(b);
  });

  // ── shared timeline player (viseme engine) ───────────────────────────────────
  var raf = null, slow = false;
  function stopLoops() { if (raf) { cancelAnimationFrame(raf); raf = null; } }
  function playUnits(units, onDone) {
    stopLoops();
    var tl = VE.buildTimeline(units, {}), end = VE.timelineEnd(tl), t0 = now(), speed = slow ? 0.25 : 1;
    (function frame() {
      var t = (now() - t0) * speed;
      var s = VE.sample(tl, t); face.coeffs = s.coeffs; drawFace(); showCoeffs(s.coeffs);
      el('lab-viseme-name').textContent = s.viseme;
      updateCoartView(tl, t);
      if (t <= end) raf = requestAnimationFrame(frame); else { face.coeffs = VE.restCoeffs(); drawFace(); raf = null; if (onDone) onDone(); }
    })();
  }
  el('lab-play-all').addEventListener('click', function () {
    var units = VE.sequenceToUnits(VM.VISEMES.filter(function (v) { return v !== 'REST'; }), 320, 0);
    playUnits(units);
  });

  // ── coarticulation ───────────────────────────────────────────────────────────
  var COART = [['MBP', 'A_AH'], ['FV', 'O'], ['TH', 'E'], ['SH_CH_J', 'U'], ['L', 'A_AH', 'MBP']];
  var coartBtns = el('lab-coart-btns');
  COART.forEach(function (seq) {
    var b = document.createElement('button'); b.className = 'lab-btn'; b.type = 'button'; b.textContent = seq.map(function (x) { return x.replace('_', '/'); }).join(' → ');
    b.addEventListener('click', function () { playUnits(VE.sequenceToUnits(seq, 300, 0)); });
    coartBtns.appendChild(b);
  });
  el('lab-slowmo').addEventListener('change', function (e) { slow = e.target.checked; });
  function updateCoartView(tl, t) {
    var v = el('lab-coart-view'); if (!v) return;
    var rows = tl.map(function (u) { var w = 0; var on = u.start, off = u.start + u.dur, b = u.blend; if (t > on - b && t < off + b) { w = t < on ? (t - (on - b)) / b : t <= off ? 1 : 1 - (t - off) / b; } return u.viseme + '  ' + bar(w); });
    v.textContent = 't=' + Math.round(t) + 'ms\n' + rows.join('\n');
  }
  function bar(w) { var n = Math.round(Math.max(0, Math.min(1, w)) * 20); return '█'.repeat(n) + '·'.repeat(20 - n) + ' ' + w.toFixed(2); }

  // ── idle life ─────────────────────────────────────────────────────────────
  var rng = IL.makeRng(20260826);
  var idleOn = true, breathP = IL.breathePeriod(rng), blinkAt = 0, blinkKind = 'single', blinkStart = 0, sacAt = 0, headAt = 0, headTgt = { yaw: 0, pitch: 0, roll: 0 }, idleT0 = now();
  function scheduleBlink(t) { var b = IL.nextBlink(rng); blinkAt = t + b.delayMs; blinkKind = b.kind; }
  scheduleBlink(0); sacAt = 400; headAt = 2000;
  function idleFrame() {
    var t = now() - idleT0;
    if (idleOn) {
      face.expr = curExpr;
      // breathing → subtle head bob (a rig maps to chest; the lab nudges the head)
      var br = IL.breathe(t % breathP, breathP);
      // blink
      if (t >= blinkAt && !blinkStart) { blinkStart = t; }
      if (blinkStart) { var p = (t - blinkStart) / IL.blinkDurationMs(blinkKind); if (p >= 1) { blinkStart = 0; scheduleBlink(t); face.blink = 0; } else face.blink = IL.blinkClosure(blinkKind, p); }
      // saccade
      if (t >= sacAt) { var sc = IL.nextSaccade(rng); face.gaze = { yaw: gazeBase.yaw + sc.dx * 6, pitch: gazeBase.pitch + sc.dy * 6 }; sacAt = t + sc.delayMs; }
      // head drift
      if (t >= headAt) { headTgt = IL.nextHeadDrift(rng); headAt = t + headTgt.durMs; }
      face.head.yaw += (headTgt.yaw - face.head.yaw) * 0.02; face.head.pitch += (headTgt.pitch + br * 0.6 - face.head.pitch) * 0.03; face.head.roll += (headTgt.roll - face.head.roll) * 0.02;
      drawFace();
      var d = el('lab-idle-diag');
      if (d) setDiag(d, [['next blink', Math.max(0, Math.round((blinkAt - t) / 100) / 10) + 's'], ['breathing', IL.breathe(t % breathP, breathP).toFixed(2)], ['gaze', face.gaze.yaw.toFixed(1) + ', ' + face.gaze.pitch.toFixed(1)], ['head yaw/pitch', face.head.yaw.toFixed(1) + ' / ' + face.head.pitch.toFixed(1)], ['expression', curExprName]]);
    }
    idleRaf = requestAnimationFrame(idleFrame);
  }
  function setDiag(d, pairs) { d.replaceChildren(); pairs.forEach(function (p) { var k = document.createElement('span'); k.className = 'k'; k.textContent = p[0]; var v = document.createElement('span'); v.textContent = p[1]; d.append(k, v); }); }   // textContent → no HTML injection
  var idleRaf = null, gazeBase = { yaw: 0, pitch: 0 }, curExpr = {}, curExprName = 'neutral';
  if (!REDUCE) idleRaf = requestAnimationFrame(idleFrame);
  el('lab-idle-on').addEventListener('change', function (e) { idleOn = e.target.checked; });
  document.querySelectorAll('[data-blink]').forEach(function (b) { b.addEventListener('click', function () { blinkKind = b.dataset.blink; blinkStart = now() - idleT0; blinkAt = 1e12; }); });
  document.querySelectorAll('[data-gaze]').forEach(function (b) { b.addEventListener('click', function () { var g = IL.gazeVector(b.dataset.gaze); gazeBase = g; face.gaze = { yaw: g.yaw * 6, pitch: g.pitch * 6 }; drawFace(); }); });
  var exprBtns = el('lab-expr-btns');
  IL.expressionNames().forEach(function (n) { var b = document.createElement('button'); b.className = 'lab-btn'; b.type = 'button'; b.textContent = n; b.addEventListener('click', function () { curExpr = IL.expressionCoefficients(n); curExprName = n; face.expr = curExpr; drawFace(); }); exprBtns.appendChild(b); });

  // ── states ────────────────────────────────────────────────────────────────
  var stateBtns = el('lab-state-btns');
  (EMB ? EMB.STATES : ['idle']).forEach(function (st) {
    var b = document.createElement('button'); b.className = 'lab-btn'; b.type = 'button'; b.textContent = st;
    b.addEventListener('click', function () { var sp = EMB.spec(st); el('lab-state').textContent = st.toUpperCase(); driver.setState(st); document.querySelector('.lab-body').style.setProperty('--stateaccent', ''); if (sp.video === 'speak') { /* speaking */ } });
    stateBtns.appendChild(b);
  });

  // ── voice lab ───────────────────────────────────────────────────────────────
  var provider = TTS.createProvider('web-speech', { preferredVoiceName: localStorage.getItem('kai.voice') || null });
  var voiceAvail = provider.availability();
  el('lab-voice-avail').textContent = voiceAvail.available ? '' : '(speechSynthesis unavailable)';
  el('lab-mic-avail');
  function loadVoices() {
    var sel = el('lab-voice-select'); if (!sel) return; sel.replaceChildren();
    var ranked = provider.rankVoices();
    ranked.forEach(function (r) { var o = document.createElement('option'); o.value = r.voice.name; o.textContent = r.voice.name + ' · ' + (r.voice.lang || '?') + (r.masculine ? ' · ♂' : '') + ' · score ' + r.score; sel.appendChild(o); });
    var pref = localStorage.getItem('kai.voice'); if (pref) sel.value = pref;
    el('lab-voice-pref').textContent = pref ? ('preferred: ' + pref) : 'no preference saved';
  }
  loadVoices();
  if (voiceAvail.available && window.speechSynthesis) window.speechSynthesis.onvoiceschanged = loadVoices;
  el('lab-voice-save').addEventListener('click', function () { var sel = el('lab-voice-select'); if (sel.value) { localStorage.setItem('kai.voice', sel.value); provider.setPreferredVoice(sel.value); el('lab-voice-pref').textContent = 'preferred: ' + sel.value; } });
  var PHRASES = [
    "Good evening. I'm KAI. All available systems are online and ready.",
    'The Research Agent found three relevant signals. I can compare the evidence or continue investigating.',
    'Maybe we should probably begin with memory.',
    'Five very fast foxes moved beyond the perimeter.',
    'The weather outside may change, but the mission remains stable.',
  ];
  var phraseBtns = el('lab-phrase-btns');
  PHRASES.forEach(function (p, i) { var b = document.createElement('button'); b.className = 'lab-btn'; b.type = 'button'; b.textContent = 'Phrase ' + (i + 1); b.title = p; b.addEventListener('click', function () { speakStreamed(p); }); phraseBtns.appendChild(b); });

  // ── streaming speech + subtitles + audio queue ────────────────────────────
  var queue = new AQ.KaiAudioQueue({ now: now, maxLen: 24 });
  var speakSession = 0, feedTimer = null;   // epoch: a stop/barge-in bumps it so the token producer stops
  var cancel = new BI.KaiSpeechCancellationController({
    now: now, cancelTTS: function () { provider.cancel(); },
    clearQueue: function () { speakSession++; if (feedTimer) { clearTimeout(feedTimer); feedTimer = null; } queue.cancelAll(); queue.prune(); renderQueue(); },
    clearVisemes: function () { stopLoops(); }, mouthToRest: function () { face.coeffs = VE.restCoeffs(); drawFace(); },
    cancelLLM: function () {}, disposeTimers: function () { if (feedTimer) { clearTimeout(feedTimer); feedTimer = null; } }, setState: function (s) { el('lab-state').textContent = s.toUpperCase(); },
  });
  function renderQueue() {
    var box = el('lab-queue'); if (!box) return; box.replaceChildren();
    queue.items.slice(-8).forEach(function (it) { var d = document.createElement('div'); d.className = 'lab-qitem'; var t = document.createElement('span'); t.textContent = it.text.slice(0, 40); var st = document.createElement('span'); st.className = 'st st-' + it.status; st.textContent = it.status; d.append(t, st); box.appendChild(d); });
  }
  function speakStreamed(full) {
    cancel.stop('restart'); var sid = ++speakSession;   // this run's epoch; any stop/barge-in/new-stream invalidates it
    el('lab-state').textContent = 'SPEAKING'; el('lab-subtitles').textContent = '';
    var chunker = new CH.KaiSpeechChunker();
    var toks = full.match(/\S+\s*/g) || [full]; var i = 0, subtitle = '';
    (function feed() {
      if (sid !== speakSession) return;   // cancelled → the producer stops
      if (i < toks.length) {
        chunker.push(toks[i]).forEach(enqueueSpeak); i++;
        feedTimer = setTimeout(feed, 45);
      } else { chunker.flush().forEach(enqueueSpeak); }
    })();
    function enqueueSpeak(chunk) {
      if (sid !== speakSession) return;
      var item = queue.enqueue(chunk); if (!item) return; renderQueue();
      subtitle += (subtitle ? ' ' : '') + chunk; setSubtitle(subtitle, chunk);
      pump();
    }
    var speaking = false;
    function pump() {
      if (sid !== speakSession || speaking) return; var it = queue.next(); if (!it) return; speaking = true;
      queue.markPlaying(it.id); renderQueue(); driver.setState('speaking');
      var units = graphemesToUnits(it.text); playUnits(units);   // APPROX grapheme timing (§16), not real phoneme sync
      if (voiceAvail.available) provider.speak(it.text, { onend: doneOne, onerror: doneOne });
      else setTimeout(doneOne, Math.max(400, it.text.length * 45));
      function doneOne() {
        if (sid !== speakSession || it.status !== 'PLAYING') return;   // a stop/barge-in cancelled this chunk — do NOT clobber state
        queue.markComplete(it.id); queue.prune(); renderQueue(); speaking = false; pump();
        if (sid === speakSession && !queue.next() && !queue.active()) { el('lab-state').textContent = 'ATTENTIVE'; face.coeffs = VE.restCoeffs(); drawFace(); }
      }
    }
  }
  // §16 APPROXIMATE speech timing from graphemes — labeled, NOT real phoneme sync
  function graphemesToUnits(text) {
    var units = [], t = 0, ms = 70;
    text.toUpperCase().replace(/[^A-Z ]/g, '').split('').forEach(function (ch) {
      if (ch === ' ') { units.push({ viseme: 'REST', start: t, dur: ms }); t += ms; return; }
      var vis = VM.phonemeToViseme(ch); units.push({ viseme: vis, start: t, dur: ms }); t += ms;
    });
    return units;
  }
  function setSubtitle(full, cur) { var s = el('lab-subtitles'); if (!s) return; s.replaceChildren(document.createTextNode(full.slice(0, full.length - cur.length))); var span = document.createElement('span'); span.className = 'cur'; span.textContent = cur; s.appendChild(span); }
  el('lab-speak-demo').addEventListener('click', function () { speakStreamed(PHRASES[0]); });
  el('lab-stop').addEventListener('click', function () { cancel.userStop(); el('lab-state').textContent = 'ONLINE'; });

  // ── microphone + barge-in ─────────────────────────────────────────────────
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var micAvail = !!SR; var recog = null, micOn = false;
  el('lab-mic-avail').textContent = micAvail ? '' : '(SpeechRecognition unavailable)';
  el('lab-mic').disabled = !micAvail;
  function stopMic() { if (recog) { try { recog.stop(); } catch (e) {} recog = null; } micOn = false; var b = el('lab-mic'); b.setAttribute('aria-pressed', 'false'); b.textContent = '🎙 Start mic'; }
  el('lab-mic').addEventListener('click', function () {
    if (!micAvail) return;
    if (micOn) { stopMic(); return; }
    recog = new SR(); recog.continuous = true; recog.interimResults = true;
    recog.onstart = function () { micOn = true; var b = el('lab-mic'); b.setAttribute('aria-pressed', 'true'); b.textContent = '● Listening — stop mic'; el('lab-state').textContent = 'LISTENING'; };
    recog.onresult = function (e) { if (el('lab-state').textContent === 'SPEAKING') doBargeIn(); };
    recog.onerror = function (e) { el('lab-bargein-diag').textContent = 'mic error: ' + (e.error || '?'); stopMic(); };
    recog.onend = function () { stopMic(); };
    try { recog.start(); } catch (e) { el('lab-bargein-diag').textContent = 'mic start failed'; }
  });
  function doBargeIn() { var m = cancel.bargeIn(); el('lab-bargein-diag').textContent = 'barge-in reaction ≈ ' + Math.round(m.reaction_ms) + 'ms → LISTENING (browser-limited)'; el('lab-state').textContent = 'LISTENING'; }
  el('lab-bargein').addEventListener('click', doBargeIn);

  // route/lifecycle cleanup + hidden-tab (§26/§27)
  window.addEventListener('beforeunload', function () { cancel.teardown('nav'); stopMic(); if (idleRaf) cancelAnimationFrame(idleRaf); stopLoops(); });
  document.addEventListener('visibilitychange', function () { if (document.hidden) { if (idleRaf) { cancelAnimationFrame(idleRaf); idleRaf = null; } } else if (!idleRaf && !REDUCE) { idleT0 = now(); idleRaf = requestAnimationFrame(idleFrame); } });

  // ── tabs ────────────────────────────────────────────────────────────────────
  document.querySelectorAll('.lab-tab').forEach(function (t) {
    t.addEventListener('click', function () {
      document.querySelectorAll('.lab-tab').forEach(function (x) { x.classList.toggle('active', x === t); });
      document.querySelectorAll('.lab-panel').forEach(function (p) { p.classList.toggle('active', p.dataset.panel === t.dataset.tab); });
    });
  });

  buildFace(); showCoeffs(VE.restCoeffs());
  window.KaiAvatarLab = { face: face, driver: driver, provider: provider, queue: queue, cancel: cancel, speakStreamed: speakStreamed, playUnits: playUnits, setCoeffs: setCoeffs };
})();
