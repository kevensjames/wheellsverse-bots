# Sol — Non-Custodial Architecture & Payment-Flow Description

**Prepared for:** Stripe (Connect use-case review) and legal counsel (money-transmitter / MSB assessment)
**Status:** Pre-revenue · test/sandbox only · not yet live · seeking approval before any live money
**Version:** 2026-07-03

> **What this document is — and isn't.** This is a *technical* description of how Sol is built so that
> members coordinate rotating savings circles **without Sol ever taking possession or control of member
> money**. It is written to (a) let Stripe assess whether the use case is permitted on Connect and (b)
> give counsel the precise facts needed to assess money-transmitter / money-services-business status.
> **It is not legal advice and states no legal conclusion.** Sol's operator will not enable live money
> movement until Stripe approves the use case in writing *and* counsel signs off.

---

## 1. What Sol is

Sol is **software** that helps a small, trusted group run a **rotating savings circle** (a ROSCA — also
called a *tanda*, *sou-sou*, *susu*, *hui*, or *committee*). In a ROSCA, N members each contribute a
fixed amount every cycle, and each cycle one member receives the pool; the recipient rotates until
everyone has received once.

**Sol does:** create circles, invite members, compute contribution schedules and the payout rotation,
send reminders, record who paid whom, show a reliability signal derived from payment history, and
surface disputes.

**Sol does not:** accept, hold, pool, custody, route, or transfer member money. Sol is **not** a bank,
money transmitter, payment processor, escrow agent, lender, or investment product. Member funds never
pass through Sol or any account Sol controls.

---

## 2. Two payment models (members choose; Sol is out of the money on both)

### 2a. Manual / external rail (default; the shippable-today model)

Members pay **each other directly, outside of Sol**, using their own payment methods (Zelle, CashApp,
Venmo, or cash). Sol **only records** it, using a two-sided confirmation:

```
Payer sends money directly to Recipient (Zelle/CashApp/Venmo/cash — entirely outside Sol)
        │
        ▼
Payer taps "I paid this" in Sol  ──►  Recipient taps "Confirm received"  ──►  Sol records: confirmed
```

On this rail Sol touches **no money whatsoever** — not even a card charge. It is a shared ledger + a
scheduler. There is no payment provider involved at all, so this rail carries no payment-provider
approval dependency.

### 2b. Stripe Connect rail (the model this review concerns)

Each member connects **their own** Stripe (Express) connected account. A contribution is settled as a
**direct charge created *on the recipient's* connected account** — i.e. the Checkout Session is created
with `stripe_account = <recipient's connected account>` and **no** `transfer_data`/destination and **no**
`application_fee_amount`:

```
Payer's card ──► Stripe Checkout (charge created ON the RECIPIENT's connected account) ──► funds settle
                 directly in the Recipient's Stripe account
        │
        ▼
Stripe webhook → Sol records the contribution as confirmed (Sol was never in the money path)
```

The consequences that matter for custody:

- **The recipient is the merchant of record.** Funds settle **directly** into the recipient's connected
  account. They never touch Sol's Stripe platform balance.
- **Sol bears no chargeback / refund liability.** Because the charge is on the recipient's account, a
  refund or dispute is drawn from the *recipient's* account, not Sol's. (This is specifically why Sol
  uses **direct** charges rather than **destination** charges — a destination charge would make Sol the
  merchant of record and leave Sol carrying chargeback liability, which we deliberately avoid.)
- **Sol takes no cut of contributions.** There is no application fee. 100% of the member's contribution
  is the recipient's; Sol earns nothing from the money that moves between members.

---

## 3. Sol's revenue — a software subscription, separate from member money

Sol's **only** revenue is a **$9.99/month software subscription** per active member — a standard Stripe
Billing subscription on **Sol's own** Stripe account, exactly like any SaaS product. It is:

- Entirely **separate** from member ROSCA money (it is Sol charging the member for the app, not Sol
  handling money between members).
- Optional to enforce, and off by default in the current build.

Sol does not profit from, mark up, or take a spread on any money that moves between members.

---

## 4. How non-custody is enforced in the code (not just policy)

These are structural guarantees in the codebase, each covered by an automated check
(`deploy/verify_sol_stage.sh`) and tests:

| Guarantee | How it's enforced | Where |
|---|---|---|
| **No bank data is ever stored** | The data model has no routing/account/card/CVV/IBAN/balance fields anywhere; a test asserts their absence. Payment-profile "handles" are external-rail identifiers only (phone/email/app-tag). | `app/models/sol.py`; `tests/test_sol_models.py::test_no_bank_or_balance_fields` |
| **Charges are always direct (recipient = merchant)** | The charge builder **refuses** to create a charge without the recipient's connected account, and never emits `transfer_data` or `application_fee_amount`. | `app/services/sol_v1/stripe_charges.py::build_direct_charge_call`, `_assert_connected_account` |
| **Money never routes to Sol's balance** | No `stripe.Transfer.create`, `stripe.Payout.create`, `stripe.Charge.create`, or `application_fee_amount` exists in the contribution code path (verifier grep). | Stage-10 verifier checks |
| **Off by default; live money is gated** | The Stripe rail is disabled unless `STRIPE_CONNECT_ENABLED=1`, and it **refuses any live key** (`sk_live_`/`rk_live_`/unknown formats, fail-closed) unless the operator sets `STRIPE_CONNECT_LIVE_APPROVED=1` — which is set only after Stripe + counsel approval. | `app/services/sol_v1/stripe_connect.py::sandbox_state`, `_guard` |
| **Settlement is verified, reversals honored** | The webhook verifies the live PaymentIntent before confirming, and refund/chargeback events un-count a contribution. | `app/services/sol_v1/stripe_webhooks.py` |

---

## 5. Member disclosure & consent

Before a member can create or join a circle, they must accept a **non-custodial terms + risk disclosure**
(server-enforced; acceptance is recorded per version). The disclosure states plainly that Sol is not a
bank, that members pay each other directly, and the risks: **a member may not pay** (Sol does not
guarantee any payment and will not reimburse), funds are **not insured**, **disputes are resolved between
members**, and Sol provides **no financial, legal, or tax advice**. (See `app/static/sol_v1_app/terms.html` —
itself marked a template pending final attorney review.)

---

## 6. Questions for Stripe

1. Is a **rotating savings circle (ROSCA)** an acceptable use case on Connect when contributions are
   settled as **direct charges on each recipient's own connected account** (recipient = merchant of
   record, no platform pooling, no application fee)?
2. Is there a preferred **account type / capability configuration** (Express + `card_payments` +
   `transfers`) for this pattern, or a recommended alternative?
3. Are there restrictions, additional disclosures, or onboarding requirements we should build in before
   requesting live access?

## 7. Questions for counsel

1. Given the architecture above — Sol **never takes possession or control** of member funds (direct
   charges settle to the recipient; the manual rail involves no Sol money at all), Sol earns **only** a
   flat SaaS subscription, and Sol moves no money between members — does this avoid classification as a
   **money transmitter** / **money services business** under applicable federal (FinCEN) and state law?
2. If any registration/licensing is nonetheless implicated, what is required, and in which jurisdictions?
3. What terms of service, disclosures, and consent records should be in place before launch? (A
   non-custodial terms + risk disclosure and a recorded consent gate already exist and can be adapted.)

## 8. Honest caveats

- Sol is **pre-revenue** and **not deployed to production**; the Stripe rail is **sandbox/test-mode only**
  and inert until explicitly approved.
- This document describes the **technical architecture**; it is **not** a legal determination that Sol is
  outside money-transmitter scope — that assessment is precisely what we are asking counsel to make.
- The operator will **not** flip the rail to live (`STRIPE_CONNECT_LIVE_APPROVED=1`) until **both** Stripe
  approves the use case in writing **and** counsel signs off.

---

*Contact / next step: operator to share this with Stripe's Connect review and with counsel, and to
provide either party any additional technical detail on request (the codebase can demonstrate every
claim above).*
