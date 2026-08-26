/* KAI Adaptive Mission Nexus — Capabilities panel (§54–57). UMD, DOM via injected document.
 *
 * Renders the CAPABILITIES view: capability · state · mode, plus a per-capability inspector.
 * Two honesty rules:
 *   (§54) NEVER display a fake READY — state is derived strictly from the catalog's real
 *         availability (AVAILABLE→READY; DISCOVERED/EXTERNAL_BLOCKED/QUARANTINED shown as-is).
 *   (§55) The inspector NEVER shows credentials/secrets — only public provenance + policy.
 * Category mapping (§57) drives which functional-halo lane lights when a capability is used.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.NexusCapabilities = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // §54 honest state — availability is the source of truth; a disabled activation shows DISABLED
  function stateLabel(cap) {
    var av = cap.availability;
    if (av === 'QUARANTINED') return 'QUARANTINED';
    if (av === 'EXTERNAL_BLOCKED') return 'BLOCKED';
    if (av === 'DISCOVERED') return 'DISCOVERED';
    if (cap.activation === 'DISABLED') return 'DISABLED';
    if (av === 'AVAILABLE') return 'READY';
    return 'UNKNOWN';
  }

  function modeLabel(cap) {
    if (cap.risk_class === 'RESTRICTED') return 'RESTRICTED';   // override — never reads as plain AUTO
    switch (cap.activation) {
      case 'ALWAYS_AVAILABLE': return 'AUTO';
      case 'ON_DEMAND': return 'ON DEMAND';
      case 'BACKGROUND': return 'BACKGROUND';
      case 'MANUAL_ONLY': return 'MANUAL';
      case 'DISABLED': return 'DISABLED';
      default: return '—';
    }
  }

  // §57 functional-halo categories
  var _TYPE_CAT = {
    KNOWLEDGE_PACK: 'KNOWLEDGE', CODE_TOOL: 'CODE', AGENT_RUNTIME: 'CODE',
    MEMORY_PROVIDER: 'MEMORY', SECURITY_ROUTER: 'ACTIVE SECURITY', BROWSER_TOOL: 'BROWSER',
    GEOSPATIAL_TOOL: 'GEO', COLLABORATION_TOOL: 'COLLABORATION', WORKSPACE_ADAPTER: 'COLLABORATION',
    MODEL_RUNTIME: 'INFERENCE', AGENT_SKILL: 'KNOWLEDGE',
    // expansion groups (§49) — high-risk security tiers are visually distinct, never plain "tools"
    SECURITY_KNOWLEDGE_PACK: 'SECURITY REFERENCE', SECURITY_DATA_PACK: 'SECURITY REFERENCE',
    OSINT_RESOURCE_PACK: 'OSINT', AGENT_BEHAVIOR_POLICY: 'AGENT BEHAVIOR',
    SECURITY_EXECUTION_FRAMEWORK: 'ADVERSARY EMULATION',
    // coding agent pool (§23) — grouped as CODING WORKFORCE
    CODING_WORKER: 'CODING WORKFORCE', CODING_CLI: 'CODING WORKFORCE',
    CODING_IDE_ADAPTER: 'CODING WORKFORCE', CODING_CLOUD_AGENT: 'CODING WORKFORCE',
  };
  function categoryOf(cap) {
    // a mobile-design agent skill groups under MOBILE DESIGN, not generic KNOWLEDGE
    if (cap.type === 'AGENT_SKILL' && /mobile|react_native|onboarding|paywall/.test((cap.capabilities || []).join(' ').toLowerCase())) return 'MOBILE DESIGN';
    if (cap.type in _TYPE_CAT) return _TYPE_CAT[cap.type];
    if (cap.type === 'MCP' || cap.type === 'NATIVE_KAI_TOOL') {
      var caps = (cap.capabilities || []).join(' ').toLowerCase();
      if (/doc|reference|library/.test(caps)) return 'KNOWLEDGE';
      if (/memory|recall/.test(caps)) return 'MEMORY';
      if (/file|repo|read_files|write_files|pr|issue/.test(caps)) return 'CODE';
      if (/browser|screenshot|dom/.test(caps)) return 'BROWSER';
    }
    return 'CODE';
  }

  function buildCapabilityRows(catalog) {
    return (catalog.capabilities || []).map(function (c) {
      return { id: c.id, name: c.name, state: stateLabel(c), mode: modeLabel(c),
               risk: c.risk_class, category: categoryOf(c), certification: c.certification };
    });
  }

  // §55 inspector — public detail only, NEVER credentials
  var _INSPECTOR_FIELDS = ['name', 'type', 'version', 'availability', 'certification', 'activation',
    'risk_class', 'capabilities', 'triggers', 'dependencies', 'conflicts', 'permissions', 'notes'];
  function inspect(cap) {
    var out = { id: cap.id };
    _INSPECTOR_FIELDS.forEach(function (f) { if (cap[f] != null) out[f] = cap[f]; });
    var p = cap.provenance || {};
    // provenance is public supply-chain metadata only; the generator already stripped secrets
    out.provenance = { upstream: p.upstream || '', owner: p.owner || '', license: p.license || '',
                       ref: p.ref || '', verified: !!p.verified };
    return out;   // no credentials key exists, by construction
  }

  // ── DOM rendering (document injected for testability) ─────────────────────────
  function renderPanel(rootEl, catalog, opts) {
    opts = opts || {};
    var doc = opts.document || (typeof document !== 'undefined' ? document : null);
    if (!doc || !rootEl) return;
    while (rootEl.firstChild) rootEl.removeChild(rootEl.firstChild);
    var rows = buildCapabilityRows(catalog);
    var table = doc.createElement('table');
    table.className = 'kai-cap-table';
    var head = doc.createElement('tr');
    ['CAPABILITY', 'STATE', 'MODE', 'RISK', 'CATEGORY'].forEach(function (h) {
      var th = doc.createElement('th'); th.textContent = h; head.appendChild(th);
    });
    table.appendChild(head);
    rows.forEach(function (r) {
      var tr = doc.createElement('tr');
      tr.dataset.capId = r.id;
      tr.dataset.state = r.state;
      [r.name, r.state, r.mode, r.risk, r.category].forEach(function (v) {
        var td = doc.createElement('td'); td.textContent = v; tr.appendChild(td);
      });
      if (typeof opts.onSelect === 'function') tr.addEventListener('click', function () { opts.onSelect(r.id); });
      table.appendChild(tr);
    });
    rootEl.appendChild(table);
    return rows.length;
  }

  return {
    stateLabel: stateLabel, modeLabel: modeLabel, categoryOf: categoryOf,
    buildCapabilityRows: buildCapabilityRows, inspect: inspect, renderPanel: renderPanel,
  };
});
