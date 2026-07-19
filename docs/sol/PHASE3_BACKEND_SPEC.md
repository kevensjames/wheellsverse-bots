# Phase 3 — Circle Catalog: Backend Implementation Spec

**Audience:** the SOL backend team (the separate `wheellsverse-sol` repo — this is a
frontend monorepo). The Phase 3 **frontend is complete and deployed dark** behind
`SOL_FEATURES.catalog=false`; it integrates against the endpoints below without
redesign. Implement these to the exact shapes here, then the frontend is wired to
real endpoints, a full money-path review is run, and only then is the flag flipped
on (feature-flag rollout).

**Source of truth for shapes:** the deployed frontend (`frontend/sol/app/pages/catalog.js`,
`pages/admin.js`, `core/features.js`) + `docs/sol/PHASE3_API_CONTRACT.md`. Where the
frontend normalizes a field, the exact key it reads is noted.

---

## 0. Locked product decisions (must hold end-to-end)
- **$9.99/mo participation subscription is NEW, alongside the existing $14.99 Premium.** Separate Stripe products; a member may hold either, both, or neither.
- **Participation gates JOINING only.** A lapsed member stays in current circles (money already committed); they just can't join **new** ones. Payouts are NOT gated by participation.
- **Trial = full access.** Stripe/backend is the source of truth; the client only reflects it. Never grant access on the client.
- **Admin = role-gated.** The frontend UX-gates on `me.is_admin`; **the backend MUST enforce authz on every `/admin/*` call** (the client gate is not a security boundary).
- **Entry fee is refundable until the circle starts** (charged at join; refunded on leave while `FORMING`; non-refundable once `ACTIVE`).
- **Distinct financial concepts:** contribution ≠ entry fee ≠ participation subscription ≠ Premium. Never conflate in ledger, receipts, or copy.

---

## 1. Data model (minimum)
- **CatalogCircle**: `id(uuid)`, `name`, `description?`, `status` (`DRAFT|OPEN|FORMING|FULL|CLOSED`), `contribution_cents(int≥1)`, `entry_fee_cents(int≥0)`, `cadence` (`WEEKLY|BIWEEKLY|MONTHLY` or `{kind:"CUSTOM",days:int}`), `fee_bps(int)` (platform fee on the payout, existing), `member_count`, `max_members`, `payout_day_of_month?`, `is_private(bool)`, `tier` (`STANDARD|PREMIUM`, reserved), `created_by(admin)`, timestamps.
- **ParticipationSubscription** (per member): Stripe subscription id, `status` (map Stripe → `TRIALING|ACTIVE|PAST_DUE|CANCELED|NONE`), `trial_end?`, `current_period_end?`, `price_cents`.
- **CircleMembership**: circle_id, user_id, `position`, `status`, `has_received_payout`, join timestamp.
- **EntryFeeCharge**: membership_id, `amount_cents`, `status` (`CHARGED|REFUNDED|NON_REFUNDABLE`), Stripe payment/refund ids — see §5.

---

## 2. Member catalog endpoints

### `GET /catalog` → `CatalogCircle[]`
Circles a member may browse (public listing — typically `OPEN`/`FORMING`, not `DRAFT`/`CLOSED`). Auth required (any member; browsing is open to all members). **No PII.** Frontend reads: `id, name, description, status, contribution_cents, entry_fee_cents, cadence, member_count, max_members, payout_day_of_month, is_private`.

### `GET /catalog/{id}` → `CatalogCircle`
One circle. Include `members[]` **only** if the caller is entitled, and never render-facing PII — the frontend never displays member identities from this. 404 if not browseable.

### `GET /catalog/{id}/eligibility` → eligibility object
**THE authoritative join decision** — the frontend renders `can_join` verbatim and never computes it.
```jsonc
{
  "can_join": true,                    // overall gate — backend-authoritative
  "checks": {
    "subscription": "ok" | "todo",     // the $9.99 participation gate
    "kyc":          "ok" | "todo",
    "bank":         "ok" | "todo",
    "account":      "ok" | "blocked"
  },
  "your_position": 4,                  // preview only; confirmed on join (frontend does NOT render it)
  "entry_fee_cents": 500,              // authoritative fee for THIS join
  "entry_fee_refundable_until": "FORMING_END"
}
```
`can_join` must be the AND of: participation active-or-trialing, KYC ok, bank ok, account active, circle joinable (open + not full + not already a member). If `checks` is omitted the frontend fails safe (renders "todo"), but ALWAYS send `checks` so the CTA is accurate.

### `POST /catalog/{id}/join` → membership result
Backend re-checks eligibility + capacity (do NOT trust the client), **charges the entry fee** (§5), creates the membership. Response MUST let the client confirm membership — the frontend treats HTTP 200 alone as NOT joined; it checks `members[].user_id === me.id`:
```jsonc
{ "id": "circle-uuid", "members": [{ "user_id": "…", "position": 5, "status": "ACTIVE" }, …] }
```
On failure return a member-safe `detail` the frontend maps: match `/full|capacity/`, `/participation|subscription/`, `/kyc|identity/`, `/bank/`, `/account status|inactive/`, `/already a member/`. **Idempotent:** a duplicate join for an existing member must NOT create a second membership or a second entry-fee charge.

### `POST /catalog/{id}/leave` → 200
Apply the refund rule: refund the entry fee **iff** the circle is still `FORMING`; non-refundable once `ACTIVE` (§5). Backend-authoritative — the frontend re-fetches, never asserts the refund.

---

## 3. Participation subscription endpoints (Stripe = source of truth)

### `GET /participation/me` → participation state
The frontend renders this verbatim (`normalizeParticipation`); it never derives access.
```jsonc
{
  "can_join": true,                    // gate decision (default false)
  "status": "TRIALING|ACTIVE|PAST_DUE|CANCELED|NONE",
  "trial_end": "2026-08-01T00:00:00Z", // null if not trialing
  "current_period_end": "…",
  "price_cents": 999
}
```

### `POST /participation/checkout` → `{ "checkout_url": "https://checkout.stripe.com/…" }`
Create a **Stripe Checkout Session (subscription mode)** for the $9.99 product (with the trial per config) and return its URL (https only — the frontend `safeUrl`-gates it). Success/cancel redirect back to `…/sol/app?participation=success|cancel`.
**CRITICAL idempotency (a review HIGH):** if the member ALREADY has a participation subscription (incl. `PAST_DUE`), this endpoint MUST NOT create a second subscription — return the existing one / an update flow, or 409. The frontend routes `PAST_DUE` to "billing help" (not this endpoint), but the backend must still refuse duplicates defensively.

### `POST /participation/cancel` → 204
Cancel at period end (not immediately) — the member keeps access through `current_period_end`. Backend-authoritative; the frontend re-fetches `/participation/me` (never optimistically flips to canceled).

### Stripe webhook (backend-internal)
Handle `checkout.session.completed`, `customer.subscription.{created,updated,deleted}`, `invoice.payment_failed` → update ParticipationSubscription.status. This is the ONLY thing that flips `can_join` to true — checkout completing on the client is NOT activation. (The frontend polls `/participation/me` on return to reflect the webhook result.)

---

## 4. Admin endpoints (authz enforced server-side on EVERY call)

All require an admin role — **do not rely on the client gate.** Non-admin → 403.

- `GET /admin/circles` → `CatalogCircle[]` incl. `DRAFT` + `CLOSED` + participation counts. Frontend reads: `id, name, status, contribution_cents, entry_fee_cents, cadence, member_count, max_members, is_private`.
- `POST /admin/circles` (body: `{name, contribution_cents, entry_fee_cents, max_members, cadence, is_private}`) → created circle (`DRAFT`). Validate: contribution ≥ 1, entry_fee ≥ 0, max_members 2–50, name non-empty, cadence in the allowed set. (Frontend already caps at $1M + validates, but re-validate.)
- `PATCH /admin/circles/{id}` (same body; **`cadence` may be OMITTED** — the frontend omits it when preserving a non-standard cadence, so treat missing `cadence` as "unchanged").
- `POST /admin/circles/{id}/close` → close the circle (`status=CLOSED`; no new joins). **Existing members + in-progress cycles MUST be unaffected** (the admin UI promises this).
- `GET /admin/circles/{id}/participants` → `[{ position, status }]`. **Return the minimum** — the frontend renders position + status + a generic "Member" label only. Do not send names/emails unless a future admin-authz decision requires it (and then it's a privacy review).

---

## 5. Entry-fee charge/refund state machine
```
join (circle FORMING/OPEN) ──charge entry_fee_cents──▶ CHARGED
CHARGED + leave while FORMING ──refund──▶ REFUNDED
CHARGED + circle activates (ACTIVE) ─────▶ NON_REFUNDABLE
```
- Charge the entry fee as part of `POST /catalog/{id}/join` (atomic with membership creation — if the charge fails, the join fails; no orphan membership, no orphan charge).
- Refund iff the circle is still `FORMING` at `leave` time; disclose "refundable until the circle starts, non-refundable once it activates" (the frontend already shows this).
- **Idempotent:** never double-charge on a retried join; never double-refund. Keyed on membership_id.
- The entry fee is a **platform fee, separate from the payout pool** — keep it out of `contribution`/payout ledgers.

---

## 6. Money-safety invariants the BACKEND must enforce
1. **`can_join` is authoritative** — the client renders it and never grants access. Compute it correctly (participation + KYC + bank + account + capacity).
2. **No duplicate participation subscription** (esp. for `PAST_DUE`) — checkout must refuse/short-circuit for existing subscribers (a reviewed HIGH on the frontend, defended there by routing PAST_DUE to billing help; enforce server-side too).
3. **Entry-fee + join atomicity + idempotency** — one charge per membership; join and charge succeed or fail together; refund only while FORMING.
4. **Checkout ≠ activation** — only the Stripe webhook flips `can_join`/status.
5. **Cancel = at period end** — access persists until `current_period_end`.
6. **Admin authz on every `/admin/*` call** — the client gate is UX only.
7. **No PII in catalog/participant payloads** beyond what an authz decision explicitly allows.
8. **Distinct ledgers** for contribution, entry fee, participation subscription, and Premium.

---

## 7. Integration + rollout sequence (after the backend is built)
1. Point the frontend API base at the real endpoints (already the case: `sol-api-production.up.railway.app`); remove the mock harness reliance (tests keep the mock).
2. Wire + smoke each surface behind the flag in a staging/preview: browse → eligibility → join (+ entry-fee charge) → subscribe (Stripe test mode) → cancel → admin CRUD.
3. **Full money-path adversarial review** on the integrated flow (real charges, refunds, subscription lifecycle, idempotency, authz).
4. Feature-flag rollout: flip `SOL_FEATURES.catalog=true` for a cohort, monitor, then general availability.

> Standing external action (unrelated but open): rotate the previously-exposed `rk_live_` Stripe key before any real Stripe traffic.
