-- ═══════════════════════════════════════════════════════════════════════════
-- Daily numbers board, Phase 1: one money ledger, lead events, ad spend,
-- clicks, report uploads, FX rates, run bookkeeping and owner sessions.
--
-- In the repo:  narai/migrations/0002_daily_numbers_board.sql
-- Run it in the Supabase SQL editor, or:
--   python3 scripts/run_supabase_migration.py narai/migrations/0002_daily_numbers_board.sql
-- Plain SQL, not an Alembic revision: Alembic in narai/migrations targets
-- NARAI_DATABASE_URL, not Supabase (same note as 0001_siteboost_suppressions.sql).
-- Idempotent: every statement is if-not-exists, or-replace or on-conflict, so
-- the file can be re-run safely.
--
-- Access: only the FastAPI backend (core/api.py on Railway) touches these
-- objects, with SUPABASE_SERVICE_KEY. service_role bypasses RLS. RLS is ON
-- with NO policies, anon and authenticated get no grants, views run as the
-- caller (security_invoker), and functions are not executable by anon or
-- authenticated. The anon key ships in public pages by design, so anything
-- left open here would be readable by anyone.
--
-- Rules the database enforces, not the app:
--   * one row per money movement: unique (source_id, external_id). For Stripe
--     the external id is the balance transaction (txn_...), so a webhook
--     retry, the hourly sync and a backfill all land on the same row.
--   * the owner's day (America/New_York) is a generated column, never typed in.
--   * money is integer minor units plus an ISO currency (cents for USD). USD
--     cents stay NULL until a real rate exists; a NULL fee means "unknown".
--   * money columns are written once; a later sync may only improve labels.
--     A bad money field fails the whole batch loudly; a bad label (an unknown
--     click id, a malformed channel or email) is dropped and never blocks a sync.
--   * send once: each report channel is claimed once per day (job_runs) and
--     each provider event once (webhook_events); only a failed or abandoned
--     claim can be taken again (board_claim_run, board_claim_webhook).
--   * adding a store later = one row in public.sources plus one connector
--     module; no schema change unless the store needs a new column.
-- ═══════════════════════════════════════════════════════════════════════════

begin;

-- ─── 0. helpers ─────────────────────────────────────────────────────────────

-- The board's own updated_at trigger. The shared public.set_updated_at() from
-- supabase_shopify_multitenant.sql is deliberately left untouched.
create or replace function public.board_touch_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  new.updated_at := now();
  return new;
end
$$;

-- ISO 4217 minor-unit exponent. JPY has no minor unit; a few dinars have three.
-- The Python parsers (core/board/ledger.py) use the same table to turn a
-- decimal amount into integer minor units.
create or replace function public.board_currency_exponent(p_currency text)
returns int
language sql
immutable strict
set search_path = public, pg_temp
as $$
  select case
    when p_currency in ('BIF','CLP','DJF','GNF','ISK','JPY','KMF','KRW','PYG','RWF',
                        'UGX','UYI','VND','VUV','XAF','XOF','XPF') then 0
    when p_currency in ('BHD','IQD','JOD','KWD','LYD','OMR','TND') then 3
    when p_currency in ('CLF','UYW') then 4
    else 2
  end
$$;

-- ─── 1. sources: one row per connector ──────────────────────────────────────
-- Seeded at the end of this file. The seed rows double as a probe. A key
-- without service_role cannot read these tables at all (no grants, so a
-- permission error, not an empty result), and an empty table means this
-- migration never ran. The backend treats either as "database not
-- connected", never as $0.
-- id is a readable text key ('stripe', 'kdp') on purpose: every connector,
-- seed row and foreign key names its source by it.
create table if not exists public.sources (
  id              text primary key
                  constraint sources_id_format check (id ~ '^[a-z0-9_]{2,32}$'),
  kind            text not null
                  constraint sources_kind_known check (kind in (
                    'stripe','kit','instantly','meta_ads','kdp','manual',
                    -- later stores, one connector each; listed now so adding one is a row, not a migration
                    'gumroad','shopify','bigcommerce','whop','payhip','stan','digistore24')),
  method          text not null check (method in ('api','upload','manual')),
  display_name    text not null check (length(display_name) between 1 and 80),
  account_ref     text,                        -- acct_..., act_..., a Kit account id; never a secret
  day_tz          text not null default 'America/New_York'
                  check (day_tz ~ '^[A-Za-z_]+(/[A-Za-z0-9_+-]+)*$'),   -- the source's own day (Meta: the ad account tz)
  currency        char(3) check (currency ~ '^[A-Z]{3}$'),
  enabled         boolean not null default true,
  measured_from   date,                        -- first owner day fully covered; earlier days read "not measured"
  synced_through  timestamptz,                 -- watermark: everything before this instant is in the tables
  last_ok_at      timestamptz,
  last_error      text,
  last_error_at   timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint sources_error_pair check ((last_error is null) = (last_error_at is null)),
  -- an unknown zone is refused when written (the cast raises), not later inside board_day
  constraint sources_day_tz_known check (('2000-01-01 00:00'::timestamp at time zone day_tz) is not null)
);

-- ─── 2. job_runs: syncs, uploads, imports and the morning report ────────────
-- unique (job, run_key) is the send-once guard for the report: run_key is
-- 'YYYY-MM-DD:channel', so each channel is claimed once per day, by one
-- container, even during a Railway deploy that briefly runs two. Syncs use
-- their start instant as run_key. Every run starts through board_claim_run(),
-- which also re-claims a failed run of the same key (the report's retries).
create table if not exists public.job_runs (
  id             uuid primary key default gen_random_uuid(),
  job            text not null
                 constraint job_runs_job_known check (job in (
                   'stripe_sync','kit_sync','instantly_sync','meta_sync','fx_sync',
                   'kdp_apply','morning_report','json_import','housekeeping')),
  source_id      text references public.sources(id) on delete restrict,
  run_key        text not null check (length(run_key) between 1 and 120),
  trigger_kind   text not null default 'schedule'
                 check (trigger_kind in ('schedule','owner','webhook','startup','script')),
  status         text not null default 'running' check (status in ('running','ok','failed','skipped')),
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  window_start   timestamptz,                  -- the slice of source time this run read
  window_end     timestamptz,
  covered_until  timestamptz,                  -- the source is complete up to this instant after the run
  rows_written   int not null default 0 check (rows_written >= 0),
  attempts       int not null default 1 check (attempts >= 1),   -- 2 or more: a failed run claimed again
  detail         jsonb not null default '{}'::jsonb check (jsonb_typeof(detail) = 'object'),
  error          text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint job_runs_once unique (job, run_key),
  constraint job_runs_finished check ((status = 'running') = (finished_at is null)),
  constraint job_runs_window check (window_start is null or window_end is null or window_end >= window_start)
);
-- One running run per job. The runner marks a 'running' row older than 30
-- minutes as failed before it starts, so a crashed run cannot block forever.
create unique index if not exists job_runs_one_running_uq on public.job_runs (job) where status = 'running';
create index if not exists job_runs_source_idx on public.job_runs (source_id) where source_id is not null;
create index if not exists job_runs_latest_idx on public.job_runs (job, finished_at desc) where status in ('ok','failed');

-- ─── 3. webhook_events: one row per provider event id ───────────────────────
-- Dedupes deliveries so the receiver's side effects (deliveries, tier
-- upgrades, bridges) run once per event. Money is NOT written from events:
-- the balance-transaction sync is the only writer of Stripe ledger rows.
-- The receiver claims each event through board_claim_webhook(): a new event
-- runs, an in-flight duplicate is told to come back later, a processed one
-- stops, and only a failed or abandoned one runs again.
create table if not exists public.webhook_events (
  id            uuid primary key default gen_random_uuid(),
  source_id     text not null references public.sources(id) on delete restrict,
  event_id      text not null check (length(event_id) between 1 and 255),
  event_type    text not null check (length(event_type) between 1 and 120),
  livemode      boolean,
  status        text not null default 'received' check (status in ('received','processed','failed','ignored')),
  attempts      int not null default 1 check (attempts >= 1),
  error         text,
  received_at   timestamptz not null default now(),
  processed_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint webhook_events_once unique (source_id, event_id),
  constraint webhook_events_processed check ((status = 'processed') = (processed_at is not null))
);
create index if not exists webhook_events_open_idx on public.webhook_events (status, received_at)
  where status in ('received','failed');

-- ─── 4. clicks: /go/{partner} redirects (replaces data/clicks.json) ─────────
-- No visitor IP is stored. The id doubles as the click id handed to a Stripe
-- Payment Link as client_reference_id.
create table if not exists public.clicks (
  id             uuid primary key default gen_random_uuid(),
  partner        text not null check (partner ~ '^[a-z0-9_-]{1,64}$'),
  clicked_at     timestamptz not null default now(),
  local_day      date generated always as ((clicked_at at time zone 'America/New_York')::date) stored,
  referrer_host  text check (referrer_host is null or length(referrer_host) <= 255),   -- host only
  destination    text not null check (length(destination) between 1 and 2048),
  utm            jsonb not null default '{}'::jsonb check (jsonb_typeof(utm) = 'object'),
  import_key     text,                         -- sha256 of an old JSON row (one-off import); NULL for live clicks
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint clicks_import_once unique (import_key)
);
create index if not exists clicks_partner_time_idx on public.clicks (partner, clicked_at desc);
create index if not exists clicks_day_idx on public.clicks (local_day);

-- ─── 5. source_uploads: report files the owner uploads (KDP in Phase 1) ─────
-- The raw file is kept in Postgres (5 MB cap), so a fixed parser can re-run
-- on it and there is no storage bucket to configure.
create table if not exists public.source_uploads (
  id              uuid primary key default gen_random_uuid(),
  source_id       text not null references public.sources(id) on delete restrict,
  file_name       text not null check (length(file_name) between 1 and 255),
  file_sha256     bytea not null check (length(file_sha256) = 32),
  file_bytes      int not null check (file_bytes between 1 and 5242880),
  content         bytea not null,
  report_type     text,                        -- detected from the header row
  parser_version  text not null check (length(parser_version) between 1 and 40),
  period_start    date,                        -- the dates the report covers (owner-confirmed)
  period_end      date,
  rows_parsed     int not null default 0 check (rows_parsed >= 0),
  rows_skipped    int not null default 0 check (rows_skipped >= 0),
  status          text not null default 'received'
                  check (status in ('received','applied','failed','superseded')),
  error           text,
  uploaded_at     timestamptz not null default now(),
  applied_at      timestamptz,
  job_run_id      uuid references public.job_runs(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint source_uploads_file_once unique (source_id, file_sha256),   -- the same file twice is one upload
  constraint source_uploads_id_source unique (id, source_id),            -- target of the ledger's composite key
  constraint source_uploads_size check (octet_length(content) = file_bytes),
  constraint source_uploads_period check (period_start is null or period_end is null or period_end >= period_start),
  constraint source_uploads_applied check ((status in ('applied','superseded')) = (applied_at is not null))
);
create index if not exists source_uploads_recent_idx on public.source_uploads (source_id, uploaded_at desc);
create index if not exists source_uploads_cover_idx on public.source_uploads (source_id, period_start, period_end)
  where status = 'applied';
create index if not exists source_uploads_run_idx on public.source_uploads (job_run_id) where job_run_id is not null;

-- ─── 6. ledger_entries: one row per money movement at a source ──────────────
-- external_id is the source's id for the MONEY MOVEMENT, not for the event
-- that announced it. Stripe: the balance transaction id (txn_...). One payment
-- fires several events (checkout.session.completed, charge.succeeded,
-- invoice.paid) and a won dispute adds a second balance transaction, so only
-- the balance transaction is one-to-one with money. KDP: a natural key per
-- report row. Manual: a server-made uuid.
create table if not exists public.ledger_entries (
  id                uuid primary key default gen_random_uuid(),
  source_id         text not null references public.sources(id) on delete restrict,
  external_id       text not null check (length(external_id) between 1 and 255),
  kind              text not null
                    check (kind in ('sale','refund','dispute','dispute_reversal','fee','adjustment')),
  occurred_at       timestamptz,               -- when the money moved at the source; never receipt time
  occurred_on       date,                      -- date-only sources (KDP rows), the source's own date
  local_day         date generated always as
                      (coalesce((occurred_at at time zone 'America/New_York')::date, occurred_on)) stored,
  amount_minor      bigint not null,           -- signed, integer minor units of currency (cents for USD)
  currency          char(3) not null check (currency ~ '^[A-Z]{3}$'),
  amount_usd_cents  bigint,                    -- signed USD cents; NULL = no real rate yet: left out of totals and counted
  fx_source         text check (fx_source in ('identity','stripe','ecb')),
  fx_rate           numeric(20,10) check (fx_rate is null or fx_rate > 0),   -- USD per 1 unit of currency
  -- processor fee in USD cents, signed like Stripe's balance transaction fee:
  -- positive = paid, negative = returned (a refunded fee, a won dispute's fee).
  -- NULL = unknown, never 0.
  fee_usd_cents     bigint,
  is_estimate       boolean not null default false,   -- KDP royalties until Amazon pays them
  product           text,
  quantity          int,
  customer_email    text check (customer_email is null
                                or (customer_email = lower(btrim(customer_email)) and customer_email like '%_@_%')),
  channel           text check (channel is null or channel ~ '^[a-z0-9_]{1,32}$'),   -- stored attribution only
  attribution       text not null default 'none' check (attribution in ('click_id','checkout_utm','none')),
  click_id          uuid references public.clicks(id) on delete restrict,   -- a click that led to a sale is kept
  order_ref         text,                      -- ties a refund or dispute to its sale (Stripe charge id)
  via_platform      text,                      -- Stripe charge.application: another store settling in this Stripe
  source_event_id   text,                      -- last provider event seen for this row; tracing only
  upload_id         uuid,                      -- set for rows that came from an uploaded file
  job_run_id        uuid references public.job_runs(id) on delete set null,
  raw               jsonb not null default '{}'::jsonb check (jsonb_typeof(raw) = 'object'),  -- normalised fields; never card data
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint ledger_entries_one_row_per_movement unique (source_id, external_id),
  -- deleting an upload removes its rows; the pair also proves the row's source owns the upload
  constraint ledger_entries_upload_fk foreign key (upload_id, source_id)
    references public.source_uploads (id, source_id) on delete cascade,
  constraint ledger_entries_one_time check ((occurred_at is null) <> (occurred_on is null)),
  constraint ledger_entries_sign check (
       (kind in ('sale','dispute_reversal') and amount_minor >= 0 and coalesce(amount_usd_cents, 0) >= 0)
    or (kind in ('refund','dispute','fee')  and amount_minor <= 0 and coalesce(amount_usd_cents, 0) <= 0)
    or  kind = 'adjustment'),
  constraint ledger_entries_usd_has_source check ((amount_usd_cents is null) = (fx_source is null)),
  constraint ledger_entries_identity check (
    fx_source is distinct from 'identity' or (currency = 'USD' and amount_usd_cents = amount_minor)),
  constraint ledger_entries_ecb_has_rate check (fx_source is distinct from 'ecb' or fx_rate is not null),
  constraint ledger_entries_rate_needs_source check (fx_rate is null or fx_source in ('ecb','stripe')),
  constraint ledger_entries_attribution check ((attribution = 'none') = (channel is null)),
  constraint ledger_entries_click check (attribution <> 'click_id' or click_id is not null)
);
create index if not exists ledger_entries_day_source_idx on public.ledger_entries (local_day, source_id);
create index if not exists ledger_entries_order_idx on public.ledger_entries (source_id, order_ref) where order_ref is not null;
create index if not exists ledger_entries_email_idx on public.ledger_entries (customer_email) where customer_email is not null;
create index if not exists ledger_entries_click_idx on public.ledger_entries (click_id) where click_id is not null;
create index if not exists ledger_entries_upload_idx on public.ledger_entries (upload_id) where upload_id is not null;
create index if not exists ledger_entries_run_idx on public.ledger_entries (job_run_id) where job_run_id is not null;
create index if not exists ledger_entries_unconverted_idx on public.ledger_entries (currency, local_day)
  where amount_usd_cents is null;

-- ─── 7. lead_events: Toodle opt-ins (Kit) and SiteBoost replies (Instantly) ─
-- Kit: external_id '<funnel>:sub:<subscriber id>' ('toodle:sub:123'), so a
-- subscriber is one opt-in per funnel, and a later funnel is one more key, not
-- a migration. The earliest time seen wins. Instantly: one row per received
-- email; the board counts distinct prospects.
create table if not exists public.lead_events (
  id             uuid primary key default gen_random_uuid(),
  source_id      text not null references public.sources(id) on delete restrict,
  external_id    text not null check (length(external_id) between 1 and 255),
  kind           text not null check (kind in ('optin','reply')),
  occurred_at    timestamptz not null,         -- Kit: first Toodle tag time; Instantly: reply received time
  local_day      date generated always as ((occurred_at at time zone 'America/New_York')::date) stored,
  email          text check (email is null or (email = lower(btrim(email)) and email like '%_@_%')),
  funnel         text check (funnel is null or funnel ~ '^[a-z0-9_]{1,32}$'),        -- 'toodle', 'siteboost'
  channel        text not null default 'unknown' check (channel ~ '^[a-z0-9_]{1,32}$'), -- 'meta', 'organic', 'outreach'
  campaign_ref   text,                         -- Instantly campaign id; Meta campaign id when known
  tags           text[] not null default '{}',
  is_auto_reply  boolean not null default false,
  job_run_id     uuid references public.job_runs(id) on delete set null,
  raw            jsonb not null default '{}'::jsonb check (jsonb_typeof(raw) = 'object'),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint lead_events_once unique (source_id, external_id),
  constraint lead_events_auto_reply_is_reply check (kind = 'reply' or not is_auto_reply)
);
create index if not exists lead_events_day_idx on public.lead_events (local_day, kind, funnel);
create index if not exists lead_events_email_time_idx on public.lead_events (email, occurred_at) where email is not null;
create index if not exists lead_events_run_idx on public.lead_events (job_run_id) where job_run_id is not null;

-- ─── 8. ad_spend_daily: Meta Insights, one row per campaign per day ─────────
-- Meta revises recent days, so the last pull wins (plain upsert on the key).
-- "day" is in the AD ACCOUNT's time zone (sources.day_tz); the board prints
-- a warning when that is not America/New_York.
create table if not exists public.ad_spend_daily (
  id               uuid primary key default gen_random_uuid(),
  source_id        text not null references public.sources(id) on delete restrict,
  campaign_id      text not null check (length(campaign_id) between 1 and 64),
  campaign_name    text,
  funnel           text check (funnel is null or funnel ~ '^[a-z0-9_]{1,32}$'),   -- 'toodle' for the plan's campaigns
  day              date not null,
  currency         char(3) not null check (currency ~ '^[A-Z]{3}$'),
  spend_minor      bigint not null check (spend_minor >= 0),
  spend_usd_cents  bigint check (spend_usd_cents is null or spend_usd_cents >= 0),
  fx_source        text check (fx_source in ('identity','ecb')),
  fx_rate          numeric(20,10) check (fx_rate is null or fx_rate > 0),
  impressions      bigint not null default 0 check (impressions >= 0),
  link_clicks      bigint not null default 0 check (link_clicks >= 0),
  platform_leads   int check (platform_leads is null or platform_leads >= 0),   -- Meta's own count: a cross-check only
  pulled_at        timestamptz not null default now(),
  job_run_id       uuid references public.job_runs(id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint ad_spend_daily_once unique (source_id, campaign_id, day),
  constraint ad_spend_daily_usd_has_source check ((spend_usd_cents is null) = (fx_source is null)),
  constraint ad_spend_daily_identity check (
    fx_source is distinct from 'identity' or (currency = 'USD' and spend_usd_cents = spend_minor)),
  constraint ad_spend_daily_ecb_has_rate check (fx_source is distinct from 'ecb' or fx_rate is not null),
  constraint ad_spend_daily_rate_needs_ecb check (fx_rate is null or fx_source = 'ecb')
);
create index if not exists ad_spend_daily_day_funnel_idx on public.ad_spend_daily (day, funnel);
create index if not exists ad_spend_daily_run_idx on public.ad_spend_daily (job_run_id) where job_run_id is not null;

-- ─── 9. fx_rates: ECB reference rates, as USD per unit ──────────────────────
-- Only non-USD rows need these (KDP marketplaces; a non-USD ad account).
-- Stripe rows take USD from Stripe's own balance transactions.
create table if not exists public.fx_rates (
  id            uuid primary key default gen_random_uuid(),
  currency      char(3) not null check (currency ~ '^[A-Z]{3}$' and currency <> 'USD'),
  day           date not null,
  usd_per_unit  numeric(20,10) not null check (usd_per_unit > 0),
  source        text not null default 'ecb' check (source in ('ecb')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint fx_rates_once unique (currency, day)   -- the natural key: the fx job upserts on it, lookups use it
);

-- ─── 10. owner_sessions: server-side sessions for the board ─────────────────
-- Sign-in checks the password with Supabase Auth once; the browser then holds
-- only a random token in an HttpOnly cookie, and only its hash is stored here.
-- Revoking a row signs that browser out at once.
create table if not exists public.owner_sessions (
  id            uuid primary key default gen_random_uuid(),
  token_sha256  bytea not null check (length(token_sha256) = 32),
  user_id       uuid not null references auth.users(id) on delete cascade,
  expires_at    timestamptz not null,
  revoked_at    timestamptz,
  last_seen_at  timestamptz not null default now(),
  user_agent    text check (user_agent is null or length(user_agent) <= 300),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint owner_sessions_token_once unique (token_sha256),
  constraint owner_sessions_expiry check (expires_at > created_at and expires_at <= created_at + interval '30 days')
);
create index if not exists owner_sessions_user_idx on public.owner_sessions (user_id);
create index if not exists owner_sessions_live_idx on public.owner_sessions (expires_at) where revoked_at is null;

-- ─── updated_at triggers ────────────────────────────────────────────────────
do $$
declare t text;
begin
  foreach t in array array['sources','job_runs','webhook_events','clicks','source_uploads',
                           'ledger_entries','lead_events','ad_spend_daily','fx_rates','owner_sessions'] loop
    execute format('drop trigger if exists %I on public.%I', 'trg_' || t || '_touch', t);
    execute format('create trigger %I before update on public.%I '
                   'for each row execute function public.board_touch_updated_at()', 'trg_' || t || '_touch', t);
  end loop;
end
$$;

-- ─── table comments ─────────────────────────────────────────────────────────
comment on table public.sources        is 'Daily numbers board: one row per connector (state, watermark, measured_from). Seed rows double as the wrong-key probe.';
comment on table public.job_runs       is 'Daily numbers board: every sync, upload apply, import and report send. unique (job, run_key) is the send-once guard.';
comment on table public.webhook_events is 'Daily numbers board: one row per provider event id, so receiver side effects run once per event.';
comment on table public.clicks         is 'Daily numbers board: /go/{partner} redirects (was data/clicks.json). No IP stored.';
comment on table public.source_uploads is 'Daily numbers board: report files the owner uploads (KDP). The newest applied upload is the truth for its period.';
comment on table public.ledger_entries is 'Daily numbers board: one row per money movement per source, deduped on (source_id, external_id).';
comment on table public.lead_events    is 'Daily numbers board: Toodle opt-ins from Kit and SiteBoost replies from Instantly.';
comment on table public.ad_spend_daily is 'Daily numbers board: Meta Insights spend per campaign per ad-account day; last pull wins.';
comment on table public.fx_rates       is 'Daily numbers board: ECB reference rates as USD per unit, for non-USD rows only.';
comment on table public.owner_sessions is 'Daily numbers board: server-side owner sessions; only the token hash is stored.';
comment on column public.ledger_entries.amount_usd_cents is 'Signed USD cents. NULL until a real rate exists; never guessed.';
comment on column public.ledger_entries.fee_usd_cents    is 'Processor fee in USD cents. NULL means unknown, not zero.';
comment on column public.ledger_entries.local_day        is 'Owner calendar day in America/New_York, computed from occurred_at (or occurred_on for date-only rows).';

-- ═══ views (security_invoker: the CALLER's grants and RLS apply) ═══════════

-- Every ledger row with its final channel. A refund or dispute takes the
-- product, buyer and channel of the sale it reverses (same order_ref). A row
-- with no stored attribution gets the channel of the buyer's FIRST lead touch
-- (opt-in or reply, with a known channel) before the sale, matched on email
-- when the view is read, so a lead that syncs an hour after the sale still
-- counts. The "last click by anyone within 72 hours" guess in
-- core/click_tracker.py is deliberately not used.
create or replace view public.board_ledger with (security_invoker = true) as
select e.id, e.source_id, e.external_id, e.kind, e.occurred_at, e.occurred_on, e.local_day,
       e.amount_minor, e.currency, e.amount_usd_cents, e.fee_usd_cents, e.is_estimate,
       e.quantity, e.order_ref, e.via_platform, e.upload_id,
       coalesce(e.product, s.product)                        as product,
       coalesce(e.customer_email, s.customer_email)          as customer_email,
       coalesce(s.channel, e.channel, t.channel, 'unattributed') as channel,
       case when s.channel is not null then s.attribution
            when e.channel is not null then e.attribution
            when t.channel is not null then 'lead_email'
            else 'none' end                                  as attribution
from public.ledger_entries e
left join lateral (
  select x.product, x.customer_email, x.channel, x.attribution, x.occurred_at
  from public.ledger_entries x
  where e.kind <> 'sale' and e.order_ref is not null
    and x.source_id = e.source_id and x.order_ref = e.order_ref and x.kind = 'sale'
  order by x.occurred_at nulls last, x.id
  limit 1
) s on true
left join lateral (
  select l.channel
  from public.lead_events l
  where coalesce(e.customer_email, s.customer_email) is not null
    and l.email = coalesce(e.customer_email, s.customer_email)
    and l.occurred_at <= coalesce(s.occurred_at, e.occurred_at)
    and not l.is_auto_reply
    and l.channel <> 'unknown'
  order by l.occurred_at, l.id
  limit 1
) t on true;

-- Revenue per owner day, source and channel. Net = sales minus refunds and
-- disputes, before fees (Baremetrics' Net Revenue rule). Fees are their own
-- number. Rows without USD are left out of the sums and counted.
create or replace view public.board_revenue_daily with (security_invoker = true) as
select local_day, source_id, channel,
       count(*) filter (where kind = 'sale')                                                    as sales,
       coalesce(sum(coalesce(quantity, 1)) filter (where kind = 'sale'), 0)                     as units,
       coalesce(sum(amount_usd_cents) filter (where kind = 'sale'), 0)                          as gross_usd_cents,
       coalesce(-sum(amount_usd_cents) filter (where kind = 'refund'), 0)                       as refunds_usd_cents,
       coalesce(-sum(amount_usd_cents) filter (where kind in ('dispute','dispute_reversal')), 0) as disputes_usd_cents,
       coalesce(sum(amount_usd_cents)
                filter (where kind in ('sale','refund','dispute','dispute_reversal','adjustment')), 0) as net_usd_cents,
       coalesce(sum(fee_usd_cents), 0)
         - coalesce(sum(amount_usd_cents) filter (where kind = 'fee'), 0)                       as fees_usd_cents,
       count(*) filter (where amount_usd_cents is null)                                         as unconverted_rows,
       coalesce(bool_or(is_estimate), false)                                                    as has_estimates
from public.board_ledger
group by local_day, source_id, channel;

-- ═══ functions (called by the backend through supabase-py .rpc) ════════════

-- State of one source for one owner day:
--   not_connected  disabled, never measured, before measured_from, or (uploads) no upload covers the day
--   partial        measured, but the source has not synced past the end of the day
--   final          synced past the end of the day (in the source's own day_tz)
--   estimate       an applied upload covers the day (KDP figures are provisional)
-- The backend also reports not_connected when the source's key is not configured.
create or replace function public.board_source_state(p_source_id text, p_day date)
returns text
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  select coalesce((
    select case
      when not s.enabled then 'not_connected'
      when s.method = 'manual' then 'final'
      when s.method = 'upload' then
        case when exists (select 1 from public.source_uploads u
                           where u.source_id = s.id and u.status = 'applied'
                             and p_day between u.period_start and u.period_end)
             then 'estimate' else 'not_connected' end
      when s.measured_from is null or p_day < s.measured_from then 'not_connected'
      when s.synced_through >= ((p_day + 1)::timestamp at time zone s.day_tz) then 'final'
      else 'partial'
    end
    from public.sources s
    where s.id = p_source_id), 'not_connected')
$$;

-- The only write path for API and manual money rows. Inserts new movements;
-- for a movement already present it may only improve labels (product, buyer,
-- channel, fee when it was unknown). Money columns never change once written:
-- a re-sync that disagrees is counted in money_mismatches, and the backend
-- records it as an error on the run instead of overwriting history.
-- Money fields go in as sent, so a bad kind, sign, amount or currency fails
-- the whole batch loudly. Labels never fail it: a malformed email is dropped,
-- a malformed channel becomes 'other', and a click id this app did not issue
-- is ignored (Stripe's client_reference_id is free text anyone can set). A
-- USD row sent without a USD amount is its own USD amount ('identity').
create or replace function public.board_ingest_ledger(p_source_id text, p_job_run_id uuid, p_rows jsonb)
returns table (received int, inserted int, relabelled int, money_mismatches int)
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if not exists (select 1 from public.sources s where s.id = p_source_id and s.method in ('api','manual')) then
    raise exception 'board_ingest_ledger: % is not an API or manual source', p_source_id;
  end if;

  return query
  with parsed as (
    select distinct on (x.external_id)
           x.external_id, x.kind, x.occurred_at, x.occurred_on, x.amount_minor,
           upper(x.currency) as currency, x.amount_usd_cents, x.fee_usd_cents, x.fx_source, x.fx_rate,
           coalesce(x.is_estimate, false) as is_estimate,
           nullif(btrim(x.product), '') as product, x.quantity,
           case when lower(btrim(x.customer_email)) like '%_@_%' then lower(btrim(x.customer_email)) end
             as customer_email,
           case when nullif(btrim(x.channel), '') is null then null
                when lower(btrim(x.channel)) ~ '^[a-z0-9_]{1,32}$' then lower(btrim(x.channel))
                else 'other' end as channel,
           coalesce(x.attribution, 'none') as attribution,
           case when x.click_id ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$' then x.click_id::uuid end
             as click_id,
           x.order_ref, x.via_platform, x.source_event_id, coalesce(x.raw, '{}'::jsonb) as raw
    from jsonb_to_recordset(p_rows) as x(
           external_id text, kind text, occurred_at timestamptz, occurred_on date,
           amount_minor bigint, currency text, amount_usd_cents bigint, fee_usd_cents bigint,
           fx_source text, fx_rate numeric, is_estimate boolean, product text, quantity int,
           customer_email text, channel text, attribution text, click_id text,
           order_ref text, via_platform text, source_event_id text, raw jsonb)
    order by x.external_id
  ),
  incoming as (
    select p.external_id, p.kind, p.occurred_at, p.occurred_on, p.amount_minor, p.currency,
           case when p.amount_usd_cents is null and p.fx_source is null and p.currency = 'USD'
                then p.amount_minor else p.amount_usd_cents end as amount_usd_cents,
           case when p.amount_usd_cents is null and p.fx_source is null and p.currency = 'USD'
                then 'identity' else p.fx_source end as fx_source,
           p.fx_rate, p.fee_usd_cents, p.is_estimate, p.product, p.quantity, p.customer_email,
           case when lab.attribution = 'none' then null else p.channel end as channel,
           lab.attribution,
           k.id as click_id,
           p.order_ref, p.via_platform, p.source_event_id, p.raw
    from parsed p
    left join public.clicks k on k.id = p.click_id
    cross join lateral (
      select case when p.attribution = 'none' or p.channel is null
                    or (p.attribution = 'click_id' and k.id is null) then 'none'
                  else p.attribution end as attribution
    ) lab
  ),
  existing as (
    select e.external_id, e.kind, e.amount_minor, e.currency::text as currency, e.occurred_at, e.occurred_on
    from public.ledger_entries e
    where e.source_id = p_source_id
      and e.external_id in (select i.external_id from incoming i)
  ),
  written as (
    insert into public.ledger_entries as e
      (source_id, external_id, kind, occurred_at, occurred_on, amount_minor, currency,
       amount_usd_cents, fee_usd_cents, fx_source, fx_rate, is_estimate, product, quantity,
       customer_email, channel, attribution, click_id, order_ref, via_platform,
       source_event_id, raw, job_run_id)
    select p_source_id, i.external_id, i.kind, i.occurred_at, i.occurred_on, i.amount_minor, i.currency,
           i.amount_usd_cents, i.fee_usd_cents, i.fx_source, i.fx_rate, i.is_estimate, i.product, i.quantity,
           i.customer_email, i.channel, i.attribution, i.click_id, i.order_ref, i.via_platform,
           i.source_event_id, i.raw, p_job_run_id
    from incoming i
    on conflict (source_id, external_id) do update set
      product         = coalesce(excluded.product, e.product),
      quantity        = coalesce(excluded.quantity, e.quantity),
      customer_email  = coalesce(excluded.customer_email, e.customer_email),
      channel         = case when excluded.attribution <> 'none' then excluded.channel else e.channel end,
      attribution     = case when excluded.attribution <> 'none' then excluded.attribution else e.attribution end,
      click_id        = case when excluded.attribution <> 'none' then excluded.click_id else e.click_id end,
      order_ref       = coalesce(e.order_ref, excluded.order_ref),
      via_platform    = coalesce(excluded.via_platform, e.via_platform),
      fee_usd_cents   = coalesce(e.fee_usd_cents, excluded.fee_usd_cents),
      source_event_id = coalesce(excluded.source_event_id, e.source_event_id)
    returning e.external_id
  )
  select (select count(*) from incoming)::int,
         (select count(*) from written w where not exists (select 1 from existing x where x.external_id = w.external_id))::int,
         (select count(*) from existing)::int,
         (select count(*) from existing x join incoming i on i.external_id = x.external_id
           where (x.kind, x.amount_minor, x.currency, x.occurred_at, x.occurred_on)
                 is distinct from (i.kind, i.amount_minor, i.currency, i.occurred_at, i.occurred_on))::int;
end
$$;

-- The only write path for opt-ins and replies. The earliest time seen wins;
-- a known channel replaces 'unknown'; tags accumulate. Labels never fail the
-- batch: a malformed email is dropped and a malformed channel becomes 'other'.
create or replace function public.board_ingest_leads(p_source_id text, p_job_run_id uuid, p_rows jsonb)
returns table (received int, inserted int, relabelled int)
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if not exists (select 1 from public.sources s where s.id = p_source_id and s.method in ('api','manual')) then
    raise exception 'board_ingest_leads: % is not an API or manual source', p_source_id;
  end if;

  return query
  with incoming as (
    select distinct on (x.external_id)
           x.external_id, x.kind, x.occurred_at,
           case when lower(btrim(x.email)) like '%_@_%' then lower(btrim(x.email)) end as email,
           nullif(lower(btrim(x.funnel)), '') as funnel,
           case when nullif(btrim(x.channel), '') is null then 'unknown'
                when lower(btrim(x.channel)) ~ '^[a-z0-9_]{1,32}$' then lower(btrim(x.channel))
                else 'other' end as channel,
           x.campaign_ref,
           coalesce(array(select lower(t) from unnest(x.tags) as t), '{}'::text[]) as tags,
           coalesce(x.is_auto_reply, false) as is_auto_reply, coalesce(x.raw, '{}'::jsonb) as raw
    from jsonb_to_recordset(p_rows) as x(
           external_id text, kind text, occurred_at timestamptz, email text, funnel text,
           channel text, campaign_ref text, tags text[], is_auto_reply boolean, raw jsonb)
    order by x.external_id, x.occurred_at
  ),
  existing as (
    select l.external_id from public.lead_events l
    where l.source_id = p_source_id and l.external_id in (select i.external_id from incoming i)
  ),
  written as (
    insert into public.lead_events as l
      (source_id, external_id, kind, occurred_at, email, funnel, channel, campaign_ref,
       tags, is_auto_reply, raw, job_run_id)
    select p_source_id, i.external_id, i.kind, i.occurred_at, i.email, i.funnel, i.channel,
           i.campaign_ref, i.tags, i.is_auto_reply, i.raw, p_job_run_id
    from incoming i
    on conflict (source_id, external_id) do update set
      occurred_at   = least(l.occurred_at, excluded.occurred_at),
      channel       = case when l.channel = 'unknown' then excluded.channel else l.channel end,
      tags          = array(select distinct u from unnest(l.tags || excluded.tags) as u order by u),
      email         = coalesce(l.email, excluded.email),
      funnel        = coalesce(l.funnel, excluded.funnel),
      campaign_ref  = coalesce(l.campaign_ref, excluded.campaign_ref),
      is_auto_reply = l.is_auto_reply or excluded.is_auto_reply
    returning l.external_id
  )
  select (select count(*) from incoming)::int,
         (select count(*) from written w where not exists (select 1 from existing x where x.external_id = w.external_id))::int,
         (select count(*) from existing)::int;
end
$$;

-- Apply one parsed report file atomically. The newest upload is the truth for
-- its whole period: KDP revises estimates, and a row missing from the newer
-- file must disappear too. Rows outside the period are refused. Duplicate keys
-- inside one file are summed; one key with two currencies or two dates is
-- refused. Non-USD rows get USD from the ECB rate on or before their date (at
-- most 6 days back); with no rate, USD stays NULL and board_fill_fx() fills it
-- later. Deleting the upload removes its rows. A received upload can be
-- applied, and so can a failed one once the parser is fixed: the kept bytes
-- are parsed again, with no new upload.
create or replace function public.board_apply_upload(p_upload_id uuid, p_rows jsonb)
returns int
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  u   public.source_uploads%rowtype;
  v_n int;
begin
  select * into u from public.source_uploads where id = p_upload_id for update;
  if not found then
    raise exception 'board_apply_upload: upload % not found', p_upload_id;
  end if;
  if not exists (select 1 from public.sources s where s.id = u.source_id and s.method = 'upload') then
    raise exception 'board_apply_upload: % is not an upload source', u.source_id;
  end if;
  if u.status not in ('received','failed') then
    raise exception 'board_apply_upload: upload % is %, only a received or failed upload can be applied',
      p_upload_id, u.status;
  end if;
  if u.period_start is null or u.period_end is null then
    raise exception 'board_apply_upload: upload % has no period', p_upload_id;
  end if;
  -- one apply per source at a time
  perform pg_advisory_xact_lock(hashtextextended('board_apply_upload:' || u.source_id, 0));
  if exists (select 1 from jsonb_to_recordset(p_rows) as r(occurred_on date)
              where r.occurred_on is null or r.occurred_on not between u.period_start and u.period_end) then
    raise exception 'board_apply_upload: upload % has rows outside % to %', p_upload_id, u.period_start, u.period_end;
  end if;
  if exists (select 1 from jsonb_to_recordset(p_rows) as r(external_id text, occurred_on date, currency text)
              group by r.external_id
             having count(distinct upper(r.currency)) > 1 or count(distinct r.occurred_on) > 1) then
    raise exception 'board_apply_upload: upload % has a key with two currencies or two dates', p_upload_id;
  end if;

  delete from public.ledger_entries e
   where e.source_id = u.source_id
     and e.local_day between u.period_start and u.period_end;

  insert into public.ledger_entries
    (source_id, external_id, kind, occurred_on, amount_minor, currency, amount_usd_cents,
     fx_source, fx_rate, fee_usd_cents, is_estimate, product, quantity, upload_id, raw)
  select u.source_id, g.external_id,
         case when g.amount_minor < 0 then 'refund' else 'sale' end,
         g.occurred_on, g.amount_minor, g.currency,
         case when g.currency = 'USD' then g.amount_minor
              when fx.usd_per_unit is not null then
                round(g.amount_minor::numeric / (10::numeric ^ public.board_currency_exponent(g.currency))
                      * fx.usd_per_unit * 100)::bigint
         end,
         case when g.currency = 'USD' then 'identity' when fx.usd_per_unit is not null then 'ecb' end,
         case when g.currency <> 'USD' then fx.usd_per_unit end,
         0,              -- a KDP royalty is already net of Amazon's share: no processor fee
         true,
         g.product, g.quantity, u.id, g.raw
  from (
    select r.external_id,
           min(r.occurred_on)                  as occurred_on,
           upper(min(r.currency))              as currency,
           sum(r.amount_minor)::bigint         as amount_minor,
           sum(coalesce(r.quantity, 0))::int   as quantity,
           max(r.product)                      as product,
           coalesce((array_agg(r.raw))[1], '{}'::jsonb) as raw
    from jsonb_to_recordset(p_rows) as r(external_id text, occurred_on date, amount_minor bigint,
                                          currency text, product text, quantity int, raw jsonb)
    group by r.external_id
  ) g
  left join lateral (
    select f.usd_per_unit
    from public.fx_rates f
    where f.currency = g.currency and f.day <= g.occurred_on and f.day > g.occurred_on - 7
    order by f.day desc
    limit 1
  ) fx on g.currency <> 'USD';
  get diagnostics v_n = row_count;

  update public.source_uploads
     set status = 'applied', applied_at = now(), rows_parsed = v_n, error = null
   where id = p_upload_id;

  -- older uploads whose whole period this one covers no longer count
  update public.source_uploads o
     set status = 'superseded'
   where o.source_id = u.source_id and o.id <> u.id and o.status = 'applied'
     and o.period_start >= u.period_start and o.period_end <= u.period_end;

  update public.sources
     set last_ok_at = now(), last_error = null, last_error_at = null
   where id = u.source_id;

  return v_n;
end
$$;

-- Fill USD for rows still missing it, from the ECB rate on or before their day
-- (at most 6 days back: weekends and TARGET holidays). Stripe rows are never
-- converted here: their USD comes from Stripe's balance transaction or not at all.
create or replace function public.board_fill_fx()
returns int
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  n_ledger int;
  n_spend  int;
begin
  update public.ledger_entries e
     set amount_usd_cents = round(e.amount_minor::numeric
                                  / (10::numeric ^ public.board_currency_exponent(e.currency))
                                  * m.rate * 100)::bigint,
         fx_source = 'ecb',
         fx_rate   = m.rate
    from (select x.id,
                 (select f.usd_per_unit from public.fx_rates f
                   where f.currency = x.currency and f.day <= x.local_day and f.day > x.local_day - 7
                   order by f.day desc limit 1) as rate
            from public.ledger_entries x
            join public.sources s on s.id = x.source_id and s.kind <> 'stripe'
           where x.amount_usd_cents is null and x.currency <> 'USD') m
   where m.id = e.id and m.rate is not null;
  get diagnostics n_ledger = row_count;

  update public.ad_spend_daily a
     set spend_usd_cents = round(a.spend_minor::numeric
                                 / (10::numeric ^ public.board_currency_exponent(a.currency))
                                 * m.rate * 100)::bigint,
         fx_source = 'ecb',
         fx_rate   = m.rate
    from (select x.id,
                 (select f.usd_per_unit from public.fx_rates f
                   where f.currency = x.currency and f.day <= x.day and f.day > x.day - 7
                   order by f.day desc limit 1) as rate
            from public.ad_spend_daily x
           where x.spend_usd_cents is null and x.currency <> 'USD') m
   where m.id = a.id and m.rate is not null;
  get diagnostics n_spend = row_count;

  return n_ledger + n_spend;
end
$$;

-- Claim a run of one job: the start of every sync, upload apply, import and
-- report send. Returns the job_runs id to work under, or NULL when there is
-- nothing to do now: that key already finished (ok or skipped), or another run
-- of the job is in progress (one running run per job). A 'failed' run with the
-- same key is claimed again, attempts + 1: that is how the morning report
-- retries a channel without ever sending it twice. A run left 'running' for 30
-- minutes (a container that died mid-run) is marked failed first, so it can be
-- retried. The caller finishes the row: status ok, failed or skipped, and
-- finished_at.
create or replace function public.board_claim_run(p_job text, p_run_key text,
                                                  p_trigger_kind text default 'schedule',
                                                  p_source_id text default null)
returns uuid
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
begin
  update public.job_runs
     set status = 'failed', finished_at = now(),
         error = coalesce(error, 'abandoned: still running after 30 minutes')
   where job = p_job and status = 'running' and started_at < now() - interval '30 minutes';

  begin
    insert into public.job_runs (job, run_key, trigger_kind, source_id)
    values (p_job, p_run_key, p_trigger_kind, p_source_id)
    on conflict (job, run_key) do nothing
    returning id into v_id;

    if v_id is null then
      update public.job_runs
         set status = 'running', started_at = now(), finished_at = null, error = null,
             trigger_kind = p_trigger_kind, attempts = attempts + 1
       where job = p_job and run_key = p_run_key and status = 'failed'
      returning id into v_id;
    end if;
  exception when unique_violation then
    v_id := null;   -- another run of this job is in progress (job_runs_one_running_uq)
  end;
  return v_id;
end
$$;

-- Claim one provider event for the webhook receiver (Stripe in Phase 1):
--   'run'   new, or an earlier delivery failed or died mid-way (received more
--           than 10 minutes ago): run the side effects, then mark the row
--           processed (answer 200) or failed (answer 500, so Stripe retries)
--   'busy'  another delivery of this event is running right now: answer 409,
--           so Stripe retries later instead of the side effects running twice
--   'done'  processed or ignored already: answer 200 and stop
-- Test-mode events (livemode false) are stored as ignored and answer 'done'.
create or replace function public.board_claim_webhook(p_source_id text, p_event_id text,
                                                      p_event_type text, p_livemode boolean)
returns text
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_status text;
begin
  insert into public.webhook_events (source_id, event_id, event_type, livemode, status)
  values (p_source_id, p_event_id, p_event_type, p_livemode,
          case when p_livemode is false then 'ignored' else 'received' end)
  on conflict (source_id, event_id) do nothing
  returning status into v_status;
  if v_status is not null then
    return case when v_status = 'ignored' then 'done' else 'run' end;
  end if;

  update public.webhook_events
     set status = 'received', attempts = attempts + 1, error = null, received_at = now()
   where source_id = p_source_id and event_id = p_event_id
     and (status = 'failed' or (status = 'received' and received_at < now() - interval '10 minutes'))
  returning status into v_status;
  if v_status is not null then
    return 'run';
  end if;

  select w.status into v_status
    from public.webhook_events w
   where w.source_id = p_source_id and w.event_id = p_event_id;
  return case when v_status = 'received' then 'busy' else 'done' end;
end
$$;

-- The plan's stop rule (marketing/GLOBAL_PLAN.md:128): stop if CPL > $5 after
-- 5 days of spend. Window = the last p_days days with Toodle campaign spend,
-- within p_lookback_days of p_day. CPL = that spend / Toodle opt-ins tagged
-- meta on those days, not Meta's own lead count. Verdicts:
--   no_spend        no Toodle spend in the lookback
--   check_currency  some spend has no USD yet
--   collecting      fewer than p_days spend days so far
--   check_tags      Toodle opt-ins arrived but none is tagged meta (tagging is broken; not a false stop)
--   stop            CPL above the threshold, or no Meta opt-in while spend passed the threshold
--   ok              otherwise
create or replace function public.board_cpl(p_day date, p_days int default 5,
                                            p_stop_cents int default 500, p_lookback_days int default 30)
returns table (spend_days int, first_day date, last_day date, spend_usd_cents bigint,
               unconverted_spend_rows bigint, meta_optins bigint, toodle_optins bigint,
               cpl_meta_usd_cents bigint, cpl_all_usd_cents bigint, stop_above_cents int, verdict text)
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  with sd as (
    select a.day,
           sum(a.spend_usd_cents)                             as spend,
           count(*) filter (where a.spend_usd_cents is null)  as unconverted
    from public.ad_spend_daily a
    where a.funnel = 'toodle'
      and a.day between p_day - (p_lookback_days - 1) and p_day
    group by a.day
    having sum(a.spend_minor) > 0
    order by a.day desc
    limit p_days
  ),
  t as (
    select count(*)::int                        as spend_days,
           min(sd.day)                          as first_day,
           max(sd.day)                          as last_day,
           coalesce(sum(sd.spend), 0)::bigint   as spend,
           coalesce(sum(sd.unconverted), 0)::bigint as unconverted
    from sd
  ),
  ld as (
    select count(*) filter (where l.channel = 'meta') as meta_optins,
           count(*)                                   as toodle_optins
    from public.lead_events l
    where l.kind = 'optin' and l.funnel = 'toodle'
      and l.local_day in (select sd.day from sd)
  )
  select t.spend_days, t.first_day, t.last_day, t.spend, t.unconverted,
         ld.meta_optins, ld.toodle_optins,
         case when ld.meta_optins > 0   then round(t.spend::numeric / ld.meta_optins)::bigint end,
         case when ld.toodle_optins > 0 then round(t.spend::numeric / ld.toodle_optins)::bigint end,
         p_stop_cents,
         case when t.spend_days = 0                                        then 'no_spend'
              when t.unconverted > 0                                       then 'check_currency'
              when t.spend_days < p_days                                   then 'collecting'
              when ld.meta_optins = 0 and ld.toodle_optins > 0             then 'check_tags'
              when ld.meta_optins = 0 and t.spend > p_stop_cents           then 'stop'
              when ld.meta_optins = 0                                      then 'collecting'
              when t.spend::numeric / ld.meta_optins > p_stop_cents        then 'stop'
              else 'ok' end
  from t, ld
$$;

-- Everything the board and the morning report need for one owner day, in one
-- round trip. p_day NULL = yesterday in America/New_York. Buyer emails leave
-- the database masked. Whether a number is "not connected" is decided from the
-- 'sources' block (null, never a fake 0); the backend adds key configuration.
create or replace function public.board_day(p_day date default null,
                                            p_cpl_days int default 5,
                                            p_cpl_stop_cents int default 500)
returns jsonb
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  with d as (
    select coalesce(p_day, (now() at time zone 'America/New_York')::date - 1) as day
  ),
  b as (
    select d.day,
           (d.day::timestamp       at time zone 'America/New_York') as starts_at,
           ((d.day + 1)::timestamp at time zone 'America/New_York') as ends_at
    from d
  ),
  led as (
    select x.* from public.board_ledger x join b on x.local_day = b.day
  ),
  money as (
    select x.* from led x where x.kind in ('sale','refund','dispute','dispute_reversal','adjustment')
  )
  select jsonb_build_object(
    'day',          b.day,
    'tz',           'America/New_York',
    'starts_at',    b.starts_at,
    'ends_at',      b.ends_at,
    'hours_in_day', (extract(epoch from (b.ends_at - b.starts_at)) / 3600)::int,
    'sources',      (select coalesce(jsonb_agg(jsonb_build_object(
                        'id', s.id, 'kind', s.kind, 'method', s.method, 'name', s.display_name,
                        'state', public.board_source_state(s.id, b.day),
                        'day_tz', s.day_tz, 'measured_from', s.measured_from,
                        'synced_through', s.synced_through, 'last_ok_at', s.last_ok_at,
                        'last_error', left(s.last_error, 300), 'last_error_at', s.last_error_at)
                        order by s.id), '[]'::jsonb)
                       from public.sources s),
    'revenue',      (select jsonb_build_object(
                        'net_usd_cents',        coalesce(sum(m.amount_usd_cents), 0),
                        'gross_usd_cents',      coalesce(sum(m.amount_usd_cents) filter (where m.kind = 'sale'), 0),
                        'refunds_usd_cents',    coalesce(-sum(m.amount_usd_cents) filter (where m.kind = 'refund'), 0),
                        'disputes_usd_cents',   coalesce(-sum(m.amount_usd_cents)
                                                  filter (where m.kind in ('dispute','dispute_reversal')), 0),
                        'attributed_usd_cents', coalesce(sum(m.amount_usd_cents) filter (where m.channel <> 'unattributed'), 0),
                        'unconverted_rows',     count(*) filter (where m.amount_usd_cents is null),
                        'has_estimates',        coalesce(bool_or(m.is_estimate), false))
                       from money m),
    'fees',         (select jsonb_build_object(
                        'fees_usd_cents',   coalesce(sum(x.fee_usd_cents), 0)
                                              - coalesce(sum(x.amount_usd_cents) filter (where x.kind = 'fee'), 0),
                        'unknown_fee_rows', count(*) filter (where x.fee_usd_cents is null and x.kind in ('sale','refund')))
                       from led x),
    'by_source',    (select coalesce(jsonb_object_agg(g.source_id, g.net), '{}'::jsonb)
                       from (select m.source_id, coalesce(sum(m.amount_usd_cents), 0) as net
                               from money m group by m.source_id) g),
    'by_channel',   (select coalesce(jsonb_object_agg(g.channel, g.net), '{}'::jsonb)
                       from (select m.channel, coalesce(sum(m.amount_usd_cents), 0) as net
                               from money m group by m.channel) g),
    'products',     (select coalesce(jsonb_agg(to_jsonb(p) order by p.net_usd_cents desc, p.product), '[]'::jsonb)
                       from (select m.source_id, coalesce(m.product, '(no product name)') as product,
                                    count(*) filter (where m.kind = 'sale') as sales,
                                    coalesce(sum(coalesce(m.quantity, 1)) filter (where m.kind = 'sale'), 0) as units,
                                    coalesce(sum(m.amount_usd_cents), 0) as net_usd_cents,
                                    coalesce(bool_or(m.is_estimate), false) as estimate
                               from money m
                              group by m.source_id, coalesce(m.product, '(no product name)')) p),
    'sales',        (select coalesce(jsonb_agg(jsonb_build_object(
                        'at', m.occurred_at, 'on', m.occurred_on, 'source', m.source_id, 'kind', m.kind,
                        'product', m.product, 'amount_minor', m.amount_minor, 'currency', m.currency,
                        'amount_usd_cents', m.amount_usd_cents, 'channel', m.channel,
                        'attribution', m.attribution, 'estimate', m.is_estimate, 'via', m.via_platform,
                        'buyer', case when m.customer_email is null then null
                                      else left(m.customer_email, 1) || '***'
                                           || substr(m.customer_email, strpos(m.customer_email, '@')) end)
                        order by m.occurred_at nulls last, m.source_id, m.external_id), '[]'::jsonb)
                       from money m),
    'optins',       (select jsonb_build_object(
                        'total', count(*),
                        'by_channel', coalesce((select jsonb_object_agg(c.channel, c.n)
                                                  from (select l2.channel, count(*) as n
                                                          from public.lead_events l2
                                                         where l2.kind = 'optin' and l2.funnel = 'toodle'
                                                           and l2.local_day = b.day
                                                         group by l2.channel) c), '{}'::jsonb))
                       from public.lead_events l
                      where l.kind = 'optin' and l.funnel = 'toodle' and l.local_day = b.day),
    'replies',      (select jsonb_build_object(
                        'people',       count(distinct coalesce(l.email, l.external_id))
                                          filter (where not l.is_auto_reply and l.local_day = b.day),
                        'auto_replies', count(*) filter (where l.is_auto_reply and l.local_day = b.day),
                        'people_7d',    count(distinct coalesce(l.email, l.external_id))
                                          filter (where not l.is_auto_reply))
                       from public.lead_events l
                      where l.kind = 'reply' and l.funnel = 'siteboost'
                        and l.local_day between b.day - 6 and b.day),
    'spend',        (select jsonb_build_object(
                        'toodle_usd_cents',   coalesce(sum(a.spend_usd_cents) filter (where a.funnel = 'toodle'), 0),
                        'all_usd_cents',      coalesce(sum(a.spend_usd_cents), 0),
                        'toodle_link_clicks', coalesce(sum(a.link_clicks) filter (where a.funnel = 'toodle'), 0),
                        'impressions',        coalesce(sum(a.impressions), 0),
                        'unconverted_rows',   count(*) filter (where a.spend_usd_cents is null),
                        'last_pulled_at',     max(a.pulled_at))
                       from public.ad_spend_daily a
                      where a.day = b.day),
    'cpl',          (select to_jsonb(c) from public.board_cpl(b.day, p_cpl_days, p_cpl_stop_cents) c),
    'kdp',          jsonb_build_object(
                      'covers_day', exists (select 1 from public.source_uploads u
                                             where u.source_id = 'kdp' and u.status = 'applied'
                                               and b.day between u.period_start and u.period_end),
                      'recent_uploads', (select coalesce(jsonb_agg(jsonb_build_object(
                                            'id', u.id, 'file', u.file_name, 'status', u.status,
                                            'from', u.period_start, 'to', u.period_end,
                                            'rows', u.rows_parsed, 'uploaded_at', u.uploaded_at)
                                            order by u.uploaded_at desc), '[]'::jsonb)
                                           from (select * from public.source_uploads
                                                  where source_id = 'kdp'
                                                  order by uploaded_at desc limit 5) u))
  )
  from b
$$;

comment on function public.board_ingest_ledger(text, uuid, jsonb) is 'Daily numbers board: write path for API and manual money rows. Money is written once; labels may improve.';
comment on function public.board_apply_upload(uuid, jsonb)       is 'Daily numbers board: apply a parsed report file; the newest upload replaces its whole period.';
comment on function public.board_cpl(date, int, int, int)         is 'Daily numbers board: the plan''s CPL stop rule over the last N days with Toodle spend.';
comment on function public.board_day(date, int, int)              is 'Daily numbers board: one owner day as JSON (yesterday in America/New_York when NULL).';
comment on function public.board_claim_run(text, text, text, text) is 'Daily numbers board: claim a job run; NULL = already done or busy. A failed run with the same key is claimed again.';
comment on function public.board_claim_webhook(text, text, text, boolean) is 'Daily numbers board: claim a provider event: run, busy (retry later) or done.';

-- ═══ access: server only ═══════════════════════════════════════════════════
do $$
declare t text;
begin
  foreach t in array array['sources','job_runs','webhook_events','clicks','source_uploads',
                           'ledger_entries','lead_events','ad_spend_daily','fx_rates','owner_sessions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from anon, authenticated', t);
    execute format('grant select, insert, update, delete on table public.%I to service_role', t);
  end loop;
end
$$;

revoke all on table public.board_ledger, public.board_revenue_daily from anon, authenticated;
grant select on table public.board_ledger, public.board_revenue_daily to service_role;

revoke execute on function
  public.board_touch_updated_at(),
  public.board_currency_exponent(text),
  public.board_source_state(text, date),
  public.board_ingest_ledger(text, uuid, jsonb),
  public.board_ingest_leads(text, uuid, jsonb),
  public.board_apply_upload(uuid, jsonb),
  public.board_fill_fx(),
  public.board_cpl(date, int, int, int),
  public.board_day(date, int, int),
  public.board_claim_run(text, text, text, text),
  public.board_claim_webhook(text, text, text, boolean)
from public, anon, authenticated;

grant execute on function
  public.board_currency_exponent(text),
  public.board_source_state(text, date),
  public.board_ingest_ledger(text, uuid, jsonb),
  public.board_ingest_leads(text, uuid, jsonb),
  public.board_apply_upload(uuid, jsonb),
  public.board_fill_fx(),
  public.board_cpl(date, int, int, int),
  public.board_day(date, int, int),
  public.board_claim_run(text, text, text, text),
  public.board_claim_webhook(text, text, text, boolean)
to service_role;

-- ═══ seed: the Phase 1 connectors (also the wrong-key probe) ═══════════════
insert into public.sources (id, kind, method, display_name) values
  ('stripe',    'stripe',    'api',    'Stripe'),
  ('kit',       'kit',       'api',    'Kit (Toodle opt-ins)'),
  ('instantly', 'instantly', 'api',    'Instantly (SiteBoost replies)'),
  ('meta_ads',  'meta_ads',  'api',    'Meta Ads'),
  ('kdp',       'kdp',       'upload', 'Amazon KDP (report upload)'),
  ('manual',    'manual',    'manual', 'Manual entries')
on conflict (id) do nothing;

commit;
