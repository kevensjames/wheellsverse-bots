# SOL Accessibility Audit

Application-wide accessibility review of the deployed SOL member app. Reviewed at
commit `6cd3d00`, production `https://wheellsverse.com/sol/app`.

> This doc is committed **with** the Increment-10 fixes and describes the
> **post-fix** state; changes made this increment are annotated inline (e.g.
> "A11Y-01", "A11Y-03").

## Standard & scope

Target: **WCAG 2.2 AA** where applicable to a static SPA. This is an internal
audit, **not a formal certification or third-party conformance claim**. Scope =
the 13 member routes + 8 dialogs + global shell/navigation.

## Automated checks

Run in this increment:

- **JS syntax / structural parse** of `app.html` (extracts every inline
  `<script>`, validates it parses) — used as a build gate.
- **Source greps** for one-`<h1>`-per-page, orphaned `aria-controls` /
  `aria-labelledby` targets, `role="dialog"` completeness, and 44 px target
  rules.
- **Harness + Playwright DOM assertions** (per feature, across increments):
  heading counts, focus trap behavior, `aria-pressed`/`aria-expanded` state,
  `offsetParent` visibility filtering, and no-UUID / escaped-content checks.

No paid axe/WAVE scan or formal AT (screen-reader) certification was performed;
manual keyboard + DOM verification stands in for it.

## Manual checks performed

- Keyboard-only navigation through the shell + each route
- Visible focus (`:focus-visible` 2 px ring, design-system.css:61)
- One `<h1>` per route; heading order
- Dialog focus trap / Escape / restoration (all 8)
- Forms: labels, inline errors, error summaries
- `aria-live` announcement regions after mutations
- Progress bars (`role="progressbar"` + `aria-valuenow/min/max`)
- Status chips readable without color (dot + text label)
- Tables → card/stacked layout on mobile
- Feed/list semantics (`<ul>`/`<article>`/`<time>`)
- Exact timestamps (`<time datetime>`)
- Color independence
- Reduced motion (see `MOTION_SYSTEM.md`)
- 320 px reflow / no horizontal overflow
- 44 px touch targets on mobile

## Global shell

- **Landmarks:** `<main>` content region; sidebar `<nav>`; mobile `<nav>`
  bottom bar. Nav items are `role="button"` with `aria-current="page"` on the
  active route.
- **Skip/redirect:** `nav()` moves the active page; focus management is
  per-action (mutations land focus deliberately).
- **Nav items are real `<button>` elements** (converted from hrefless
  `<a role="button">` in Increment 10 — A11Y-01) with `aria-current="page"` on
  the active route, so the entire sidebar is keyboard-operable.
- **Unread badge** (`#navUnread`) is a visual count paired with the "Alerts"
  text label — not color-only.

## Page-by-page matrix

| Route | H1 | Landmarks | Keyboard / focus | Announcements | Notes |
|-------|----|-----------|-----------------|---------------|-------|
| dashboard | 1 | main, cards | cards keyboard-reachable; Orb `aria-hidden` | partial-failure cards render Retry | Orb decorative |
| groups (Circles) | 1 | main, list | card links focusable | — | legacy `showGroup` detail (below) |
| group-detail (legacy) | 1 (`<h2>`-led detail) | main, table | member table keyboard-navigable | — | **legacy**; member labels "You"/"SOL member" only |
| discover | 1 | main, list, dialog | detail dialog trap | `aria-live` count + join/reserve result | net payout + fee disclosed |
| payments | 1 | main, list | pay actions focusable | `aria-live` on pay result | per-row `data-label` on mobile |
| bank | 1 | main, list, dialog | remove dialog trap | persistent page `aria-live` | masked `account_last4` |
| kyc | 1 | main, form | DOB form; submit guard | `aria-live` on state | 5 states + Status unavailable |
| premium | 1 | main, dialog | cancel dialog trap | `aria-live` on cancel | checkout via `safeUrl` |
| notifications | 1 | main, list | mark-read focusable | `aria-live` unread count | bounded page |
| goals | 1 | main, list, dialogs (×4) | form/progress/confirm dialogs trap | `#goalsLiveStatus` `aria-live` | Tracked ≠ balance |
| community | 1 | main, feed (`<article>`), dialog | report dialog trap; filters `aria-pressed`; comments `aria-expanded` | `#commLive` `aria-live` | escaped plain-text bodies |
| timeline | 1 | main, list | list keyboard-reachable | — | read-only |
| trust (SOL Score) | 1 | main | — | — | read-only |

## Dialog inventory

All eight share the `.bank-modal` contract. Verified behaviors:

| Dialog | Initial focus | Tab loop | Shift+Tab | Escape | Busy-guard | Restore |
|--------|---------------|----------|-----------|--------|-----------|---------|
| Bank removal (`bankRemoveDialog`) | first action | ✓ | ✓ | ✓ | `_bankRemoveInFlight` | lands on list (trigger destroyed by re-render) |
| Premium cancellation (`premCancelDialog`) | first action | ✓ | ✓ | ✓ | `_premCancelInFlight` | ✓ trigger |
| Goal create/edit (`goalFormDialog`) | first field | ✓ (visible-only) | ✓ | ✓ | form guard | ✓ trigger |
| Goal progress (`goalProgressDialog`) | amount field | ✓ | ✓ | ✓ | guard | ✓ trigger |
| Goal archive/delete (`goalConfirmDialog`) | confirm/cancel | ✓ | ✓ | ✓ | guard | ✓ trigger |
| Discover detail/join (`circleDetailDialog`) | close/into-dialog | ✓ | ✓ | ✓ (`dataset.busy`) | `_discJoinBusy` | ✓ trigger |
| Community report (`commReportDialog`) | first reason radio | ✓ (radio group = 1 stop) | ✓ | ✓ (`dataset.busy`) | `_commReportBusy` | ✓ trigger |
| Mobile More sheet (`moreSheet`) | first item | ✓ | ✓ | ✓ (scoped `_moreTrapKey`) | n/a | ✓ trigger |

Focus traps filter to **visible** focusables (`offsetParent !== null`) so a
control inside a `display:none` region can never be tabbed to. Radio groups
collapse to a single tab stop (matches native order; prevents Shift+Tab escape).

## Known accessibility limitations

- **No formal AT certification.** Manual keyboard + DOM verification only; no
  screen-reader conformance sign-off.
- **Legacy `group-detail`** carries a visually-hidden `<h1>` ("Circle detail",
  added in Increment 10 — A11Y-05) and is visually `<h2>`-led; it remains a data
  table on mobile (horizontally scrollable), not fully card-stacked.
- **The mobile "More" sheet** now implements a full focus trap (Increment 10 —
  A11Y-03): on open it stores the trigger and moves focus to the first item; a
  scoped `_moreTrapKey` handler traps Tab/Shift+Tab and Escape; on close it
  restores focus to the trigger. (The old always-on global Escape handler was
  removed.)
- **Automated contrast** was reasoned from tokens, not machine-measured for
  every state; the semantic tokens were chosen for AA but a full per-state
  contrast report is future work.

## Regression checklist (reuse each increment)

- [ ] Exactly one `<h1>` on the page; logical heading order
- [ ] Every interactive control is a real `<button>`/`<a>`/input (not a bare
      `div`), keyboard-operable, with a visible focus ring
- [ ] Every dialog: role/aria-modal, initial focus in-dialog, Tab + Shift+Tab
      loop, Escape (busy-guarded), focus restored on close
- [ ] Focus trap filters to visible focusables; radio groups = one tab stop
- [ ] Mutations announce via an `aria-live` region and land focus deliberately
- [ ] Status conveyed by text/shape, never color alone
- [ ] `<time datetime>` for timestamps; `fmt$` for money
- [ ] 44 px targets on mobile; no horizontal overflow at 320 px
- [ ] Reduced motion: no animation, no lost state
- [ ] No raw UUID/provider id / member PII rendered; untrusted content escaped

## Findings

_Populated from the Increment-10 audit + fix sweep — see `UX_AUDIT.md` for the
consolidated findings table and dispositions._
