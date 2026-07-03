/* Pure-helper unit tests for the Sol operator dashboard. Run: node --test app.test.js
 * app.js exports its pure helpers and returns before touching the DOM under node. */
const test = require("node:test");
const assert = require("node:assert/strict");
const H = require("./app.js");

test("money formats + guards junk", () => {
  assert.equal(H.money(30), "$30.00");
  assert.equal(H.money("1234.5"), "$1,234.50");
  assert.equal(H.money("nope"), "$0.00");
});

test("shortDate", () => {
  assert.equal(H.shortDate("2026-07-08"), "Jul 8, 2026");
  assert.equal(H.shortDate("2026-07-08T04:00:00Z"), "Jul 8, 2026");
  assert.equal(H.shortDate(null), "—");
});

test("shortId truncates", () => {
  assert.equal(H.shortId("abcdef1234567890"), "abcdef12");
  assert.equal(H.shortId(null), "—");
});

test("statusBadge maps status → css class", () => {
  assert.equal(H.statusBadge("confirmed"), "b-ok");
  assert.equal(H.statusBadge("disputed"), "b-danger");
  assert.equal(H.statusBadge("overdue"), "b-warn");
  assert.equal(H.statusBadge("marked"), "b-info");
  assert.equal(H.statusBadge("whatever"), "b-muted");
});
