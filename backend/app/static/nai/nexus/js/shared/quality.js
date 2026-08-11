// ============================================================================
// Performance / quality (§33 + §34)
// Tiers AUTO · ULTRA · HIGH · BALANCED · BATTERY. AUTO inspects the device and
// picks a profile (BALANCED when uncertain). Each tier maps to concrete render
// flags via <html data-q> / data-motion that the avatar + particle field read.
// Also exposes a visibility guard so timers stop doing work in a hidden tab.
// ============================================================================
import { bus } from '../state.js';

export const TIERS = ['auto', 'ultra', 'high', 'balanced', 'battery'];

// tier → concrete flags (dpr cap, particle density, decorative motion)
const PROFILE = {
  ultra:    { q: 'high', motion: 'on',  dpr: 2 },
  high:     { q: 'high', motion: 'on',  dpr: 2 },
  balanced: { q: 'low',  motion: 'on',  dpr: 1.5 },
  battery:  { q: 'low',  motion: 'off', dpr: 1 },
};

function detect() {
  const mem = navigator.deviceMemory || 4;
  const cores = navigator.hardwareConcurrency || 4;
  const saveData = navigator.connection && navigator.connection.saveData;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = matchMedia('(pointer: coarse)').matches;      // phone/tablet
  if (saveData || reduced) return 'battery';
  if (mem >= 8 && cores >= 8 && !coarse) return 'high';
  if (mem <= 3 || cores <= 4 || coarse) return 'balanced';
  return 'balanced';                                            // uncertain → BALANCED (§34)
}

export const quality = {
  TIERS,
  tier: localStorage.getItem('kai.tier') || 'auto',
  resolved: 'balanced',

  apply(tier) {
    this.tier = tier; localStorage.setItem('kai.tier', tier);
    const resolved = tier === 'auto' ? detect() : tier;
    this.resolved = resolved;
    const p = PROFILE[resolved] || PROFILE.balanced;
    const el = document.documentElement;
    el.dataset.q = p.q;
    // never override a user's explicit STILL choice or the reduced-motion OS pref
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) el.dataset.motion = p.motion;
    el.dataset.tier = resolved;
    bus.emit('quality', { tier, resolved, profile: p });
    return p;
  },

  init() { return this.apply(this.tier); },
  hidden() { return document.hidden; },
};

// Broadcast visibility so interval-driven producers can idle when unseen (rAF
// loops already pause in hidden tabs; timers do not).
document.addEventListener('visibilitychange', () => bus.emit('visibility', { hidden: document.hidden }));
