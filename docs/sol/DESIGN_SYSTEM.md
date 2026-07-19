# SOL Design System

The **implemented** design system of the deployed SOL member app. Source of
truth: `frontend/sol/sol-design-system.css` (shared tokens) + the inline
`<style>` block in `frontend/sol/app.html`. Reviewed at commit `6cd3d00`,
production `https://wheellsverse.com/sol/app`.

> This doc is committed **with** the Increment-10 fixes and describes the
> **post-fix** state (e.g. the AA chip-contrast tokens from A11Y-02).

> This documents what ships, not an ideal. Where the app diverges from the
> shared stylesheet (e.g. button class names), that divergence is called out
> rather than hidden.

## Design principles

- **Warm-trust.** A bank-grade neutral base (deep ink text, warm off-white
  paper) with a single sunrise accent — the ROSCA metaphor of the payout
  "coming around" to each member.
- **Financial truth over conversion.** Money states are semantic and backed by
  the server; nothing is styled to imply a state the backend hasn't confirmed.
- **Calm, low-noise.** Restrained motion, no vanity metrics, no urgency.
- **Accessible by construction.** Status is never color-only; focus is always
  visible; dialogs trap and restore focus.

## Information hierarchy

Every member page follows the same shape: one `<h1>` (page title) + a `.sub`
subtitle, then summary/attention content, then the primary list/feed, then
dialogs. Section headers are `<h2>`; card titles `<h3>`. Money figures use
`.tnum` (tabular numerals) so columns align.

## Layout system

- **Shell:** fixed-width sidebar (`.sidebar`, 230 px) + fluid `.main`
  (`flex:1; min-width:0` — the `min-width:0` is load-bearing: it lets long
  content shrink instead of forcing horizontal overflow).
- **Sidebar (desktop):** grouped nav — Dashboard/Timeline/Alerts,
  Circles/Discover/Goals, Bank/Payments, Verify ID/SOL Score, Community,
  Premium. Active item gets `.active` + `aria-current="page"`.
- **Mobile navigation:** a fixed bottom bar (`.mobile-nav`) with 5 slots —
  Home, Circles, Pay, Alerts, **More** — where More opens a bottom sheet
  (`.more-sheet`, `role="dialog"`) holding the eight secondary destinations.
- **Page width:** content flows full-width inside `.main` padding; cards and
  grids constrain line length.
- **Card grids:** `auto-fill`/`auto-fit minmax()` grids (e.g. Discover
  `minmax(300px,1fr)`), collapsing to a single column on mobile.
- **Breakpoints actually used:** `max-width: 560px`, `640px`, `820px` (and a
  couple of component-local ones). There is no exhaustive breakpoint scale —
  each page adds the queries it needs, mostly at ~560–640 px.

## Typography

From `sol-design-system.css`:

- **Font stack:** display = `"Space Grotesk", system-ui, -apple-system, sans-serif`;
  body = `"Inter", system-ui, -apple-system, sans-serif`. Loaded via Google
  Fonts `@import` (the one external asset — see `PERFORMANCE.md`).
- **Type scale** (`--step-*`, a ~1.2 ratio): `--step--1:.833rem`,
  `--step-0:1rem`, `--step-1:1.2rem`, `--step-2:1.44rem`, `--step-3:1.728rem`,
  `--step-4:2.07rem`, `--step-5:2.49rem`, `--step-6:3rem`.
- **Line heights:** `--lh-tight:1.2` (headings), `--lh-body:1.55` (body).
- **Heading hierarchy:** `h1 → --step-5`, `h2 → --step-4`, `h3 → --step-2`,
  `h4 → --step-1`, all `font-family:--font-display; font-weight:600`. (The
  app's inline `h1` is tuned to `1.5rem` for the denser app chrome.)
- **Monetary typography:** `.tnum` / `font-variant-numeric:tabular-nums` on
  every money figure; `fmt$()` renders `$` + `cents/100` with 2 decimals,
  `en-US` grouping.
- **Metadata typography:** `.hint-muted` / `.sub` — `--step--1`, `--ink-500`.

## Spacing

Space tokens (`--s-*`): `--s-1:.25rem`, `--s-2:.5rem`, `--s-3:.75rem`,
`--s-4:1rem`, `--s-6:1.5rem`, `--s-8:2rem`, `--s-12:3rem`, `--s-16:4rem`. The
shared components use these; the app's inline component CSS more often uses
literal `rem` values tuned per component (e.g. card padding `1rem 1.15rem`).

## Radius & elevation

- **Radius:** `--r-sm:.375rem`, `--r-md:.625rem`, `--r-lg:1rem`,
  `--r-pill:999px`.
- **Shadow:** `--shadow-1:0 1px 2px rgba(14,23,38,.06)` (cards),
  `--shadow-2:0 4px 16px rgba(14,23,38,.10)` (modals/toasts),
  `--shadow-glow:0 8px 32px rgba(232,147,36,.25)` (sunrise glow — primary-button
  hover + landing).

## Color roles

Semantic roles (hex from `sol-design-system.css`):

| Role | Token | Value |
|------|-------|-------|
| Text primary | `--ink-900` | `#0E1726` |
| Text secondary / muted | `--ink-500` (`--muted`) | `#46577A` |
| Surface (base) | `--paper` | `#FBFAF7` (warm off-white, never cold `#fff`) |
| Surface (card) | `--surface` | `#FFFFFF` |
| Surface (sunken) | `--surface-2` | `#F4F2EC` |
| Border | `--line` | `#E7E2D7` |
| Accent (brand) | `--sol-500` / `--sol-600` | `#E89324` / `#C9781F` |
| Success | `--success-600` / `-100` | `#1E9E6A` / `#DCF3E8` |
| Warning | `--warn-600` / `-100` | `#C98A14` / `#FBEFD2` |
| Danger | `--danger-600/700/100` | `#D33A3A` / `#B02525` / `#FBE3E1` |
| Information | (neutral) `--ink-100` / `--ink-700` | `#E5E9F0` / `#1E3050` |
| Premium | gradient `#1a2740→--ink-800` | dark "premium-card" |
| Focus ring | `--sol-500` | 2 px outline, 2 px offset (`:focus-visible`) |

## Status chips (canonical matrix)

`.status` (design-system.css:150) = tinted pill + **leading dot** + text label,
so it never relies on color alone. Semantic variants and their token pairs:

| Chip class | Fg / Bg token | Used for |
|------------|---------------|----------|
| `status--active` | `--st-active` `#1E7A54` / `#DCF3E8` | active circle, active subscription, active goal |
| `status--forming` | `--st-forming` `#7A5309` / `#FBEFD2` | forming/open circle |
| `status--completed` | `--st-completed` `#3B4A66` / `#E5E9F0` | completed circle, settled |
| `status--failed` | `--st-failed` `#B02525` / `#FBE3E1` | failed payment / circle |
| `status--cancelled` | `--st-cancelled` `#5E6B85` / `#EDEBE4` | cancelled / archived |
| `status--pending` | `--st-pending` `#7A4600` / `#FBD9A2` | processing / under review / pending |
| `status--overdue` | `--st-overdue` `#B02525` / `#FBE3E1` | overdue goal |
| `status--verified` | `--st-verified` `#1E7A54` / `#DCF3E8` | identity verified, bank verified |
| `status--warning` | `--st-warning` `#7A5309` / `#FBEFD2` | action required |
| `status--blocked` | `--st-blocked` `#8A1C1C` / `#FBE3E1` | blocked / suspended |

Chip foreground colors were darkened in Increment 10 (A11Y-02) to meet WCAG AA
for 13px bold text: `--st-pending` `#B4700F`→`#7A4600` (2.95→5.75:1),
`--st-forming`/`--st-warning` `#9A6A0F`→`#7A5309` (4.14→5.99:1).

`.status--active.is-live` adds the calm 2.4 s `sol-breathe` on the single live
payout slot (opacity-only; off under reduced motion).

## Buttons

**The app uses its own inline button classes** (not the design-system's
`btn--primary`/`btn--ghost`/`btn--danger`, which serve the landing/admin
surfaces):

| Class | Role | Style |
|-------|------|-------|
| `.btn` | base | inline-flex, display font, `transition:.15s` |
| `.btn-primary` | primary | `--sol-500` bg, ink text, glow on hover |
| `.btn-ghost` | secondary | transparent, `--line` border |
| `.btn-danger` | destructive | `--danger-700` bg, white text |
| `.btn--sm` | size modifier | smaller padding/size |
| `.btn--loading` | loading | transparent text + spinner (`sol-spin`) |
| `:disabled` | disabled | `opacity:.5`, `not-allowed` |

Usage counts in markup: `btn-ghost` ×88, `btn-primary` ×41, `btn-danger` ×4,
`btn--sm` ×57. **Naming inconsistency (documented, NOTE):** variants use a single
dash (`btn-primary`) while modifiers use a double dash (`btn--sm`); the shared
stylesheet uses double-dash for both. Reconciling to one convention is safe
future cleanup, deferred to avoid churning 130+ call sites this increment.

## Forms

- **Labels:** every field has an explicit `<label for>` (or `.sr-only` label for
  compact composers). Field styling from `.field` (design-system).
- **Descriptions/hints:** `.hint` / `.comm-note` — muted, `--step--1`.
- **Validation:** inline `.err` (role="alert") per field/form; error summary is
  the per-dialog `<p class="err" role="alert">`.
- **Sensitive fields:** bank/KYC never echo full account/routing numbers or
  document IDs; masked `account_last4` only.
- **Date inputs:** native `<input type="date">` with a `max` of today where a
  future date is invalid (e.g. KYC DOB `max = today`).
- **Currency inputs:** goal amounts entered in dollars, converted to cents
  (`dollarsToCents`) before the API call; displayed with `fmt$`.

## Cards

| Pattern | Class | Used by |
|---------|-------|---------|
| Summary / side card | `.card`, `.side-card` | Dashboard cards |
| Attention card | `.attn-card` (+ `status--*`) | Dashboard "needs attention" |
| Financial row | `.pay-card` | Payments settlement rows |
| Goal card | `.goal-card` | Goals |
| Circle card | `.circle-card` / `.disc-card` | Circles / Discover |
| Notification | `.notif-item` | Notifications |
| Community post | `.comm-post` (`<article>`) | Community |

All cards share `--surface` bg, `--line` border, `--r-lg` radius, `--shadow-1`.

## Dialogs & sheets

Eight dialogs, all built on the shared `.bank-modal` overlay pattern with an
identical accessibility contract (see `ACCESSIBILITY.md` for the per-dialog
matrix):

circleDetailDialog · premCancelDialog · commReportDialog · goalFormDialog ·
goalProgressDialog · goalConfirmDialog · bankRemoveDialog · moreSheet.

Contract:

- **Focus trap** filtered to *visible* focusables (`offsetParent !== null`) so
  hidden controls never receive focus; radio groups collapse to one tab stop.
- **Escape** closes — but is **busy-guarded**: while a mutation is in flight
  (`dataset.busy === '1'` / an in-flight flag) Escape is ignored so a submit
  can't be interrupted mid-request.
- **Focus restoration** to the triggering control on close (except where the
  re-render destroys the trigger, e.g. bank removal, which lands focus on a
  stable element itself).
- **Initial focus** moves into the dialog on open.
- **Mobile:** dialogs are centered cards; the More sheet becomes a bottom sheet.

## Icons

A single inline **SVG sprite** (`<symbol>` defs, 14 symbols) referenced with
`<use href="#ic-*">`. `.ic` sets `stroke:currentColor; fill:none; stroke-width:2`
so icons inherit text color. Decorative icons carry `aria-hidden="true"`.

## Content guidance

### Canonical vocabulary

The app must use one word per state and must **never mix** the forbidden pairs
below. (State machines live in the per-page `normalize*()` functions.)

**Payment contribution** (`normalizePayment` / `PAY_STATE`): `Due` · `Submitted`
· `Processing` · `Settled` · `Failed` · `Returned` · `Pending review` ·
*fallback* `Status unavailable`. Only backend `SUCCESS` becomes **Settled**.

**Premium invoice:** `Paid` · `Pending` · `Failed` · `Refunded` (only if the
backend reports it). Invoice **Paid** is a distinct concept from a contribution
being **Settled** — they are never conflated.

**KYC** (`normalizeKycState`): `Verification required` · `Under review`
(backend `SUBMITTED`) · `Identity verified` · `Action required` ·
`Status unavailable`.

**Bank** (`normalizeBank`): `Connected` · `Verified` · `Payment ready` ·
`Pending verification` · `Disconnected` · `Status unavailable`. **Connected is
not Payment ready** — payment-ready requires an ACTIVE, verified account *and*
KYC.

**Subscription** (`normalizeSubscriptionState`): `Active` ·
`Cancellation scheduled` / `Active through <date>` · `Billing action required` ·
`Cancelled` · `Status unavailable`. A scheduled cancellation stays **Active
through** its period end — never shown as already Cancelled.

**Goals** (`GOAL_STATE`): amounts are `Tracked` vs `Target`; states `Active` ·
`Achieved` · `Overdue` · `Archived` · `Status unavailable`. Tracked progress is
a **planning value, not an account balance**.

**Circle availability** (`normalizeAvailability`): `Open` · `Limited` · `Full` ·
`Invite only` · `Active — closed` · `Waitlisted` · `Unavailable`. Visible ≠
Joinable; Waitlisted ≠ Joined.

### Must-never-mix pairs

`Paid`≠`Settled` · `Submitted`≠`Verified` · `Connected`≠`Payment ready` ·
`Visible`≠`Joinable` · `Selected`≠`Reserved` · `Waitlisted`≠`Joined` ·
`Tracked progress`≠`Account balance` · `Member opinion`≠`Official status`.

### Safe financial language

- **Prohibited claims:** guaranteed payout / return / yield / credit /
  affordability; "your money is safe/insured"; any implied investment return.
  SOLCIRCLE is described as a savings arrangement, **not a bank, not an
  investment**.
- **Payout previews** always show the **net** amount after the disclosed
  platform fee, never the gross pool, and never a guaranteed date.
- **Error messages:** generic and safe — never a raw provider/Stripe/Plaid/ACH
  message or internal ID. Rate-limit → "you're doing that a lot"; auth →
  "session expired"; else "something went wrong, please try again."
- **Empty states:** honest and non-blaming ("No community posts yet."); on a
  *fetch failure* the copy says "temporarily unavailable" + Retry — it never
  claims a true zero.
- **Privacy-sensitive language:** community/legacy author identity is only "You"
  or "SOL member"; no names, emails, phones, or UUIDs.

## Component inventory (pattern → pages)

| Pattern | Pages |
|---------|-------|
| Summary/attention cards | Dashboard |
| Status chip | Circles, Discover, Payments, Bank, KYC, Premium, Goals, Timeline |
| `.bank-modal` dialog | Bank, Premium, Goals, Discover, Community |
| Skeleton (`.sk`) | Discover, Community, (loaders) |
| Feed/list (`<ul>`/`<article>`) | Community, Notifications, Payments |
| Progress bar (`.pbar`) | Dashboard, Goals |
| Empty/error/Retry block | every loader |
| SOL Orb (Canvas) | Dashboard only |
