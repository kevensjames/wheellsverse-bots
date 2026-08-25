// ============================================================================
// KAI NEXUS — canonical Signal model + intelligence logic (Phase 6B). PURE.
// UMD: window.NexusIntel in the browser, module.exports in node.
//
// Data honesty (§6H): every signal carries provenance; nothing is REAL without a
// real source. Security (§6AD/§6AE): external signal text is UNTRUSTED DATA —
// source_url is scheme-validated (http/https only), text is never HTML/eval'd
// (the UI renders via textContent), and content never gains authority over KAI
// (a signal fed to "Ask KAI" goes in as a USER message, never a system/tool
// instruction). Fact vs analysis (§6C) stay in separate fields.
// ============================================================================
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NexusIntel = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const CATEGORIES = ['AI', 'TECH', 'CYBERSECURITY', 'FINANCE', 'MARKETS', 'WORLD', 'STARTUPS', 'INFRASTRUCTURE', 'REGULATION'];
  const VERIFICATION = ['PRIMARY_SOURCE', 'CORROBORATED', 'SINGLE_SOURCE', 'UNVERIFIED', 'CONFLICTING', 'STALE', 'UNKNOWN'];
  const IMPORTANCE = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'];
  const SOURCE_HEALTH = ['NOMINAL', 'DEGRADED', 'OFFLINE', 'STALE', 'UNKNOWN'];

  // ── URL safety (§6AD) — only absolute http/https; reject javascript:/data:/file:/relative.
  function safeUrl(url) {
    if (typeof url !== 'string' || !url.trim()) return null;
    let u; try { u = new URL(url.trim()); } catch { return null; }   // relative/garbage → throws → null
    return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : null;
  }
  // Defensive HTML escaper (the UI uses textContent, but expose for any raw path).
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const _canonUrl = (u) => { try { const x = new URL(u); return x.hostname.replace(/^www\./, '').toLowerCase() + x.pathname.replace(/\/+$/, '').toLowerCase(); } catch { return u; } };
  const _domain = (url) => { const s = safeUrl(url); if (!s) return null; try { return new URL(s).hostname.replace(/^www\./, '').toLowerCase(); } catch { return null; } };
  const _normHeadline = (h) => String(h || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
  const _srcKey = (s) => _domain(s.source_url) || (s.source_name ? 'name:' + String(s.source_name).toLowerCase() : null);
  function _hash(s) { let h = 5381; s = String(s); for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; return 'sig_' + h.toString(36); }

  // §6M freshness — real timestamps only; unknown stays UNKNOWN (never faked).
  function freshness(publishedAt, now) {
    if (typeof publishedAt !== 'number') return 'UNKNOWN';
    const dt = now - publishedAt; if (dt < 0) return 'UNKNOWN';
    if (dt < 5 * 60e3) return 'NOW';
    if (dt < 60 * 60e3) return '<1H';
    if (dt < 24 * 3600e3) return 'TODAY';
    if (dt < 48 * 3600e3) return '1D';
    if (dt < 7 * 24 * 3600e3) return '2-7D';
    return 'STALE';
  }

  function normalizeSignal(raw) {
    const url = safeUrl(raw.source_url);
    return {
      signal_id: raw.signal_id || raw.id || _hash((raw.headline || '') + '|' + (raw.source_url || '')),
      category: CATEGORIES.includes(String(raw.category || '').toUpperCase()) ? String(raw.category).toUpperCase() : 'TECH',
      headline: String(raw.headline || '').slice(0, 400),        // stored as DATA (untrusted); UI uses textContent
      summary: String(raw.summary || '').slice(0, 2000),
      source_name: String(raw.source_name || 'unknown'),
      source_type: raw.source_type === 'primary' ? 'primary' : (raw.source_type === 'secondary' ? 'secondary' : 'unknown'),
      source_url: url,                                           // null if unsafe/relative scheme
      source_url_rejected: !url && !!raw.source_url,             // a url was present but rejected as unsafe
      published_at: typeof raw.published_at === 'number' ? raw.published_at : null,
      observed_at: typeof raw.observed_at === 'number' ? raw.observed_at : null,
      verification_status: VERIFICATION.includes(raw.verification_status) ? raw.verification_status : 'UNKNOWN',
      corroboration_count: typeof raw.corroboration_count === 'number' ? raw.corroboration_count : (url ? 1 : 0),
      corroborating_sources: Array.isArray(raw.corroborating_sources) ? raw.corroborating_sources : [],
      entities: Array.isArray(raw.entities) ? raw.entities.slice(0, 20).map(String) : [],
      topics: Array.isArray(raw.topics) ? raw.topics.slice(0, 20).map(String) : [],
      regions: Array.isArray(raw.regions) ? raw.regions : [],
      related_businesses: Array.isArray(raw.related_businesses) ? raw.related_businesses : [],
      related_systems: Array.isArray(raw.related_systems) ? raw.related_systems : [],
      related_missions: Array.isArray(raw.related_missions) ? raw.related_missions : [],
      importance: IMPORTANCE.includes(String(raw.importance || '').toUpperCase()) ? String(raw.importance).toUpperCase() : 'UNKNOWN',
      relevance: (raw.relevance && typeof raw.relevance === 'object' && Array.isArray(raw.relevance.reasons)) ? raw.relevance : null, // never a bare number
      analysis: raw.analysis ? String(raw.analysis).slice(0, 2000) : null,   // KAI ANALYSIS — kept separate from source facts (§6C)
      recommended_actions: Array.isArray(raw.recommended_actions) ? raw.recommended_actions.map(String) : [],
      provenance: raw.provenance || 'UNKNOWN',
      untrusted: true,                                          // §6AE — always external/untrusted
      metadata: raw.metadata || {},
    };
  }

  // §6K/§6L — dedupe exact-same-article (canonical URL), then corroborate an EVENT
  // across DISTINCT sources. Mirrors/syndications from ONE source do NOT count.
  function dedupeAndCorroborate(signals) {
    const byUrl = new Map(); const noUrl = [];
    for (const s of signals) { const u = safeUrl(s.source_url); if (u) { const k = _canonUrl(u); if (!byUrl.has(k)) byUrl.set(k, s); } else noUrl.push(s); }
    const unique = [...byUrl.values(), ...noUrl];
    const groups = new Map();
    for (const s of unique) { const ev = _normHeadline(s.headline) || _srcKey(s) || s.signal_id; if (!groups.has(ev)) groups.set(ev, []); groups.get(ev).push(s); }
    const out = [];
    for (const grp of groups.values()) {
      const distinct = new Set(grp.map(_srcKey).filter(Boolean));
      const primary = grp.find(x => x.source_type === 'primary') || grp[0];
      const corroborated = distinct.size >= 2;
      out.push(Object.assign({}, primary, {
        verification_status: corroborated ? 'CORROBORATED' : (primary.source_type === 'primary' ? 'PRIMARY_SOURCE' : (primary.verification_status || 'SINGLE_SOURCE')),
        corroboration_count: distinct.size || (grp.length ? 1 : 0),
        corroborating_sources: grp.map(x => ({ source_name: x.source_name, source_url: safeUrl(x.source_url), source_type: x.source_type })),
      }));
    }
    return out;
  }

  // §6O — explainable relevance. Returns {score, reasons} ONLY when factors match;
  // never a bare number. context: {mission_text, systems[], businesses[], stack[]}.
  function computeRelevance(signal, context) {
    if (!context) return null;
    const hay = (signal.headline + ' ' + signal.summary + ' ' + (signal.entities || []).join(' ')).toLowerCase();
    const reasons = [];
    for (const sys of (context.systems || [])) if (sys && hay.includes(String(sys).toLowerCase())) reasons.push('mentions ' + sys);
    for (const biz of (context.businesses || [])) if (biz && hay.includes(String(biz).toLowerCase())) reasons.push('affects ' + biz);
    for (const tech of (context.stack || [])) if (tech && hay.includes(String(tech).toLowerCase())) reasons.push('stack: ' + tech);
    if (context.mission_text && signal.category === 'INFRASTRUCTURE' && /latency|deploy|database|postgres|\bdb\b|redis/.test(String(context.mission_text).toLowerCase()) && /latency|deploy|database|postgres|redis/.test(hay)) reasons.push('relevant to current mission');
    if (!reasons.length) return null;
    return { score: Math.min(99, 40 + reasons.length * 18), reasons };
  }

  // §6P — a signal becomes an alert only on explicit criteria + evidence.
  function promoteToAlert(signal) {
    const hay = (signal.headline + ' ' + signal.summary).toLowerCase();
    let rule = null, severity = null;
    if (signal.category === 'CYBERSECURITY' && /critical|\brce\b|zero-day|zeroday|actively exploited/.test(hay)) { rule = 'critical-security-advisory'; severity = 'critical'; }
    else if (signal.category === 'INFRASTRUCTURE' && /outage|down|incident/.test(hay) && (signal.related_systems || []).length) { rule = 'provider-outage-affecting-dependency'; severity = 'warning'; }
    else if (signal.category === 'REGULATION' && (signal.related_businesses || []).length) { rule = 'regulation-affecting-active-business'; severity = 'warning'; }
    else if (signal.category === 'FINANCE' && /payment|payout|reconciliation|dwolla|stripe/.test(hay) && (signal.related_systems || []).length) { rule = 'payment-provider-incident'; severity = 'warning'; }
    if (!rule) return null;
    return { signal_id: signal.signal_id, rule, severity, evidence: signal.source_url || signal.source_name, timestamp: signal.published_at || signal.observed_at, title: signal.headline };
  }

  // §6S — source freshness → health (never let a silent-empty feed read as "no news").
  function sourceHealth(lastUpdate, now, ttlMs) {
    if (typeof lastUpdate !== 'number') return 'UNKNOWN';
    const dt = now - lastUpdate;
    if (dt < ttlMs) return 'NOMINAL';
    if (dt < ttlMs * 3) return 'DEGRADED';
    return 'STALE';
  }

  function summarize(signals) {
    const c = { TOTAL: 0, VERIFIED: 0, CORROBORATED: 0, PRIMARY: 0, HIGH: 0, STALE: 0 };
    for (const s of signals) { c.TOTAL++; if (s.verification_status === 'CORROBORATED') { c.CORROBORATED++; c.VERIFIED++; } if (s.verification_status === 'PRIMARY_SOURCE') { c.PRIMARY++; c.VERIFIED++; } if (s.importance === 'HIGH' || s.importance === 'CRITICAL') c.HIGH++; if (s.verification_status === 'STALE') c.STALE++; }
    return c;
  }

  return { CATEGORIES, VERIFICATION, IMPORTANCE, SOURCE_HEALTH, safeUrl, escapeHtml, freshness, normalizeSignal, dedupeAndCorroborate, computeRelevance, promoteToAlert, sourceHealth, summarize };
});
