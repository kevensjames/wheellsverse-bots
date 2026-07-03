# Sol — Outreach drafts (Stripe review + counsel)

Send-ready messages to start the two conversations that gate live money. Attach or link
`NON_CUSTODIAL_ARCHITECTURE.md`. Fill in the `[bracketed]` bits. **The assistant did not send these** —
sending is yours (your accounts, your contacts).

---

## A. To Stripe — Connect use-case review

**How to send:** Stripe Dashboard → Support (or your Connect account manager if you have one). Ask for
the request to reach the **Connect risk / use-case review** team.

**Subject:** Connect use-case review — rotating savings circle (direct charges, non-custodial)

> Hi Stripe team,
>
> We operate **Sol**, a software tool that helps small trusted groups run **rotating savings circles**
> (ROSCAs / *tandas* / *sou-sous*). We want to confirm the use case is permitted on Connect before we
> request live access.
>
> **How money moves (our design):** each member connects **their own** Stripe Express account.
> A contribution is a **direct charge created on the recipient's connected account**
> (`stripe_account = <recipient>`, no `transfer_data`/destination, no `application_fee`). So the
> **recipient is the merchant of record**, funds settle directly in their account, our platform balance
> is never touched, and we bear no chargeback liability. We take **no cut** of contributions — our only
> revenue is a flat **$9.99/month software subscription** (standard Stripe Billing on our own account).
>
> **Our questions:**
> 1. Is a rotating savings circle an acceptable Connect use case with this **direct-charge** model?
> 2. Is there a preferred account type / capability setup (Express + `card_payments` + `transfers`), or
>    a better pattern you'd recommend?
> 3. Any restrictions, disclosures, or onboarding requirements we should build in before live access?
>
> We've attached a short technical description of the flow and the non-custody guarantees. Happy to walk
> through the integration or share test-mode details. Currently everything is **test-mode only** and
> gated off until we have your confirmation.
>
> Thank you,
> [Name] — [Sol / company], [email]

---

## B. To legal counsel — money-transmitter / MSB assessment

**Who:** a fintech / payments-regulatory attorney (money-transmission licensing experience). If you
don't have one, ask for a referral or use a fintech-focused firm.

**Subject:** Assessment request — non-custodial ROSCA coordinator (money-transmitter / MSB status)

> Hi [Attorney / firm],
>
> I'm building **Sol**, software that helps small trusted groups run rotating savings circles (ROSCAs).
> I'd like an assessment of whether it is (or can be structured to stay) **outside money-transmitter /
> MSB scope**, and what, if any, licensing or registration applies.
>
> **Key facts (details in the attached architecture description):**
> - Sol is a **coordination tool**. It **never takes possession or control** of member funds.
> - Default model: members pay **each other directly, outside the app** (Zelle/CashApp/cash); Sol only
>   **records** it.
> - Optional card model: contributions are **Stripe direct charges on each recipient's own connected
>   account** — the recipient is merchant of record; money never touches an account we control.
> - Sol earns **only** a flat **$9.99/month software subscription**; it takes no cut of and moves no
>   money between members.
> - We already have a **non-custodial terms + risk disclosure** with a recorded consent gate (draft;
>   would want your review).
>
> **What I'm asking:**
> 1. Does this architecture avoid money-transmitter / MSB classification under federal (FinCEN) and
>    state law? If not, what changes would help, and what licensing is required (and where)?
> 2. What terms, disclosures, and records should be in place before launch?
> 3. Rough scope and estimate for the above.
>
> I can provide the codebase or a technical walkthrough — the design is built specifically to avoid
> custody, and I can demonstrate each guarantee. Nothing is live yet; live money is gated on your
> sign-off and Stripe's approval.
>
> Thanks,
> [Name], [email], [jurisdiction / state of operation]

---

*Both messages reference `NON_CUSTODIAL_ARCHITECTURE.md`, which is accurate to the codebase (every code
citation in it was verified). Keep the honest framing: we're **asking** for review, not asserting a
conclusion.*
