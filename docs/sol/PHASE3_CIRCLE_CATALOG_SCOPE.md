# Phase 3 — Circle Catalog + Subscription: Scope & Decisions

**Status:** scoping for sign-off. This is the *next feature milestone* after the Phase 2 modularization + P3–P5 refactor. Unlike P3–P5 (frontend-only), Phase 3 is **majority backend work**, and the Sol backend is a **separate repo not checked out in this monorepo** — so this doc defines scope, surfaces the decisions only you can make, and marks what can start now vs. what is backend-gated.

---

## 1. The vision (as specified)

A **Circle Catalog**: admin-defined circles a member browses and joins, with:
- **Admin-defined circles** — an operator creates circles (name, size, contribution, cadence, entry fee, rules) rather than members creating them ad hoc.
- **Flexible cadence** — not just monthly; weekly/bi-weekly/custom frequencies.
- **Per-circle entry fee**.
- **One $9.99/month participation subscription** — a single subscription (not per-circle) gates the ability to participate, with **Stripe (trial) as the source of truth** for subscription state.
- **Backend-authoritative payout eligibility** — the backend decides who is eligible for a payout; the client never asserts it.
- **Admin tools** — to create/manage circles and view participation.

---

## 2. Current reality (what already exists, so we build on it — not over it)

- **Premium today is $14.99/mo** (live in prod, Stripe product + price + webhook). Phase 3 introduces a **$9.99/mo** number. → **Decision needed** (see §4-A): is $9.99 a *new participation* subscription distinct from the $14.99 Premium, a *replacement/repricing* of Premium, or does Premium get repurposed as the participation gate?
- **Circles/groups** already exist: `/groups`, `/groups/{id}`, `/groups/{id}/join`, `/groups?status=FORMING`, plus Discover (`/circles/reserve`, `/circles/waitlist/me`). Today circles are member-created/FORMING-based. Phase 3's "admin-defined catalog" is a **new creation/ownership model** layered on top.
- **Cadence today is monthly** (`payout_day_of_month`). Flexible cadence is a **new backend field + settlement-schedule change**.
- **Subscriptions** already exist: `/subscriptions/me`, `/subscriptions/checkout`, `/subscriptions/cancel`, `/subscriptions/invoices`, with Stripe as truth. The participation-gating semantics are new.
- **Eligibility** is already backend-authoritative for join (KYC + verified bank). Payout eligibility gating is an extension.

---

## 3. Work split (why Phase 3 ≠ P3–P5)

| Capability | Backend (separate repo — NOT here) | Frontend (this repo — buildable now) |
|---|---|---|
| Admin-defined circles | circle model: admin ownership, entry_fee, cadence enum; admin CRUD endpoints; catalog list endpoint | Catalog browse UI, circle-detail w/ entry fee + cadence, admin console screens |
| Flexible cadence | cadence field + settlement scheduler changes | render cadence; cadence picker in admin |
| Entry fee | charge/collect entry fee at join; ledger | show fee, disclose in join preview + confirm |
| $9.99 participation subscription | Stripe product/price, trial, webhook, **participation gate** enforced server-side | subscribe CTA, gate messaging, trial state, "source of truth = backend" polling |
| Payout eligibility | eligibility rules + endpoint | render eligibility, never assert it |
| Admin tools | admin authz + endpoints | admin UI |

**Bottom line:** ~70% of Phase 3 is backend. Without the Sol backend repo, the frontend can only be built against a **mock contract** and cannot be integration-verified or shipped as a working feature.

---

## 4. Decisions only you can make (blocking)

- **A. Subscription model.** Is the **$9.99 participation** subscription *new alongside* the $14.99 Premium, a *replacement* of Premium, or is Premium *repurposed* as the participation gate? (Affects Stripe products, existing subscribers, and all gating copy.)
- **B. Gate semantics.** Does the subscription gate **joining** circles, **receiving payouts**, both, or only *premium* circles? What happens to a member who joined then lapsed mid-cycle (money already committed)?
- **C. Trial.** Length, and what a trial user can do (browse only? join? receive payout during trial?). "Stripe trial as source of truth" — confirm the client only ever *reflects* Stripe/backend state, never grants access optimistically.
- **D. Admin surface.** Is admin a screen *inside this member app* (role-gated route) or a *separate console*? Who are the admins (authz model)?
- **E. Entry fee.** Refundable? On join or on circle start? Where does it go (platform vs pool)? This is real money movement — needs explicit rules and disclosure copy.

---

## 5. Proposed plan (backend-gated, staged)

1. **Contract first** — agree the API contract (catalog list, circle shape w/ entry_fee + cadence, subscription-gate check, eligibility) as a written spec. (Doable now; needs your §4 answers.)
2. **Frontend scaffold against the mock** — build Catalog browse, circle-detail (entry fee + cadence + gate messaging), subscribe flow, and admin screens against the enriched mock harness (P5). Fully testable in-browser, **not shipped** until the backend exists. (Doable now, after step 1.)
3. **Backend build** — in the Sol repo (requires that repo + access): models, admin CRUD, participation gate, Stripe $9.99 product/trial/webhook, eligibility endpoint. (Blocked here.)
4. **Integrate + money-safety review + staged rollout** — wire frontend to real endpoints, adversarial review of every money path, feature-flag rollout. (Blocked on step 3.)

---

## 6. What I can safely start now (with your §4 answers)

- The **API contract spec** (step 1).
- **Frontend scaffold** against the mock (step 2): Catalog + circle-detail + subscribe + admin screens, behind a feature flag, money-safe (no optimistic gating, backend-authoritative, all fees disclosed, no guaranteed-return language) — mirroring the discipline used through Phases 1–2.

What I **cannot** do here: build or verify the real backend (separate repo), run a real $9.99 Stripe flow, or ship a working paid feature. Those need the Sol backend repo and your money-movement rules.

> Recommendation: answer §4-A first (the subscription-model fork drives everything else), then I'll draft the contract spec and scaffold the Catalog frontend against the mock so you can see and click the flow before any backend or money is involved.
