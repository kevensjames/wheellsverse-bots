# NarAI Daily Briefing

Proactive morning + evening status pings to your Telegram chat. Aggregates revenue, trading P&L, calendar, inbox, crypto, and KPI deltas into a single concise message.

## Architecture

```
APScheduler cron (FastAPI startup)
   │
   ├── 7am ET weekdays (NARAI_BRIEFING_CRON)
   └── 6pm ET weekdays (NARAI_RECAP_CRON)
        │
        └── _fire_briefing()
              │
              ├── assemble_briefing()      # narai/integrations/briefing.py
              │     └── 6 section assemblers, each defensive (returns "—" on failure)
              │
              └── deliver_via_telegram()   # bot.send_message(chat_id, html)
```

Same `_fire_briefing()` is exposed as `POST /api/v2/narai/briefing/test` so
you can verify Telegram setup without waiting for cron.

## Environment variables

| Var | Purpose | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather token | — (scheduler self-disables if unset) |
| `TELEGRAM_CHAT_ID` | Owner chat ID (numeric, can be negative for groups) | — |
| `NARAI_BRIEFING_CRON` | Morning briefing cron | `0 7 * * 1-5` (7am ET weekdays) |
| `NARAI_RECAP_CRON` | Evening recap cron, set to `off` to disable | `0 18 * * 1-5` (6pm ET weekdays) |
| `NARAI_BRIEFING_TZ` | Timezone for cron expressions | `America/New_York` |

Cron is standard 5-field: `minute hour dom month dow`.

## Sections

Each section is wrapped in try/except — a missing data source produces `—`,
never a crash. Order is fixed (most-actionable first):

| Section | Source | Lights up when |
|---|---|---|
| 💰 Revenue | `core.board.day.summary_line(day_view(yesterday))`: yesterday's net, attributed revenue by channel and fees, New York day (the board's 07:00 line) | The board's database and Stripe sync are connected (otherwise "not connected", never $0) |
| 📈 Trading | `narai.core.trading.paper.PaperBroker.status()` | Always (defaults to $10k starting equity) |
| 📅 Calendar | `narai.godmode.adapters.google.get_service('calendar')` | Google OAuth connected |
| 📨 Inbox | Same, `gmail` service, `q='is:important is:unread'` | Google OAuth connected |
| 🪙 Crypto | `yfinance` BTC-USD + ETH-USD, 2-day history | Always (yfinance is unauthenticated) |
| ✅ KPIs | `core.click_tracker.clicks_on(day)` + the board's day view (net revenue) | Always (yesterday vs the day before, New York days; "—" for a number that cannot be read; a partial day's revenue reads "so far" and gets no arrow) |

## HTTP endpoints

All require a Bearer JWT from `/api/v2/narai/auth/login`. The 💰 Revenue and
✅ KPIs lines are the daily numbers board's, the owner's numbers: a route puts
them in only when the request also passes the app's owner check, the
`X-API-Key` header or an owner `wv_session` cookie (core/api.py
`owner_request_ok`), and leaves them out otherwise (`assemble_briefing(board=False)`;
the rest of the briefing is unchanged, and nothing is refused for it). The
07:00 cron keeps them. The briefing is built in a worker thread, never on the
event loop.

| Endpoint | Method | Returns | Side effect |
|---|---|---|---|
| `/api/v2/narai/briefing/preview` | POST | `{text, delivered:false}` (HTML) | None |
| `/api/v2/narai/briefing/markdown` | POST | `{text, format:'plain'}` | None |
| `/api/v2/narai/briefing/now` | POST | `{text, delivered:bool}` | Telegram if env set |
| `/api/v2/narai/briefing/test` | POST | `{status:'fired'}` | Calls `_fire_briefing(board=…)` (cron path; the board's lines only for the owner) |

## Dashboard integration

When v2 is active, the **📋** button next to 🧠 / 🎙 calls `naraiShowBriefing()`
which fetches `/briefing/markdown` and drops the briefing into your chat
history as a NarAI message.

## Files

| File | Role |
|---|---|
| `narai/integrations/briefing.py` | Section assemblers + `assemble_briefing()` + `deliver_via_telegram()` |
| `narai/integrations/scheduler.py` | APScheduler `start_briefing_scheduler()` (registered on FastAPI startup in `core/api.py`) |
| `narai/api/routes/briefing.py` | The 4 HTTP routes |
| `dashboard/index.html` | The 📋 button + `naraiShowBriefing()` JS |

## Adding a new section

1. Write `_section_name(now: datetime) -> str` in `briefing.py`. Wrap the body
   in try/except and return a `—` placeholder string on any failure. Never
   raise — the cron should not break because a single section's API is down.
2. Add `_section_name(now)` to the `lines = [...]` list inside
   `assemble_briefing()` at the position where you want it rendered.
3. The plain-text endpoint and Telegram delivery automatically inherit it.

## Adding a new delivery channel (Slack / email / SMS)

`/briefing/markdown` returns the briefing stripped of HTML tags. Wire it into
your destination's send API and call it on whatever schedule you want.
Example: SendGrid email at 7am — POST to `/briefing/markdown` from a cron in
your email provider.

## Common ops

| Goal | Action |
|---|---|
| Verify Telegram delivery without waiting for 7am | `POST /briefing/test` with auth |
| Disable evening recap, keep morning | `NARAI_RECAP_CRON=off` |
| Move briefing to 8am ET | `NARAI_BRIEFING_CRON=0 8 * * 1-5` |
| Add Saturday/Sunday | `NARAI_BRIEFING_CRON=0 7 * * *` |
| Different timezone | `NARAI_BRIEFING_TZ=Europe/London` |
| See current scheduler state | `railway logs … \| grep "briefing scheduler"` |
