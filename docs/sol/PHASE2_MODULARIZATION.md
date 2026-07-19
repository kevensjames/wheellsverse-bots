# SOL Member App — Phase 2 Modularization & Reliability

**Status:** verification complete; awaiting adversarial-review sign-off before deploy.
**Scope:** pure modularization + dialog/guard centralization. **No API-layer, no business-feature, and no security-posture change.** (The Circle Catalog / $9.99 participation model is deliberately *out of scope* — that is Phase 3.)

---

## 1. What Phase 2 changed

| Item | Before | After |
|------|--------|-------|
| App shell | one 326 KB `app.html` (markup + CSS + JS) | `app.html` (~40 KB markup) + `/sol/app/styles/app.css` + **19** classic `<script src>` module files |
| Module system | inline `<script>` | classic multi-file, **shared global scope** (NOT ES modules — inline `onclick` handlers + shared globals `me`/`token` require globals) |
| Dialogs | ~6 bespoke focus-trap/close implementations | one `window.SolDialog` (`core/dialog.js`) |
| Duplicate-submit guards | ~18 bespoke `_xInFlight`/`_xBusy` flags/Sets/Maps | one `window.SolGuard` (`core/guard.js`) |

Script load order (dependencies flow top→down; all top-level symbols are globals):
`state → router → api → dialog → guard → dashboard → circles → circle-detail → kyc → bank → payments → discover → timeline → trust → premium → notifications → community → goals → main`

### SolGuard key map (all keys are stable internal strings — no PII/amount/provider-id)
Per-record (concurrent distinct records must not block each other):
`payment:initiate:<groupId>`, `circle:join:<id>`, `bank:remove:<id>`, `community:like:<id>`, `community:comment:<postId>`, `notification:read:<id>`, `goal:restore:<id>`
Global (must serialize):
`checkout`, `subscription:cancel`, `circle:reserve`, `kyc:submit`, `community:post`, `community:report`, `notification:read-all`, `goal:save`, `goal:progress`, `goal:confirm`

> `checkout` is intentionally acquired-but-not-released on the success path: a successful Stripe checkout navigates the whole page away, so holding the lock through the redirect window is the correct double-submit guard. A return is a fresh page load that resets all globals.

---

## 2. Verification results (all green)

**P2b — static + unit + boot (Node + real Chromium via mock-fetch harness):**
- 19/19 files pass `node --check`.
- **Concatenation parse** (all files in load order) passes → no duplicate top-level `let`/`const`/`class` across the shared global scope.
- Duplicate top-level symbol scan across all files → none.
- **SolGuard unit/concurrency suite: 25/25** — acquire/duplicate-drop, idempotent release, `run()` success + rejection + synchronous-throw all release in `finally`, same-key duplicate returns `undefined` without invoking fn, distinct-key concurrency, per-record (`runFor`) concurrency.
- Boot in real Chromium: 0 load errors, 0 console errors/warnings; all module globals present; dialog open→initial-focus→trap→Escape-close verified; guard-aware `canClose`.

**P2d — authenticated regression (enriched mock backend; real Sol backend is a separate repo not checked out here — see §5):**
- Journeys **A–J all pass** (auth/shell, KYC, bank, discover, payments/timeline, premium, goals, notifications, community, cancellation): each route renders populated real-shape data, opens its dialog, and drops duplicate submits.
- Privacy held: no raw UUIDs / provider IDs / other-member PII in rendered output.
- **All 19 JS modules + both CSS files return 200**; extracted `app.css` is applied (computed styles resolve).
- **Responsive 375 / 768 / 1440 px: 0 px horizontal overflow** across all routes.
- 0 console errors across 88 API round-trips.

---

## 3. Cache-busting decision (P2c)

**Decision: stable filenames + always-revalidate. No content hashing.**

Rationale — a *buildless* multi-file split cannot content-hash filenames without a build step to rewrite the 19 `<script src>` references (that would reintroduce the bundler the project deliberately avoids). Correctness instead comes from three layers that together eliminate any "split-brain cache" (new `app.html` served with a stale `guard.js`):

1. **Cloudflare Pages atomic deploys** — each deploy is an immutable snapshot; the alias flips atomically, so the *origin* never serves a half-old/half-new set.
2. **HTTP revalidation** — `frontend/_headers` gives BOTH `/*.html` and `/sol/app/*` → `Cache-Control: public, max-age=0, must-revalidate`. Every file is revalidated before use (conditional GET → cheap `304`, or fresh `200` when changed).
3. **No service worker** — `frontend/sw.js` is a self-destruct kill switch (no fetch handler; deletes caches + unregisters on activate). No page registers a SW, so nothing intercepts `/sol/app/*`.

Trade-off accepted: one conditional request per file per load. For a member app (not a high-traffic marketing page) this is the correct correctness/performance balance, and it matches the existing `*.html` policy.

---

## 4. Rollback plan

**Last known-good production commit:** `74e3f31` (Phase 1 — single-file `app.html`, already deployed & verified).
Phase 2a split landed locally at `03957c8` (NOT deployed). Phase 2b/2d (dialog + guard) is the uncommitted delta on top.

**If a regression appears after deploying Phase 2:**
```bash
cd /Users/jhonwheeler/conductor/repos/wheellsverse-bots
git revert --no-edit <phase2-merge-sha>        # preferred: keep history linear & auditable
# — or, emergency full rollback of the SOL app tree only —
git checkout 74e3f31 -- frontend/sol/app.html frontend/_headers
git rm -r frontend/sol/app                       # remove the split module tree
git commit -m "revert(sol-ui): roll SOL app back to single-file 74e3f31"
git push origin main                             # Cloudflare Pages redeploys atomically
```
**Post-rollback verification markers** (must all hold):
- `https://<sol-domain>/sol/app` returns 200 and boots (title "Sol — Dashboard").
- No `/sol/app/*.js` requests in the network panel (single-file app is self-contained).
- Login → dashboard renders active circles; no console errors.

---

## 5. Deployment gate (do NOT push until every box is checked)

- [x] P2b static/unit/boot suite green
- [x] P2d journeys A–J + responsive + network/console gates green
- [x] Cache policy verified (`_headers` covers `/sol/app/*`; SW inert)
- [ ] **Adversarial review (10 lenses, 2 independent reviewers): no unresolved HIGH** — *pending*
- [ ] Temp harness `frontend/sol/boot-test.html` deleted (never commit it)
- [ ] Commits authored (dialog/guard + retrofit; cache; docs)
- [ ] Pushed to `origin/main`
- [ ] Cloudflare post-deploy: all 19 `/sol/app/*.js` + 2 CSS files return 200 with `max-age=0, must-revalidate`
- [ ] Production authenticated smoke at `/sol/app`: dashboard + one dialog + one guarded mutation, 0 console errors
- [ ] Prior invariants spot-checked in prod (safeUrl, statusChip, safeError, no PII)

> **Standing external action (not code):** rotate the previously-exposed `rk_live_` Stripe key.

---

## 6. Adversarial review findings

Two independent reviewers ran the 10 lenses against the uncommitted diff, each comparing suspect spots to the pre-split reference `74e3f31`.

### Security & privacy reviewer — verdict: **SAFE TO SHIP** (no HIGH)
- Money-safety: CLEAN. `safeUrl()` still gates both external-URL sinks (`premium.js` checkout `window.location.href` and invoice `hosted_url` href); no optimistic financial-state promotion introduced; double-submit locks intact on every money flow (`payment:initiate:<id>`, `bank:remove:<id>`, `circle:join:<id>`, `checkout`, `subscription:cancel`). The `isLocked()`-then-`acquire()` sites have no `await` between check and acquire, so the second click is still dropped — behavior-equivalent to the old flags.
- Privacy: CLEAN. No render function changed; other members still render as `You`/`SOL member`; `SolGuard` keeps keys in an in-memory `Set` only (no storage/network/render).
- XSS: CLEAN. No `esc()` call dropped; no new raw-innerHTML sink; the only moved innerHTML lines are static literals; `SolDialog` uses only `classList`/`setAttribute`/`focus()`.
- Guard-key safety: CLEAN. Every key is a stable `scope[:id]` string (UUID-validated where per-record); no email/name/amount/provider-id in any key.
- **LOW (deploy hygiene):** the temp `frontend/sol/boot-test.html` embeds the internal API route map; if a deploy wholesale-copies the tree it would publish backend recon at `/sol/boot-test.html`. **Resolution:** it is untracked and is deleted before commit; deploy serves only committed files.

### Correctness reviewer — verdict: **SAFE TO SHIP** (no HIGH)
Traced all 10 changed files, both new modules, load order, and every guard acquire/release path.
- Behavior preservation: no HIGH regressions. Restore-focus, focus-trap, radio-collapse, Escape-when-canClose, aria-hidden, single-keydown-listener all preserved.
- Lock correctness: no leaks / no missing releases / no double-run on any path. Per-record vs global keys correct. `checkout` deliberately held on navigate-away (matches pre-refactor). acquire-after-sync-validation sites have no `await` in the gate→acquire window, so the second click still can't double-run.
- Load order / global scope: clean — new globals assigned synchronously at parse, before all page scripts; no top-level dup; no inline `onclick` touches the new globals.
- Regression cleanup: all removed flags/traps have zero orphaned references.

**Fixed before ship (was the one behavior delta): Escape now routes each dialog's state reset.**
The refactor's Escape path called `SolDialog.close()` directly, skipping each page's `closeX()` state reset (`_bankRemove`, `_premCancel`, `_commReportTarget/Trigger`, `_discDetailId/_discDlgTrigger`, `_goalDlg`). Reviewer verified this was benign today, but it was a real behavior delta and a latent footgun. **Fix:** pass an `onClose` callback in each of the 5 `open()` calls (bank/premium/community/discover/goals) — `SolDialog.close()` already invokes `opts.onClose` on every close including Escape. Purely additive (one option per `open()`); the wrapper's own reset stays as defense-in-depth for the close-a-non-active-dialog edge case. **Verified in-browser:** all 5 dialogs reset state on Escape AND on explicit close; focus trap intact; 0 console errors.

Remaining LOWs accepted as follow-up tickets (not shipping-blockers): single-active-dialog tracking (no nested dialogs today), widened focusables selector (equivalent today), `run()`/`runFor()` unused API surface (intentional), and the pre-existing raw-`e.message` in `bank.js` `confirmRemove` catch (NOT introduced by this diff).

---

## 7. Verdict

**Both independent reviewers: SAFE TO SHIP. Zero HIGH, zero MEDIUM. The one behavior delta is fixed and re-verified.** Phase 2 is a faithful, behavior-preserving modularization + reliability milestone. Ready to commit; deploy is user-gated.
