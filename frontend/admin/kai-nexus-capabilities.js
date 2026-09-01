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

  // ══ EXECUTION UI (§3-9) — the live governed-execution layer over the catalog ══════════════
  // Execution talks to App B via the bridge path /admin/kai/capabilities/* (NEVER App A's own
  // /admin/capabilities* catalog routes — §16 contract). The catalog display is unchanged.
  var EXEC_BASE = '/admin/kai/capabilities';

  // §33 truthful KAI-server runtime state (backend is authoritative; fall back to honest CATALOG_ONLY)
  function serverStateLabel(meta) {
    return (meta && meta.server_state) ? meta.server_state : 'CATALOG_ONLY';
  }

  // §4 a TEST button is offered ONLY when the backend declares a safe_test operation (never invented)
  function testableOperation(meta) {
    var op = ((meta && meta.operations) || []).filter(function (o) { return o.safe_test; })[0];
    return op ? op.operation : null;
  }

  // §6 execution status → display label
  function executionStateLabel(status) {
    switch (String(status || '').toUpperCase()) {
      case 'OK': case 'COMPLETED': return 'COMPLETED';
      case 'RUNNING': return 'RUNNING';
      case 'APPROVAL_REQUIRED': return 'APPROVAL REQUIRED';
      case 'DENIED': case 'OPERATION_NOT_ENABLED': return 'DENIED';
      case 'CAPABILITY_UNAVAILABLE': return 'UNAVAILABLE';
      case 'INPUT_REJECTED': return 'REJECTED';
      case 'RATE_LIMITED': return 'RATE LIMITED';
      case 'TIMEOUT': return 'TIMEOUT';
      case 'FAILED': return 'FAILED';
      default: return status || '—';
    }
  }

  // §7 halo lane + a SAFE activity label — never exposes model reasoning
  var _ACTIVITY = { 'yt-dlp': 'Inspecting media metadata', 'markitdown': 'Converting document',
                    'codebase-memory-mcp': 'Searching code knowledge' };
  function activityLabel(capId) { return _ACTIVITY[capId] || 'Running capability'; }
  function haloLane(cap) { return categoryOf(cap); }

  // §5 invocation history rows — public fields only (no request bodies, no secrets)
  function historyRows(invocations) {
    return (invocations || []).map(function (i) {
      return { capability: i.capability, operation: i.operation, state: executionStateLabel(i.status),
               duration_ms: i.duration_ms, provenance: i.provenance, correlation_id: i.correlation_id };
    });
  }
  function renderHistory(rootEl, invocations, opts) {
    opts = opts || {};
    var doc = opts.document || (typeof document !== 'undefined' ? document : null);
    if (!doc || !rootEl) return 0;
    while (rootEl.firstChild) rootEl.removeChild(rootEl.firstChild);
    var rows = historyRows(invocations);
    var table = doc.createElement('table'); table.className = 'kai-cap-history';
    var head = doc.createElement('tr');
    ['CAPABILITY', 'OPERATION', 'STATE', 'MS', 'PROVENANCE', 'CORRELATION'].forEach(function (h) {
      var th = doc.createElement('th'); th.textContent = h; head.appendChild(th);
    });
    table.appendChild(head);
    rows.forEach(function (r) {
      var tr = doc.createElement('tr'); tr.dataset.state = r.state;
      [r.capability, r.operation, r.state, r.duration_ms, r.provenance, r.correlation_id]
        .forEach(function (v) { var td = doc.createElement('td'); td.textContent = (v == null ? '—' : v); tr.appendChild(td); });
      table.appendChild(tr);
    });
    rootEl.appendChild(table);
    return rows.length;
  }

  // Thin controller — fetch is injected for testability; emits halo/mission events via opts.onEvent.
  function CapabilityConsole(opts) {
    opts = opts || {};
    var _fetch = opts.fetch || (typeof fetch !== 'undefined' ? fetch.bind(null) : null);
    var base = opts.base || EXEC_BASE;
    var emit = typeof opts.onEvent === 'function' ? opts.onEvent : function () {};
    return {
      base: base,
      loadExecutable: function () {
        return _fetch(base, { headers: { Accept: 'application/json' } }).then(function (r) { return r.json(); });
      },
      history: function () {
        return _fetch(base + '/invocations', { headers: { Accept: 'application/json' } }).then(function (r) { return r.json(); });
      },
      // §4/§6/§7: run the server-owned safe test; emit started→(completed|failed) for the halo
      runTest: function (capId) {
        emit({ event: 'capability.started', capability: capId, activity: activityLabel(capId), lane: null });
        return _fetch(base + '/' + encodeURIComponent(capId) + '/test',
                      { method: 'POST', headers: { 'Content-Type': 'application/json' } })
          .then(function (r) { return r.json(); })
          .then(function (er) {
            var ok = er.status === 'OK';
            emit({ event: ok ? 'capability.completed' : 'capability.failed', capability: capId,
                   status: er.status, correlation_id: er.correlation_id });
            return er;
          })
          .catch(function (e) { emit({ event: 'capability.failed', capability: capId, error: 'unreachable' }); throw e; });
      },
    };
  }

  return {
    stateLabel: stateLabel, modeLabel: modeLabel, categoryOf: categoryOf,
    buildCapabilityRows: buildCapabilityRows, inspect: inspect, renderPanel: renderPanel,
    // execution UI (§3-9)
    EXEC_BASE: EXEC_BASE, serverStateLabel: serverStateLabel, testableOperation: testableOperation,
    executionStateLabel: executionStateLabel, activityLabel: activityLabel, haloLane: haloLane,
    historyRows: historyRows, renderHistory: renderHistory, CapabilityConsole: CapabilityConsole,
  };
});
