// ============================================================================
// Data honesty (§36 + §6 CRITICAL RULE + §45 anti-scaffolding)
// A dashboard must never present invented values as real. Every domain carries
// a freshness level; panels render a badge from it; the header shows a global
// DEMO indicator whenever anything is simulated. When real feeds are wired,
// call dataFreshness.set('<domain>', FRESH.LIVE) and the badges flip automatically.
// ============================================================================
import { bus } from '../state.js';

export const FRESH = { LIVE: 'live', CACHED: 'cached', STALE: 'stale', DEMO: 'demo', UNAVAILABLE: 'unavailable' };
const LABEL = { live: 'LIVE', cached: 'CACHED', stale: 'STALE', demo: 'DEMO', unavailable: 'NO DATA' };
const TITLE = {
  live: 'Live data from a real source',
  cached: 'Recent value, may be slightly behind',
  stale: 'Last known value — the source is not updating',
  demo: 'Simulated sample data — NOT a live feed',
  unavailable: 'No data available from the source',
};

// Every domain defaults to DEMO — nothing is "live" until a real feed proves it.
const state = new Map();

export const dataFreshness = {
  FRESH,
  set(domain, level) { state.set(domain, level); bus.emit('freshness', { domain, level }); },
  level(domain) { return state.get(domain) || FRESH.DEMO; },
  isDemo(domain) { return this.level(domain) === FRESH.DEMO; },
  anyReal() { for (const v of state.values()) if (v === FRESH.LIVE || v === FRESH.CACHED) return true; return false; },
  allDemo() { for (const v of state.values()) if (v !== FRESH.DEMO) return false; return state.size > 0; },

  // a small, safe-DOM badge element
  badge(domain) {
    const lvl = typeof domain === 'string' && FRESH[domain.toUpperCase()] ? domain : this.level(domain);
    const s = document.createElement('span');
    s.className = 'fresh fresh-' + lvl;
    s.textContent = LABEL[lvl] || lvl.toUpperCase();
    s.title = TITLE[lvl] || '';
    s.setAttribute('aria-label', 'data status: ' + (LABEL[lvl] || lvl));
    return s;
  },
};
