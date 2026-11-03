# Architecture: Daily numbers board, Phase 1 (a rebuild of Baremetrics' core features)

Final plan, 2026-11-02. The owner's app #1, Phase 1 only.

- Inputs: replica/recon.md (Core loop, Inferred data model, Size, Owner's stores, Reuse from this repo), replica/features.csv, marketing/GLOBAL_PLAN.md:125-198.
- Built from two drafts. Base: the reuse-first draft. Grafted from the ledger-first draft: Stripe keys on balance transactions, per-source "measured from" and day states, server-side owner sessions, per-channel report claims with a startup catch-up, raw files kept in Postgres. "How this plan was chosen" at the end has the scores.
- Repo evidence is cited as path:line at HEAD 55ab030.
- Vendor field names (Kit, Instantly, Meta, the KDP export) were not checked against vendor docs. Each is marked **verify**. The list is in "Verify before coding".
- The SQL is in `schema.sql` next to this file. It was applied twice to a throwaway PostgreSQL 16 set up like Supabase, and 98 behaviour checks pass: 65 in `judge-work/test.sql` and 33 in `critic-work/test_critic.sql` (`critic-work/run.sh` runs both).

## Phase 1 in one screen

Every day at 07:00 New York time, one message, plus the board at /admin/scoreboard, answers for yesterday, as one New York calendar day:

1. **Toodle opt-ins.** Kit subscribers who got a Toodle tag that day, split by channel (meta, organic). Target: 3 a day (marketing/GLOBAL_PLAN.md:196).
2. **SiteBoost replies.** Distinct prospects who sent a real reply in the SiteBoost Instantly campaign that day, and over 7 days. Target: 1 a week (marketing/GLOBAL_PLAN.md:197).
3. **Attributed revenue.** Net revenue in USD (sales minus refunds and disputes, before fees), split by store and channel. Revenue with no known channel shows as "unattributed" (marketing/GLOBAL_PLAN.md:198).
4. **Meta spend and cost per lead,** with the plan's stop rule: stop if CPL is above $5 after 5 days of spend (marketing/GLOBAL_PLAN.md:128).

What the board does not do:

- It never adds an estimate to money. "Kit subs x LTV estimate" (marketing/GLOBAL_PLAN.md:198) is not revenue, and the invented KDP figure goes (core/api.py:10315, 10370).
- KDP royalties are real but provisional. They are labelled "estimate" with the upload time.
- Gumroad, Shopify, Digistore24, BigCommerce, Whop, Payhip and Stan come later, one connector each.

The morning message for the test fixture day:

```
Sun 1 Nov (New York; a 25-hour day: clocks went back)
Toodle opt-ins: 2 · target 3 · meta 1, organic 1
SiteBoost replies: 1 · last 7 days: 2 (target 1 a week) · 1 automatic reply or bounce ignored
Revenue: $10.00 net · attributed $29.99 (meta) · fees $3.17
  Stripe $10.00: 1 sale, 1 refund, 1 dispute won
Meta: Toodle spend $5.02 · 9 link clicks → 2 opt-ins
Stop rule: CPL $6.28 over the last 5 spend days (4 Meta opt-ins) → STOP (above $5.00)
Sources: Stripe final · Kit final · Instantly final · Meta final · KDP: no upload covers 1 Nov
```

## Stack

| layer | choice | why |
| --- | --- | --- |
| web | The existing FastAPI app, core/api.py, one uvicorn process on Railway (railway.json:7). New code lives in a `core/board/` package that core/api.py includes as one router. The page stays frontend/admin/scoreboard.html, extended. | The board extends what exists. A package keeps edits to the 15,390-line core/api.py small. |
| database | The existing Supabase Postgres, through supabase-py and the service-role client in core/narai_user.py:19-32. Writes that must be atomic are SQL functions called with `.rpc()`. | One database. supabase-py is deployed (requirements-server.txt:29); the server has no other Postgres driver. Rules that protect the money live where every caller is bound by them. |
| auth | Supabase Auth checks the owner's email and password once, on the server, with one HTTP password grant using the anon key: the pattern of backend/app/services/supabase_auth.py:164-207, copied rather than imported (core/api.py never loads backend/app, and its settings read other variable names). The browser then holds a random session token in an HttpOnly cookie; only its hash is stored (`owner_sessions`). One allow-listed user id. | Revocable at once, no token refresh, no signing-key assumptions, and no supabase-py client ever holds a user session. The anon key name is already read (core/api.py:913). The cookie flags follow backend/app/dependencies/cookie_auth.py:38-59. |
| payments (read only) | Stripe: balance transactions with a restricted read-only key, hourly. The existing webhook stays for its side effects, now deduped. | One balance transaction per money movement gives amount, fee and the settled USD, refunds and disputes included. Backfill uses list endpoints, not /v1/events (recon, Owner's stores). |
| email and messages | Telegram through core/telegram.py:117 `notify()`. Email through core/output_automation.py:85-137 `EmailSender.send`. Slack optional, core/output_automation.py:185-207. | These senders exist and return success, so a send can be marked done. |
| jobs | APScheduler (requirements-server.txt:7). A `start_board_scheduler()` next to the briefing in narai/integrations/scheduler.py, time zone America/New_York, registered at startup (core/api.py:15004-15009). | The cron plumbing exists (narai/integrations/scheduler.py:46-87). Unlike the briefing, it does not skip itself when Telegram is unset (:52-54). |
| hosting | Unchanged: Railway, with Cloudflare in front. | No new service. |
| lead and ad sources | Kit v4 (core/kit.py), Meta Marketing API Insights with ads_read (core/meta_ads.py), Instantly v2 (core/siteboost_instantly.py). | Every client exists. Each gains one read method. |
| files | KDP reports kept as `bytea` in Postgres (5 MB cap), parsed with openpyxl (requirements-server.txt:10), uploaded through python-multipart (:30). | No storage bucket to configure. A fixed parser can re-run on the kept file. |
| FX | ECB euro reference rates (public, no key), only for non-USD rows. | Stripe reports its own USD. KDP marketplaces and a non-USD ad account do not. |

New Python dependencies: none. nixpacks installs requirements-server.txt (nixpacks.toml:8), which already has everything above. One pin: `APScheduler>=3.10.4,<4` (requirements-server.txt:7), because version 4 drops the `AsyncIOScheduler` that narai/integrations/scheduler.py:16 imports, and the morning report runs on it.

New environment variable names (values never go in the repo or the page):

- `BOARD_OWNER_USER_ID`: the Supabase Auth user id allowed in. Unset means the board is closed.
- `STRIPE_READ_KEY`: a restricted read-only key. Without it the sync uses `STRIPE_SECRET_KEY` and the card says so.
- `META_INSIGHTS_TOKEN`: a system-user token with ads_read only. Without it, `META_ACCESS_TOKEN`.
- `META_GRAPH_VERSION`: exists today. The default is now v26.0 (core/meta_ads.py:71).
- `BOARD_TOODLE_META_CAMPAIGN_IDS`: for example 120249191226470279 (marketing/GLOBAL_PLAN.md:125). Unset means the Toodle spend and the stop rule read "not connected".
- `BOARD_TOODLE_KIT_TAGS`: Toodle tags and their channel, for example `toodle:,meta_ad:meta,meta:meta,blog:organic`. An empty channel marks the funnel only.
- `BOARD_SITEBOOST_CAMPAIGN_IDS`: set it. Its fallback, `get_active_campaign_id()` (core/siteboost_instantly.py:38-53), prefers a file written at run time on the container disk (:32), which a deploy wipes. Empty means "not connected", never 0.
- `BOARD_BACKFILL_FROM` (default 2026-01-01), `BOARD_REPORT_CRON` (default `0 7 * * *`), `BOARD_CPL_STOP_CENTS` (500), `BOARD_CPL_DAYS` (5).
- `BOARD_REPORT_EMAIL_TO` (optional): unset means no email report. Passing no recipient would make `EmailSender` fall back to its own default (core/output_automation.py:79).

Add every new name to .env.example with an empty value. .env.example also lacks the existing names the board relies on: `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (core/narai_user.py:24-25), `SUPABASE_ANON_KEY` (core/api.py:913) and `INSTANTLY_API_KEY` (core/siteboost_instantly.py:148). Add those names too. For the email channel, `EmailSender` reads `EMAIL_SMTP_HOST` and `EMAIL_SMTP_PORT` (core/output_automation.py:75-76), but .env.example documents `EMAIL_HOST` and `EMAIL_PORT` (.env.example:64-65): set the names the code reads.

### What changes where

| file | change | evidence |
| --- | --- | --- |
| core/board/auth.py (new) | Sign-in is one HTTP password grant with the anon key, never a sign-in on the shared service-role client. Owner allow-list. Session create, check and revoke. `require_owner` dependency. Origin check on writes. Sign-in rate limit. Closed when the owner id is unset. | backend/app/services/supabase_auth.py:164-207; core/narai_user.py:19-32; backend/app/dependencies/cookie_auth.py:38-65 |
| core/board/routes.py (new) | `APIRouter(prefix="/api/board", dependencies=[Depends(require_owner)])`, plus /board/login and /board/auth/*. Handlers are plain `def`, so FastAPI runs blocking supabase-py calls in its threadpool. | the scoreboard route pulls Stripe live today (core/api.py:1716-1722, core/scoreboard.py:23-27) |
| core/board/ledger.py (new) | `LedgerRow` and `LeadRow` dataclasses and the RPC calls. Amounts parsed with `Decimal` into integer minor units, with the same exponent table as `board_currency_exponent` (JPY 0, KWD 3). | dedupe pattern: supabase_shopify_multitenant.sql:88-99 |
| core/board/connectors/ (new) | One module per source: stripe_sync, kit_sync, instantly_sync, meta_sync, fx_sync, kdp_upload. Each writes a job_runs row and moves its source's watermark. | "one connector per store" (recon, Size) |
| core/board/day.py (new) | Calls `board_day`, then shapes each number as `{value, connected, state, source, note}`. Also `summary_line()` and `render_report()`. | core/scoreboard.py:18-20 |
| core/board/jobs.py (new) | The sync, Meta, FX, report and housekeeping job bodies, with the startup catch-up. Every run starts with `board_claim_run` and skips when it returns null. | backend/app/services/checkin/storage.py:75-77 (insert-once guard) |
| core/kit.py | Add `list_tag_subscribers(tag_id, tagged_after, tagged_before, after)`, a read through `_request`. | core/kit.py:90-121, 133-135 |
| core/meta_ads.py | Add `account_info()` and `daily_insights(since, until)`. Let `_get` take extra query params. Readiness for reads must not need a page id. | core/meta_ads.py:63-74, 86-87, 98-105 |
| core/siteboost_instantly.py | Add `list_replies(campaign_id, since, until)`. | core/siteboost_instantly.py:35-53 |
| core/click_tracker.py | Storage moves to the clicks table; no visitor IP. A key is lower-cased and must then be `[a-z0-9_-]{1,64}`. `new_click` builds the row (the referring host only, the visitor's own `utm_*` tags from the /go link) and the redirect: the destination, plus `client_reference_id=<click id>` when it is `https://buy.stripe.com`. `save_click` is best effort and never raises. `allow_click` counts stored clicks in memory: 30 a minute per client address, 300 in all, keyed by a salted hash, never logged. `record_click`, `get_stats`, `_load_clicks` and `tracking_url` keep their signatures, so other callers keep working; `get_stats` reads null, with `connected: false`, when the database cannot be read. `clicks_on` and `clicks_between` count by New York day in SQL. The conversion log goes: attribution lives in the ledger. Its two users change in the same step: the webhook's `record_conversion` call and the briefing's `_load_conversions` import. The other readers of the old click file (core/affiliate_optimizer.py, bots/agent_workforce/101_analytics_bot/bot.py) read `_load_clicks()`. | core/click_tracker.py:35-36, 102-136, 181-244. Callers kept: core/api.py:4317, 7247, 7282, 7587, 8024; core/publish_pipeline.py:407; narai/integrations/briefing.py:39; narai/integrations/scheduler_promo.py:261. Callers changed: core/api.py:10232-10246; narai/integrations/briefing.py:269 |
| core/revenue.py | Stop writing data/revenue.json. `record()` writes a manual ledger row. Totals read the ledger by New York day. `pull_stripe` stops recording charges and keeps only the MRR card. | core/revenue.py:30, 94-104, 143-149, 198-242 |
| core/scoreboard.py | Revenue cards read the ledger. "leads" becomes "places scanned (outreach)". The conversion card goes. Surface flags come from `sources`. | core/scoreboard.py:44-59, 79-81, 90-97 |
| core/api.py | (1) /admin/scoreboard is served behind the owner session as a plain static file (:1739-1749). (2) Include the board router and add `/api/board/` to the middleware's own-auth prefixes, as `/api/v2/narai/` is (:859-868). (3) Rework the Stripe webhook (:10141-10293); its `record_conversion` call (:10232-10246) goes with the conversion log. (4) `/go/{partner}` writes clicks (:7230-7241): the insert is a background task after the 302, and the redirect is `Cache-Control: no-store`. `/api/clicks`, `/api/blog/articles` and `/api/revenue/v2` become plain `def` (database reads in the threadpool); their click counts come from SQL, null when unreadable. (5) Money and revenue routes read the ledger (:10296-10399, 11181-11206). (6) Remove the 08:00 report that only `launch()` starts (:13817-13823). (7) Register `start_board_scheduler` (:15004-15009). | as cited |
| frontend/admin/scoreboard.html | The top becomes the morning board (S22). Data calls go to `/api/board/*` and carry only the session cookie. Add the KDP upload panel (S24) and source pills. Keep the cards (:83-91), `esc()` (:68), the surface pills (:92-94) and the opportunity list (:97-106). | as cited |
| frontend/admin/board_login.html (new) | The sign-in form (S23). A static file with nothing secret in it. | |
| narai/integrations/scheduler.py | Add `start_board_scheduler()` beside `start_briefing_scheduler()`. Lift its cron helper `_safe_trigger` to module level so both can use it: today it is nested inside `start_briefing_scheduler`. The board's zone is fixed to America/New_York, the zone the SQL uses, not `NARAI_BRIEFING_TZ`. | narai/integrations/scheduler.py:46-87, 61, 63-68 |
| narai/integrations/briefing.py | The revenue line is `core.board.day.summary_line` for yesterday's New York day, escaped. The KPI line compares yesterday with the day before, both New York days: `click_tracker.clicks_on` and the day view's net. A number it cannot read prints "—", never 0. Both take `now`, never `now - 24h`, which lands on the wrong day around a clock change. The scheduler builds the briefing in a worker thread (`asyncio.to_thread`). Today they read lifetime click stats and bucket JSON by UTC date. | narai/integrations/briefing.py:37-53, 263-302 |
| narai/migrations/0002_daily_numbers_board.sql (new) | `schema.sql`, run with scripts/run_supabase_migration.py, which sends the whole file in one call (:91-95). Follows 0001's conventions: idempotent, RLS on, no policies, service role only, a probe. | narai/migrations/0001_siteboost_suppressions.sql:1-28 |
| scripts/board_import_json.py (new, one-off) | Import whatever survives in data/stripe_payments.json (manual rows only), data/revenue.json and data/clicks.json, with deterministic keys so it can re-run. Copy the files out of the running container before the deploy that switches stores (every deploy wipes data/), then run it from the owner's machine, before or after that deploy. Local files only: no API-key route serves the raw records. A click keeps its referring host and no UTM tags; its IP is never read, stored or hashed. | .gitignore:42-45 |
| tests/ | New: test_board_auth.py, test_board_day.py, test_stripe_sync.py, test_kdp_parse.py, test_board_report.py. Update test_scoreboard.py and test_scoreboard_mount.py. Move the in-memory Supabase fake to tests/conftest.py. | tests/test_scoreboard_mount.py:8-12; tests/test_siteboost_suppressions.py:37-131 |

## Schema

Tables: 10. Access rules: RLS on every table with no policies, and no grants to anon or authenticated. Only the backend's service role reads and writes. The owner check is in the data layer: one FastAPI dependency on every board route.

There is no owner column. One owner, one tenant, no client-side database access. This is a decision, not a default.

| table | holds | key | step |
| --- | --- | --- | --- |
| sources | One row per connector: state, watermark, `measured_from`, the source's day time zone. The seed rows are also a probe: a wrong key gets a permission error, and an empty table means the migration never ran. | `id` text: a readable key ('stripe') that every connector and foreign key names | 1 |
| job_runs | Every sync, upload, import and report send, each claimed through `board_claim_run`. | uuid; unique (job, run_key) | 1 |
| webhook_events | One row per Stripe event id, claimed through `board_claim_webhook`. | unique (source_id, event_id) | 1 |
| ledger_entries | One row per money movement per source. | unique (source_id, external_id) | 1 |
| lead_events | Toodle opt-ins (Kit) and SiteBoost replies (Instantly). | unique (source_id, external_id) | 2b, 2d |
| ad_spend_daily | Meta spend per campaign per ad-account day. | unique (source_id, campaign_id, day) | 2c |
| clicks | /go redirects, no IP. | uuid (the click id) | 2e |
| source_uploads | KDP files: bytes, hash, period, status. | unique (source_id, file_sha256) | 2f |
| fx_rates | ECB rate as USD per unit, per day. | uuid; unique (currency, day) | 2f |
| owner_sessions | Board sessions: token hash, expiry, revoked. | unique token_sha256 | 0 |

Plus 2 views (`board_ledger`, `board_revenue_daily`) and 11 functions (`board_day`, `board_cpl`, `board_source_state`, `board_ingest_ledger`, `board_ingest_leads`, `board_apply_upload`, `board_fill_fx`, `board_claim_run`, `board_claim_webhook`, and two helpers).

Decisions the SQL encodes:

- **Dedupe keys.**
  - Stripe ledger rows key on the balance transaction id (`txn_...`), not on the event. One payment fires checkout.session.completed, charge.succeeded and invoice.paid, and a won dispute adds a second balance transaction to the same dispute. Today each delivery is appended again (core/api.py:10133-10138, 10176).
  - `order_ref` (the charge id) ties a refund or dispute to its sale.
  - Webhook event ids are deduped separately, in webhook_events, and claimed with `board_claim_webhook` (run, busy or done), so side effects run once, a duplicate that arrives mid-run is told to retry later, and a failed event runs again.
  - Kit: `<funnel>:sub:<subscriber id>` (`toodle:sub:123`), one opt-in per person per funnel; the earliest time seen wins. Instantly: the email id. Meta: campaign and day. KDP: a natural key per report row. Report: `('morning_report', 'YYYY-MM-DD:channel')`, claimed with `board_claim_run`: a failed channel is claimed again by the retry, a sent one never.
- **Money is written once.** `board_ingest_ledger` inserts new movements. For a movement already there it may only improve labels (product, buyer, channel, an unknown fee). If a re-sync disagrees on money, the row is kept and the run records a mismatch.
- **Labels never block money.** A bad money field (kind, sign, amount, currency) fails the batch, and the source shows the error. A bad label is dropped instead, so one odd sale cannot stall the hourly sync: a click id the app did not issue (Stripe's `client_reference_id` is free text anyone can set), a malformed UTM or lead channel (stored as `other`), a malformed email.
- **Owner day.** A generated `local_day` (America/New_York) on every timestamped table. Date-only KDP rows use `occurred_on` instead of a made-up time.
- **Not measured is null, never 0.** A day before a source's `measured_from`, or not yet synced past its end, reads "not connected" or "partial". A real 0 stays 0.
- **USD.** `amount_usd_cents` stays NULL until a real rate exists: Stripe's own balance transaction, or ECB. It is never guessed. NULL rows are left out of totals and counted.
- **Fees.** `fee_usd_cents` NULL means unknown, never 0. It is signed as Stripe signs a balance transaction's fee: a refunded fee, or the fee Stripe returns on a won dispute, is negative. Net revenue is before fees; fees are their own number, as in Baremetrics (recon M19, M20).
- **Attribution.** A click id or checkout UTM is stored when the row is written. Otherwise `board_ledger` uses the buyer's first opt-in or reply with a known channel before the sale, matched on email when read, so a lead that syncs an hour later still counts. A refund takes the channel, product and buyer of its sale. The "last click by anyone within 72 hours" guess (core/click_tracker.py:181-244) is not used.
- **KDP uploads.** The same bytes are one upload. The newest upload replaces its whole period in one transaction. Deleting an upload removes its rows. A failed upload keeps its bytes, and `board_apply_upload` accepts it again once the parser is fixed.
- **Adding a store later** is one row in `sources` (its kind is already allowed) plus one connector module. No migration unless the store needs a new column.

```sql
-- The heart of it; the full migration is schema.sql.
create table if not exists public.ledger_entries (
  id               uuid primary key default gen_random_uuid(),
  source_id        text not null references public.sources(id) on delete restrict,
  external_id      text not null,            -- Stripe txn_..., a KDP row key, a manual uuid
  kind             text not null check (kind in ('sale','refund','dispute','dispute_reversal','fee','adjustment')),
  occurred_at      timestamptz,              -- when the money moved, never receipt time
  occurred_on      date,                     -- date-only rows (KDP)
  local_day        date generated always as
                     (coalesce((occurred_at at time zone 'America/New_York')::date, occurred_on)) stored,
  amount_minor     bigint not null,          -- integer minor units (cents for USD)
  currency         char(3) not null,
  amount_usd_cents bigint,                   -- NULL until a real rate exists
  fee_usd_cents    bigint,                   -- NULL = unknown
  ...
  constraint ledger_entries_one_row_per_movement unique (source_id, external_id)
);
```

What the tests assert (judge-work/test.sql, then critic-work/test_critic.sql, against schema.sql applied twice):

- **Owner day.** 04:30Z on 2 Nov is 1 Nov; 05:00Z is 2 Nov. 1 Nov 2026 has 25 hours; 14 Mar 2027 has 23.
- **Dedupe.** A re-sent movement inserts nothing. A disagreeing re-sync is reported, and the money stays as written. A won dispute keeps both of its balance transactions.
- **Net.** For 1 Nov: a $29.99 sale, a refund of a 31 Oct sale, and a dispute that was won give $10.00 net. Fees ($3.17) stay apart.
- **Attribution.** The sale is credited to meta through the buyer's earlier opt-in. A refund carries its sale's product. A tracked click attributes exactly. Buyers leave the database masked.
- **Leads.** Opt-ins split by channel. Two replies from one prospect count once; auto-replies are left out; 7-day replies work.
- **CPL rule.** $25.10 over 5 spend days for 4 Meta opt-ins gives $6.28 and stop. 3 spend days give collecting. Untagged opt-ins give check_tags. No opt-ins at all after $25.10 give stop.
- **KDP and FX.** A GBP row stays unconverted until a rate exists, then Sunday uses Friday's ECB rate. Duplicate keys in one file are summed. A newer file replaces its period and supersedes the older upload. Rows outside the period and the same file twice are refused. Deleting an upload removes its rows.
- **States.** Final, partial, not measured before `measured_from`, estimate for a covered KDP day.
- **Refusals and access.** A positive refund, USD without a rate source, an API write to an upload source and a source with no row are refused. A second report claim for the same day and channel is refused. anon and authenticated can read no table or view and run no function.
- **Claims** (critic). A report channel is claimed once; a failed one is claimed again with attempts 2; a sent one never; a run abandoned for 30 minutes is marked failed and the job runs again. A webhook event runs once; a duplicate mid-run gets "busy"; a failed or abandoned one runs again; a test-mode one is stored as ignored.
- **Robustness** (critic). A won dispute's returned fee (negative) is accepted and nets out of fees. An unknown click id, a client_reference_id that is not a uuid, a malformed channel or email never fail a batch; a bad money field still does. A USD row sent without USD gets its own amount. The earliest lead time wins. A failed upload re-applies; one key with two currencies is refused. An unknown time zone is refused when written.

Not tested: real Supabase and PostgREST, `.rpc()` from supabase-py, and concurrency under load. Phase 1 volume is tens of rows a day.

## API

New screen and flow ids (the recon used S00 to S21 and F01 to F10):

- S22: the morning board, the extended /admin/scoreboard. S23: board sign-in. S24: the KDP upload panel on S22.
- F11: sign in to the board. F12: upload a KDP report. F13: a tracked link leads to an attributed sale. F14: the morning report, sent by the system.
- The board also serves the recon's F02 (read the morning numbers), F01 (connect a source: here, set its key and run the first sync) and F05 (daily email).

Sign in (F11, the security prerequisite):

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| GET /board/login | The sign-in form (S23), a static file. | anyone | | HTML | F11 |
| POST /board/auth/login | Checks the password with one HTTP password grant to Supabase Auth (no supabase-py client signs in). Requires the user id to equal `BOARD_OWNER_USER_ID`. Creates an `owner_sessions` row (7 days). Sets `__Host-board_session` (HttpOnly, Secure, SameSite=Lax, path /). Lax, so the link in the morning message opens the board; writes are guarded by the Origin check. | anyone; 5 failures per 15 min per IP and per email (counted in memory), then 429 | form: email, password | 303 to /admin/scoreboard; 401; 403 for a valid user who is not the owner; 503 when the owner id is unset | F11 |
| POST /board/auth/logout | Revokes the session and clears the cookie. | owner, same origin | | 303 to /board/login | F11 |

Read and run the board (F02, F14):

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| GET /admin/scoreboard (changed) | The board page (S22). The same static bytes for every visitor. | owner session; otherwise 302 to /board/login | `?date=` (read by the page) | HTML | F02 |
| GET /api/board/day | The morning view: the four numbers, CPL verdict, revenue by source, product and channel, every sale, source states. | owner | `date` (YYYY-MM-DD, default yesterday in New York) | day JSON, below | F02 |
| GET /api/board/scoreboard | The existing snapshot cards, now backed by the ledger. | owner | | `snapshot()` | F02 |
| GET /api/board/opportunities | The existing opportunity scan, moved behind the session. | owner | `limit` | `scan()` | F02 |
| POST /api/board/sync/{source} | Runs one sync now: stripe, kit, instantly, meta_ads or fx. The page's Sync now buttons. | owner, same origin; once a minute per source | `days` (at most 31) | the job_runs row; 202 while the run is still going after 50 seconds | F01 |
| POST /api/board/report/send | Sends the report for a date to one channel without claiming the day. For setup. | owner, same origin | `date`, `channel` | send result | F14 |
| POST /api/board/replies | Logs a SiteBoost reply by hand. Built only if the Instantly read is not available on the owner's plan. | owner, same origin | `{occurred_at, email?}` | `{id}` | F02 |

POST /api/board/sync/{source} runs the sync in a thread of its own and waits 50 seconds at most, well under Cloudflare's cut at about 100 seconds. A run that ends in time is answered: 200 ok, 409 another run is in progress, 502 failed, 503 not configured or disabled. A run still going gets 202 `{source, status: "running", note}` and is left to finish, holding its claim. The page says so and reloads the day a minute later.

Upload a KDP report (F12):

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| POST /api/board/uploads/kdp | Hashes and stores the file, parses it, sets the period, calls `board_apply_upload`. | owner, same origin | multipart: one .xlsx or .csv, at most 5 MB; optional `period_start`, `period_end` (default: the file's first and last date) | `{upload_id, report_type, period, rows, unconverted, per_day}`; 409 with the existing upload if the bytes were seen; 422 with the headers found if the layout is unknown (the upload is kept as failed, so a fixed parser can apply its bytes) | F12 |
| DELETE /api/board/uploads/{upload_id} | Removes an upload and its rows. Older rows for those days do not come back; upload the right file again. | owner, same origin | | 204 | F12 |

Ingestion (existing routes, reworked):

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| POST /api/stripe/webhook (changed) | Refuses any post it cannot verify: 503 when no signing secret is configured, 400 on a bad signature. Then `board_claim_webhook(event)`: "done" (processed already, or a `livemode: false` event, stored as ignored) answers 200 and stops; "busy" (the same event mid-run) answers 409, so Stripe retries later; "run" executes the existing side effects, each in its own try/except as today, marks the event processed and answers 200, or marks it failed and answers 500 when the receiver itself fails. Writes no money: it starts the normal Stripe sync in the background. | Stripe (signature) | raw body, Stripe-Signature | 200, 400, 409, 500 or 503 | F01, F13 |
| GET /go/{partner} (changed) | Lower-cases the key; a key outside `[a-z0-9_-]{1,64}` answers 404, like an unknown partner today (core/api.py:7238-7239). Inserts a click (no IP) and redirects. The insert is best effort and runs after the 302: a database error is logged, at most once a minute, and never blocks the redirect. At most 30 stored clicks a minute per client address and 300 in all, counted in memory; past that it still redirects and stores nothing. For a Stripe Payment Link destination (`https://buy.stripe.com`, that host exactly) it appends `client_reference_id=<click id>`, only for a click it stores. `Cache-Control: no-store`. HEAD is not routed (405), so link checkers store nothing. | anyone | partner, `utm_*` | 302 or 404 | F13 |

Kept working on the new store, same contracts (server API key, as today):

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| GET /api/narai/scoreboard | `snapshot()`, backed by the ledger. | API key | | JSON | F02 |
| GET /api/money/summary | Today's and the week's figures from the ledger by New York day. The invented KDP figure goes. | API key | | JSON | |
| GET /api/money/stripe | Stripe ledger rows instead of data/stripe_payments.json. | API key | `days` | JSON | |
| POST /api/money/record | Writes a manual ledger row. The key is a server uuid; an `Idempotency-Key` header is honoured if sent. Both callers (the NarAI bot and the dashboard) now send one, so a retried request records once. Fails closed: while API_KEY is not set on the server, only the signed-in owner's own page may record; anything else answers 503 "Not recorded: API_KEY is not set on the server." and writes nothing. | API key, or the owner's session | source, amount, note | JSON | |
| GET /api/revenue/summary, GET /api/revenue/dashboard | RevenueEngine reads the ledger by calendar day, net of refunds. | API key | | JSON | |
| POST /api/revenue/record | Same as /api/money/record, failing closed the same way. | API key, or the owner's session | source, label, amount | JSON | |
| GET /api/revenue/report, POST /api/revenue/send-report | RevenueEngine's report, now from the ledger. | API key | | JSON | |
| GET /api/clicks | Click stats from the clicks table, and the sales that came through a tracked link from the ledger. The 20 newest clicks carry no IP. Counts are null, with `connected: false` and a note, when the database cannot be read. | API key | | JSON | |

Routes: 24 (11 new, 13 changed).

`GET /api/board/day` extends the scoreboard contract (core/scoreboard.py:18-20) with a `state`, so a partial or stale number can never look final. `value` is null when not connected; a real 0 stays 0:

```json
{
  "day": "2026-11-01", "tz": "America/New_York", "hours_in_day": 25,
  "numbers": {
    "optins":  {"value": 2, "connected": true, "state": "final", "source": "kit",
                "by_channel": {"meta": 1, "organic": 1}, "target": 3},
    "replies": {"value": 1, "value_7d": 2, "auto_replies_ignored": 1, "connected": true,
                "state": "final", "source": "instantly"},
    "revenue": {"net_usd_cents": 1000, "attributed_usd_cents": 2999, "fees_usd_cents": 317,
                "by_source": {"stripe": 1000}, "by_channel": {"meta": 2999, "unattributed": -1999},
                "unconverted_rows": 0, "has_estimates": false, "connected": true, "state": "final"},
    "spend":   {"toodle_usd_cents": 502, "toodle_link_clicks": 9, "connected": true, "state": "final",
                "day_tz": "America/New_York"},
    "cpl":     {"first_day": "2026-10-28", "last_day": "2026-11-01", "spend_days": 5,
                "spend_usd_cents": 2510, "meta_optins": 4, "toodle_optins": 5,
                "cpl_meta_usd_cents": 628, "cpl_all_usd_cents": 502, "stop_above_cents": 500,
                "verdict": "stop"}
  },
  "products": [{"source_id": "stripe", "product": "AI Entrepreneur Blueprint Kit", "sales": 1, "net_usd_cents": 2999}],
  "sales": [{"at": "2026-11-02T04:30:00Z", "source": "stripe", "kind": "sale", "amount_usd_cents": 2999,
             "channel": "meta", "attribution": "lead_email", "buyer": "b***@example.com"}],
  "sources": [{"id": "kdp", "state": "not_connected", "note": "no KDP upload covers 1 Nov"}]
}
```

How core/board/day.py decides each number's state:

- The `board_day` call fails, or `sources` comes back empty: "database not connected" for everything, never $0. A wrong or missing service key gets a permission error, because anon and authenticated have no grants; an empty `sources` means the migration never ran.
- The source's key is not configured, or its state is not_connected: `connected: false`, `value: null`.
- `final` means the source synced past the end of that day in its own time zone; otherwise `partial` with the sync time.
- KDP: `estimate` when an applied upload covers the day.
- The CPL verdict is one of no_spend, check_currency, collecting, check_tags, stop, ok.
- The 7-day reply count is null while any of its 7 days is before Instantly's `measured_from`. A count over fewer days is not a week's.
- The Toodle spend and the stop rule read "not connected" while `BOARD_TOODLE_META_CAMPAIGN_IDS` names no campaign. They have no number yet (`partial`) while the list differs from the one the last complete Meta sync used, or no sync is on record: the next Meta sync relabels every stored day. All campaigns' spend stays in the day's data (`all_usd_cents`), but the card and the message show no spend number until then.
- A no_spend verdict repeats the Meta sync's warning about a listed campaign it saw no spend for, by id. A mistyped id looks like a paused campaign, so the verdict and its 0 stay.

Webhooks in: Stripe only, at the existing endpoint. Events: charge.succeeded, charge.refunded, charge.dispute.created, charge.dispute.closed, checkout.session.completed, invoice.paid, plus the subscription events it already handles. Kit and Instantly are polled, not webhooked, in Phase 1: no new public endpoint and no new secret. Hourly is enough for a morning view.

Webhooks out: none. The report goes out through the existing senders.

Jobs. One `AsyncIOScheduler`, time zone America/New_York, `coalesce=True`, `max_instances=1`, `misfire_grace_time=900`. Job bodies are plain `def`, so APScheduler runs them in a worker thread and the event loop never blocks. Every run starts with `board_claim_run(job, run_key)` and skips when it returns null; syncs use their start instant as run_key. The claim first marks a run left `running` for 30 minutes as failed, so a dead container cannot block a job. Each connector's first complete run sets its source's `measured_from`, and a watermark only moves forward.

| job | schedule (New York) | what it does |
| --- | --- | --- |
| board_sync_hourly | every hour at :07, and in the background after each verified Stripe event | **Stripe:** list balance transactions created from the watermark minus 48 h up to now; the watermark then moves to the run's start minus 5 min. Charge and payment are sales; refund and payment_refund are refunds; dispute adjustments are dispute or dispute_reversal by sign; Stripe fee types are fees; refund_failure is an adjustment; payouts, transfers, top-ups, reserve movements and Climate contributions are skipped; any other type is skipped and named in the run's detail, so a new type shows up instead of quietly changing revenue. For each sale, fetch the charge and its Checkout Session once, for product, buyer email, `application` (via_platform), `client_reference_id` and UTM metadata. `client_reference_id` is a click id only when it is the uuid of a stored click; the SQL drops any other. Then `board_ingest_ledger`. The first run backfills from `BOARD_BACKFILL_FROM`. **Kit:** for each tag in `BOARD_TOODLE_KIT_TAGS`, list subscribers tagged from the watermark minus 1 h up to now (**verify** filter names); the watermark moves to the run's start minus 10 min, so a tag applied a moment later is read again. When the tag setting changes, the next run reads again from `BOARD_BACKFILL_FROM`, so a tag or channel added later reaches older opt-ins. Merge per subscriber, then `board_ingest_leads` with funnel toodle; a channel tag that arrives later fills an unknown channel. **Instantly:** for each SiteBoost campaign, list received emails stored from the watermark minus 48 h (**verify** endpoint). Rows are replies with funnel siteboost and channel outreach. A reply is dated by when Instantly stored it (`timestamp_created`), so a day marked final never changes. An email is automatic if Instantly flags it, its interest status is Out of Office (0), or the subject or sender says so; a bounce is automatic too. Automatic emails are not counted. |
| board_meta | 06:30 and 12:30 | Read the ad account's `timezone_name` and currency into `sources`. Read Insights at level=campaign, time_increment=1, for today and the last 28 days, every run, since Meta revises a day for 28 days (90 days on the first run): campaign_id, campaign_name, spend, impressions, inline_link_clicks, actions. Spend is a decimal string: parse it with `Decimal`. funnel = toodle for the configured campaign ids. Upsert. When the campaign list changes, every stored day is relabelled, not only the days read, and the run records the list it used. Then `board_fill_fx()`, so a non-USD account's re-pulled spend is not left unconverted until the 11:05 FX run. |
| board_fx | 11:05 | Fetch the ECB 90-day file (published about 16:00 CET). The first run, and an upload with rows older than 90 days, fetch the full-history file instead (a zip, read with the standard library). USD per X = (USD per EUR) / (X per EUR). Upsert fx_rates on (currency, day), then `board_fill_fx()`. Also run before applying an upload with non-USD rows. |
| board_morning_report | 07:00 every day (`BOARD_REPORT_CRON`); retries 07:30 and 08:15 for any channel not yet sent; at startup, if it is before 12:00 and yesterday is unsent, now | Run the three hourly syncs, and Meta if it has no ok run since 06:00, all at once, waiting 60 s at most in all. Then `board_day(yesterday)`, render with every value escaped, and for each configured channel: `board_claim_run('morning_report', 'YYYY-MM-DD:channel')` (null: sent already, or another container is sending, so skip), send, mark ok or failed. A retry claims only a failed or unclaimed channel, so a sent channel is never sent twice. |
| board_housekeeping | Sundays 03:17 | Delete expired and revoked sessions. Mark stuck runs failed. |

The connector contract for the stores that come later:

```python
@dataclass(frozen=True)
class LedgerRow:                      # one row of public.ledger_entries
    external_id: str; kind: str; amount_minor: int; currency: str
    occurred_at: datetime | None = None; occurred_on: date | None = None
    amount_usd_cents: int | None = None; fx_source: str | None = None; fee_usd_cents: int | None = None
    product: str | None = None; quantity: int | None = None; customer_email: str | None = None
    channel: str | None = None; attribution: str = "none"; click_id: UUID | None = None
    order_ref: str | None = None; via_platform: str | None = None; raw: dict = field(default_factory=dict)

class Connector(Protocol):
    source_id: str                                                      # a row in public.sources
    def sync(self, since: datetime, until: datetime) -> list[LedgerRow]: ...    # API stores
    def parse(self, data: bytes, file_name: str) -> list[LedgerRow]: ...        # file stores (KDP; later Stan, Payhip history)
```

Adding Gumroad, for example: insert its `sources` row; write core/board/connectors/gumroad_sync.py on top of core/gumroad_client.py, with `external_id` = the Gumroad sale id plus `:sale` or `:refund`; register it in the hourly job; add a fixture test from a real payload with a refund and a duplicate. No change to the views, `board_day`, the page or the report: they group by source.

## The parts that bite

- **Time zones and daylight saving.** The owner day is computed in Postgres, in the generated `local_day`. Yesterday, 1 Nov 2026, ran from 04:00Z to 05:00Z the next day: 25 hours. 14 Mar 2027 has 23. The cron runs in America/New_York, so 07:00 stays 07:00. "Yesterday" is computed in SQL, not from the container clock. Meta reports days in the ad account's time zone; it is stored in `sources.day_tz` and the board warns when it is not New York. KDP dates are Amazon's (**verify** its time zone) and labelled estimates. Fixed along the way: the briefing's UTC buckets (narai/integrations/briefing.py:270-273) and RevenueEngine's rolling 24-hour windows (core/revenue.py:198-206, 239-242).
- **Idempotency.** The ledger key is the money movement, not the event. Event ids are deduped separately so side effects run once. Every sync re-reads an overlapping window and lands on the same rows. Money is written once. A KDP file is accepted once, and the newest upload replaces its period in one transaction. The report is claimed once per day and channel; only a failed channel is claimed again. A webhook event mid-run answers 409 to its duplicate, so the side effects never run twice at once.
- **Races.** Stripe money has one writer, the sync; the webhook only nudges it. One run per job at a time (a partial unique index). Upload applies take a lock per source. Two containers during a deploy both run the scheduler: the claims stop a double send. A Kit channel tag can land seconds after the Toodle tag: the watermark lags 10 minutes, and a later tag fills an unknown channel.
- **Fake zeros.** A wrong key, a failed sync, a day before the backfill or a missing upload must read "not connected" or "partial", never 0. This is the probe, `measured_from`, the watermark and the scoreboard contract (core/scoreboard.py:3-5, 18-20). Tests assert it.
- **Currency.** Stripe's USD is what settled, from the balance transaction; the buyer's own amount is kept beside it. The design assumes the Stripe account settles in USD and flags any other. Other rows use the ECB rate on or before their date, at most 6 days back; with none, USD stays NULL and the card counts the rows. JPY has no minor unit. Today every amount is divided by 100 as dollars, whatever the currency (core/revenue.py:122, core/api.py:10164-10165).
- **Refunds, disputes, fees.** Refunds and disputes are negative rows dated when they happen, and take their sale's channel and product. A won dispute adds a positive reversal, and the fee Stripe returns with it is a negative fee. Fees are their own number, never netted into revenue. Today refunds are ignored (core/revenue.py:117-130).
- **Attribution limits.** A click id reaches Stripe only through a Payment Link destination, and today `/go` sends every key except `insider` to Stan Store (core/click_tracker.py:45-81). So in Phase 1 most attribution is the buyer's earlier opt-in, matched on email. KDP has no buyer, so it is always unattributed. Meta's own conversion counts are a cross-check only. A stored click's channel is the visitor's `utm_source` on the /go link, else the /go key (`insider`), so a tracked click always wins over the buyer's earlier opt-in. The sync finds a sale's Checkout Session by `payment_intent`, which a subscription-mode session lacks: click attribution covers one-time Payment Links until that is checked (verify item 5).
- **Opt-ins can read 0 for funnel reasons.** The Toodle capture route is mounted only in the separate NarAI app (narai/api/main.py:90), which runs on the owner's machine (marketing/META_ADS_MANUAL_FINISH.md:57) and writes SQLite by default (narai/core/db.py:14-17). Kit is the record. The ad's URL points at a PDF (marketing/META_ADS_MANUAL_FINISH.md:39). So the board shows Toodle link clicks next to opt-ins: "ad serving, no opt-ins" is visible on day one. The Meta CPL needs the capture to tag Meta leads (narai/api/routes/toodle.py:240, 290-296); `check_tags` keeps broken tagging from looking like a stop.
- **Rate limits.** Kit self-limits at 4 a second (core/kit.py:49); the recon believes the key limit is about 120 a minute. A sync makes a few calls an hour and honours 429 and Retry-After. Stripe is far above need. Meta: two runs a day, a few calls each. Instantly allows about 20 calls a minute, so the sync makes one call every 3.5 seconds at most. `/go/{partner}` is public and now writes a row per hit: a Cloudflare rate-limiting rule on `/go/*` caps it. The app also stores at most 30 clicks a minute per client address and 300 in all, in memory; past that the link still redirects. The address comes from CF-Connecting-IP or X-Forwarded-For, which a caller that skips Cloudflare can set, so the Cloudflare rule stays the real cap. Supabase Auth limits sign-in attempts per client address, and every board sign-in reaches it from the server's one address, so the board's own limit must trip first (**verify** Supabase's current number); an existing session is unaffected either way.
- **Supabase API row cap.** A read through supabase-py returns at most 1,000 rows by default. Totals come from SQL (`board_day`, `board_revenue_daily`), never from summing fetched rows in Python; a legacy route that lists rows pages through them. Click counts are exact counts in SQL; a list of every click (`get_stats`, `_load_clicks`) is read with limit and offset until an empty page, never trusting a short one.
- **Graph version.** The default is now v26.0 (core/meta_ads.py:71). A `META_GRAPH_VERSION` older than v25.0, the oldest version Meta still serves for ads calls, makes the run warn. The card shows the error, never $0.
- **File limits.** 5 MB, also a check constraint. .xlsx or .csv only; .xlsm is refused. Before openpyxl opens a file, check its uncompressed size (at most 50 MB) and row count (at most 50,000). Read with `read_only=True, data_only=True`. An unknown layout gets a 422 listing the headers found, and the file is kept as a failed upload that `board_apply_upload` accepts once the parser is fixed. The bytes go to Postgres through the Supabase API as hex text, so a 5 MB file is a request of about 10 MB (**verify** the API's request size limit before keeping the 5 MB cap).
- **Tokens.** Stripe: a restricted read key for the sync; the signing secret is required. Meta: a system-user token with ads_read only, kept apart from the token that creates campaigns. supabase-py switches a client's auth header after a sign-in, so the board signs in with a plain HTTP password grant and no supabase-py client ever signs in.
- **The scheduler on Railway.** In-process jobs die with the container, and a deploy at 07:00 would skip the report. The startup catch-up and the claims cover it, with no new worker. The board reads only the database; today's scoreboard pulls Stripe live on every load (core/scoreboard.py:23-27).
- **Deploys wipe data/.** After Phase 1 nothing writes revenue or clicks to data/*.json (.gitignore:42-45).
- **Email deliverability.** The report email uses the existing SMTP account and can land in spam; Telegram is the main channel. Telegram sends HTML (core/telegram.py:54) and the digest helper inserts section text as given (core/output_automation.py:155-180), so every value is escaped.
- **Multi-tenancy.** None. One owner; the data is server-only.
- **GDPR deletion.** Buyer and lead emails are stored. The board and report show them masked. Delete-by-email is a later should (replica/features.csv:55). Clicks no longer store an IP (core/click_tracker.py:119 does today): the table has no column for one, and the per-client limit keeps only a salted hash, in memory.
- **Search, realtime, offline.** Not needed. Hourly syncs, a webhook nudge and a 07:00 report fit the core loop.

## Build order

**0. Prerequisite: owner sign-in for the board.** Ship this alone, first, before any board number is shown. About 1 day.

The board shows revenue and buyer emails, so it does not reuse the current admin-page serving pattern. The reasons went to the owner privately. Done when all of these hold:

- `/admin/scoreboard` and every `/api/board/*` route check an owner session on the server. Without one, the page answers 302 to /board/login and the API answers 401.
- The page is the same static bytes for every visitor. No key, token or other secret is ever written into HTML or JavaScript. Its fetches are same-origin and carry only the session cookie.
- Sign-in checks the password with one HTTP password grant to Supabase Auth, so no supabase-py client ever holds a user session. The user id must equal `BOARD_OWNER_USER_ID`; any other user gets 403. Sign-in is rate-limited.
- The session is a random 32-byte token in a `__Host-` cookie (HttpOnly, Secure, SameSite=Lax). Only its hash is stored. It expires in 7 days, and sign-out revokes it at once.
- State-changing routes also check that the Origin header is the board's own origin. GET routes change nothing.
- With `BOARD_OWNER_USER_ID` unset, sign-in and every board route answer 503: the board fails closed.
- Tests: no session gives 302 and 401; a test walks `app.routes` and fails if any `/api/board/` route lacks the owner dependency; a non-owner gets 403; a bad Origin gets 403; a signed-in page is 200 and contains none of the configured secret values; logout revokes; tests/test_scoreboard_mount.py:8-12 changes to the new behaviour.
- Later, a should: TOTP for that one user.

Screens: S23, and S22 as a shell. Tables: owner_sessions (apply the whole migration now; the other tables stay empty). Routes: GET /board/login, POST /board/auth/login, POST /board/auth/logout, the change to GET /admin/scoreboard, GET /api/board/scoreboard and GET /api/board/opportunities (the page's existing cards and list, now behind the session, so the page keeps working once it carries no key), and the guard on /api/board/*.

**1. Vertical slice: yesterday's Stripe revenue, from Stripe to the morning message.** About 2 days.

- Tables: sources, job_runs, webhook_events, ledger_entries. Views: board_ledger, board_revenue_daily. Functions: board_ingest_ledger, board_day, board_source_state, board_claim_run, board_claim_webhook.
- Code: core/board/connectors/stripe_sync.py, ledger.py, day.py; the webhook rework; a minimal 07:00 Telegram line with the claim and the startup catch-up.
- Routes: GET /api/board/day, POST /api/board/sync/stripe, POST /api/stripe/webhook (changed).
- Screen: S22's revenue card, with every sale listed and the Stripe pill.
- Before this deploy: confirm `STRIPE_WEBHOOK_SECRET` is set in Railway. The reworked receiver answers 503 without it, and store deliveries and tier upgrades run from the receiver, so they would wait on Stripe's retries (up to 3 days).
- Done when:
  - Yesterday's New York net and fees on the board equal Stripe's balance-transaction export for the same New York day, to the cent.
  - Replaying a webhook from the Stripe dashboard changes nothing: no second row, no second delivery.
  - Unsetting the key shows "not connected", not $0.
  - A deploy at 06:59 still yields exactly one message.

**2. Must-haves, the rest of Phase 1**, in order:

- **2a. Retire the JSON revenue store.** The webhook stops writing data/stripe_payments.json. /api/money/*, /api/revenue/* and RevenueEngine read the ledger by New York day. Manual records become manual ledger rows. The invented KDP figure and the `launch()`-only 08:00 report go. The scoreboard's revenue cards read the ledger, and "leads" becomes "places scanned (outreach)". Run the one-off import first. Done when a test finds no writer of data/stripe_payments.json or data/revenue.json and each legacy route returns the ledger's numbers. Screen: S22's existing cards. Tables: ledger_entries (manual rows), job_runs (`json_import`). Routes: GET /api/narai/scoreboard, GET /api/board/scoreboard, GET /api/money/summary, GET /api/money/stripe, POST /api/money/record, GET /api/revenue/summary, GET /api/revenue/dashboard, POST /api/revenue/record, GET /api/revenue/report, POST /api/revenue/send-report. About half a day.
- **2b. Toodle opt-ins.** kit_sync, `KitClient.list_tag_subscribers`, board_ingest_leads, the opt-ins card. Number 1 goes live. Done when a past day's count equals Kit's own list for the Toodle tags on that New York day. Screen: S22's opt-ins card. Table: lead_events. Route: POST /api/board/sync/kit (GET /api/board/day gains the number). About half a day.
- **2c. Meta spend and the stop rule.** ad_spend_daily, meta_sync, `MetaAdsClient.daily_insights`, board_cpl, the CPL card with its verdict pill and link clicks beside opt-ins. Done when spend per day equals Ads Manager for the same ad-account day. Screen: S22's spend and CPL cards. Table: ad_spend_daily. Route: POST /api/board/sync/meta_ads. About 1 day.
- **2d. SiteBoost replies.** instantly_sync, or the manual route if the API is not on the owner's plan. Number 2 goes live. Done when a past day matches the Instantly inbox. Screen: S22's replies card. Table: lead_events. Route: POST /api/board/sync/instantly, or POST /api/board/replies. About half a day.
- **2e. Attributed revenue and the click store.** The clicks table, `/go` writing it and handing the click id to Payment Links, the one-off import of data/clicks.json (IP dropped), data/conversions.json retired, the briefing's revenue and KPI lines repointed. The Stripe sync credits a new sale whose `client_reference_id` names a stored click to that click (attribution `click_id`, the click's channel); a refund takes its sale's. The morning message and the revenue card add "attributed $29.99 (meta)" and each sale says how it was credited. Number 3 goes live. Done when a test purchase through a tracked link shows `click_id` with its channel, and a buyer with an earlier opt-in shows `lead_email`. Screen: S22's sales list with its channel column. Table: clicks. Routes: GET /go/{partner}, GET /api/clicks. About 1 day.
- **2f. KDP upload.** source_uploads, core/board/connectors/kdp_upload.py, board_apply_upload, the S24 panel; then fx_rates, fx_sync and board_fill_fx. Done when an uploaded month equals the KDP report's own totals per marketplace, the same file twice changes nothing, and a newer overlapping file replaces only its period. Screen: S24. Tables: source_uploads, fx_rates. Routes: POST /api/board/uploads/kdp, DELETE /api/board/uploads/{upload_id}, POST /api/board/sync/fx. About 1 day, after one real KDP file from the owner fixes the header map.
- **2g. The full morning report.** All four numbers, the stop-rule verdict and source states; email and Slack when configured; the retries. Done when a failed Telegram send at 07:00 is sent by the 07:30 retry and never twice. Screen: S22's source pills, and the message itself (F14). Table: job_runs. Route: POST /api/board/report/send. About half a day.

Total for steps 0 to 2: about 8 to 10 working days.

**3. Should-haves, after Phase 1, one connector at a time against the contract:**

- Gumroad (core/gumroad_client.py). Shopify, once read_all_orders is added (shopify.app.toml:29). BigCommerce. Payhip: a webhook, plus history as a CSV through source_uploads. Stan: a CSV through source_uploads. Digistore24 and Whop.
- Spotting store sales that also settle in Stripe (`via_platform` is already stored). Channel from store data. Slack report. Date ranges and 7- and 30-day charts. Delete-by-email. TOTP on sign-in. Excluding the owner's own test purchases. Feeding `revenue_gate.set_metrics_provider()` (core/revenue_gate.py:107-169).

**4. Fixes from replica-entrepreneur:** not run yet. They slot in after Phase 1.

Feature matrix (features.csv):

- **Owner must rows Phase 1 closes:** the morning view by store and product with every sale; leads next to revenue; store as a dimension everywhere; New York calendar days; one ledger; verified webhooks (Stripe, the only receiver in Phase 1); Kit subscribers per day (per tag; per form is a could); a channel per sale from click id, UTM or lead email, with no recency guess.
- **Owner must rows deferred by the Phase 1 scope:** the Gumroad and Shopify connectors.
- **Baremetrics must rows covered:** Net Revenue, Other Revenue (every one-off sale is a ledger sale), Refunds by refund date, the daily summary (Telegram and email), Connect Stripe with history, combining sources, the home cards.
- **Baremetrics must rows deferred:** the sidebar navigation, per-metric pages with a date-range picker, and the live stream (the sales list stands in).
- **Promoted from could by the scope:** Meta ad spend against revenue.

## Verify before coding

Each item is a guess or unchecked, takes minutes against vendor docs or a real file, and sits in one function:

1. Kit v4, list subscribers for a tag: the `tagged_after` and `tagged_before` filters, the `tagged_at` field, cursor paging, and the API-key rate limit.
2. Instantly v2: listing received emails per campaign (filters, timestamp, sender, any auto-reply flag), and whether the owner's plan has API access. Otherwise use the manual route.
3. Meta: a supported Graph version; that a system-user token with ads_read can read the ad account; the account's `timezone_name`.
4. KDP: the sheet and header names of the report the owner downloads, the time zone of its dates, and whether it has a USD column. The parser's header map is one dict.
5. Stripe: that the account settles in USD; which events the endpoint receives; whether Payment Links carry `client_reference_id` and UTM to the Checkout Session, and whether a subscription-mode link's session can be found from its charge; where the product name lives; whether this account's country gets the dispute fee back on a won dispute (the SQL takes either sign).
6. Toodle: which `source` and `product_interest` values the live form sends. narai/api/routes/toodle.py:240 documents `meta_ad` as an example and the ad's URL carries `utm_source=meta` (marketing/META_ADS_MANUAL_FINISH.md:39). The simplest fix is for the form to also send `extra_tags: ["toodle"]` (narai/api/routes/toodle.py:243).
7. Supabase: that the owner's user can sign in with a password, and that `SUPABASE_ANON_KEY` is set in Railway; Auth's sign-in limit per client address; the API's request size limit for a 5 MB upload (about 10 MB as hex).
8. Email: the `EMAIL_SMTP_HOST` and `EMAIL_SMTP_PORT` names are what Railway sets, not .env.example's `EMAIL_HOST` and `EMAIL_PORT` (see the variables above).

## Summary

- Stack: FastAPI (core/api.py) on Railway, Supabase Postgres (one database, RLS deny-all, SQL write path), Supabase Auth with server-side owner sessions, in-process APScheduler, the existing Telegram, SMTP and Slack senders; Stripe read-only; ECB rates for KDP.
- Tables: 10, plus 2 views and 11 functions. Routes: 24 (11 new, 13 changed). Jobs: 5.
- The three riskiest parts:
  1. Opt-in counts that are right but low for funnel reasons: the ad lands on a PDF, the capture runs off Railway, and tagging is unverified. The board must make that visible, not hide it.
  2. Reworking the Stripe receiver that also triggers deliveries and tier upgrades. Dedupe must not change those side effects.
  3. Day boundaries and formats in unverified sources (Meta ad-account time zone, KDP layout and dates, Instantly reply fields). Each needs a real fixture before its card may say "final".
- Next step: build step 0. Then `/replica-design`, kept light: S22 extends an existing page and its components (cards, pills, `esc()`); the new pieces are the CPL verdict pill, the sales table, the upload panel and the sign-in form.

## How this plan was chosen

Two drafts, scored 1 to 5:

| criterion | reuse-first | ledger-first |
| --- | --- | --- |
| fit to the Phase 1 scope | 5: extends the scoreboard; adds nothing outside the scope | 4: adds GDPR redaction, retention, a preview step, range and rebuild routes; drops the opportunity list |
| reuse of existing code | 5: every change mapped to an existing file | 3: a parallel package and rollup machinery; cites requirements.txt, but production installs requirements-server.txt (nixpacks.toml:8); requires an `Idempotency-Key` that today's callers do not send |
| correctness of the numbers | 4: Stripe disputes keyed on `du_` collide when a dispute is won; days before a backfill read 0; the CPL window needs 5 calendar days in a row | 5: balance-transaction keys, `measured_from`, per-channel claims, append-only provenance |
| the security prerequisite | 4: first and alone, but JWT cookies need a refresh flow and an unverified signing-key assumption, and cannot be revoked before expiry | 4: revocable server-side sessions, but `GET /login` already exists (core/api.py:1052) |
| effort for a solo owner | 4.5: 9 tables, views read live, 6 to 8 days | 2.5: 17 tables, 9 functions, rollups to rebuild after every write, triggers, a preview and commit flow |
| total | 22.5 | 18.5 |

Base: reuse-first. Grafted from ledger-first:

- Stripe rows key on the balance transaction (`txn_...`), with `order_ref` for the sale. This fixes the dispute collision.
- A `sources` table with `measured_from`, a watermark and the source's own day time zone, so a day before the backfill reads "not measured", and a new store is one row.
- Server-side owner sessions with a hashed token, instead of JWT cookies, and failing closed when the owner id is unset.
- Report claims per day and channel, plus a startup catch-up before noon.
- KDP files kept in Postgres instead of a storage bucket.
- Money written once, with a mismatch report instead of an overwrite.
- One running run per job, file-parsing limits, ignoring `livemode: false`, and "done when" checks against each source's own numbers.

Kept from reuse-first: the reuse map, views computed on read (no rollups to rebuild), NULL-means-unknown for USD and fees, the `check_tags` verdict, masked buyers, `board_day` in one round trip, the newest-upload-replaces-its-period rule, the `/board/login` path, and the manual reply fallback.

Changed by the judge:

- The webhook no longer writes money. The sync is the only writer of Stripe money, so the two cannot race.
- The CPL window is the last 5 days with Toodle spend, not 5 calendar days in a row. A zero-opt-in stop needs spend above the threshold.
- The session cookie is SameSite=Lax, not Strict: both drafts used Strict, which would make the owner sign in again every time they open the board from the morning message. Writes keep the Origin check.
- The board's trigger function has its own name, so the shared `set_updated_at()` is left alone.
- The manual record route keeps working for callers that send no `Idempotency-Key`.

Changed by the critic (checked against the replica-architect checklist and the repo at 55ab030):

- Fees are signed. A refunded fee or a won dispute's returned fee is negative, and the old `>= 0` check would have failed the whole Stripe sync on the first won dispute.
- Labels never block money. An unknown or malformed click id, a malformed UTM channel or a malformed email used to fail the whole batch (a foreign-key, cast or check error), so one odd sale could stall the hourly sync. They are now dropped; money fields still fail loudly.
- Send-once is now defined in SQL: `board_claim_run` (a failed report channel is retried, a sent one never, a run dead for 30 minutes is recovered) and `board_claim_webhook` (run, busy or done). Before, a failed channel could not be claimed again, and a duplicate event arriving mid-run had no rule.
- fx_rates has a uuid id; an unknown day time zone is refused when written instead of breaking `board_day`; a failed upload can be applied again from its kept bytes; one key with two currencies is refused instead of summed; the earliest lead time wins; Kit keys carry the funnel.
- Step 0 carries the page's two existing data routes, which it needs once the page carries no key; every milestone lists its screens, tables and routes.
- Sign-in copies the stateless password grant in backend/app/services/supabase_auth.py:164-207. The cron helper is nested and must be lifted (narai/integrations/scheduler.py:63-68). The click tracker's full caller list, the `.env.example` gaps, the `EMAIL_SMTP_*` name mismatch, the `APScheduler<4` pin, the Supabase API's 1,000-row cap, Meta's FX timing, ECB history for old uploads and the wrong-key probe wording (a permission error, not an empty table) are now in the plan.
