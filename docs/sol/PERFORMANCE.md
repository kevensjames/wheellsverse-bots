# SOL Performance Audit

Frontend performance review of the deployed SOL member app. Reviewed at commit
`6cd3d00`, production `https://wheellsverse.com/sol/app`.

> This doc is committed **with** the Increment-10 fixes; the source metrics below
> are re-measured against the **post-fix** files (the gzip transfer figure is
> pre-Inc10 and will be re-confirmed after deploy).

Measurements below are **real** — taken from the production response and a
source parse. No Lighthouse score is quoted because a reliable Lighthouse run
was not performed in this environment (see *Measurements*).

## Architecture

- **Static single-file SPA.** One `frontend/sol/app.html` served by Cloudflare
  Pages at the clean route `/sol/app`. All view logic is one inline `<script>`;
  all app CSS is one inline `<style>` plus the shared `sol-design-system.css`.
- **External dependencies:** exactly one — Google Fonts (`Space Grotesk` +
  `Inter`) via an `@import` in `sol-design-system.css`. No JS framework, no CDN
  script, no bundler.
- **API loading strategy:** the shell renders immediately; each route's data is
  fetched lazily by its `load*()` function when navigated to. The dashboard is
  the only route that fans out multiple requests, and it does so with
  `Promise.allSettled` so one failing card never blocks the others.

## Measurements

Values below are the **Increment-10 source** (post-fix); the gzip transfer figure
is the pre-Increment-10 production measurement and will shrink slightly (dead
code removed) — re-confirm after the Increment-10 deploy.

| Metric | Value | How |
|--------|-------|-----|
| HTML transfer (gzip) | **~77 KB** (77,882 B pre-Inc10) | `curl -H "Accept-Encoding: gzip"` prod |
| HTML source (uncompressed) | **322,074 bytes** (~315 KB; was 324,238 pre-Inc10) | source parse |
| Compression ratio | ~76% | derived |
| Inline JS | **228,536 bytes** | source parse |
| Inline CSS | **54,784 bytes** | source parse |
| `sol-design-system.css` | 14,332 bytes (separate request, cacheable) | `wc -c` |
| Static DOM elements | **~563** across all 13 hidden pages | HTML start-tag parse |
| `<style>` blocks | 1 | parse |
| `<script>` blocks | 1 (no `src=`) | parse |
| SVG sprite symbols | 14 (one inline sprite, reused via `<use>`) | parse |
| Inline `style=` attributes | 26 | parse |

Element mix (static): 180 `div`, **69 `button`** (up from 57 — Increment 10
converted 12 sidebar `<a>` nav items to `<button>`, A11Y-01), 32 `svg` + 31
`use`, 31 `p`, 30 `label`, 26 `option`, 22 `input`, 13 `h1`, 17 `li`, ~6 `a`.

**Not measured in this environment (documented, not invented):** Lighthouse
score, TBT/long-tasks, CLS, script parse time, LCP. The app requires an
authenticated token, so a headless Lighthouse run would measure the login
redirect, not the app. A future measured run should authenticate first.

## Loader architecture

- **Dashboard (`loadDashboard`)** — a single consolidated load feeding every
  card via `Promise.allSettled`; each card renders its own error/Retry on
  partial failure, so the dashboard never shows a false zero when one endpoint
  is down.
- **Per-page lazy loaders** — `loadGroups`, `loadBank`, `loadKYC`,
  `loadMyPayments`, `loadDiscover`, `loadTimeline`, `loadTrust`, `loadPremium`,
  `loadNotifications`, `loadCommunity`, `loadGoals`. Each fires only on
  navigation to its route (`nav()` dispatch).
- **Pagination:** Community pages the feed at `limit=30` via offset with a
  "Load more" (dedup-guarded); Notifications loads a bounded default page.
- **Progressive rendering:** loaders paint a skeleton/spinner first, then swap
  in content; dialogs render a spinner during their own async fetch.
- **Duplicate-fetch guards:** every mutation carries an in-flight flag
  (`_checkoutInFlight`, `_premCancelInFlight`, `_kycInFlight`,
  `_bankRemoveInFlight`, `_payInFlight[groupId]`, `_discJoinBusy`,
  `_reserveBusy`, `_commPostBusy`, `_commLikeBusy`, `_commCommentBusy`,
  `_commReportBusy`), preventing double-submit and duplicate network calls.
- **Mutation re-fetch pattern:** mutations never optimistically mutate financial
  state — they re-fetch the backend truth after success
  (`await loadBank()` / `loadPremium()` / `loadGoals()` / `loadDiscover()` /
  `loadCommunity()`), which costs a request but guarantees correctness.

## Performance risks

Ranked by likelihood × cost:

1. **`app.html` monolith growth (~324 KB / 226 KB JS).** Every increment adds
   to one file that must be parsed on first load. Still gzips to ~76 KB and
   parses fast on modern devices, but the file has grown ~1.5× across the
   transformation and has no code-splitting. *Medium risk, high inertia.*
2. **CSS duplication.** `sol-design-system.css` and the inline `<style>` both
   define `.btn`, `.status`-adjacent, and other primitives; the app overrides
   several. ~55 KB of inline CSS overlaps the 14 KB shared sheet. *Low runtime
   cost, medium maintenance cost.*
3. **All 13 pages live in the DOM at once** (`display:none`), ~562 static
   elements before any data. Cheap today, but every new page adds permanent
   nodes. *Low risk now.*
4. **Repeated inline HTML templates** — card/dialog markup is re-built as
   template strings on each render; large feeds (Community, Notifications,
   Payments) rebuild the whole list on re-render rather than diffing. *Low risk
   at current data volumes; watch for large feeds.*
5. **Repeated date/currency formatting** — `fmt$` and `toLocaleDateString`
   called per row on each render; negligible at current volumes.
6. **SOL Orb rAF loop** — cheap (opacity/gradient on a 220 px canvas) and
   correctly paused off-dashboard, on hidden tabs, and under reduced motion.
   *No risk.*
7. **Notification / Community payloads** — bounded (notifications default page;
   community `limit=30`), so no unbounded render.

## Safe optimization recommendations

Non-architectural, low-risk (ranked by impact/risk); **none performed this
increment** to avoid destabilizing a shipped app:

1. **Centralize formatters** — a single `fmtDate()` (see Consistency findings)
   removes duplicated logic and fixes inconsistent date formatting in one place.
   *High value, low risk.*
2. **De-duplicate CSS** — delete inline primitives that exactly re-declare the
   shared sheet, keeping only genuine app overrides. *Medium value, medium
   risk (visual regression) — do behind a screenshot diff.*
3. **Shared render/dialog helpers** — a small template helper for cards and a
   single dialog-manager would shrink repeated markup. *Medium value, medium
   risk.*
4. **Incremental feed rendering** — append new posts/rows to the DOM instead of
   rebuilding the `<ul>` on "load more" (also preserves in-progress drafts).
   *Medium value, low risk.*
5. **Response caching for idempotent GETs** (e.g. `/auth/me`) within a session.
   *Low value, low risk.*
6. **Request cancellation** on rapid route switches (`AbortController`). *Low
   value, low risk.*

Explicitly **out of scope** for this documentation increment: splitting
`app.html` into versioned static modules or route-level code loading — a real
architectural change to schedule deliberately, not fold into an audit.
