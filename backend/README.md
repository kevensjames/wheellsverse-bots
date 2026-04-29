# Wheellsverse Backend

FastAPI + PostgreSQL backend for Wheellsverse Trade.

## One-time setup

```bash
cd backend

# Virtualenv (keep it inside backend/ so it's isolated from the parent repo's venvs)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Dependencies
pip install -r requirements.txt

# Env file
cp .env.example .env
# Generate a JWT secret and paste it into .env as JWT_SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Database

Requires Postgres running locally.

**Option A — Homebrew:**
```bash
brew install postgresql@16
brew services start postgresql@16
createdb wheellsverse_dev
```

**Option B — Docker:**
```bash
docker run --name wv-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:16
docker exec -it wv-pg createdb -U postgres wheellsverse_dev
```

## Migrations

```bash
alembic upgrade head      # apply all migrations
alembic downgrade base    # roll everything back
```

## Seed data

```bash
python -m scripts.seed_plans
python -m scripts.seed_assets
```

Both scripts are idempotent.

## Run the server

```bash
uvicorn app.main:app --reload
```

Health check: `curl http://localhost:8000/health`

## Running tests

Tests need a dedicated Postgres database (they truncate everything between tests).

```bash
createdb wheellsverse_test
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/wheellsverse_test"
pytest -v
```

`TEST_DATABASE_URL` defaults to the same URL shown above if you don't export it. The test suite:

- Creates the `pgcrypto` extension and all tables at session start (via `Base.metadata.create_all`, not Alembic)
- Truncates every table with `RESTART IDENTITY CASCADE` before each test
- Drops all tables at session end

## Smoke test

After `uvicorn app.main:app --reload` is running in another terminal:

```bash
python -m scripts.smoke_test_auth
```

Exits 0 on success, 1 on auth failure, 2 if the server isn't reachable.

## Market data ingestion (Stage 3)

Three ways to drive it:

### 1. One-shot CLI (no workers or Redis needed)

```bash
python -m scripts.ingest_once --all
python -m scripts.ingest_once --symbol AAPL --lookback-days 7
python -m scripts.ingest_once --symbol BTC-USD    # crypto trades 24/7; safest choice
```

### 2. Celery worker + beat (scheduled every 15 min)

Requires Redis: `redis-cli ping` must return `PONG`. If you don't have it:

```bash
brew install redis && brew services start redis         # Homebrew
# OR
docker run --name wv-redis -p 6379:6379 -d redis:7-alpine
```

Then three terminals:

```bash
# Terminal 1 — API
uvicorn app.main:app --reload

# Terminal 2 — Celery worker
celery -A app.workers.celery_app worker --loglevel=info

# Terminal 3 — Celery beat (scheduler)
celery -A app.workers.celery_app beat --loglevel=info
```

### 3. Admin API (manual trigger)

Temporary admin auth: `X-Admin-Token` header equal to `JWT_SECRET_KEY` (Stage 11 replaces this).

```bash
# trigger full ingest
curl -X POST http://localhost:8000/admin/ingest/all \
  -H "X-Admin-Token: $JWT_SECRET_KEY"

# one symbol
curl -X POST http://localhost:8000/admin/ingest/AAPL \
  -H "X-Admin-Token: $JWT_SECRET_KEY"

# check task status
curl http://localhost:8000/admin/ingest/status/<task_id> \
  -H "X-Admin-Token: $JWT_SECRET_KEY"
```

## Predictions (Stage 4)

Rule-based BUY/SELL/HOLD engine using RSI + MACD crossover + SMA crossover. Different thresholds per asset class — see `app/ml/predictor_config.py`.

### Scheduled (Celery beat)

Runs every `STOCK_PREDICTION_INTERVAL_MINUTES` / `CRYPTO_PREDICTION_INTERVAL_MINUTES` (default 60). Each run writes one prediction row per active asset.

### Manual trigger

```bash
# CLI — synchronous, no worker needed
python -m scripts.predict_once --all
python -m scripts.predict_once --stocks
python -m scripts.predict_once --crypto
python -m scripts.predict_once --symbol BTC-USD

# Admin API
curl -X POST http://localhost:8000/admin/predict/all \
  -H "X-Admin-Token: $JWT_SECRET_KEY"
curl -X POST http://localhost:8000/admin/predict/AAPL \
  -H "X-Admin-Token: $JWT_SECRET_KEY"
```

### User-facing API

```bash
# Public — feeds the landing page "live proof" block. Cached 5 min in Redis.
curl http://localhost:8000/predictions/stats

# Authenticated — latest prediction per asset (today)
curl http://localhost:8000/predictions/today \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Authenticated — historical predictions for one asset
curl http://localhost:8000/predictions/AAPL \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Free-tier users get `plans.predictions_per_day` calls to `/today` and `/{symbol}` per day (default 3). After that: `402 Payment Required`. Usage is tracked in `usage_log`.

### Known limits of rules-v1

- No backtesting / historical win-rate reporting yet (prediction rows have `actual_outcome=null` until Stage 5 adds outcome tracking).
- Rules don't learn — Stage 8 replaces this with an LSTM trained per asset class.
- No regime detection (bull vs bear). Same thresholds run in all conditions.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `yfinance returns empty DataFrame` | Market closed (weekend / after-hours). Test with `BTC-USD` instead. |
| `No module named 'app.workers'` when starting celery | Run from `backend/` with venv active. |
| Worker starts but never picks up tasks | Broker URL mismatch between API and worker — both read `settings.CELERY_BROKER_URL`. |
| `Too Many Requests` from Yahoo | Bump `YFINANCE_REQUEST_DELAY_SECONDS` to 1.0 or 2.0; or switch to Alpha Vantage. |
| `crontab is not defined` | Already imported in `workers/celery_app.py`. If you're editing that file, keep the import. |

## Billing (Stage 5)

Stripe Checkout + webhook integration. Free-tier users that hit their daily limit get a `402` with `detail.upgrade_url` pointing at the dashboard's `/pricing` page.

### One-time setup

1. **Create test-mode keys.** [stripe.com](https://dashboard.stripe.com/test/apikeys) → Developers → API keys → copy the **Secret key** (`sk_test_...`).

2. **Create Products + Prices** in the Stripe dashboard (test mode):
   - `Pro` — $19/month recurring → copy the **Price ID** (`price_...`)
   - `Elite` — $49/month recurring → copy the **Price ID**

3. **Update `.env`:**
   ```bash
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PRICE_PRO=price_...
   STRIPE_PRICE_ELITE=price_...
   ```

4. **Sync price IDs into the `plans` table:**
   ```bash
   python -m scripts.seed_plans
   ```
   This is idempotent — re-runs are safe and will update `plans.stripe_price_id`.

5. **Forward webhooks locally** (in a separate terminal):
   ```bash
   stripe login                                            # one-time
   stripe listen --forward-to localhost:8000/billing/webhook
   ```
   Copy the displayed `whsec_...` into `.env` as `STRIPE_WEBHOOK_SECRET`, then restart `uvicorn`.

### End-to-end test

With Stripe CLI listening + uvicorn running + dashboard running on `:5173`:

1. Sign up as a new user → land on `/dashboard`.
2. Refresh 3 times → 4th request returns `402` with `upgrade_url`.
3. Hit `/pricing` → click `Subscribe` on Pro → redirected to Stripe Checkout.
4. Test card: `4242 4242 4242 4242` · any future expiry · any 3-digit CVC.
5. Stripe redirects back to `/billing/success`. The CLI tunnel POSTs `checkout.session.completed` to `/billing/webhook`, which flips your subscription to `active`.
6. Refresh `/dashboard` → 402 is gone, plan is now Pro.

### Endpoints

```bash
# Authenticated — what plan is the caller on?
curl http://localhost:8000/billing/subscription \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Authenticated — start a Checkout session
curl -X POST http://localhost:8000/billing/checkout \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_code": "pro"}'

# Authenticated — open the customer portal (manage / cancel)
curl -X POST http://localhost:8000/billing/portal \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Stripe → us. Always returns 2xx (Stripe retries non-2xx aggressively).
# Bad signatures get 400. Bad payloads or unknown event types still 200.
POST /billing/webhook    Stripe-Signature: t=...,v1=...
```

### Webhook events handled

| Event | Effect |
|---|---|
| `checkout.session.completed` | Upsert `subscriptions` row → `status=active`, link to plan via `metadata.plan_code` |
| `customer.subscription.updated` | Sync status + `current_period_end`. Re-link to a different plan if the price changed. |
| `customer.subscription.deleted` | Set `status=canceled` |
| `invoice.payment_failed` | Set `status=past_due` |

Anything else gets logged and returns 200 — Stripe retries non-2xx, so silent ignore is the safer default.

## Layout

```text
backend/
├── app/
│   ├── config.py        pydantic-settings config
│   ├── database.py      SQLAlchemy engine + Base + get_db
│   ├── main.py          FastAPI app
│   ├── models/          one file per domain
│   ├── schemas/         Pydantic request/response schemas (Stage 2+)
│   ├── routers/         FastAPI routers (Stage 2+)
│   ├── services/        business logic (Stage 3+)
│   ├── ml/              prediction models (Stage 4+)
│   └── workers/         Celery tasks (Stage 3+)
├── alembic/             migrations
├── scripts/             idempotent seed scripts
└── tests/               pytest suite (Stage 2+)
```
