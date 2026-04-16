-- ─────────────────────────────────────────────────────────────────────────────
-- WheellsVerse / NarAI — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query → Run
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- ─── USERS ───────────────────────────────────────────────────────────────────
-- Extends Supabase auth.users with profile + tier info
create table if not exists public.profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  email         text unique not null,
  name          text,
  avatar_url    text,
  tier          text not null default 'free'
                  check (tier in ('free', 'pro', 'max', 'ultra')),
  messages_used_today  int not null default 0,
  last_reset_date      date not null default current_date,
  stripe_customer_id   text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ─── SUBSCRIPTIONS ───────────────────────────────────────────────────────────
create table if not exists public.subscriptions (
  id                     uuid primary key default uuid_generate_v4(),
  user_id                uuid not null references public.profiles(id) on delete cascade,
  tier                   text not null check (tier in ('pro', 'max', 'ultra')),
  stripe_subscription_id text unique,
  stripe_price_id        text,
  status                 text not null default 'active'
                           check (status in ('active', 'canceled', 'past_due', 'trialing')),
  current_period_start   timestamptz,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

-- ─── CONVERSATIONS ───────────────────────────────────────────────────────────
create table if not exists public.conversations (
  id          uuid primary key default uuid_generate_v4(),
  user_id     uuid not null references public.profiles(id) on delete cascade,
  title       text not null default 'New Chat',
  model_used  text,
  message_count int not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- ─── MESSAGES ────────────────────────────────────────────────────────────────
create table if not exists public.messages (
  id              uuid primary key default uuid_generate_v4(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id         uuid not null references public.profiles(id) on delete cascade,
  role            text not null check (role in ('user', 'assistant', 'system')),
  content         text not null,
  model_used      text,
  tokens_used     int,
  created_at      timestamptz not null default now()
);

-- ─── MEMORY NOTES ────────────────────────────────────────────────────────────
-- NarAI remembers facts about each user across all conversations
create table if not exists public.memory_notes (
  id                    uuid primary key default uuid_generate_v4(),
  user_id               uuid not null references public.profiles(id) on delete cascade,
  fact                  text not null,
  category              text default 'general'
                          check (category in ('general', 'preference', 'goal', 'identity', 'project')),
  source_conversation_id uuid references public.conversations(id) on delete set null,
  created_at            timestamptz not null default now()
);

-- ─── INDEXES ─────────────────────────────────────────────────────────────────
create index if not exists idx_conversations_user_id on public.conversations(user_id);
create index if not exists idx_conversations_updated on public.conversations(updated_at desc);
create index if not exists idx_messages_conversation_id on public.messages(conversation_id);
create index if not exists idx_messages_created on public.messages(created_at asc);
create index if not exists idx_memory_notes_user_id on public.memory_notes(user_id);

-- ─── ROW LEVEL SECURITY ──────────────────────────────────────────────────────
alter table public.profiles enable row level security;
alter table public.subscriptions enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.memory_notes enable row level security;

-- Profiles: users can only see/edit their own
create policy "profiles: own row" on public.profiles
  for all using (auth.uid() = id);

-- Subscriptions: users can only see their own
create policy "subscriptions: own row" on public.subscriptions
  for all using (auth.uid() = user_id);

-- Conversations: users can only see their own
create policy "conversations: own rows" on public.conversations
  for all using (auth.uid() = user_id);

-- Messages: users can only see messages in their conversations
create policy "messages: own rows" on public.messages
  for all using (auth.uid() = user_id);

-- Memory notes: users can only see their own
create policy "memory: own rows" on public.memory_notes
  for all using (auth.uid() = user_id);

-- ─── SERVICE ROLE BYPASS (for FastAPI backend) ───────────────────────────────
-- The FastAPI backend uses the service_role key which bypasses RLS by default.
-- No additional policy needed — service_role has full access.

-- ─── AUTO-CREATE PROFILE ON SIGNUP ──────────────────────────────────────────
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (id, email, name, avatar_url)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    new.raw_user_meta_data->>'avatar_url'
  );
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ─── AUTO-RESET DAILY MESSAGE COUNT ─────────────────────────────────────────
create or replace function public.reset_daily_messages()
returns void language plpgsql as $$
begin
  update public.profiles
  set messages_used_today = 0,
      last_reset_date = current_date
  where last_reset_date < current_date;
end;
$$;

-- ─── DONE ────────────────────────────────────────────────────────────────────
-- After running this:
-- 1. Go to Supabase → Settings → API
-- 2. Copy: Project URL, anon public key, service_role secret key
-- 3. Add to Railway environment variables:
--    SUPABASE_URL=https://xxxx.supabase.co
--    SUPABASE_ANON_KEY=eyJ...
--    SUPABASE_SERVICE_KEY=eyJ...
