/* Node tests for kai-nexus-pulse.js — the §24 safety boundary for the halo/activity viz.
 * Run: node test_nexus_pulse.js   (no framework, assert-based) */
const assert = require('assert');
const P = require('./kai-nexus-pulse.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

// ── state labels ─────────────────────────────────────────────────────────────
test('activityLabel maps every kaiState to a safe status word', () => {
  assert.strictEqual(P.activityLabel('thinking'), 'Thinking…');
  assert.strictEqual(P.activityLabel('speaking'), 'Responding…');
  assert.strictEqual(P.activityLabel('researching'), 'Researching…');
  assert.strictEqual(P.activityLabel('alert'), 'Attention');
  assert.strictEqual(P.activityLabel('offline'), 'Offline');
  assert.strictEqual(P.activityLabel('online'), 'Ready');
  assert.strictEqual(P.activityLabel(undefined), 'Ready');   // never blank/undefined
});

// ── describeEvent: topic-derived, pulse-worthy ───────────────────────────────
test('kai.<state> event → safe state descriptor with pulse', () => {
  const d = P.describeEvent({ topic: 'kai.thinking', payload: {} });
  assert.strictEqual(d.safe, true); assert.strictEqual(d.kind, 'state');
  assert.strictEqual(d.label, 'Thinking…'); assert.strictEqual(d.pulse, true);
});
test('agent.tool.started → shows the tool NAME only', () => {
  const d = P.describeEvent({ topic: 'agent.tool.started', payload: { tool: 'Railway' } });
  assert.strictEqual(d.safe, true); assert.strictEqual(d.label, 'tool · Railway');
});
test('procedure.step.started → step label with title', () => {
  const d = P.describeEvent({ topic: 'procedure.step.started', payload: { title: 'Deploy' } });
  assert.strictEqual(d.safe, true); assert.ok(d.label.indexOf('Deploy') !== -1);
});
test('unknown / non-allowlisted topic → not safe (dropped)', () => {
  assert.strictEqual(P.describeEvent({ topic: 'debug.raw', payload: { text: 'x' } }).safe, false);
  assert.strictEqual(P.describeEvent({}).safe, false);
});

// ── §24 GUARANTEE: content fields never reach the label ──────────────────────
test('§24: describeEvent NEVER surfaces reasoning/answer/prompt/args content', () => {
  const leaky = {
    topic: 'agent.tool.started',
    payload: {
      tool: 'browser',
      text: 'SECRET_ANSWER_TOKENS',
      reasoning: 'SECRET_CHAIN_OF_THOUGHT',
      thought: 'SECRET_THOUGHT',
      scratchpad: 'SECRET_SCRATCH',
      prompt: 'SECRET_SYSTEM_PROMPT',
      args: { password: 'SECRET_ARG' },
      critique: 'SECRET_CRITIQUE',
    },
  };
  const d = P.describeEvent(leaky);
  assert.strictEqual(d.safe, true);
  for (const secret of ['SECRET_ANSWER_TOKENS', 'SECRET_CHAIN_OF_THOUGHT', 'SECRET_THOUGHT', 'SECRET_SCRATCH', 'SECRET_SYSTEM_PROMPT', 'SECRET_ARG', 'SECRET_CRITIQUE']) {
    assert.strictEqual(d.label.indexOf(secret), -1, 'label leaked: ' + secret);
  }
  assert.strictEqual(d.label, 'tool · browser');   // ONLY the allowlisted name field
});
test('§24: a state event carrying content still yields only the state word', () => {
  const d = P.describeEvent({ topic: 'kai.speaking', payload: { text: 'LEAKED ANSWER', reasoning: 'LEAKED COT' } });
  assert.strictEqual(d.label, 'Responding…');
  assert.strictEqual(d.label.indexOf('LEAK'), -1);
});
test('§24: a name field that is itself an object is not stringified into the label', () => {
  const d = P.describeEvent({ topic: 'agent.started', payload: { name: { secret: 'X' } } });
  assert.strictEqual(d.label, 'agent · active');   // object name ignored → fallback, no [object Object]
});

// ── stripReasoning: the client-side CoT guard ────────────────────────────────
test('stripReasoning removes a closed <think> block, keeps the answer', () => {
  const out = P.stripReasoning('<think>plan the reply, be careful</think>The answer is 42.');
  assert.strictEqual(out.indexOf('plan the reply'), -1);
  assert.ok(out.indexOf('The answer is 42.') !== -1);
});
test('stripReasoning handles variants + multiple + unclosed trailing (mid-stream)', () => {
  assert.strictEqual(P.hasReasoning(P.stripReasoning('<thinking>a</thinking>x<reasoning>b</reasoning>y')), false);
  assert.strictEqual(P.stripReasoning('visible<think>still thinking...'), 'visible');   // unclosed trailing removed
  assert.strictEqual(P.hasReasoning('<THINK>A</THINK>'), true);   // detection is case-insensitive
  assert.strictEqual(P.hasReasoning(P.stripReasoning('<THINK>A</THINK>done')), false);
});
test('stripReasoning is a no-op on a normal answer (never eats real text)', () => {
  const normal = 'Here is a plan: 1) do X 2) do Y. No hidden tags here.';
  assert.strictEqual(P.stripReasoning(normal), normal);
  assert.strictEqual(P.stripReasoning(''), '');
  assert.strictEqual(P.stripReasoning(null), '');
  assert.strictEqual(P.stripReasoning('a < b and c > d'), 'a < b and c > d');   // bare angle brackets untouched
});
test('finalized=true preserves a LONE literal reasoning tag (no silent answer loss)', () => {
  const answer = 'Use a <think> tag to mark reasoning. Then close it.';
  // mid-stream default strips the unclosed-trailing (avoid flashing a partial scratchpad)
  assert.strictEqual(P.stripReasoning(answer), 'Use a ');
  // finalized: a completed answer with a lone literal tag is kept verbatim
  assert.strictEqual(P.stripReasoning(answer, { finalized: true }), answer);
  // but a CLOSED reasoning block is still removed even when finalized
  assert.strictEqual(P.stripReasoning('<think>hidden</think>Answer.', { finalized: true }), 'Answer.');
});
test('stripReasoning strips a reasoning tag that carries attributes', () => {
  assert.strictEqual(P.stripReasoning('<think type="cot">secret</think>Ans.'), 'Ans.');
  assert.strictEqual(P.hasReasoning('<think id="1">'), true);   // attributed tag is detected
});

console.log('\n' + pass + ' passed');
