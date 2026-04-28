# Abandoned Cart Email Sequence — 3 emails

Triggered by your `checkouts/create` webhook (already wired to `app.wheellsverse.com/api/shopify/webhook`). Send via your existing email service (Resend / SendGrid / native Shopify Email).

**Detection:** customer started checkout, didn't complete within 60 minutes.
**Stop:** customer completes purchase OR clicks unsubscribe OR opts out.

---

## Email 1 — 1 hour after abandon

**Subject:** `You left this in your cart`

> Hey {{ first_name | default: "there" }},
>
> You added **{{ product.title }}** to your cart but didn't finish checking out.
>
> If something stopped you — payment, shipping, second thoughts — hit reply. I'll fix it personally.
>
> If life just got in the way, here's a one-click way to come back:
>
> [→ Finish checkout](https://shop.wheellsverse.com/{{ recovery_url }})
>
> — J.K.W.

---

## Email 2 — 24 hours after abandon

**Subject:** `Quick question about {{ product.title }}`

> {{ first_name | default: "Hey" }},
>
> Yesterday you came close to grabbing **{{ product.title }}** but didn't pull the trigger.
>
> Three things I want to mention:
>
> 1. **It's still in your cart.** [Click here to finish.](https://shop.wheellsverse.com/{{ recovery_url }})
> 2. **The 7-day free trial means $0 today.** You don't pay until day 8. If you don't get value in week one, cancel — no save-the-relationship loop.
> 3. **If something else is the blocker — payment, doubt, technical issue — hit reply.** I read every reply.
>
> The fastest way to know if something works is to use it for a week.
>
> — J.K.W.

---

## Email 3 — 72 hours after abandon (last touch)

**Subject:** `Last note — then I stop`

> {{ first_name | default: "Hey" }},
>
> Last email about your cart. After this I leave you alone.
>
> The cart's still there if you want it: [shop.wheellsverse.com/cart](https://shop.wheellsverse.com/{{ recovery_url }})
>
> If it's a no, no hard feelings — I'll keep building. The AI alerts go out daily either way; you can read along on the blog.
>
> If it's a "later," it'll be here when later comes.
>
> — J.K.W.
>
> [Unsubscribe from cart reminders](https://shop.wheellsverse.com/unsubscribe)

---

## Wiring (technical)

The `checkouts/create` webhook already POSTs to `https://app.wheellsverse.com/api/shopify/webhook`. To turn this sequence on:

1. **Add a queue + scheduler in your existing FastAPI** that:
   - On webhook: store `{checkout_id, email, product_title, recovery_url, abandoned_at}` in Supabase
   - Cron every 15 min: find rows where `abandoned_at` is in the right window AND no purchase event has been received → send the next email in sequence
   - On `orders/paid` webhook for matching email: stop the sequence

2. **Email send via Resend** (cheap, dev-friendly):
   ```python
   import resend
   resend.api_key = os.getenv("RESEND_API_KEY")
   resend.Emails.send({
       "from": "J.K.W. <hi@wheellsverse.com>",
       "to": [customer_email],
       "subject": subject,
       "html": rendered_html,
   })
   ```

3. **Suppression list** — if customer hits unsubscribe, store in `email_suppressions` table; check before sending.

If you want me to wire this end-to-end (queue + cron + send), say the word.
