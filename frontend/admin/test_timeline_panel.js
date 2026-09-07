// §61 Timeline panel contract. Runs the REAL renderTimeline() lifted out of holding.html against the
// three payload states and proves the operator is never left inferring:
//   1. events present            → exactly those events, nothing added
//   2. sources readable, 0 rows  → "no observable events recorded" (a fact about the sources)
//   3. nothing readable          → an explicit UNAVAILABLE state, NOT the same message as (2)
// Run: node test_timeline_panel.js
const assert = require('assert');
const fs = require('fs');

const HTML = fs.readFileSync(__dirname + '/holding.html', 'utf8');
const slice = (start, end) => {
  const i = HTML.indexOf(start);
  assert.ok(i >= 0, 'holding.html no longer contains: ' + start);
  return HTML.slice(i, HTML.indexOf(end, i) + end.length);
};
const fn = name => slice('function ' + name + '(', '\n}\n');

// the panel plus exactly the helpers it renders through — no browser, no network
const SRC = [slice('const esc = s =>', '\n'), slice('const arr = v =>', '\n'),
             slice('const failed = d =>', '\n'), slice('const STATE_META = {', '\n};'),
             fn('badge'), fn('fmtTs'), fn('honest'), slice('const emptyMsg = t =>', '\n'),
             fn('renderTimeline')].join('\n');

let html = '';
const $ = () => ({ set innerHTML(v) { html = v; } });
const renderTimeline = new Function('$', SRC + '\nreturn renderTimeline;')($);

const render = timeline => { html = ''; renderTimeline({ timeline: timeline }); return html; };
const textOf = h => h.replace(/<[^>]*>/g, ' ').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
                     .replace(/\s+/g, ' ').trim();
const rows = h => (h.match(/<div class="row">/g) || []).length;

let pass = 0;
const test = (n, f) => { try { f(); pass++; console.log('  ok  ' + n); }
                         catch (e) { console.error('FAIL  ' + n + '\n      ' + e.message); process.exitCode = 1; } };

const SOURCES = [
  { source: 'governance.audit_log', status: 'CONNECTED', events: 1 },
  { source: 'holding.mission', status: 'CONNECTED', events: 0 },
  { source: 'holding.proposals_store', status: 'CONNECTED', events: 0 },
  { source: 'security.evidence_bus', status: 'UNAVAILABLE', events: 0 },
  { source: 'holding.holding_deployment', status: 'CONNECTED', events: 1 },
];
const DEAD = SOURCES.map(s => ({ source: s.source, status: 'UNAVAILABLE', events: 0 }));
const EVENT = { event_id: 'approval:a1', ts: '2026-09-04T01:00:00Z', type: 'approval', company: 'sol',
                summary: 'owner-approved execute (sol.deploy) → success',
                source: 'governance.audit_log', provenance: 'REAL' };

const WITH_EVENTS = render({ events: [EVENT], store: 'CONNECTED', sources: SOURCES });
const EMPTY = render({ events: [], store: 'CONNECTED', sources: SOURCES });
const NOT_READABLE = render({ events: [], store: 'UNAVAILABLE', sources: DEAD });

test('events render one row each, from the stored record only — nothing added', () => {
  assert.equal(rows(WITH_EVENTS), 1);
  assert.ok(WITH_EVENTS.includes('owner-approved execute (sol.deploy) → success'));
  assert.ok(WITH_EVENTS.includes('governance.audit_log'));
  assert.ok(textOf(WITH_EVENTS).includes('REAL'));          // provenance is always shown
});

test('no events + a readable source states the FACT, and never claims unavailability', () => {
  assert.ok(textOf(EMPTY).includes('No observable events recorded by the connected sources'));
  assert.equal(rows(EMPTY), 0);                              // no fabricated event stands in for the gap
  assert.ok(!textOf(EMPTY).includes('No timeline source is readable'));
});

test('nothing readable is an EXPLICIT unavailable state, not the empty message', () => {
  assert.ok(textOf(NOT_READABLE).includes('UNAVAILABLE'));
  assert.ok(textOf(NOT_READABLE).includes('does NOT mean nothing happened'));
  assert.ok(!textOf(NOT_READABLE).includes('No observable events recorded'));
  assert.notEqual(textOf(NOT_READABLE), textOf(EMPTY));      // THE distinction this panel owes the operator
  assert.equal(rows(NOT_READABLE), 1);                       // the state line, not an event
});

test('every payload names which sources fed the panel, and each source status', () => {
  for (const h of [WITH_EVENTS, EMPTY, NOT_READABLE]) {
    assert.ok(h.includes('Ingested live from:'));
    for (const s of SOURCES) assert.ok(h.includes(s.source), 'source not named: ' + s.source);
    assert.ok(textOf(h).includes('store'));
  }
  // the source this build cannot read is named with its state, not silently dropped from the line
  assert.ok(/security\.evidence_bus[^·]*UNAVAILABLE/.test(textOf(EMPTY)));
});

test('a legacy bare-array payload (older backend) still renders and is treated as unknown-source', () => {
  const legacy = render([EVENT]);
  assert.equal(rows(legacy), 1);
  assert.ok(legacy.includes('owner-approved execute'));
  assert.ok(!textOf(render([])).includes('No observable events recorded'));  // unknown ⇒ the honest state
});

test('a transport failure stays the NOT_CONNECTED story (never "no events")', () => {
  html = ''; renderTimeline({ __unavailable: true, __http: 401 });
  assert.ok(textOf(html).includes('NOT CONNECTED'));
  assert.ok(!textOf(html).includes('No observable events'));
});

console.log('\n' + pass + ' passed');
console.log('\n--- rendered text, EMPTY (sources readable, nothing recorded) ---\n' + textOf(EMPTY));
console.log('\n--- rendered text, NOT READABLE (no source readable) ---\n' + textOf(NOT_READABLE));
console.log('\n--- rendered text, WITH EVENTS ---\n' + textOf(WITH_EVENTS));
