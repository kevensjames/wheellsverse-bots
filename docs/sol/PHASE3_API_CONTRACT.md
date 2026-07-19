# Phase 3 — Circle Catalog + Subscription: API Contract

**Status:** contract draft for the frontend build. Locks the 5 product decisions and defines the API the frontend consumes. The frontend is built against this contract using the mock harness; the **backend (a separate repo) must implement it** before the feature ships. Frontend is developed behind a feature flag and never asserts access/eligibility locally.

## Locked decisions (2026-07-19)
- **A. Subscription model** — the **$9.99/mo participation** subscription is **new, alongside** the existing **$14.99/mo Premium**. Independent products; a member may hold either, both, or neither.
- **B. Gate** — the participation subscription gates **JOINING only**. A member who lapses mid-circle **stays in** their current circles (money already committed); they simply cannot join **new** ones. Payouts are NOT gated by the subscription.
- **C. Trial** — **full access** during the trial. **Stripe/backend is the source of truth**; the client only ever *reflects* subscription/trial state and NEVER grants access optimistically.
- **D. Admin** — a **role-gated `/admin` route inside this app** (backend-authorized), reusing the design system.
- **E. Entry fee** — **refundable until the circle starts**: charged at join, refunded if the member leaves while the circle is `FORMING`, non-refundable once it activates. Real money movement — disclosed in the join preview AND the confirm dialog.

## Money-safety invariants (carry over from Phases 1–2; every one is mandatory)
- Backend-authoritative for subscription, participation-eligibility, entry-fee, join, and payout state. **No optimistic promotion.**
- The client reads a gate/eligibility decision from the backend and renders it; it never computes "you may join" itself.
- All fees disclosed before any charge; refund rules stated in plain language.
- No "guaranteed payout/return/yield" language. A circle is a savings arrangement, not an investment.
- Other members rendered as "You"/"SOL member"; no UUIDs/PII/provider IDs.
- External URLs via `safeUrl`; untrusted strings via `esc`; mutations guarded by `SolGuard`; GET route-loads cancellable (P3), mutations never cancelled.

---

## Endpoints the frontend needs

> Shapes follow existing conventions (cents integers, ISO dates, UUID ids, enum strings). `?` = nullable/optional. All amounts in **cents**.

### Catalog (member)
`GET /catalog` → admin-defined circles open to browse/join.
```jsonc
[{
  "id": "uuid",
  "name": "Weekly Starter Circle",
  "description": "…",                 // optional, esc()'d
  "status": "OPEN" | "FORMING" | "FULL" | "CLOSED",
  "contribution_cents": 5000,
  "cadence": "WEEKLY" | "BIWEEKLY" | "MONTHLY" | { "kind": "CUSTOM", "days": 10 },
  "entry_fee_cents": 500,             // 0 if none; disclosed + refundable-until-start
  "fee_bps": 1000,                    // platform fee on the payout (existing)
  "member_count": 3,
  "max_members": 8,
  "payout_day_of_month": null,        // for MONTHLY; null otherwise
  "is_private": false,
  "tier": "STANDARD"                  // reserved; B gates joining regardless of tier
}]
```
`GET /catalog/{id}` → one circle, same shape (+ `members` when the caller is entitled; never raw user_ids rendered).

### Participation subscription (member) — reflects Stripe truth
`GET /participation/me` → the client's gate state. **The frontend renders this verbatim; it never derives `can_join`.**
```jsonc
{
  "can_join": true,                   // THE gate decision — backend-authoritative
  "status": "TRIALING" | "ACTIVE" | "PAST_DUE" | "CANCELED" | "NONE",
  "trial_end": "2026-08-01T00:00:00Z", // null if not trialing
  "current_period_end": "2026-08-15T00:00:00Z",
  "price_cents": 999,
  "reason": null                      // when can_join=false: "NO_SUBSCRIPTION" | "PAST_DUE" | …  (for member-safe messaging)
}
```
`POST /participation/checkout` → `{ "checkout_url": "https://checkout.stripe.com/…" }` (gated through `safeUrl`; may start a trial per Stripe config).
`POST /participation/cancel` → 204; client re-fetches `/participation/me` (never optimistically flips to canceled).

### Join eligibility + join (member)
`GET /catalog/{id}/eligibility` → per-circle readiness the client renders (never computes):
```jsonc
{
  "can_join": true,                   // backend-authoritative overall
  "checks": {
    "subscription": "ok" | "todo",    // maps to the $9.99 gate (B)
    "kyc": "ok" | "todo",
    "bank": "ok" | "todo",
    "account": "ok" | "blocked"
  },
  "your_position": 4,                 // preview only; confirmed on join
  "entry_fee_cents": 500,
  "entry_fee_refundable_until": "FORMING_END"  // plain-language refund rule for disclosure
}
```
`POST /catalog/{id}/join` → 200 on success. On failure returns a member-safe `detail` the client maps (existing `joinGroup` pattern: bank/kyc/subscription → deep-link CTA). Charging the entry fee is **backend-side** at join.
`POST /catalog/{id}/leave` → 200; backend applies the refund rule (refund iff still FORMING). Client shows the resulting state from a re-fetch, never asserts the refund.

### Admin (role-gated `/admin`) — all require admin authz server-side
- `GET /admin/circles` → all circles incl. drafts + participation counts.
- `POST /admin/circles` / `PATCH /admin/circles/{id}` / `POST /admin/circles/{id}/close` → create/edit/close (name, size, contribution, cadence, entry_fee, tier, private).
- `GET /admin/circles/{id}/participants` → roster + payment/participation status (no member PII beyond what admins are authorized to see).
- The frontend `/admin` route is only *rendered* for admin-role accounts, but authorization is enforced by the backend on every call (the client gate is UX only).

---

## Frontend build increments (each: mock-backed, feature-flagged `SOL_CATALOG`, money-safe, adversarially reviewed)
1. **Catalog browse** — `nav('catalog')`: list circles with contribution, cadence, entry fee, and a subscription-gate banner driven by `/participation/me` (`can_join`). No optimistic gating.
2. **Circle detail + join** — entry-fee + refund-rule disclosure, `/catalog/{id}/eligibility`-driven CTA (subscribe / verify / connect-bank / join), confirm dialog stating the fee + refund rule; `SolGuard`-guarded join.
3. **Participation subscribe flow** — subscribe CTA → `/participation/checkout` (safeUrl), trial/active state reflected from `/participation/me` (polled, never optimistic), cancel via confirm dialog.
4. **Admin console** — role-gated `/admin`: circle CRUD + participant view.

## Backend (separate repo — NOT in this monorepo; blocks steps that need real data)
Implement the endpoints above: catalog + admin CRUD, the participation Stripe product ($9.99, trial) + webhook + the `can_join` gate, entry-fee charge/refund tied to the FORMING→ACTIVE lifecycle, and the eligibility endpoint. Then integrate, run a full money-path adversarial review, and roll out behind the flag.
