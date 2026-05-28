# 0008 — Path X: align Stage 6 auth to Supabase Auth

Date: 2026-05-28
Status: locked
Supersedes: 0007's self-managed JWT user-auth path (cookies / rate limits /
security headers from 0007 are preserved unchanged).

## Root cause

Stage 6 (decision log 0007) reinvented self-managed JWT auth against a
`public.users` table that does not exist in production. The prod schema is
canonical Supabase: `auth.users` (Supabase-managed) is the identity table,
the `on_auth_user_created → handle_new_user()` trigger mirrors rows into
`public.profiles`, and every app table FKs to `profiles.id`.

Stage 6's `/auth/signup` would have crashed with `relation "users" does not
exist` on the first prod call. The 29 conversations + 98 messages from
NarAI v1 work because *they* used Supabase Auth — Stage 6 never did. The
local tests passed only because conftest fabricated a `public.users` table
via `Base.metadata.create_all()`. That fabrication is exactly what hid the
bug.

## Investigation findings (STEP 1)

- JWT signing: ASYMMETRIC. JWKS endpoint returns one EC P-256 key (alg=ES256).
- supabase-py: 2.30.0, already installed.
- Trigger `handle_new_user` reads `raw_user_meta_data->>'full_name'` for
  `profiles.name`; falls back to email local-part.
- RLS enabled on all 6 chat-tier tables; backend connects as `postgres`
  superuser so it bypasses RLS (backend is the security boundary).
- Self-managed-auth surface: 13 files referenced the fiction (User model,
  bcrypt, JWT_SECRET_KEY, decode_token, create_*_token).
- `dependencies/admin.py` reused `JWT_SECRET_KEY` as a shared admin-API
  token (unrelated to user auth). Renamed via new `ADMIN_TOKEN` env var
  with `JWT_SECRET_KEY` as fallback so existing deployments don't break.

## Fix

| Surface | Change |
|---|---|
| Signup | `supabase.auth.admin.create_user()` via service-role; trigger creates profile row. Auto-login after for cookie issuance. |
| Login | Password grant proxied via publishable key. |
| Refresh | refresh_token grant, cookie-first with JSON-body fallback. |
| JWT validation | `PyJWKClient` against the project's JWKS endpoint; ES256 only. Audience `authenticated`. |
| User model | Deleted. `Profile` SQLAlchemy mapper added — matches prod profiles schema. |
| `app/core/security.py` | Deleted entirely (bcrypt + jose-based encode/decode). |
| FK targets | `subscriptions.user_id`, `alerts.user_id`, `watchlists.user_id`, `usage_log.user_id` repointed to `profiles.id`. |
| Identity in routers | `UserPrincipal` (frozen dataclass with id/email/role from JWT claims). Aliased as `User` in nai/predictions where only `.id` is used; billing imports `UserPrincipal` directly + loads `Profile` rows for `stripe_customer_id`. |
| conftest | No longer fabricates `public.users`. Adds `fake_supabase_auth` autouse fixture (in-memory user store + HS256 tokens) + patches `decode_supabase_jwt` to HS256 verification in tests. Tests now exercise real `profiles`-keyed identity. |
| Cookies / rate limits / security headers / UI | Unchanged. |

## Proof — 155 tests PASS

- `tests/test_auth.py` rewritten for Path X: 16/16 PASS.
- `tests/test_cookie_auth.py`: 13/13 PASS.
- `tests/test_auth_rate_limit.py`: 3/3 PASS.
- `tests/test_security_headers.py`: 13/13 PASS.
- `tests/test_billing.py`: refactored to read `stripe_customer_id` from `profiles` directly; 13/13 PASS.
- `tests/test_brain.py`: 5/5 PASS.
- All other suites: 89 PASS.

Stage 6 verifier: 49 PASS (was 39). All-stage sweep: 0 real FAILs; 1 expected
DEFER (Stage 3 smoke safety-gate vs prod DATABASE_URL).

## Security notes

- `SUPABASE_SECRET_KEY` (god key) is backend-only, `backend/.env` mode 0600,
  never logged or sent to the frontend. The actual secret was pasted in the
  conversation transcript while configuring — **operator must rotate** via
  Supabase dashboard as next step.
- Password grant uses publishable key, not service-role — service-role login
  would be an auth bypass.
- JWT validation is signature-verified: ES256 against JWKS, audience
  `authenticated`, strict exp/iat (no leeway).
- CSP unchanged: still strict (`script-src 'self'`, no `unsafe-inline`).

## Reversible?

- Restore self-managed auth: yes, but `User` model + `core/security.py`
  would need restoring from git history and FK changes reverted.
- Switch JWT validation to HS256 shared secret: yes, single function
  rewrite in `supabase_jwt.py`.

## Out of scope

- Email verification + password reset UX (Supabase supports both; wire the
  frontend later).
- Real-Supabase smoke test (writes to prod `auth.users`; runs operator-side
  after secret rotation).
- Multi-worker rate-limit storage (slowapi in-memory; Redis when workers > 1).
