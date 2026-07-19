# SOL Member Application UX Audit

## Scope

- **Production URL:** https://wheellsverse.com/sol/app
- **Reviewed commit (pre-Increment-10):** `6cd3d00`
- **Audit date:** 2026-07-19
- **Pages reviewed:** all 13 member page-containers + 8 dialogs + global shell
- **Frontend architecture:** static single-file SPA (`frontend/sol/app.html`,
  ~324 KB) + shared `sol-design-system.css`. No framework; one inline `<script>`,
  one inline `<style>`. Client-side router (`nav()`) toggles `.page.active`.

This audit was produced by an 8-domain parallel review of the deployed code
(page-inventory, design-system, motion, accessibility, consistency/terminology,
security-regression, dead-code, performance), followed by a narrow fix sweep.
Every statement describes what actually ships.

## Product principles

- **Financial truth over conversion** — never show a money/eligibility state the
  backend hasn't confirmed; payout previews are net after fee; no guaranteed
  return/payout/credit language.
- **Backend authority** — mutations re-fetch server truth; no optimistic
  financial state.
- **Privacy by default** — no member PII, provider IDs, or internal identifiers
  rendered; community/legacy authors are "You"/"SOL member" only.
- **Progressive disclosure** — dashboard summarizes; detail lives on each page;
  dialogs gate destructive/irreversible actions.
- **Calm operational design** — restrained motion, no vanity metrics, honest
  empty/error states.
- **No manipulative financial UX** — no urgency, confetti, or dark patterns.

## Page inventory

| Route (`nav`) | Container | H1 | Loader | Key mutations | Primary data | Desktop | Mobile | Complete |
|---------------|-----------|----|--------|---------------|--------------|:-------:|:------:|:--------:|
| dashboard | `#page-dashboard` | greeting | `loadDashboard` (allSettled) | — (aggregation) | `/auth/me`,`/groups`,`/payments`,`/notifications`,`/subscriptions`,`/goals`,`/trust` | ✓ sidebar | ✓ Home | ✓ |
| timeline | `#page-timeline` | Your timeline | `loadTimeline` | — | `/timeline`,payments | ✓ | ✓ More | ✓ |
| notifications | `#page-notifications` | Notifications | `loadNotifications` | mark read / all | `/notifications` | ✓ Alerts | ✓ Alerts | ✓ |
| groups (Circles) | `#page-groups` | Your circles | `loadGroups` | join-by-code | `/groups` | ✓ | ✓ Circles | ✓ |
| group-detail (legacy) | `#page-group-detail` | *(sr-only)* Circle detail | `showGroup(id)` | `joinGroup` | `/groups/{id}`,`/my-payments` | — (via Circles) | — | legacy |
| discover | `#page-discover` | Discover circles | `loadDiscover` | join, reserve | `/groups?status=FORMING`,`/auth/me`,`/bank/list`,`/circles/waitlist/me` | ✓ | ✓ More | ✓ |
| goals | `#page-goals` | Savings goals | `loadGoals` | create/edit/progress/archive/delete | `/goals` | ✓ | ✓ More | ✓ |
| bank | `#page-bank` | Bank & payment methods | `loadBank` | add / verify micro / remove | `/bank/list`,`/bank`,`/bank/{id}/verify` | ✓ | ✓ More | ✓ |
| payments | `#page-payments` | Payments | `loadMyPayments` | pay contribution | `/payments` | ✓ | ✓ Pay | ✓ |
| kyc (Verify ID) | `#page-kyc` | Verify your identity | `loadKYC` | submit (DOB) | `/auth/me`,`/kyc/submit` | ✓ | ✓ More | ✓ |
| trust (SOL Score) | `#page-trust` | Your SOL Score | `loadTrust` | — | `/trust` | ✓ | ✓ More | ✓ |
| premium | `#page-premium` | SOL Premium | `loadPremium` | checkout / cancel | `/subscriptions/me`,`/checkout`,`/cancel`,invoices | ✓ | ✓ More | ✓ |
| community | `#page-community` | Community | `loadCommunity` | post / comment / like / report | `/feed`,`/feed/{id}/comments`,`/feed/{id}/like`,`/community/report` | ✓ | ✓ More | ✓ |

**Nav-chrome notes:** the sidebar (desktop) carries all 12 top-level routes; the
mobile bottom bar carries 5 (Home, Circles, Pay, Alerts, More) with a sheet for
the other 8. `group-detail` has no nav entry (sub-state of Circles).

**Dead / orphaned code found (this increment):** `loadDashGroups()` — zero
callers, rendered into a nonexistent `#dashGroups`, carried two `javascript:`
links → **removed**. `loadOnboarding()` — inert legacy shim that always
short-circuits to `loadDashboard()`; **retained** as a working dashboard-refresh
call from the bank/KYC flows (documented tech debt).

## User journeys reviewed

1. **New member** — Register → Verify ID (DOB) → Bank (add + micro-verify) →
   Discover (eligibility gates: KYC + ACTIVE bank + account status) → Join. Each
   gate is backend-authoritative; ineligible states deep-link to the fix.
2. **Existing circle member** — Dashboard (summary + attention card) → Circles →
   Payments (contribution states) → Timeline (history). `badge()` was
   canonicalized (TERM-01) so Timeline + legacy detail show friendly labels with
   correct severity colors (e.g. a **RETURNED** payment now reads as a failure,
   not a neutral chip) and never expose raw enums. Note the Payments page uses
   the richer `PAY_STATE` model (e.g. "Due" for a pending contribution); `badge()`
   uses generic labels ("Pending") since it also serves circle/cycle/member
   status — the two are aligned in severity and free of raw enums, not identical
   in every word.
3. **Failed payment** — Notification → Payments → resolve (retry / bank).
4. **Premium** — Premium page → Stripe Checkout (`safeUrl(checkout_url)`) →
   backend-confirmed active (no optimistic activation; return-note polling).
5. **Cancellation** — Active subscription → cancel dialog (busy-guarded) →
   "Cancellation scheduled / Active through <date>" (never shown as Cancelled;
   dashboard card now uses the same label — SUB-01).
6. **Goal planning** — Create → update tracked progress (a planning value, not a
   balance) → achieve/archive.
7. **Community** — Create post → comment → appreciate → report (all
   backend-authoritative; plain-text escaped; author = "You"/"SOL member").

## Findings

Full Increment-10 findings and dispositions. **All HIGH fixed; MED fixed where
narrow, else documented; LOW fixed where trivial, else documented.**

| ID | Sev | Area | Issue | Disposition |
|----|-----|------|-------|-------------|
| A11Y-01 | HIGH | Sidebar nav | 12 nav items were hrefless `<a role=button>` — not keyboard-focusable (WCAG 2.1.1 A) | **Fixed** → real `<button>` |
| TERM-01 / LEGACY-01 | HIGH | badge() | Raw backend enums (SUCCESS/DELINQUENT/COLLECTING) shown on Timeline + legacy detail | **Fixed** → canonical labels + escaped |
| SEC-01 | HIGH | nav links | 5 `href="javascript:nav()"` action paths (3 live, 2 in dead code) | **Fixed** → buttons; dead 2 removed |
| SEC-02 | HIGH | joinGroup | Raw backend `e.message` rendered unescaped into innerHTML on fall-through | **Fixed** → `esc(msg)` |
| PAGE-02 | MED | dashboard | `nav('dashboard')` ran no loader → stale summary after mutations | **Fixed** → dispatch `loadDashboard()` |
| A11Y-02 | MED | status chips | `--st-pending` 2.95:1, `--st-forming/warning` 4.14:1 (fail AA) | **Fixed** → darkened to 5.75 / 5.99; removed bank-only override |
| A11Y-03 | MED | More sheet | `aria-modal` with no focus trap / restore | **Fixed** → trap + focus-in + restore |
| DS-01 | MED | tokens | `--sol-50/-100/-300/-700` referenced but undefined (styling silently failed) | **Fixed** → tokens defined |
| MOT-01 | MED | openBankAdd | Smooth-scroll with no reduced-motion guard | **Fixed** → guarded |
| ERR-01 | MED | Timeline/Trust/legacy | Raw error dumped, no Retry | **Fixed** → friendly copy + Retry |
| SUB-01 | MED | dashboard | "Cancels soon" vs canonical "Cancellation scheduled" | **Fixed** → canonical label + `fmtDate` |
| PRICE-01 | MED | dashboard | Hardcoded `$14.99` price fallback | **Fixed** → "Price unavailable" |
| DATE-01 | MED | dates | 4 inconsistent date formats, no shared helper | **Partially fixed** → added `fmtDate()`; routed dashboard + Timeline; remaining sites documented |
| DS-02 | MED | class names | flat `btn-primary` vs BEM `btn--primary`; markup uses flat | **Documented** (130+ call sites; convention noted in DESIGN_SYSTEM.md) |
| DS-03 | MED | type scale | 157 hardcoded rem sizes bypass `--step-*` | **Documented** (broad; future consolidation) |
| PERF-01 | MED | boot | `/notifications` fetched twice on cold load | **Documented** (touches boot; PERFORMANCE.md) |
| PERF-02 | MED | api() | no GET cache / in-flight dedup | **Documented** (additive future work) |
| PERF-03 | MED | feeds | notifications/payments/discover render uncapped | **Documented** (mirror Community pagination later) |
| PAGE-03 | LOW | dead code | `loadDashGroups()` orphaned | **Fixed** → removed |
| A11Y-04 | LOW | bank remove | Escape not busy-guarded | **Fixed** |
| A11Y-05 / PAGE-06 | LOW | group-detail | no `<h1>` | **Fixed** → sr-only h1 |
| A11Y-06 | LOW | landmarks | `notif-side`/`bank-side` `<aside>` unlabeled | **Fixed** → aria-label |
| TERM-02 | LOW | subtitles | Timeline/Trust missing period | **Fixed** |
| DS-05 | LOW | fields | `.field` selector omitted `textarea` | **Fixed** |
| DS-04 | LOW | duplicate CSS | `.btn/.card/.badge/.field` defined twice | **Documented** |
| MOT-02 | LOW | motion | `.status--active.is-live` breathe defined but `is-live` never applied | **Documented** (unused-in-app; see MOTION_SYSTEM.md) |
| MOT-03 | LOW | motion | duplicate `spin`/`sol-spin` keyframes | **Documented** |
| PAGE-04 | LOW | onboarding | `loadOnboarding()` inert shim | **Documented** (retained) |
| PAGE-05 | LOW | group-detail | no nav highlight when active | **Documented** |
| BADGE-DUP / MONEY-DUP | LOW | design | parallel badge/money duplication | **Documented** (retire with future badge()→status migration) |

## Truth-model invariants

- Only backend `SUCCESS` → **Settled**; invoice **Paid** ≠ contribution
  **Settled**.
- KYC `SUBMITTED` → **Under review**, never Verified; a POST is never treated as
  final verification (status read from the response).
- Bank **Connected** ≠ **Payment ready** (requires ACTIVE + verified + KYC).
- Subscription cancel-scheduled → **Active through <date>**, never Cancelled.
- Goal `saved_cents` is **tracked planning value**, never an account balance.
- Circle **Waitlisted** ≠ **Joined**; **Visible** ≠ **Joinable**; payout preview
  is **net after fee**.
- Community content is **member opinion**, never promoted to official status.
- Redirects: only `safeUrl()`-validated `checkout_url` / `hosted_url` (http(s)
  only); after this increment there are **zero `javascript:` action paths**.
- Identifiers: no Stripe/KYC/bank/ACH/provider IDs, no user or author UUID /
  `created_by` / member-id fragment rendered as visible content. Group ids appear
  only as opaque routing args inside event handlers/attributes, never as visible
  PII. **Exception (by design):** a circle's own `invite_code` is deliberately
  shown (escaped) to its members in the "Invite your friends" card so it can be
  shared — it is a shareable circle token, not member PII.
- Every mutation is dup-guarded and backend-authoritative (no optimistic
  post/comment/like/join/reserve/pay/cancel/remove state).

## Remaining limitations

- **Notifications** load a bounded default page (no incremental "older").
- **No Premium resume endpoint** — a scheduled cancellation can't be undone
  in-app (only re-subscribe).
- **Manual goal progress** — `saved_cents` is user-advanced, not a live balance.
- **Community author identity** limited to "You"/"SOL member" (backend returns
  only UUIDs).
- **No Community edit/delete** for members (`hide` is owner/admin only).
- **Community pagination filters client-side** ("My circles"/"My posts" page the
  loaded window; "Load more" reaches the rest).
- **No Community like-count until interaction** (feed payload has no like state).
- **Legacy `group-detail`** remains a `showGroup`-injected view (data table on
  mobile; no nav highlight — PAGE-05).
- **Backend capabilities not surfaced:** circle chat, polls, and announcements
  (member-only, per-circle) and the `/match/recommend` scoring engine exist but
  are not exposed in the member UI.
- **DATE-01 partial:** `fmtDate()` exists and is used on the dashboard + Timeline
  table; other date sites still use their prior per-page formats.

## Recommended future work

Ranked (security/financial-truth risk → member value → engineering leverage):

1. **External — rotate the exposed `rk_live_` Stripe key** (see
   `PRODUCTION_UI_VERIFICATION.md` §External actions). Highest priority; outside
   the frontend code.
2. **Finish DATE-01** — route every date through `fmtDate()` for one format.
3. **Retire `badge()`/`.badge-*`** in favor of the `.status--*` chip system
   (BADGE-DUP) once all call sites are migrated.
4. **De-duplicate CSS + reconcile button class convention** (DS-02/DS-04).
5. **Perf:** dedupe the boot `/notifications` fetch (PERF-01); add a small GET
   cache (PERF-02); cap notifications/payments/discover renders (PERF-03).
6. **Surface backend features** (circle chat / polls / announcements) as a real
   circle-detail experience, replacing the legacy `showGroup` view.
7. **Consider splitting `app.html`** into versioned static modules — a deliberate
   architectural project, not an audit-increment change.
