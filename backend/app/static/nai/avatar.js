// KAI Avatar — a PHOTOREAL human (generated with Higgsfield) presented as a
// living portrait. No WebGL/3D: the face is a real rendered human, and "life"
// is done with CSS — breathing, cursor-follow parallax, a glowing mood aura,
// and a speaking pulse + equalizer. Far more human than any procedural mesh.
//
// Same public API as the old 3D avatar so command.js is unchanged:
//   new KaiAvatar(canvas); .start()/.stop(); .setSpeaking(b); .pulseMouth(s);
//   .setThinking(b); .setMood(name); .setState({...}); .dispose()
//
// To swap KAI's face: replace kai_portrait.png (or pass {src}) — e.g. a new
// Higgsfield render or a Ready Player Me export.

const MOODS = {
  calm: '#35c6ff', focused: '#2f8bff', happy: '#22f0d6', alert: '#ffb347', critical: '#ff4d6d',
};

export class KaiAvatar {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.opts = opts;
    this.running = false;
    this.ready = false;
    this.mood = 'calm';
    this.speaking = false;
    this.thinking = false;

    this.stage = (canvas && canvas.parentElement) || document.body;
    if (canvas) canvas.style.display = 'none';   // retire the old 3D canvas

    this.root = document.createElement('div');
    this.root.className = 'kai-photo-wrap';

    this.aura = document.createElement('div');
    this.aura.className = 'kai-aura';

    // A looping cinematic video (Higgsfield) is the living face; the still
    // portrait is the poster + fallback if video can't play.
    this.photo = document.createElement('video');
    this.photo.className = 'kai-photo';
    this.photo.muted = true; this.photo.loop = true; this.photo.autoplay = true;
    this.photo.playsInline = true;
    this.photo.setAttribute('muted', ''); this.photo.setAttribute('playsinline', '');
    this.photo.poster = opts.poster || './kai_portrait.png';
    this.photo.src = opts.src || './kai_avatar.mp4';
    this.photo.addEventListener('loadeddata', () => { this.ready = true; this.photo.play().catch(() => {}); });
    this.photo.addEventListener('error', () => this._useStill());

    this.eq = document.createElement('div');
    this.eq.className = 'kai-eq';
    for (let i = 0; i < 5; i++) this.eq.appendChild(document.createElement('span'));

    this.root.appendChild(this.aura);
    this.root.appendChild(this.photo);
    this.root.appendChild(this.eq);
    this.stage.appendChild(this.root);

    this.setMood('calm');

    // cursor-follow parallax — KAI subtly leans toward you
    this._onPointer = (e) => {
      const r = this.stage.getBoundingClientRect();
      if (!r.width) return;
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      this.root.style.setProperty('--kx', (x * 12).toFixed(1) + 'px');
      this.root.style.setProperty('--ky', (y * 9).toFixed(1) + 'px');
      this.root.style.setProperty('--kr', (x * 2.4).toFixed(2) + 'deg');
    };
    window.addEventListener('pointermove', this._onPointer, { passive: true });
  }

  _useStill() {
    try {
      const img = document.createElement('img');
      img.className = 'kai-photo'; img.alt = 'KAI'; img.src = './kai_portrait.png';
      img.addEventListener('load', () => { this.ready = true; });
      img.addEventListener('error', () => { this.root.classList.add('kai-photo-missing'); this.ready = true; });
      if (this.photo && this.photo.parentElement) this.photo.replaceWith(img);
      this.photo = img;
    } catch (_) { this.root.classList.add('kai-photo-missing'); this.ready = true; }
  }

  start() { if (this.running) return; this.running = true; this.root.classList.add('kai-live'); }
  stop() { this.running = false; this.root.classList.remove('kai-live'); }

  setSpeaking(on) { this.speaking = !!on; this.root.classList.toggle('kai-speaking', !!on); }
  pulseMouth() {
    this.root.classList.add('kai-pulse');
    clearTimeout(this._pt);
    this._pt = setTimeout(() => this.root.classList.remove('kai-pulse'), 150);
  }
  setThinking(on) { this.thinking = !!on; this.root.classList.toggle('kai-thinking', !!on); }

  setMood(name) {
    const c = MOODS[name] || MOODS.calm;
    this.mood = name;
    this.root.style.setProperty('--kai-glow', c);
  }
  setState({ securityScore = null, alerts = 0, plansActive = 0, mood = null } = {}) {
    if (mood && MOODS[mood]) { this.setMood(mood); return; }
    let n = 'calm';
    if (securityScore != null && securityScore < 40) n = 'critical';
    else if (alerts >= 3) n = 'alert';
    else if (alerts >= 1 || plansActive >= 1) n = 'focused';
    this.setMood(n);
  }

  dispose() {
    this.stop();
    clearTimeout(this._pt);
    window.removeEventListener('pointermove', this._onPointer);
    if (this.root && this.root.parentElement) this.root.parentElement.removeChild(this.root);
  }
}
