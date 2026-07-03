/* Pure-helper unit tests for the Sol v1 app. Run: node app.test.js
 * app.js exports its pure helpers via module.exports (and returns before touching
 * the DOM) when required under node. */
const test = require("node:test");
const assert = require("node:assert/strict");
const H = require("./app.js");

test("money formats decimals + thousands, guards junk", () => {
  assert.equal(H.money(50), "$50.00");
  assert.equal(H.money("50.00"), "$50.00");
  assert.equal(H.money("1234.5"), "$1,234.50");
  assert.equal(H.money("not-a-number"), "$0.00");
});

test("shortDate handles date + datetime + empty", () => {
  assert.equal(H.shortDate("2026-07-08"), "Jul 8, 2026");
  assert.equal(H.shortDate("2026-07-08T04:00:00Z"), "Jul 8, 2026");
  assert.equal(H.shortDate(null), "—");
  assert.equal(H.shortDate("2026-12-31"), "Dec 31, 2026");
});

test("statusMeta maps every payment status", () => {
  assert.equal(H.statusMeta("pending").cls, "badge--muted");
  assert.equal(H.statusMeta("marked").cls, "badge--info");
  assert.equal(H.statusMeta("confirmed").cls, "badge--ok");
  assert.equal(H.statusMeta("disputed").label, "Disputed");
  assert.equal(H.statusMeta("late").cls, "badge--warn");
});

test("dueMeta buckets", () => {
  assert.equal(H.dueMeta("overdue").cls, "badge--danger");
  assert.equal(H.dueMeta("due_today").cls, "badge--warn");
  assert.equal(H.dueMeta("upcoming").cls, "badge--info");
  assert.equal(H.dueMeta("scheduled").cls, "badge--muted");
});

test("repMeta by label", () => {
  assert.equal(H.repMeta("excellent").cls, "badge--ok");
  assert.equal(H.repMeta("good").cls, "badge--ok");
  assert.equal(H.repMeta("fair").cls, "badge--warn");
  assert.equal(H.repMeta("poor").cls, "badge--danger");
  assert.equal(H.repMeta("unrated").cls, "badge--muted");
});

test("groupStatusMeta labels", () => {
  assert.equal(H.groupStatusMeta("open").label, "Open to join");
  assert.equal(H.groupStatusMeta("locked").label, "Active");
  assert.equal(H.groupStatusMeta("complete").label, "Complete");
});

test("shortId truncates", () => {
  assert.equal(H.shortId("abcdef1234567890"), "abcdef12");
  assert.equal(H.shortId(null), "—");
});

test("safeHref allows only http(s), blocks script/data URLs", () => {
  assert.equal(H.safeHref("https://img.example/p.png"), "https://img.example/p.png");
  assert.equal(H.safeHref("http://x.io/a"), "http://x.io/a");
  assert.equal(H.safeHref("  https://x.io/a  "), "https://x.io/a");
  assert.equal(H.safeHref("javascript:alert(document.cookie)"), null);
  assert.equal(H.safeHref("JavaScript:alert(1)"), null);
  assert.equal(H.safeHref("data:text/html,<script>alert(1)</script>"), null);
  assert.equal(H.safeHref("ftp://x"), null);
  assert.equal(H.safeHref(""), null);
  assert.equal(H.safeHref(null), null);
});

test("inAppLink allows only well-formed in-app hashes", () => {
  assert.equal(H.inAppLink("#/payment/abc-123"), "#/payment/abc-123");
  assert.equal(H.inAppLink("#/group/9a9d23c"), "#/group/9a9d23c");
  assert.equal(H.inAppLink("  #/payment/x  "), "#/payment/x");
  assert.equal(H.inAppLink("#/payment/a/b"), null);        // too deep
  assert.equal(H.inAppLink("#/payment"), null);            // no id
  assert.equal(H.inAppLink("https://evil.example"), null); // not a hash
  assert.equal(H.inAppLink("javascript:alert(1)"), null);
  assert.equal(H.inAppLink("#/payment/<script>"), null);   // no injection chars
  assert.equal(H.inAppLink(""), null);
  assert.equal(H.inAppLink(null), null);
});

test("parseHash routes + params + query", () => {
  assert.deepEqual(H.parseHash("#/groups"), { route: "groups", id: null, sub: null, query: {} });
  assert.equal(H.parseHash("#/group/abc123").route, "group");
  assert.equal(H.parseHash("#/group/abc123").id, "abc123");
  assert.equal(H.parseHash("#/groups/new").id, "new");
  assert.equal(H.parseHash("#/join?code=ABCD1234").query.code, "ABCD1234");
  assert.equal(H.parseHash("").route, "groups");           // default
  assert.equal(H.parseHash("#/payment/xyz").route, "payment");
});
