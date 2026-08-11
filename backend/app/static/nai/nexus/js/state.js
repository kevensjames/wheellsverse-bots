// ============================================================================
// KAI state machine + event bus  (Increment 5)
// Single source of truth for KAI's state. Sets <html data-kai="..."> so the
// whole design system re-themes, and broadcasts on a tiny pub/sub bus that the
// avatar, panels, sound and transitions all subscribe to.
// ============================================================================

// Canonical KAI states. 'idle' is the resting PRESENCE state; 'sleep' is a
// deeper dormant state; 'understanding' bridges listening → thinking.
export const STATES = [
  'idle', 'listening', 'understanding', 'thinking', 'researching',
  'executing', 'speaking', 'success', 'warning', 'critical', 'sleep',
];

// States that KAI settles back into; transient states auto-revert to these.
const STABLE = new Set(['idle', 'listening', 'warning', 'critical', 'sleep']);

const GREET = {
  idle:         'What can I do for you?',
  listening:    'Listening…',
  understanding:'Understanding…',
  thinking:     'Thinking it through…',
  speaking:     '',                       // greeting is replaced by the reply
  executing:    'On it — executing.',
  researching:  'Researching across sources…',
  warning:      'Something needs your attention.',
  critical:     'Critical condition detected.',
  success:      'Done.',
  sleep:        '',
};

// ---- event bus -------------------------------------------------------------
class Bus {
  #m = new Map();
  on(evt, fn)  { (this.#m.get(evt) ?? this.#m.set(evt, new Set()).get(evt)).add(fn); return () => this.off(evt, fn); }
  off(evt, fn) { this.#m.get(evt)?.delete(fn); }
  emit(evt, p) { this.#m.get(evt)?.forEach(fn => { try { fn(p); } catch (e) { console.error(e); } }); }
}
export const bus = new Bus();

// ---- controller ------------------------------------------------------------
class KaiController {
  #state = 'idle';
  #prevStable = 'idle';
  #revertT = 0;

  get state() { return this.#state; }
  get greeting() { return GREET[this.#state] ?? ''; }
  get isStable() { return STABLE.has(this.#state); }

  set(state, meta = {}) {
    if (!STATES.includes(state) || state === this.#state) {
      if (state === this.#state) bus.emit('state:refresh', { state, meta });
      return;
    }
    if (STABLE.has(this.#state)) this.#prevStable = this.#state;
    clearTimeout(this.#revertT);
    this.#state = state;
    document.documentElement.dataset.kai = state;
    bus.emit('state', { state, prev: this.#prevStable, meta, greeting: this.greeting });
  }

  // Flash a transient state for `ms`, then settle back to the last stable one.
  transient(state, ms = 1600, meta = {}) {
    this.set(state, meta);
    clearTimeout(this.#revertT);
    this.#revertT = setTimeout(() => this.set(this.#prevStable, { auto: true }), ms);
  }

  settle() { this.set(this.#prevStable, { auto: true }); }
}

export const KAI = new KaiController();

// Boot into idle so the design system has an accent immediately.
document.documentElement.dataset.kai = 'idle';
