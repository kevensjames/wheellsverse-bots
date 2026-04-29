# Telegram Private-Group Subscription — Setup

End-to-end flow:

```
User clicks "Subscribe" on website
       │
       ▼  POST /api/v2/narai/telegram/subscription/checkout
Stripe Checkout (subscription mode, metadata.tg_pairing_token=…)
       │
       ▼  on payment success
Stripe webhook → checkout.session.completed
       │       (row promoted to status=pending_pair)
       ▼
success_url redirects browser to t.me/<bot>?start=<token>
       │
       ▼  user opens Telegram, taps "Start"
Bot receives /start <token>
       │       (validates, mints single-use invite, marks status=active)
       ▼
Bot DMs single-use invite link → user joins private channel ✅
       …
       (months later, user cancels or payment fails repeatedly)
       │
       ▼  Stripe webhook → customer.subscription.deleted
Bot kicks the user from the channel; row → status=revoked
```

## 1. Create the private channel

In Telegram:

1. **New Channel** → name it (e.g. "WheellsVerse Insider")
2. **Channel type: Private**
3. **Add member** → search your bot's username → add it
4. **Promote** the bot to admin with **only** these rights:
   - ✅ Invite users via link
   - ✅ Restrict members
   - (everything else off; minimum-privilege)

## 2. Get the channel ID

The channel ID looks like `-1001234567890` (note the leading `-100`).

Either:
- Forward any message from the channel to [@username_to_id_bot](https://t.me/username_to_id_bot), or
- Run from a Python shell with the bot token loaded:
  ```py
  from telegram import Bot; import asyncio, os
  bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"])
  print(asyncio.run(bot.get_chat("@your_channel_username_or_invite")).id)
  ```

## 3. Create the Stripe product + price

```sh
stripe products create --name "WheellsVerse Insider — Private Group"
# copy the prod_… id, then:
stripe prices create --product prod_XXXXXXX --unit-amount 1900 --currency usd \
  --recurring "interval=month"
# copy the price_… id
```

Or use the Stripe Dashboard → Products → Add Product → Recurring.

## 4. Set environment variables

Add to `.env` (and Railway / your deploy env):

```ini
# Telegram bot
TELEGRAM_BOT_TOKEN=123456:ABC…                  # already set
TELEGRAM_BOT_USERNAME=wheellsverse_insider_bot  # NO @ prefix
TELEGRAM_PRIVATE_CHANNEL_ID=-1001234567890

# Stripe
STRIPE_SECRET_KEY=sk_live_…                     # already set
STRIPE_WEBHOOK_SECRET=whsec_…                   # already set
STRIPE_PRICE_TG_GROUP=price_XXXXXXX             # NEW

# Public base URL (used to build success/cancel pages)
APP_BASE_URL=https://app.wheellsverse.com
```

## 5. Verify the Stripe webhook hits production

Stripe → Developers → Webhooks → Add endpoint:

- URL: `https://app.wheellsverse.com/api/stripe/webhook`
- Events:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - (the existing `invoice.paid` handler still works for affiliate attribution)

Run a Stripe **test event** and tail the prod logs — you should see
`Stripe checkout.session.completed: $X.XX from …`. Copy the signing secret
(`whsec_…`) into `STRIPE_WEBHOOK_SECRET` if it isn't there yet.

## 6. Add a "Subscribe" button to your site

Frontend snippet:

```html
<button id="sub-btn">Join private group — $19/mo</button>
<script>
  document.getElementById("sub-btn").onclick = async () => {
    const email = prompt("Email for receipt?");
    if (!email) return;
    const r = await fetch("/api/v2/narai/telegram/subscription/checkout", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({email}),
    });
    const {checkout_url} = await r.json();
    window.location = checkout_url;
  };
</script>
```

Stripe success page redirects to your `success_url`, which carries
`?goto=t.me/<bot>?start=<token>`. Either auto-redirect on the success page
(`window.location = new URLSearchParams(location.search).get("goto")`) or
render a "Open Telegram" button that points there.

## 7. Test the round trip

Use a Stripe test card (`4242 4242 4242 4242`) and your real Telegram
account:

1. Click Subscribe → enter email → land on Stripe checkout
2. Pay with test card
3. On success, browser opens `t.me/<bot>?start=<token>`
4. Tap **Start** → bot DMs single-use invite link
5. Tap link → you're in the private channel ✅
6. Cancel the test subscription in Stripe Dashboard, advance the clock
   past `current_period_end` → bot kicks you ✅

## Operational notes

- **Single-use invite links** expire in 1 hour. If a user loses theirs they
  must reach out (no automatic re-issue yet — TODO).
- **Pairing tokens** expire in 24 hours. After that the row is dead and the
  customer needs to contact support (Stripe still bills them — refund manually).
- **Database** is `data/telegram_subscriptions.db` (SQLite). Override with
  `TG_SUB_DB_PATH=…`. Back it up if you rely on subscriber state.
- **Kicking** uses `banChatMember` + `unbanChatMember` (the canonical pattern):
  ban removes them from the channel, unban allows future re-subscription.
- **Grace period** is implicit: Stripe only sends `customer.subscription.deleted`
  after `current_period_end`, so cancellations naturally expire at the
  end of the paid period.

## Known limitations

- One channel only (`TELEGRAM_PRIVATE_CHANNEL_ID`). Multiple tiers would need a
  per-tier mapping plus tier discrimination on the Stripe price id.
- No Telegram-native checkout (`/subscribe` command). Web-first flow only.
- No re-issue command for lost invite links. Users must contact support
  (or you query `data/telegram_subscriptions.db` directly).
