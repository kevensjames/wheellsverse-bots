/**
 * The Command Center reported an outage that was not happening.
 *
 * /admin/registry.json is owner-gated by require_admin_json — a deliberate change, because the
 * registry carries the system inventory, internal route names, per-system deploy state and the
 * running build SHA. But the page had no way to authenticate: it fetched with only an Accept
 * header, and on failure printed
 *
 *     "Telemetry unavailable: registry 401. Last successful update: never."
 *
 * Every panel then showed "—". Refusing to fabricate numbers was correct and stays. What was wrong
 * is that a signed-out owner had no way to tell an AUTHORIZATION problem from an OUTAGE, and no way
 * to fix it from the page they were looking at. The route's own docstring still says "Always
 * available" — it was built anonymous and gated later, and the UI was never updated to match.
 *
 * The existing advice made it worse: ceo.html told the operator to "sign in at
 * /admin/session/login", which is a POST-only API endpoint and answers 405 to a browser. There is
 * no owner login page anywhere in App A (/admin/login is 404; /login is the CUSTOMER page).
 *
 * So: a 401 now renders an inline sign-in that exchanges the owner key for the HttpOnly wv_session
 * cookie. The key is never stored — not localStorage, not a closure that outlives the handler, not
 * the URL. It is read from the field, sent, and the field is cleared. A stored operator key is
 * precisely what the /admin/ceo credential leak was.
 *
 * Plain node, no framework — matching the other frontend suites (ADR-017).
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const PAGE = fs.readFileSync(path.join(ROOT, "frontend/admin/command-center.html"), "utf8");

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log(`  PASS  ${name}`); }
  else { fail++; console.log(`  FAIL  ${name}${detail ? " — " + detail : ""}`); }
}

// ── the 401 path is distinguished from a generic failure ─────────────────────────────────────────
check("401 is handled as its own case",
  /\/\\b401\\b\/\.test\(e\.message/.test(PAGE) || /\b401\b/.test(PAGE.split("catch(function(e)")[1] || ""),
  "the catch handler does not branch on 401");

check("a 401 renders a sign-in prompt, not an outage message",
  PAGE.includes("signInPrompt()") && PAGE.includes("Owner sign-in required"));

check("the generic outage message survives for non-401 failures",
  PAGE.includes("Telemetry unavailable: ") && PAGE.includes("Nothing fabricated in its place"));

// ── sign-in mechanics ────────────────────────────────────────────────────────────────────────────
check("sign-in POSTs to the session endpoint",
  /fetch\("\/admin\/session\/login",\{method:"POST"/.test(PAGE));

check("sign-in sends credentials so the Set-Cookie is honoured",
  /\/admin\/session\/login[\s\S]{0,200}credentials:"same-origin"/.test(PAGE));

check("telemetry fetches send credentials explicitly",
  /credentials:"same-origin"[\s\S]{0,120}signal:ac\.signal/.test(PAGE) ||
  /var opt=\{[^}]*credentials:"same-origin"/.test(PAGE));

// ── the credential must never be retained ────────────────────────────────────────────────────────
check("the owner key is never written to localStorage or sessionStorage",
  !/localStorage\.setItem[\s\S]{0,80}(key|secret|KEY|SECRET)/.test(PAGE) &&
  !/sessionStorage\.setItem[\s\S]{0,80}(key|secret|KEY|SECRET)/.test(PAGE));

check("the input is cleared immediately after being read",
  /var secret=el\.value;\s*el\.value="";/.test(PAGE),
  "the key should not remain in the DOM after submission");

check("the key never travels in a URL",
  !/session\/login\?[^"]*secret=/.test(PAGE) && !/[?&]api_key=/.test(PAGE));

check("the field is a password input, not plain text",
  /id="ownerkey"[^>]*type="password"/.test(PAGE) ||
  /type="password"[^>]*id="ownerkey"/.test(PAGE) ||
  /'<input id="ownerkey" type="password"/.test(PAGE));

// ── failure feedback is specific ─────────────────────────────────────────────────────────────────
check("a rejected key says so, rather than looking like an outage",
  PAGE.includes("That key was not accepted."));

check("a non-401 sign-in failure reports its status",
  /Sign-in unavailable \("\+r\.status\+"\)/.test(PAGE));

// ── the misleading pointer is gone ───────────────────────────────────────────────────────────────
const CEO = fs.readFileSync(path.join(ROOT, "dashboard/ceo.html"), "utf8");
check("ceo.html no longer sends the operator to a POST-only endpoint",
  !/SIGN IN REQUIRED[^']*\/admin\/session\/login\)/.test(CEO),
  "/admin/session/login answers 405 to a browser; there is no owner login page");

console.log(`\n  ${pass}/${pass + fail} passed`);
process.exit(fail === 0 ? 0 : 1);
