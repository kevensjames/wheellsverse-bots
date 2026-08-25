// ============================================================================
// KAI NEXUS — systems telemetry model + topology (Phase 4B/4D). PURE (no DOM).
// UMD: window.NexusSystems in the browser, module.exports in node.
//
// Data honesty (§4F): status is DERIVED from real probe results; deep metrics
// with no source are UNAVAILABLE, never faked. Alerts (§4K) come only from real
// state. Topology (§4D) is the actual repo architecture, not invented.
// ============================================================================
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NexusSystems = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const STATES = ['NOMINAL', 'DEGRADED', 'CAUTION', 'WARNING', 'CRITICAL', 'OFFLINE', 'UNKNOWN'];

  // Canonical topology — the real architecture (see docs/KAI_TELEMETRY_SOURCES.md).
  // `probe` = a REAL liveness endpoint (null ⇒ no probe ⇒ UNKNOWN unless a
  // scenario/other signal sets it; never green-by-default).
  const TOPOLOGY = {
    nodes: [
      { id: 'client', name: 'Client', type: 'client', layer: 0, probe: null },
      { id: 'cloudflare', name: 'Cloudflare', sub: 'apex', type: 'edge', layer: 1, probe: null },
      { id: 'appA', name: 'App A', sub: 'core/api', type: 'app', layer: 2, probe: '/api/v2/narai/health' },
      { id: 'bridge', name: 'Bridge', sub: '/admin/kai/*', type: 'bridge', layer: 2, probe: '/admin/kai-bridge/health' },
      { id: 'appB', name: 'App B', sub: 'KAI brain', type: 'app', layer: 3, probe: '/health' },
      { id: 'postgres', name: 'Postgres', type: 'db', layer: 4, probe: null },
      { id: 'redis', name: 'Redis', type: 'cache', layer: 4, probe: null },
      { id: 'providers', name: 'Providers', sub: 'ollama/openai', type: 'provider', layer: 4, probe: null },
    ],
    edges: [
      ['client', 'cloudflare'], ['cloudflare', 'appA'], ['appA', 'bridge'], ['bridge', 'appB'],
      ['appB', 'postgres'], ['appB', 'redis'], ['appB', 'providers'],
    ],
  };

  // Map a probe result to a discrete state (§4F: discrete > fake %).
  function classifyProbe(res) {
    if (!res || res.error) return 'UNKNOWN';
    if (res.ok) return 'NOMINAL';
    if (res.status >= 500) return 'CRITICAL';
    if (res.status === 429 || res.status === 408) return 'WARNING';
    if (res.status >= 400) return 'DEGRADED';
    return 'UNKNOWN';
  }

  function summarize(nodes) {
    const c = { NOMINAL: 0, DEGRADED: 0, CAUTION: 0, WARNING: 0, CRITICAL: 0, OFFLINE: 0, UNKNOWN: 0 };
    for (const n of nodes) { const s = String(n.status || 'UNKNOWN').toUpperCase(); if (c[s] != null) c[s]++; else c.UNKNOWN++; }
    return c;
  }

  function isStale(node, now, ttlMs) { return !node.last_seen || (now - node.last_seen) > ttlMs; }

  // §4K — alerts come ONLY from real/derived state, never arbitrary.
  function alertsFromSystems(nodes) {
    const out = [];
    for (const n of nodes) {
      const s = String(n.status || '').toUpperCase();
      if (s === 'CRITICAL') out.push({ sev: 'critical', system: n.id, title: n.name + ' critical', detail: n.detail || 'subsystem critical', source: n.provenance || 'DERIVED' });
      else if (s === 'OFFLINE') out.push({ sev: 'warning', system: n.id, title: n.name + ' offline', detail: 'no successful probe', source: n.provenance || 'DERIVED' });
      else if (s === 'WARNING') out.push({ sev: 'warning', system: n.id, title: n.name + ' warning', detail: n.detail || '', source: n.provenance || 'DERIVED' });
    }
    return out;
  }

  // Exponential backoff with jitter (§4H). fails: consecutive failure count.
  function backoffMs(base, fails, cap) {
    const b = Math.min(cap || 60000, (base || 20000) * Math.pow(2, Math.max(0, fails)));
    return Math.round(b * (0.75 + 0.5 * ((fails * 2654435761 % 1000) / 1000))); // deterministic jitter (no Math.random)
  }

  return { STATES, TOPOLOGY, classifyProbe, summarize, isStale, alertsFromSystems, backoffMs };
});
