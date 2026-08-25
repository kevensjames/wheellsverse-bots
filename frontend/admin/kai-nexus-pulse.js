/* KAI Adaptive Mission Nexus — Functional Halo + Safe Activity/Thinking viz (Phase 10, §23/§24)
 *
 * Pure UMD logic (browser + node), no DOM. This is the §24 SAFETY BOUNDARY for the halo
 * and the "what KAI is doing" indicator: it maps observable bus events → a safe display
 * descriptor and NEVER surfaces model reasoning, system prompts, token/answer content,
 * tool arguments, or any payload free-text. The label is derived STRUCTURALLY from the
 * event topic + a small allowlist of name/count fields — content fields are ignored by
 * construction, so a "thinking" viz cannot leak chain-of-thought (docs/KAI_HALO_SOURCES.md).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.NexusPulse = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Coarse lifecycle states the halo binds to (kaiState). "thinking" = request sent,
  // awaiting first token — a status label, NOT the model's actual thoughts.
  const STATE_LABEL = {
    offline: 'Offline', online: 'Ready', idle: 'Ready',
    listening: 'Listening…', thinking: 'Thinking…', researching: 'Researching…',
    speaking: 'Responding…', alert: 'Attention',
  };
  function humanState(s) { return STATE_LABEL[String(s || 'online').toLowerCase()] || 'Ready'; }
  function activityLabel(kaiState) { return humanState(kaiState); }

  // ONLY these name/count fields may contribute to a label. Any other payload field
  // (text, content, answer, reasoning, thought, scratchpad, prompt, system, context,
  // args, arguments, critique, delta) is NEVER read — the §24 guarantee.
  const NAME_FIELDS = ['tool', 'name', 'agent', 'title', 'step', 'label'];
  function _safeName(payload) {
    if (!payload || typeof payload !== 'object') return '';
    for (const k of NAME_FIELDS) { if (payload[k] != null && typeof payload[k] !== 'object') return String(payload[k]); }
    return '';
  }

  // Map a bus event → { safe, kind, label, pulse }. Unknown/unsafe topics → { safe:false }.
  // The label is topic-derived; content fields are structurally ignored.
  function describeEvent(ev) {
    ev = ev || {};
    const topic = String(ev.topic || '');
    const p = ev.payload || {};
    const name = _safeName(p);
    if (topic.indexOf('kai.') === 0) {
      const st = topic.slice(4);
      return { safe: true, kind: 'state', label: humanState(st), pulse: true };
    }
    if (topic === 'agent.tool.started') return { safe: true, kind: 'tool', label: 'tool · ' + (name || 'running'), pulse: true };
    if (topic === 'agent.started' || topic === 'task.assigned') return { safe: true, kind: 'agent', label: 'agent · ' + (name || 'active'), pulse: true };
    if (topic === 'agent.blocked' || topic === 'agent.waiting') return { safe: true, kind: 'agent', label: 'agent waiting' + (name ? ' · ' + name : ''), pulse: true };
    if (topic === 'agent.failed') return { safe: true, kind: 'agent', label: 'agent failed' + (name ? ' · ' + name : ''), pulse: true };
    if (topic === 'agent.result.returned' || topic === 'agent.completed') return { safe: true, kind: 'agent', label: 'agent done' + (name ? ' · ' + name : ''), pulse: true };
    if (topic.indexOf('procedure.step.') === 0) return { safe: true, kind: 'step', label: 'step ' + topic.slice(15) + (name ? ' · ' + name : ''), pulse: true };
    if (topic === 'approval.required') return { safe: true, kind: 'approval', label: 'approval required' + (name ? ' · ' + name : ''), pulse: true };
    if (topic === 'procedure.completed') return { safe: true, kind: 'step', label: 'procedure complete', pulse: true };
    if (topic === 'procedure.failed') return { safe: true, kind: 'step', label: 'procedure failed', pulse: true };
    if (topic === 'stream.token') return { safe: true, kind: 'stream', label: 'Responding…', pulse: true };   // pulse on CADENCE, never content
    if (topic === 'stream.done') return { safe: true, kind: 'stream', label: 'Ready', pulse: false };
    return { safe: false };
  }

  // §24 client-side defense-in-depth: strip inline reasoning scratchpads a reasoning model
  // (deepseek-r1/qwq) may emit. Removes <think>/<thinking>/<reasoning>/<scratchpad> blocks,
  // including an unclosed trailing one (mid-stream). The default model is non-reasoning, so
  // this is a no-op for normal answers — it only ever removes reasoning tags, never answer text.
  const _REASON_TAGS = 'think|thinking|reasoning|scratchpad|reflection';
  // tolerate attributes: <think>, <think foo="bar">  (closing tags carry no attrs)
  const _CLOSED = new RegExp('<(' + _REASON_TAGS + ')(?:\\s[^>]*)?>[\\s\\S]*?<\\/\\1>', 'gi');
  const _OPEN_TRAILING = new RegExp('<(' + _REASON_TAGS + ')(?:\\s[^>]*)?>[\\s\\S]*$', 'i');
  // opts.finalized: the answer is complete (stream done). A well-formed reasoning model
  // always emits paired <think>…</think>, so a LONE opening tag in a finished answer is
  // literal content (e.g. KAI explaining tag syntax) — preserve it. Only strip the
  // unclosed-trailing block MID-STREAM, to avoid flashing a partial scratchpad before its close.
  function stripReasoning(text, opts) {
    if (text == null) return '';
    let out = String(text).replace(_CLOSED, '');
    if (!(opts && opts.finalized)) out = out.replace(_OPEN_TRAILING, '');
    return out;
  }
  // True if the text still contains a reasoning tag after a strip attempt (for assertions/guards).
  function hasReasoning(text) { return new RegExp('<(' + _REASON_TAGS + ')(?:\\s[^>]*)?>', 'i').test(String(text == null ? '' : text)); }

  return { STATE_LABEL, humanState, activityLabel, describeEvent, stripReasoning, hasReasoning, NAME_FIELDS };
});
