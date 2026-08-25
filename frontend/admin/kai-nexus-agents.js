// ============================================================================
// KAI NEXUS — canonical Agent model + AgentRegistry (Phase 5C/5D). PURE (no DOM).
// UMD: window.NexusAgents in the browser, module.exports in node.
//
// Data honesty (§5V): every agent carries a provenance tag; nothing is REAL
// until a real source/event set it. The registry NORMALIZES source-specific
// states, RECONCILES duplicate identities (one agent, not two), derives summary
// counts, detects STALE agents, and applies the canonical event contract (§5U).
// SUGGESTED agents (§5T) are excluded from operational counts.
// ============================================================================
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NexusAgents = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const STATUS = ['OFFLINE', 'IDLE', 'STARTING', 'ACTIVE', 'WAITING', 'BLOCKED', 'APPROVAL_REQUIRED', 'SUCCESS', 'FAILED', 'CANCELLED', 'UNKNOWN'];
  const HEALTH = ['NOMINAL', 'DEGRADED', 'STALE', 'OFFLINE', 'UNKNOWN'];
  const BLOCKED_REASONS = ['WAITING_FOR_TOOL', 'WAITING_FOR_APPROVAL', 'WAITING_FOR_PROVIDER', 'WAITING_FOR_USER', 'DEPENDENCY_FAILED', 'RATE_LIMIT', 'SPEND_LIMIT', 'NO_CREDENTIAL', 'UNKNOWN'];

  // Source-specific → canonical status. Extend per real source in the adapter.
  const DEFAULT_STATUS_MAP = {
    running: 'ACTIVE', active: 'ACTIVE', busy: 'ACTIVE', working: 'ACTIVE',
    idle: 'IDLE', online: 'IDLE', ready: 'IDLE', offline: 'OFFLINE', stopped: 'OFFLINE',
    starting: 'STARTING', waiting: 'WAITING', blocked: 'BLOCKED',
    done: 'SUCCESS', success: 'SUCCESS', complete: 'SUCCESS', completed: 'SUCCESS',
    failed: 'FAILED', error: 'FAILED', cancelled: 'CANCELLED', canceled: 'CANCELLED',
  };

  function normalizeStatus(raw, map) {
    if (raw == null) return 'UNKNOWN';
    const up = String(raw).trim().toUpperCase();
    if (STATUS.includes(up)) return up;
    return (map && map[String(raw).trim().toLowerCase()]) || DEFAULT_STATUS_MAP[String(raw).trim().toLowerCase()] || 'UNKNOWN';
  }

  function createAgent(spec) {
    return Object.assign({
      agent_id: spec.agent_id || spec.id || 'agent', name: spec.name || spec.agent_id || spec.id || 'Agent',
      type: spec.type || 'agent', domain: spec.domain || 'operations',
      status: 'UNKNOWN', health: 'UNKNOWN', capabilities: [], tools: [],
      current_mission_id: null, current_task_id: null, current_task: null, delegated_by: null,
      started_at: null, last_heartbeat: null, last_activity: null, progress: null,
      blocking_reason: null, last_result: null, cost: null, provider: null, model: null,
      environment: null, permissions: null, provenance: spec.provenance || 'UNKNOWN',
      suggested: !!spec.suggested, invocable: !!spec.invocable, approval_required: !!spec.approval_required,
      stale_for: null, activity: [], metadata: {},
    }, spec);
  }

  function _uniq(a, b) { return Array.from(new Set([...(a || []), ...(b || [])])); }

  function createRegistry() {
    const byId = new Map();

    // upsert = reconcile by canonical id (§5D — no duplicate identity).
    function upsert(spec) {
      const id = spec.agent_id || spec.id; if (!id) throw new Error('agent needs an id');
      if (byId.has(id)) {
        const cur = byId.get(id);
        const merged = Object.assign({}, cur, spec);
        merged.tools = _uniq(cur.tools, spec.tools); merged.capabilities = _uniq(cur.capabilities, spec.capabilities);
        merged.activity = cur.activity || []; merged.provenance = spec.provenance || cur.provenance;
        merged.metadata = Object.assign({}, cur.metadata, spec.metadata || {});
        byId.set(id, merged); return merged;
      }
      const a = createAgent(spec); byId.set(id, a); return a;
    }
    const get = (id) => byId.get(id) || null;
    const all = () => Array.from(byId.values());
    const operational = () => all().filter(a => !a.suggested);

    function summarize() {
      const c = { TOTAL: 0, ACTIVE: 0, WAITING: 0, BLOCKED: 0, FAILED: 0, OFFLINE: 0, IDLE: 0, SUCCESS: 0, UNKNOWN: 0, SUGGESTED: 0 };
      for (const a of all()) {
        if (a.suggested) { c.SUGGESTED++; continue; }
        c.TOTAL++; if (c[a.status] != null) c[a.status]++;
      }
      return c;
    }

    // §5N — STALE ≠ FAILED. An ACTIVE/WAITING agent whose heartbeat exceeds ttl
    // is flagged STALE (health), never auto-failed. Threshold is caller-driven.
    function detectStale(now, ttlMs) {
      for (const a of all()) {
        if (a.suggested) continue;
        const seen = a.last_heartbeat || a.last_activity;
        if ((a.status === 'ACTIVE' || a.status === 'WAITING') && seen && (now - seen) > ttlMs) {
          a.health = 'STALE'; a.stale_for = now - seen;
        }
      }
    }

    function _log(a, ev) { a.activity.push({ ts: ev.ts || 0, event: ev.topic, mission: a.current_mission_id, task: a.current_task, tool: (ev.payload && ev.payload.tool) || null }); a.last_activity = ev.ts || a.last_activity; a.last_heartbeat = ev.ts || a.last_heartbeat; }

    // §5U — canonical event contract → registry mutation. Returns the agent.
    function applyEvent(ev) {
      const p = ev.payload || {}; const id = p.agent_id; if (!id) return null;
      const a = byId.has(id) ? byId.get(id) : upsert({ agent_id: id, name: p.name || id, provenance: p.provenance || 'UNKNOWN' });
      switch (ev.topic) {
        case 'agent.registered': a.status = normalizeStatus(p.status || 'IDLE'); a.health = 'NOMINAL'; break;
        case 'agent.online': a.status = a.status === 'OFFLINE' || a.status === 'UNKNOWN' ? 'IDLE' : a.status; a.health = 'NOMINAL'; break;
        case 'agent.offline': a.status = 'OFFLINE'; a.health = 'OFFLINE'; break;
        case 'agent.started': a.status = 'ACTIVE'; a.health = 'NOMINAL'; a.started_at = ev.ts; a.current_mission_id = p.mission_id || a.current_mission_id; a.current_task_id = p.task_id || a.current_task_id; a.current_task = p.task || a.current_task; a.delegated_by = p.delegated_by || a.delegated_by || 'KAI'; a.stale_for = null; break;
        case 'task.assigned': a.current_task_id = p.task_id || a.current_task_id; a.current_task = p.task || a.current_task; a.current_mission_id = p.mission_id || a.current_mission_id; break;
        case 'task.started': a.status = 'ACTIVE'; break;
        case 'agent.waiting': a.status = 'WAITING'; break;
        case 'agent.blocked': a.status = 'BLOCKED'; a.blocking_reason = BLOCKED_REASONS.includes(p.reason) ? p.reason : (p.reason || 'UNKNOWN'); break;
        case 'agent.resumed': a.status = 'ACTIVE'; a.blocking_reason = null; break;
        case 'agent.completed': case 'task.completed': a.status = 'SUCCESS'; a.last_result = p.result || a.last_result; a.cost = p.cost != null ? p.cost : a.cost; break;
        case 'agent.failed': case 'task.failed': a.status = 'FAILED'; a.last_result = p.error || p.result || 'failed'; break;
        case 'agent.cancelled': a.status = 'CANCELLED'; break;
        case 'agent.tool.started': a.tools = _uniq(a.tools, [p.tool]); break;
        case 'agent.tool.completed': break;
        case 'agent.tool.failed': break;
        case 'agent.result.returned': a.last_result = p.result || a.last_result; break;
        default: break;
      }
      if (p.cost != null) a.cost = p.cost; if (p.model) a.model = p.model; if (p.provider) a.provider = p.provider;
      _log(a, ev);
      return a;
    }

    return { upsert, get, all, operational, summarize, detectStale, applyEvent, _map: byId };
  }

  return { STATUS, HEALTH, BLOCKED_REASONS, DEFAULT_STATUS_MAP, normalizeStatus, createAgent, createRegistry };
});
