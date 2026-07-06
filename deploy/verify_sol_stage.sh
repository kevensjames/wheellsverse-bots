#!/usr/bin/env bash
# verify_sol_stage.sh — independent stage verifier for SOL (non-custodial ROSCA).
#
# Separate from deploy/verify_stage.sh: that file's stage numbers (0-6) belong
# to the NAI/KAI project. Sol has its own staged spec, verified here.
#
# Usage:   ./deploy/verify_sol_stage.sh <stage_number>
# Output:  evidence/sol_stage_<N>_<timestamp>.log
# Exit:    0 all pass · 1 a check failed · 4 checks deferred · 2/3 usage errors
#
# Philosophy (per HONESTY.md): raw output + exit code for every check, no
# summaries, evidence hashed. If this disagrees with a completion report, this
# wins.

set -uo pipefail

STAGE="${1:-}"
if [ -z "$STAGE" ]; then echo "ERROR: stage number required"; echo "Usage: $0 <stage_number>"; exit 2; fi
if ! [[ "$STAGE" =~ ^[0-9]+$ ]]; then echo "ERROR: stage must be a number, got: $STAGE"; exit 2; fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/backend:${PYTHONPATH:-}"

# Pin the interpreter to the project's own venv when present, so bare `python`
# (here AND inside pytest/conftest, which import app.main → slowapi etc.) is the
# daemon's interpreter with all deps — NOT whatever stale venv happens to sit
# first on PATH (e.g. a *.OLD_PRE_MIGRATION/.venv on the external SSD).
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

# Importing app.* loads app.config, which requires DATABASE_URL to exist (it is
# NOT connected to — SQLAlchemy's create_engine is lazy). Provide a harmless
# non-connecting placeholder ONLY if the operator hasn't set one, so import
# checks can run offline. The placeholder deliberately does NOT match the
# localhost/127.0.0.1/"test" pattern, so the DB-apply checks below still DEFER
# (never run migrations against an unintended target).
export DATABASE_URL="${DATABASE_URL:-postgresql://sol_verify_noconnect/x}"

EVIDENCE_DIR="$REPO_ROOT/evidence"; mkdir -p "$EVIDENCE_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$EVIDENCE_DIR/sol_stage_${STAGE}_${TIMESTAMP}.log"

TOTAL_CHECKS=0; PASSED=0; FAILED=0; DEFERRED=0
FAILED_NAMES=(); DEFERRED_NAMES=()

log() { echo "$*" | tee -a "$LOG"; }
section() { log ""; log "─── $* ───"; }

run_check() {
  local name="$1"; shift
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  log ""; log ">>> CHECK [$TOTAL_CHECKS]: $name"; log ">>> CMD: $*"
  local output exit_code
  output=$("$@" 2>&1); exit_code=$?
  log "$output"; log ">>> EXIT_CODE: $exit_code"
  if [ $exit_code -eq 0 ]; then log ">>> RESULT: PASS"; PASSED=$((PASSED + 1))
  else log ">>> RESULT: FAIL"; FAILED=$((FAILED + 1)); FAILED_NAMES+=("$name"); fi
  return $exit_code
}

defer_check() {
  local name="$1"; local reason="$2"
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1)); DEFERRED=$((DEFERRED + 1)); DEFERRED_NAMES+=("$name :: $reason")
  log ""; log ">>> CHECK [$TOTAL_CHECKS]: $name"; log ">>> RESULT: DEFERRED"; log ">>> REASON: $reason"
}

run_or_defer() {
  local precond="$1"; local name="$2"; shift 2
  if eval "$precond" >/dev/null 2>&1; then run_check "$name" "$@"; else defer_check "$name" "precondition failed: $precond"; fi
}

log "════════════════════════════════════════════════════════════════"
log "VERIFY_SOL_STAGE.SH — Independent Sol Stage Verifier"
log "Stage: $STAGE   Timestamp: $TIMESTAMP   Repo: $REPO_ROOT"
log "User: $(whoami)   Host: $(hostname)"
log "════════════════════════════════════════════════════════════════"

section "Environment baseline"
run_check "git: HEAD commit"  git rev-parse HEAD
run_check "git: branch"       git rev-parse --abbrev-ref HEAD
run_check "python: version"   python --version

case "$STAGE" in
  1)
    section "Sol Stage 1 — Data model + migrations"

    run_check "models: sol module imports" \
      python -c "from app.models.sol import SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof"
    run_check "models: registered in app.models" \
      python -c "from app.models import SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof"
    run_check "models: table names namespaced sol_*" \
      python -c "from app.models.sol import SolGroup,SolPayment; assert SolGroup.__tablename__=='sol_groups' and SolPayment.__tablename__=='sol_payments'"
    run_check "non-custodial: no bank/routing/balance columns" \
      bash -c "! grep -qiE 'routing_number|account_number|\\bbalance\\b|iban|card_number|cvv' backend/app/models/sol.py"
    run_check "migration: 0007 file exists"  test -f backend/alembic/versions/0007_sol_v1_data_model.py
    run_check "migration: chains onto 0006"  bash -c "grep -qE 'down_revision.*0006_add_kai_api_keys' backend/alembic/versions/0007_sol_v1_data_model.py"

    run_check "tests: pytest test_sol_models (unit)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_models.py -v --tb=short'

    # DB apply — LOCAL/TEST DB ONLY. Never run alembic against prod: gate on the
    # URL clearly pointing at localhost/127.0.0.1/"test".
    run_or_defer 'echo "${DATABASE_URL:-}" | grep -qE "localhost|127\.0\.0\.1|test"' \
      "migration: alembic upgrade head (local/test DB only)" \
      bash -c 'cd backend && alembic upgrade head'
    run_or_defer 'echo "${DATABASE_URL:-}" | grep -qE "localhost|127\.0\.0\.1|test"' \
      "schema: sol_groups table present (local/test DB only)" \
      python deploy/db_check.py table sol_groups
    ;;
  2)
    section "Sol Stage 2 — Group lifecycle API (create/join/lock + calendar)"

    run_check "service: sol_v1 package imports" \
      python -c "from app.services.sol_v1 import lifecycle"
    run_check "schemas: sol_v1 imports" \
      python -c "from app.schemas.sol_v1 import GroupCreate, GroupOut, JoinRequest, LockRequest, GroupDetail, MembershipOut, CycleOut"
    run_check "router: sol_v1 exposes the 4 lifecycle routes" \
      python -c "from app.routers.sol_v1 import router; p={r.path for r in router.routes}; assert p=={'/sol/v1/groups','/sol/v1/groups/join','/sol/v1/groups/{group_id}','/sol/v1/groups/{group_id}/lock'}, p"
    run_check "router: registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with /sol/v1 mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/groups' in paths and '/sol/v1/groups/{group_id}/lock' in paths, 'sol_v1 routes missing from app'"

    # NON-CUSTODIAL guard: the Sol v1 surface must contain no money-movement or
    # bank primitives — no Dwolla/Stripe client imports, no ACH/wallet/escrow
    # calls, no routing/account/card fields. Targets actual CODE (imports, calls,
    # field names) over .py only, so prose that merely NAMES the custodial system
    # it deliberately avoids ("separate from the legacy Dwolla Sol") is not a hit.
    run_check "non-custodial: no money-movement/bank primitives in sol_v1" \
      bash -c "! grep -rnE --include='*.py' 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|StripeClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1 backend/app/routers/sol_v1.py backend/app/schemas/sol_v1.py"

    run_check "tests: pytest test_sol_v1_lifecycle (unit + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_lifecycle.py -v --tb=short'

    # End-to-end DB lifecycle — needs a reachable test Postgres.
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: create→join→lock→detail on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_lifecycle.py::test_full_lifecycle_on_real_db -v'
    ;;
  3)
    section "Sol Stage 3 — Ledger + double confirmation (manual/external rail)"

    run_check "service: sol_v1 ledger imports" \
      python -c "from app.services.sol_v1 import ledger"
    run_check "schemas: sol_v1_ledger imports" \
      python -c "from app.schemas.sol_v1_ledger import PaymentOut, PaymentDetail, MarkPaidRequest, PaymentProfileUpsert, PaymentProfileOut, ProofOut, CycleActivateOut"
    run_check "router: sol_v1_ledger exposes the 9 ledger routes" \
      python -c "from app.routers.sol_v1_ledger import router; p={r.path for r in router.routes}; want={'/sol/v1/cycles/{cycle_id}/activate','/sol/v1/payments','/sol/v1/payments/{payment_id}','/sol/v1/payments/{payment_id}/mark','/sol/v1/payments/{payment_id}/confirm','/sol/v1/payments/{payment_id}/dispute','/sol/v1/payments/{payment_id}/proofs','/sol/v1/payment-profiles','/sol/v1/payment-profiles/{profile_id}'}; assert p==want, p"
    run_check "router: ledger registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_ledger\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with the ledger routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/payments/{payment_id}/confirm' in paths and '/sol/v1/payment-profiles' in paths, 'ledger routes missing from app'"

    run_check "model: sol_payments.method is nullable (materialized-before-paid)" \
      python -c "from app.models.sol import SolPayment; assert SolPayment.__table__.c.method.nullable is True, 'method must be nullable'"
    run_check "migration: 0008 exists + chains onto 0007" \
      bash -c "test -f backend/alembic/versions/0008_sol_payment_method_nullable.py && grep -qE 'down_revision.*0007_sol_v1_data_model' backend/alembic/versions/0008_sol_payment_method_nullable.py"
    run_check "migration: 0009 exists + chains onto 0008" \
      bash -c "test -f backend/alembic/versions/0009_sol_payments_cycle_payer_uq.py && grep -qE 'down_revision.*0008_sol_payment_method_nullable' backend/alembic/versions/0009_sol_payments_cycle_payer_uq.py"
    run_check "model: sol_payments has UNIQUE(cycle_id,payer_id) backstop" \
      python -c "from app.models.sol import SolPayment; names={c.name for c in SolPayment.__table__.constraints}; assert 'sol_payments_cycle_payer_uq' in names, names"

    # NON-CUSTODIAL guard over the ledger surface — recording payments, never
    # moving them. No payment-SDK imports, no bank/card fields, no transfer calls.
    run_check "non-custodial: no money-movement/bank primitives in ledger" \
      bash -c "! grep -rnE --include='*.py' 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|StripeClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/ledger.py backend/app/routers/sol_v1_ledger.py backend/app/schemas/sol_v1_ledger.py"

    run_check "tests: pytest test_sol_v1_ledger (state machine + guard + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_ledger.py -v --tb=short'

    # End-to-end DB ledger flow — needs a reachable test Postgres.
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: activate→mark→confirm→complete on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_ledger.py::test_ledger_end_to_end_on_real_db -v'
    ;;
  4)
    section "Sol Stage 4 — reminders (due/overdue sweep + member view)"

    run_check "service: sol_v1 reminders imports" \
      python -c "from app.services.sol_v1 import reminders; reminders.classify_due"
    run_check "service: sol_v1 reminder_scheduler imports" \
      python -c "from app.services.sol_v1 import reminder_scheduler as s; s.start; s.stop; s.status"
    run_check "schemas: RemindersOut/ReminderItem import" \
      python -c "from app.schemas.sol_v1_ledger import RemindersOut, ReminderItem"
    run_check "router: sol_v1_reminders exposes /sol/v1/reminders" \
      python -c "from app.routers.sol_v1_reminders import router; assert {r.path for r in router.routes}=={'/sol/v1/reminders'}"
    run_check "router: reminders registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_reminders\\.router\\)' backend/app/main.py"
    run_check "lifespan: reminder scheduler wired (start + stop)" \
      bash -c "grep -qE 'reminder_scheduler import start' backend/app/main.py && grep -qE 'reminder_scheduler import stop' backend/app/main.py"
    run_check "app: full app assembles with /sol/v1/reminders mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/reminders' in paths, 'reminders route missing'"

    run_check "scheduler: OFF by default (no thread without the env flag)" \
      python -c "import os; os.environ.pop('SOL_V1_REMINDERS_ENABLED', None); from app.services.sol_v1 import reminder_scheduler as s; assert s.start() is False and s.is_running() is False, 'scheduler must not start without SOL_V1_REMINDERS_ENABLED'"

    # NON-CUSTODIAL guard over the reminders surface.
    run_check "non-custodial: no money-movement/bank primitives in reminders" \
      bash -c "! grep -rnE --include='*.py' 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|StripeClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/reminders.py backend/app/services/sol_v1/reminder_scheduler.py backend/app/routers/sol_v1_reminders.py"

    run_check "tests: pytest test_sol_v1_reminders (buckets + digest + scheduler + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_reminders.py -v --tb=short'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: overdue→late + member_reminders on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_reminders.py::test_reminders_flow_on_real_db -v'
    ;;
  5)
    section "Sol Stage 5 — reputation (0-100 trust score from payer history)"

    run_check "service: sol_v1 reputation imports" \
      python -c "from app.services.sol_v1 import reputation; reputation.classify_payment; reputation.score_from_counts; reputation.compute_reputation"
    run_check "schemas: ReputationOut imports" \
      python -c "from app.schemas.sol_v1_reputation import ReputationOut, ReputationBreakdown"
    run_check "router: sol_v1_reputation exposes the 2 routes" \
      python -c "from app.routers.sol_v1_reputation import router; assert {r.path for r in router.routes}=={'/sol/v1/reputation/me','/sol/v1/groups/{group_id}/reputation'}"
    run_check "router: reputation registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_reputation\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with reputation routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/reputation/me' in paths and '/sol/v1/groups/{group_id}/reputation' in paths"

    # scoring sanity: pure function behaves (unrated / on-time-100 / overdue-drags)
    run_check "scoring: unrated with no history, 100 all-on-time, 0 all-overdue" \
      python -c "from app.services.sol_v1.reputation import score_from_counts as s; assert s({})['score'] is None; assert s({'on_time':3})['score']==100; assert s({'overdue':3})['score']==0; assert s({'on_time':5,'disputed':5})['score']==50"
    run_check "anti-gaming: marked-past-due→overdue; disputes sticky" \
      python -c "from datetime import date; from app.services.sol_v1.reputation import classify_payment as c; assert c(status='marked', due_date=date(2020,1,1), today=date(2026,1,1), marked_on=None)=='overdue'; assert c(status='marked', due_date=date(2030,1,1), today=date(2026,1,1), marked_on=None, ever_disputed=True)=='disputed'"
    run_check "migration: 0010 exists + chains onto 0009" \
      bash -c "test -f backend/alembic/versions/0010_sol_payment_disputed_at.py && grep -qE 'down_revision.*0009_sol_payments_cycle_payer_uq' backend/alembic/versions/0010_sol_payment_disputed_at.py"
    run_check "model: sol_payments has disputed_at (sticky dispute)" \
      python -c "from app.models.sol import SolPayment; assert 'disputed_at' in SolPayment.__table__.c, 'disputed_at column missing'"

    run_check "non-custodial: no money-movement/bank primitives in reputation" \
      bash -c "! grep -rnE --include='*.py' 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|StripeClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/reputation.py backend/app/routers/sol_v1_reputation.py backend/app/schemas/sol_v1_reputation.py"

    run_check "tests: pytest test_sol_v1_reputation (classify + scoring + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_reputation.py -v --tb=short'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: compute_reputation + group_reputations on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_reputation.py::test_reputation_on_real_db -v'
    ;;
  6)
    section "Sol Stage 6 — mobile-first member app (static SPA over /sol/v1)"

    run_check "files: index.html + app.js + styles.css exist" \
      bash -c "test -f backend/app/static/sol_v1_app/index.html && test -f backend/app/static/sol_v1_app/app.js && test -f backend/app/static/sol_v1_app/styles.css"
    run_check "index: mobile viewport + wires app.js/styles.css" \
      bash -c "grep -q 'name=\"viewport\"' backend/app/static/sol_v1_app/index.html && grep -q 'src=\"app.js\"' backend/app/static/sol_v1_app/index.html && grep -q 'href=\"styles.css\"' backend/app/static/sol_v1_app/index.html"
    run_check "mount: /sol-app registered in main.py" \
      bash -c "grep -qE '\"/sol-app\"' backend/app/main.py && grep -qE 'sol_v1_app' backend/app/main.py"
    run_check "security: no innerHTML sink in app.js (XSS)" \
      bash -c "! grep -q '\\.innerHTML' backend/app/static/sol_v1_app/app.js"
    run_check "non-custodial: disclosure copy present in app.js" \
      bash -c "grep -qi 'never' backend/app/static/sol_v1_app/app.js && grep -qi 'pay each other' backend/app/static/sol_v1_app/app.js"

    run_or_defer 'command -v node >/dev/null 2>&1' \
      "js: app.js parses (node --check)" \
      node --check backend/app/static/sol_v1_app/app.js
    run_or_defer 'command -v node >/dev/null 2>&1' \
      "js: pure-helper unit tests (node --test app.test.js)" \
      bash -c 'cd backend/app/static/sol_v1_app && node --test app.test.js'

    run_check "tests: pytest test_sol_v1_frontend (files + contract + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_frontend.py -v --tb=short'
    ;;
  7)
    section "Sol Stage 7 — legal disclosure surface (non-custodial terms + consent gate)"

    run_check "service: sol_v1 disclosures imports" \
      python -c "from app.services.sol_v1 import disclosures; disclosures.require_consent; disclosures.record_consent; disclosures.CURRENT['version']"
    run_check "schemas: LegalStatusOut/AcceptRequest import" \
      python -c "from app.schemas.sol_v1_legal import LegalStatusOut, AcceptRequest"
    run_check "model: sol_consents (SolConsent) registered" \
      python -c "from app.models import SolConsent; assert SolConsent.__tablename__=='sol_consents'"
    run_check "migration: 0011 exists + chains onto 0010" \
      bash -c "test -f backend/alembic/versions/0011_sol_consents.py && grep -qE 'down_revision.*0010_sol_payment_disputed_at' backend/alembic/versions/0011_sol_consents.py"
    run_check "router: sol_v1_legal exposes current + accept" \
      python -c "from app.routers.sol_v1_legal import router; assert {r.path for r in router.routes}=={'/sol/v1/legal/current','/sol/v1/legal/accept'}"
    run_check "router: legal registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_legal\\.router\\)' backend/app/main.py"
    run_check "gate: create + join require consent (server-enforced)" \
      bash -c "grep -qE 'require_consent' backend/app/routers/sol_v1.py"
    run_check "app: full app assembles with legal routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/legal/current' in paths and '/sol/v1/legal/accept' in paths"

    run_check "terms: non-custodial disclosure document present" \
      bash -c "test -f backend/app/static/sol_v1_app/terms.html && grep -qi 'not a bank' backend/app/static/sol_v1_app/terms.html && grep -qi 'pay each other directly' backend/app/static/sol_v1_app/terms.html"
    run_check "app: consent screen wired in the SPA" \
      bash -c "grep -q 'consentScreen' backend/app/static/sol_v1_app/app.js && grep -q '/sol/v1/legal/accept' backend/app/static/sol_v1_app/app.js"

    run_check "non-custodial: no money-movement/bank primitives in legal surface" \
      bash -c "! grep -rnE --include='*.py' 'routing_number|account_number|card_number|\\bcvv\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|StripeClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/disclosures.py backend/app/routers/sol_v1_legal.py backend/app/schemas/sol_v1_legal.py"

    run_check "tests: pytest test_sol_v1_legal (consent + gate + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_legal.py -v --tb=short'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: consent recording + create-gate on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_legal.py::test_consent_and_create_gate_on_real_db -v'
    ;;
  8)
    section "Sol Connect Stage A — Stripe Connect rail foundation (sandbox-locked onboarding)"

    run_check "service: sol_v1 stripe_connect imports" \
      python -c "from app.services.sol_v1 import stripe_connect as s; s.sandbox_state; s._guard; s.onboarding_link; s.account_status"
    run_check "schemas: ConnectStatusOut/OnboardingLinkOut import" \
      python -c "from app.schemas.sol_v1_stripe import ConnectStatusOut, OnboardingLinkOut"
    run_check "model: SolStripeAccount registered" \
      python -c "from app.models import SolStripeAccount; assert SolStripeAccount.__tablename__=='sol_stripe_accounts'"
    run_check "migration: 0012 exists + chains onto 0011" \
      bash -c "test -f backend/alembic/versions/0012_sol_stripe_accounts.py && grep -qE 'down_revision.*0011_sol_consents' backend/alembic/versions/0012_sol_stripe_accounts.py"
    run_check "router: sol_v1_stripe exposes the 3 account routes" \
      python -c "from app.routers.sol_v1_stripe import router; assert {r.path for r in router.routes}=={'/sol/v1/stripe/account','/sol/v1/stripe/account/onboard','/sol/v1/stripe/account/refresh'}"
    run_check "router: stripe registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_stripe\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with stripe routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/stripe/account/onboard' in paths"

    # SANDBOX LOCK: the rail must default OFF, and Stage A must NOT move money.
    run_check "sandbox: Connect defaults OFF (enabled + live-approved both default False)" \
      python -c "from app.config import Settings; f=Settings.model_fields; assert f['STRIPE_CONNECT_ENABLED'].default is False and f['STRIPE_CONNECT_LIVE_APPROVED'].default is False"
    run_check "sandbox: guard + sandbox_state present (live-key lock)" \
      python -c "from app.services.sol_v1 import stripe_connect as s; assert callable(s._guard) and callable(s.sandbox_state)"
    run_check "scope: Stage A moves NO money (no Transfer/Payout/Charge/PaymentIntent)" \
      bash -c "! grep -qE 'stripe\\.(Transfer|Payout|Charge|PaymentIntent)' backend/app/services/sol_v1/stripe_connect.py"

    run_check "tests: pytest test_sol_v1_stripe (sandbox lock + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_stripe.py -v --tb=short'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: onboarding + refresh (mocked Stripe) on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_stripe.py::test_onboarding_and_refresh_with_mocked_stripe -v'
    ;;
  9)
    section "Sol Connect Stage B — member subscription (\$9.99/mo SaaS fee) + access gate"

    run_check "service: sol_v1 subscription imports" \
      python -c "from app.services.sol_v1 import subscription as s; s.create_checkout; s.refresh; s.status; s.require_active_if_enabled; s.is_active"
    run_check "schemas: SubscriptionStatusOut/CheckoutOut/PortalOut import" \
      python -c "from app.schemas.sol_v1_subscription import SubscriptionStatusOut, CheckoutOut, PortalOut"
    run_check "model: SolMemberSubscription registered" \
      python -c "from app.models import SolMemberSubscription; assert SolMemberSubscription.__tablename__=='sol_member_subscriptions'"
    run_check "migration: 0013 exists + chains onto 0012" \
      bash -c "test -f backend/alembic/versions/0013_sol_member_subscriptions.py && grep -qE 'down_revision.*0012_sol_stripe_accounts' backend/alembic/versions/0013_sol_member_subscriptions.py"
    run_check "router: sol_v1_subscription exposes the 4 routes" \
      python -c "from app.routers.sol_v1_subscription import router; assert {r.path for r in router.routes}=={'/sol/v1/subscription','/sol/v1/subscription/checkout','/sol/v1/subscription/refresh','/sol/v1/subscription/portal'}"
    run_check "router: subscription registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_subscription\\.router\\)' backend/app/main.py"
    run_check "gate: create + join call require_active_if_enabled (opt-in access gate)" \
      bash -c "test \$(grep -cE 'require_active_if_enabled' backend/app/routers/sol_v1.py) -ge 2"
    run_check "app: full app assembles with subscription routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/subscription/checkout' in paths"

    # SAFE DEFAULT: access suspension OFF by default so the free manual rail works.
    run_check "default: SOL_REQUIRE_SUBSCRIPTION defaults OFF (manual rail stays free)" \
      python -c "from app.config import Settings; assert Settings.model_fields['SOL_REQUIRE_SUBSCRIPTION'].default is False"

    run_check "tests: pytest test_sol_v1_subscription (status + gate + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_subscription.py -v --tb=short'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: checkout + refresh + gate (mocked Stripe) on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_subscription.py::test_subscription_flow_and_gate -v'
    ;;
  10)
    section "Sol Connect Stage C — destination-charge contribution flow (non-custodial)"

    run_check "service: sol_v1 stripe_charges imports" \
      python -c "from app.services.sol_v1 import stripe_charges as c; c.build_direct_charge_call; c.create_contribution_checkout; c.mark_settled; c.reconcile; c.to_cents"
    run_check "schemas: ChargeCheckoutOut/ChargeStatusOut import" \
      python -c "from app.schemas.sol_v1_charges import ChargeCheckoutOut, ChargeStatusOut"
    run_check "model: SolStripePayment registered" \
      python -c "from app.models import SolStripePayment; assert SolStripePayment.__tablename__=='sol_stripe_payments'"
    run_check "migration: 0014 chains 0013 + 0015 chains 0014" \
      bash -c "grep -qE 'down_revision.*0013_sol_member_subscriptions' backend/alembic/versions/0014_sol_stripe_payments.py && grep -qE 'down_revision.*0014_sol_stripe_payments' backend/alembic/versions/0015_sol_payment_method_stripe.py"
    run_check "router: sol_v1_charges exposes the 3 routes" \
      python -c "from app.routers.sol_v1_charges import router; assert {r.path for r in router.routes}=={'/sol/v1/stripe/payments/{payment_id}/checkout','/sol/v1/stripe/payments/{payment_id}/reconcile','/sol/v1/stripe/payments/{payment_id}'}"
    run_check "router: charges registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_charges\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with charge routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/stripe/payments/{payment_id}/checkout' in paths"

    # ── NON-CUSTODIAL INVARIANT (the whole point of Stage C) ──────────────────
    run_check "non-custodial: DIRECT charge on the recipient's account (no transfer_data); empty is REFUSED" \
      python -c "
from uuid import uuid4
from app.services.sol_v1 import stripe_charges as c
from app.services.sol_v1.lifecycle import SolError
p = c.build_direct_charge_call(connected_account_id='acct_x', amount_cents=4000, payment_id=uuid4(), payer_id=uuid4(), success_url='s', cancel_url='c')
assert p['stripe_account']=='acct_x', 'charge not on the connected account'
assert 'transfer_data' not in p.get('payment_intent_data',{}), 'must not be a destination charge (Sol would be merchant of record)'
try:
    c.build_direct_charge_call(connected_account_id='', amount_cents=4000, payment_id=uuid4(), payer_id=uuid4(), success_url='s', cancel_url='c')
    raise SystemExit('FAIL: empty connected account was allowed')
except SolError:
    pass
"
    run_check "non-custodial: destination_account_id is NOT NULL (never a chargeless charge)" \
      python -c "from app.models.sol import SolStripePayment; assert SolStripePayment.__table__.c.destination_account_id.nullable is False"
    run_check "non-custodial: NO application_fee_amount + NO transfer_data key/Transfer/Payout (Sol never merchant/holder)" \
      bash -c "! grep -qE 'application_fee_amount|\"transfer_data\"|stripe\\.Charge\\.create|stripe\\.Transfer\\.create|stripe\\.Payout\\.create' backend/app/services/sol_v1/stripe_charges.py"
    run_check "sandbox: contribution checkout goes through the Connect sandbox lock" \
      bash -c "grep -qE '_connect_guard\\(\\)' backend/app/services/sol_v1/stripe_charges.py"

    run_check "tests: pytest test_sol_v1_charges (invariant + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_charges.py -v --tb=short'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: pay→settle→cycle-complete (mocked Stripe) on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_charges.py::test_contribution_flow_on_real_db -v'
    ;;
  11)
    section "Sol Connect Stage D — Stripe webhooks (settle / mirror / reverse)"

    run_check "service: sol_v1 stripe_webhooks imports" \
      python -c "from app.services.sol_v1 import stripe_webhooks as w; w.handle_event; w.HANDLED_TYPES"
    run_check "router: sol_v1_webhook exposes /sol/v1/stripe/webhook" \
      python -c "from app.routers.sol_v1_webhook import router; assert '/sol/v1/stripe/webhook' in {r.path for r in router.routes}"
    run_check "router: webhook registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_webhook\\.router\\)' backend/app/main.py"
    run_check "config: STRIPE_CONNECT_WEBHOOK_SECRET exists (separate from KAI billing)" \
      python -c "from app.config import Settings; assert 'STRIPE_CONNECT_WEBHOOK_SECRET' in Settings.model_fields"
    run_check "app: full app assembles with the webhook mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/stripe/webhook' in paths"

    run_check "events: HANDLED_TYPES covers settle + subscription + account + refund/dispute" \
      python -c "from app.services.sol_v1.stripe_webhooks import HANDLED_TYPES as H; need={'checkout.session.completed','customer.subscription.updated','customer.subscription.deleted','account.updated','charge.refunded','charge.dispute.created'}; assert need <= H, need - H"
    run_check "security: signature verified with the Sol secret + idempotency via ProcessedStripeEvent" \
      bash -c "grep -q 'construct_event' backend/app/routers/sol_v1_webhook.py && grep -q 'STRIPE_CONNECT_WEBHOOK_SECRET' backend/app/routers/sol_v1_webhook.py && grep -q 'ProcessedStripeEvent' backend/app/routers/sol_v1_webhook.py"
    run_check "non-custodial: webhook records/settles only (no Charge/Transfer/Payout money-move)" \
      bash -c "! grep -qE 'stripe\\.(Charge|Transfer|Payout|PaymentIntent)\\.create' backend/app/services/sol_v1/stripe_webhooks.py"

    run_check "tests: pytest test_sol_v1_webhooks (dispatch + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_webhooks.py -v --tb=short'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: settle/mirror/account/refund handlers on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_webhooks.py::test_webhook_handlers_on_real_db -v'
    ;;
  12)
    section "Sol Stage 12 — notifications (durable in-app inbox + member reminders)"

    run_check "service: sol_v1 notifications imports" \
      python -c "from app.services.sol_v1 import notifications as n; n.emit; n.emit_due_overdue_scan; n.content_for_payer_obligation; n.list_for_user; n.unread_count; n.mark_read; n.mark_all_read"
    run_check "schemas: sol_v1_notifications imports" \
      python -c "from app.schemas.sol_v1_notifications import NotificationOut, NotificationListOut, UnreadCountOut, MarkedOut"
    run_check "model: SolNotification registered + namespaced" \
      python -c "from app.models import SolNotification; assert SolNotification.__tablename__=='sol_notifications'"
    run_check "model: dedup_key UNIQUE(user_id,dedup_key) + kind CHECK + payment_id FK SET NULL" \
      python -c "
from app.models.sol import SolNotification as N
cons={c.name for c in N.__table__.constraints}
assert 'sol_notifications_user_dedup_uq' in cons, cons
assert 'sol_notifications_kind_check' in cons, cons
fk=list(N.__table__.c.payment_id.foreign_keys)[0]
assert fk.ondelete=='SET NULL', fk.ondelete
"
    run_check "migration: 0016 exists + chains onto 0015" \
      bash -c "test -f backend/alembic/versions/0016_sol_notifications.py && grep -qE 'down_revision.*0015_sol_payment_method_stripe' backend/alembic/versions/0016_sol_notifications.py"
    run_check "router: sol_v1_notifications exposes the 4 routes" \
      python -c "from app.routers.sol_v1_notifications import router; p={r.path for r in router.routes}; want={'/sol/v1/notifications','/sol/v1/notifications/unread-count','/sol/v1/notifications/{notification_id}/read','/sol/v1/notifications/read-all'}; assert p==want, p"
    run_check "router: notifications registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_notifications\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with the notification routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/sol/v1/notifications/unread-count' in paths and '/sol/v1/notifications/read-all' in paths"

    run_check "scheduler: run_once emits member notifications (fail-soft)" \
      bash -c "grep -qE 'emit_due_overdue_scan' backend/app/services/sol_v1/reminder_scheduler.py"
    run_check "authz: mark_read/mark_all_read are ownership-scoped (user_id in the WHERE)" \
      bash -c "grep -qE 'SolNotification.user_id == user_id' backend/app/services/sol_v1/notifications.py"
    run_check "default: external channels OFF (email + sms both default False)" \
      python -c "from app.config import Settings; f=Settings.model_fields; assert f['SOL_NOTIFY_EMAIL_ENABLED'].default is False and f['SOL_NOTIFY_SMS_ENABLED'].default is False"

    # NON-CUSTODIAL guard: notifications carry text only — no money-move/bank primitives.
    run_check "non-custodial: no money-movement/bank primitives in notifications surface" \
      bash -c "! grep -rnE --include='*.py' 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|StripeClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/notifications.py backend/app/routers/sol_v1_notifications.py backend/app/schemas/sol_v1_notifications.py"

    # SPA: the bell + screen are wired, deep-links are validated, no XSS sink.
    run_check "spa: notifications bell + screen + inAppLink validator wired" \
      bash -c "grep -q 'notificationsScreen' backend/app/static/sol_v1_app/app.js && grep -q 'refreshBell' backend/app/static/sol_v1_app/app.js && grep -q 'inAppLink' backend/app/static/sol_v1_app/app.js"
    run_check "spa: no innerHTML sink introduced (XSS)" \
      bash -c "! grep -q '\\.innerHTML' backend/app/static/sol_v1_app/app.js"

    run_check "tests: pytest test_sol_v1_notifications (builders + emit + readers + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_notifications.py -v --tb=short'
    run_or_defer 'command -v node >/dev/null 2>&1' \
      "js: SPA pure-helper unit tests incl. inAppLink (node --test app.test.js)" \
      bash -c 'cd backend/app/static/sol_v1_app && node --test app.test.js'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: emit idempotency + ownership + due/overdue scan on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_notifications.py -k "idempotent or scan" -v'
    ;;
  13)
    section "Sol Stage 13 — operator dashboard (read-only, admin-token gated)"

    run_check "service: sol_v1 admin_metrics imports" \
      python -c "from app.services.sol_v1 import admin_metrics as m; m.overview; m.risk_items; m.disputes; m.groups; m.group_detail; m.recent_activity"
    run_check "schemas: sol_v1_admin imports" \
      python -c "from app.schemas.sol_v1_admin import OverviewOut, RiskOut, DisputesOut, GroupsOut, GroupDetailOut, ActivityOut"
    run_check "router: sol_v1_admin exposes the 6 routes under /admin/sol-v1" \
      python -c "from app.routers.sol_v1_admin import router; p={r.path for r in router.routes}; want={'/admin/sol-v1/overview','/admin/sol-v1/risk','/admin/sol-v1/disputes','/admin/sol-v1/groups','/admin/sol-v1/groups/{group_id}','/admin/sol-v1/activity'}; assert p==want, p"

    # ── THE security boundary: EVERY route is admin-token gated (fail-closed),
    #    NOT the member cookie. This is the whole point of the stage.
    run_check "AUTHZ: router gated by require_admin_token at the router level" \
      python -c "from app.routers.sol_v1_admin import router; from app.dependencies.admin import require_admin_token; assert require_admin_token in [d.dependency for d in router.dependencies], 'admin router is NOT token-gated'"
    run_check "AUTHZ: does NOT use the member cookie/JWT dependency" \
      bash -c "! grep -qE 'get_current_user|UserPrincipal|supabase_jwt' backend/app/routers/sol_v1_admin.py"
    run_check "prefix: /admin/sol-v1 (distinct from the legacy custodial /admin/sol)" \
      bash -c "grep -qE 'prefix=\"/admin/sol-v1\"' backend/app/routers/sol_v1_admin.py"

    run_check "router: registered in the OPERATOR profile (not is_consumer)" \
      bash -c "grep -qE 'include_router\\(sol_v1_admin\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with the /admin/sol-v1 routes mounted" \
      python -c "import app.main as m; paths=[r.path for r in m.app.routes]; assert '/admin/sol-v1/overview' in paths and '/admin/sol-v1/groups/{group_id}' in paths"
    run_check "ui: /sol-admin static page files exist + mounted" \
      bash -c "test -f backend/app/static/sol_v1_admin/index.html && test -f backend/app/static/sol_v1_admin/app.js && grep -qE '\"/sol-admin\"' backend/app/main.py"

    # NON-CUSTODIAL: read-only aggregation — no money-move/bank primitives, no writes.
    run_check "non-custodial: no money-movement/bank primitives in admin surface" \
      bash -c "! grep -rnE --include='*.py' 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|StripeClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/admin_metrics.py backend/app/routers/sol_v1_admin.py backend/app/schemas/sol_v1_admin.py"
    run_check "read-only: admin surface performs no writes (no commit/add/delete)" \
      bash -c "! grep -qE '\\.commit\\(|\\.add\\(|\\.delete\\(|db\\.execute\\(update|db\\.execute\\(insert' backend/app/services/sol_v1/admin_metrics.py backend/app/routers/sol_v1_admin.py"
    run_check "spa: no innerHTML sink in the admin page (XSS)" \
      bash -c "! grep -q '\\.innerHTML' backend/app/static/sol_v1_admin/app.js"

    run_check "tests: pytest test_sol_v1_admin (authz + aggregation + wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_admin.py -v --tb=short'
    run_or_defer 'command -v node >/dev/null 2>&1' \
      "js: admin page pure-helper unit tests (node --test app.test.js)" \
      bash -c 'cd backend/app/static/sol_v1_admin && node --test app.test.js'

    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: aggregations over a seeded circle on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_admin.py::test_aggregations_over_a_seeded_circle -v'
    ;;
  14)
    section "Sol Stage 14 — security hardening (rate limits on the member API)"

    SOL_MEMBER_ROUTERS="backend/app/routers/sol_v1.py backend/app/routers/sol_v1_ledger.py backend/app/routers/sol_v1_legal.py backend/app/routers/sol_v1_subscription.py backend/app/routers/sol_v1_stripe.py backend/app/routers/sol_v1_charges.py backend/app/routers/sol_v1_notifications.py"

    run_check "rate-limit: shared limiter imported across the sol member routers" \
      bash -c "test \$(grep -l 'from app.core.rate_limit import limiter' $SOL_MEMBER_ROUTERS | wc -l) -ge 7"
    run_check "rate-limit: >=18 endpoints decorated with @limiter.limit" \
      bash -c "test \$(grep -rh '@limiter.limit' $SOL_MEMBER_ROUTERS | wc -l) -ge 18"
    run_check "rate-limit: JOIN is the strictest (invite-code brute-force → 10/minute)" \
      bash -c "grep -A2 '10/minute' backend/app/routers/sol_v1.py | grep -q 'def join_group'"
    run_check "rate-limit: the write mutations (mark/confirm/dispute/activate) are limited" \
      bash -c "test \$(grep -c '@limiter.limit' backend/app/routers/sol_v1_ledger.py) -ge 7"
    run_check "app: full app assembles with the rate-limited routes mounted" \
      python -c "import app.main as m; paths=[getattr(r,'path','') for r in m.app.routes]; assert '/sol/v1/groups/join' in paths and '/sol/v1/payments/{payment_id}/mark' in paths; assert hasattr(m.app.state,'limiter'), 'limiter not wired on app'"

    run_check "safe default: the limiter is DISABLED in the test suite (no flakiness)" \
      bash -c "grep -qE '_disable_rate_limiter' backend/tests/conftest.py"

    # NON-CUSTODIAL: rate-limiting is orthogonal to custody — the change is
    # decorators only; no money-move/bank primitives in the member routers.
    run_check "non-custodial: no money-movement/bank primitives in the sol member routers" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +dwolla|from +dwolla|services\\.dwolla|DwollaClient|\\bwallet\\b|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' $SOL_MEMBER_ROUTERS"

    run_check "tests: pytest test_sol_v1_ratelimit (limiter RE-ENABLED → 429 past the cap)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_ratelimit.py -v --tb=short'
    ;;
  15)
    section "Sol Stage 15 — supervisor (read-only integrity + health monitor)"

    run_check "service: sol_v1 supervisor imports" \
      python -c "from app.services.sol_v1 import supervisor as s; s.run_checks; s.integrity_violations; s.health; s.build_alert; s.is_noteworthy"
    run_check "scheduler: sol_v1 supervisor_scheduler imports" \
      python -c "from app.services.sol_v1 import supervisor_scheduler as s; s.start; s.stop; s.status; s.run_once"
    run_check "schemas: SupervisorReportOut imports" \
      python -c "from app.schemas.sol_v1_admin import SupervisorReportOut, IntegrityViolation, SupervisorHealth"
    run_check "router: /admin/sol-v1/supervisor exposed (admin-gated router)" \
      python -c "from app.routers.sol_v1_admin import router; assert '/admin/sol-v1/supervisor' in {r.path for r in router.routes}"
    run_check "app: full app assembles with the supervisor endpoint mounted" \
      python -c "import app.main as m; paths=[getattr(r,'path','') for r in m.app.routes]; assert '/admin/sol-v1/supervisor' in paths"

    run_check "scheduler: OFF by default (no thread without the env flag)" \
      python -c "import os; os.environ.pop('SOL_V1_SUPERVISOR_ENABLED', None); from app.services.sol_v1 import supervisor_scheduler as s; assert s.start() is False and s.is_running() is False"
    run_check "lifespan: supervisor scheduler wired (start + stop)" \
      bash -c "grep -qE 'supervisor_scheduler import start' backend/app/main.py && grep -qE 'supervisor_scheduler import stop' backend/app/main.py"

    # READ-ONLY: a monitor must never mutate. NON-CUSTODIAL: no money.
    run_check "read-only: supervisor performs NO writes (no commit/add/update/insert/delete)" \
      bash -c "! grep -qE '\\.commit\\(|\\.add\\(|\\.delete\\(|db\\.execute\\(update|db\\.execute\\(insert|UPDATE |INSERT |DELETE ' backend/app/services/sol_v1/supervisor.py"
    run_check "non-custodial: no money-movement/bank primitives in the supervisor" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|DwollaClient|StripeClient|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/supervisor.py backend/app/services/sol_v1/supervisor_scheduler.py"
    run_check "custody check present: supervisor flags Stripe payments to the wrong destination" \
      bash -c "grep -q 'stripe_payment_wrong_destination' backend/app/services/sol_v1/supervisor.py"

    run_check "tests: pytest test_sol_v1_supervisor (integrity + corruption + health + authz)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_supervisor.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: clean circle → no violations; injected corruption caught (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_supervisor.py::test_clean_circle_has_no_violations_then_corruption_is_caught -v'
    ;;
  16)
    section "Sol Stage 16 — observability (health + Prometheus metrics)"

    run_check "service: sol_v1 health imports" \
      python -c "from app.services.sol_v1 import health as h; h.health; h.prometheus_metrics"
    run_check "schemas: HealthOut/SchedulerStatus import" \
      python -c "from app.schemas.sol_v1_admin import HealthOut, SchedulerStatus"
    run_check "router: /admin/sol-v1/health + /metrics exposed" \
      python -c "from app.routers.sol_v1_admin import router; p={r.path for r in router.routes}; assert '/admin/sol-v1/health' in p and '/admin/sol-v1/metrics' in p"
    run_check "app: full app assembles with the observability endpoints mounted" \
      python -c "import app.main as m; paths=[getattr(r,'path','') for r in m.app.routes]; assert '/admin/sol-v1/health' in paths and '/admin/sol-v1/metrics' in paths"

    run_check "read-only: health service performs NO writes" \
      bash -c "! grep -qE '\\.commit\\(|\\.add\\(|\\.delete\\(|db\\.execute\\(update|db\\.execute\\(insert|UPDATE |INSERT |DELETE ' backend/app/services/sol_v1/health.py"
    run_check "non-custodial: no money-movement/bank primitives in observability" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|DwollaClient|StripeClient|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/health.py"

    run_check "tests: pytest test_sol_v1_observability (authz + health shape + prometheus)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_observability.py -v --tb=short'
    ;;
  17)
    section "Sol Stage 17 — template / instance / round (additive)"

    run_check "migration: 0017 exists + chains onto 0016" \
      bash -c "test -f backend/alembic/versions/0017_sol_circle_templates.py && grep -qE 'down_revision.*0016_sol_notifications' backend/alembic/versions/0017_sol_circle_templates.py"
    run_check "model: SolCircleTemplate registered + namespaced" \
      python -c "from app.models import SolCircleTemplate; assert SolCircleTemplate.__tablename__=='sol_circle_templates'"
    run_check "model: SolGroup gains template_id/round_number/previous_group_id" \
      python -c "from app.models.sol import SolGroup as G; c=G.__table__.c; assert 'template_id' in c and 'round_number' in c and 'previous_group_id' in c"
    run_check "ADDITIVE: template_id is nullable (existing groups untouched)" \
      python -c "from app.models.sol import SolGroup as G; assert G.__table__.c.template_id.nullable is True and str(G.__table__.c.round_number.server_default.arg)=='1'"
    run_check "service: sol_v1 templates imports" \
      python -c "from app.services.sol_v1 import templates as t; t.create_template; t.spawn_instance; t.start_next_round; t.list_templates; t.instances_of"
    run_check "schemas: sol_v1_templates imports" \
      python -c "from app.schemas.sol_v1_templates import TemplateCreate, TemplateOut, TemplateDetail, SpawnRequest"
    run_check "router: sol_v1_templates exposes the 4 routes" \
      python -c "from app.routers.sol_v1_templates import router; p={r.path for r in router.routes}; want={'/sol/v1/templates','/sol/v1/templates/{template_id}','/sol/v1/templates/{template_id}/spawn','/sol/v1/groups/{group_id}/next-round'}; assert p==want, p"
    run_check "router: templates registered in main.py" \
      bash -c "grep -qE 'include_router\\(sol_v1_templates\\.router\\)' backend/app/main.py"
    run_check "app: full app assembles with the template routes mounted" \
      python -c "import app.main as m; paths=[getattr(r,'path','') for r in m.app.routes]; assert '/sol/v1/templates/{template_id}/spawn' in paths and '/sol/v1/groups/{group_id}/next-round' in paths"

    run_check "rate-limit: template writes (create/spawn/next-round) are limited" \
      bash -c "test \$(grep -c '@limiter.limit' backend/app/routers/sol_v1_templates.py) -ge 3"
    run_check "gate: create_template is consent-gated (server-enforced, non-custodial)" \
      bash -c "grep -q 'require_consent' backend/app/routers/sol_v1_templates.py"

    run_check "non-custodial: no bank cols in the template model + no money in the service/router" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|DwollaClient|StripeClient|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/templates.py backend/app/routers/sol_v1_templates.py backend/app/schemas/sol_v1_templates.py"

    run_check "tests: pytest test_sol_v1_templates (create/spawn/owner-scope/next-round)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_templates.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: spawn instance + next-round cohort clone on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_templates.py -k "spawn or next_round" -v'
    ;;
  18)
    section "Sol Stage 18 — template waitlist (+ notify-on-spawn)"

    run_check "migration: 0018 exists + chains onto 0017" \
      bash -c "test -f backend/alembic/versions/0018_sol_waitlist.py && grep -qE 'down_revision.*0017_sol_circle_templates' backend/alembic/versions/0018_sol_waitlist.py"
    run_check "model: SolWaitlist registered + namespaced" \
      python -c "from app.models import SolWaitlist; assert SolWaitlist.__tablename__=='sol_waitlist'"
    run_check "model: NOTIFICATION_KINDS includes circle_opening" \
      python -c "from app.models.sol import NOTIFICATION_KINDS; assert 'circle_opening' in NOTIFICATION_KINDS"
    run_check "service: sol_v1 waitlist imports" \
      python -c "from app.services.sol_v1 import waitlist as w; w.join_waitlist; w.leave_waitlist; w.list_waitlist; w.my_waitlists; w.notify_waitlist"
    run_check "schemas: WaitlistEntryOut imports" \
      python -c "from app.schemas.sol_v1_templates import WaitlistEntryOut"
    run_check "router: waitlist routes exposed" \
      python -c "from app.routers.sol_v1_templates import router; p={r.path for r in router.routes}; assert '/sol/v1/templates/{template_id}/waitlist' in p and '/sol/v1/waitlists' in p"
    run_check "app: full app assembles with the waitlist routes mounted" \
      python -c "import app.main as m; paths=[getattr(r,'path','') for r in m.app.routes]; assert '/sol/v1/waitlists' in paths"

    run_check "notify: spawn_instance nudges the waitlist (fail-soft)" \
      bash -c "grep -qE 'notify_waitlist' backend/app/services/sol_v1/templates.py"
    run_check "rate-limit: waitlist join/leave are limited" \
      bash -c "test \$(grep -c '@limiter.limit' backend/app/routers/sol_v1_templates.py) -ge 5"
    run_check "owner-scope: list_waitlist is creator-only" \
      bash -c "grep -qE 'only the template creator can see its waitlist' backend/app/services/sol_v1/waitlist.py"

    run_check "non-custodial: no bank cols/money in the waitlist model + service" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +stripe|from +stripe|import +dwolla|from +dwolla|DwollaClient|StripeClient|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/waitlist.py"

    run_check "tests: pytest test_sol_v1_waitlist (join/leave/owner-scope/notify)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_waitlist.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: waitlist + notify-on-spawn on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_waitlist.py -k notify -v'
    ;;
  19)
    section "Sol Stage 19 — auto-spawn a template's next instance on fill"

    run_check "service: templates exposes auto_spawn_next_if_full + _do_spawn" \
      python -c "from app.services.sol_v1 import templates as t; t.auto_spawn_next_if_full; t._do_spawn; t.spawn_instance"
    run_check "hook: join_group calls auto_spawn_next_if_full" \
      bash -c "grep -qE 'auto_spawn_next_if_full' backend/app/services/sol_v1/lifecycle.py"
    run_check "fail-soft: the auto-spawn hook is wrapped (try/except + rollback), never breaks the join" \
      bash -c "grep -qE 'auto-spawn-on-fill failed' backend/app/services/sol_v1/lifecycle.py"
    run_check "guard: only spawns when NO other open instance has room (no over-spawn)" \
      bash -c "grep -qE 'open_with_room' backend/app/services/sol_v1/templates.py"
    run_check "app: full app assembles (lifecycle+templates import clean, no cycle)" \
      python -c "import app.main as m; from app.services.sol_v1 import templates, lifecycle; assert hasattr(templates,'auto_spawn_next_if_full')"

    run_check "non-custodial: no money-movement/bank primitives introduced in the hook" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\bcvv\\b|\\biban\\b|import +dwolla|from +dwolla|DwollaClient|\\bescrow\\b|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/templates.py backend/app/services/sol_v1/lifecycle.py"

    run_check "tests: pytest test_sol_v1_autospawn (fill→spawn+notify / room-guard / standalone)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_autospawn.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: fill auto-spawns the next instance + notifies waitlist (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_autospawn.py::test_fill_auto_spawns_next_instance_and_notifies_waitlist -v'
    ;;
  20)
    section "Sol Stage 20 — email notification channel (opt-in, fail-soft)"

    run_check "config: SMTP_* keys present + email OFF by default" \
      python -c "from app.config import Settings; f=Settings.model_fields; assert all(k in f for k in ('SMTP_HOST','SMTP_PORT','SMTP_FROM','SMTP_STARTTLS')); assert f['SOL_NOTIFY_EMAIL_ENABLED'].default is False"
    run_check "service: notifications email channel present" \
      python -c "from app.services.sol_v1 import notifications as n; n._email_configured; n._resolve_email; n._send_email; n._deliver_external"
    run_check "gated: email sends only when opt-in flag AND SMTP config (both)" \
      bash -c "grep -qE '_email_enabled\\(\\) and _email_configured\\(\\)' backend/app/services/sol_v1/notifications.py"
    run_check "fail-soft: email failure is swallowed (never breaks emission)" \
      bash -c "grep -qE 'a broken channel must never break emission' backend/app/services/sol_v1/notifications.py"
    run_check "off critical path: email delivered on a background daemon thread" \
      bash -c "grep -qE 'threading.Thread\\(target=_run.*daemon=True' backend/app/services/sol_v1/notifications.py"
    run_check "own session: _resolve_email uses its own SessionLocal (no shared-session poison)" \
      bash -c "grep -qE 'from app.database import SessionLocal' backend/app/services/sol_v1/notifications.py && grep -qE 'def _resolve_email\\(user_id' backend/app/services/sol_v1/notifications.py"
    run_check "security: TLS certificate verification on send (blocks MITM)" \
      bash -c "grep -qE 'ssl.create_default_context\\(\\)' backend/app/services/sol_v1/notifications.py && grep -qE 'starttls\\(context=ctx\\)' backend/app/services/sol_v1/notifications.py"
    run_check "security: refuse SMTP AUTH over cleartext" \
      bash -c "grep -qE 'refusing SMTP AUTH over cleartext' backend/app/services/sol_v1/notifications.py"
    run_check "resolve: the address comes from the member's Profile" \
      bash -c "grep -qE 'from app.models.profile import Profile' backend/app/services/sol_v1/notifications.py"

    run_check "non-custodial: no money/bank primitives in the email channel" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\biban\\b|import +dwolla|from +dwolla|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/notifications.py"

    run_check "tests: pytest test_sol_v1_email (send / no-op / fail-soft / message build)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_email.py -v --tb=short'
    ;;
  21)
    section "Sol Stage 21 — dispute resolution (payee withdraw + organizer waive)"

    run_check "model: 'waived' status + resolution audit columns exist" \
      python -c "from app.models.sol import PAYMENT_STATUSES, SolPayment; assert 'waived' in PAYMENT_STATUSES; c=SolPayment.__table__.c; assert all(k in c for k in ('resolution_note','resolved_by','resolved_at'))"
    run_check "model: 'payment_resolved' notification kind added" \
      python -c "from app.models.sol import NOTIFICATION_KINDS; assert 'payment_resolved' in NOTIFICATION_KINDS"
    run_check "transitions: disputed→marked (withdraw) and disputed→waived (waive)" \
      python -c "from app.services.sol_v1 import ledger as L; assert L._TRANSITIONS[('disputed','withdraw')]=='marked'; assert L._TRANSITIONS[('disputed','waive')]=='waived'; assert {'withdraw','waive'} <= set(L.PAYMENT_ACTIONS)"
    run_check "completion guard now treats 'waived' as settled (no bare != 'confirmed')" \
      bash -c "grep -qE 'status.notin_..\"confirmed\", \"waived\"' backend/app/services/sol_v1/ledger.py && ! grep -qE 'SolPayment.status != .confirmed.' backend/app/services/sol_v1/ledger.py"
    run_check "authz: withdraw is payee-only; waive is organizer-only" \
      bash -c "grep -A12 'def withdraw_dispute' backend/app/services/sol_v1/ledger.py | grep -qE \"side=.payee.\" && grep -A28 'def waive_dispute' backend/app/services/sol_v1/ledger.py | grep -qE 'organizer_id != actor_id'"
    run_check "safety: waive reads organizer via scalar (never loads SolGroup ORM pre-lock)" \
      bash -c "grep -A28 'def waive_dispute' backend/app/services/sol_v1/ledger.py | grep -qE 'select.SolGroup.organizer_id.'"
    run_check "reputation: 'waived' is a neutral, EXCLUDED category" \
      python -c "from app.services.sol_v1 import reputation as R; assert 'waived' in R.CATEGORIES and 'waived' not in R._ACTIONABLE; assert R.classify_payment(status='waived', due_date=__import__('datetime').date(2026,1,1), today=__import__('datetime').date(2026,6,1), marked_on=None, ever_disputed=True)=='waived'"
    run_check "service: notification builder + hook present" \
      python -c "from app.services.sol_v1 import notifications as n; n.content_payment_resolved; n.notify_dispute_resolved"
    run_check "endpoints: withdraw + resolve routes registered" \
      python -c "import app.main as m; p={r.path for r in m.app.routes}; assert '/sol/v1/payments/{payment_id}/dispute/withdraw' in p and '/sol/v1/payments/{payment_id}/resolve' in p"
    run_check "migration: 0019 revises 0018 and is additive (widen CHECK + ADD COLUMN, no DROP COLUMN in upgrade)" \
      bash -c "grep -qE \"down_revision.*0018_sol_waitlist\" backend/alembic/versions/0019_sol_dispute_resolution.py && grep -qE 'ADD COLUMN IF NOT EXISTS resolution_note' backend/alembic/versions/0019_sol_dispute_resolution.py && ! sed -n '/def upgrade/,/def downgrade/p' backend/alembic/versions/0019_sol_dispute_resolution.py | grep -qE 'DROP COLUMN'"

    run_check "non-custodial: no money/bank primitives in the resolution code" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\biban\\b|import +dwolla|from +dwolla|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/ledger.py backend/app/services/sol_v1/notifications.py"

    run_check "tests: pytest test_sol_v1_dispute_resolution (pure state-machine / reputation / notify)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_dispute_resolution.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: withdraw + waive-completes-cycle + authz + reputation on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_dispute_resolution.py::test_dispute_resolution_end_to_end_on_real_db -v'
    ;;
  22)
    section "Sol Stage 22 — open-circle membership management (leave + remove)"

    run_check "service: leave_group + remove_member present" \
      python -c "from app.services.sol_v1 import lifecycle as l; l.leave_group; l.remove_member"
    run_check "guard: both require an OPEN circle (409 after lock)" \
      bash -c "grep -A20 'def leave_group' backend/app/services/sol_v1/lifecycle.py | grep -qE \"status != .open.\" && grep -A20 'def remove_member' backend/app/services/sol_v1/lifecycle.py | grep -qE \"status != .open.\""
    run_check "authz: organizer can't leave; remove is organizer-only + can't remove organizer" \
      bash -c "grep -A20 'def leave_group' backend/app/services/sol_v1/lifecycle.py | grep -qE 'user_id == group.organizer_id' && grep -A20 'def remove_member' backend/app/services/sol_v1/lifecycle.py | grep -qE 'organizer_id != actor_id' && grep -A20 'def remove_member' backend/app/services/sol_v1/lifecycle.py | grep -qE 'target_user_id == group.organizer_id'"
    run_check "concurrency: lock_group locks the group row (serialize vs join/leave/remove)" \
      bash -c "grep -A6 'def lock_group' backend/app/services/sol_v1/lifecycle.py | grep -qE 'with_for_update=True' || grep -A12 'Lock the group row so lock serializes' backend/app/services/sol_v1/lifecycle.py | grep -qE 'with_for_update=True'"
    run_check "endpoints: DELETE /members/me + /members/{user_id} registered" \
      python -c "import app.main as m; p={r.path for r in m.app.routes}; assert '/sol/v1/groups/{group_id}/members/me' in p and '/sol/v1/groups/{group_id}/members/{user_id}' in p"

    run_check "non-custodial: no money/bank primitives in the membership ops" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\biban\\b|import +dwolla|from +dwolla|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/lifecycle.py"

    run_check "tests: pytest test_sol_v1_membership (routes + guards)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_membership.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: leave + remove + seat-frees + post-lock-frozen on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_membership.py::test_membership_leave_and_remove_on_real_db -v'
    ;;
  23)
    section "Sol Stage 23 — member timeline (what's-next projection, read-only)"

    run_check "service: build_timeline + status classifiers present" \
      python -c "from app.services.sol_v1 import timeline as t; t.build_timeline; t.contribution_status; t.payout_status; t.contribution_labels; t.payout_labels"
    run_check "pure: contribution status buckets (paid / overdue / upcoming)" \
      python -c "from app.services.sol_v1 import timeline as t; from datetime import date; d=date(2026,6,1); assert t.contribution_status(payment_status='confirmed',due_date=date(2026,5,1),today=d)=='paid'; assert t.contribution_status(payment_status='pending',due_date=date(2026,5,1),today=d)=='overdue'; assert t.contribution_status(payment_status='pending',due_date=date(2026,7,1),today=d)=='upcoming'"
    run_check "pure: payout status buckets (received / incoming / scheduled)" \
      python -c "from app.services.sol_v1 import timeline as t; from datetime import date; d=date(2026,6,1); assert t.payout_status(cycle_status='complete',due_date=d,today=d)=='received'; assert t.payout_status(cycle_status='active',due_date=d,today=d)=='incoming'; assert t.payout_status(cycle_status='pending',due_date=date(2026,7,1),today=d)=='scheduled'"
    run_check "endpoint: GET /sol/v1/timeline registered" \
      python -c "import app.main as m; assert '/sol/v1/timeline' in {r.path for r in m.app.routes}"
    run_check "read-only: the projection never writes (no add/commit/delete/flush)" \
      bash -c "! grep -qE 'db.add\\(|db.commit\\(|db.delete\\(|db.flush\\(' backend/app/services/sol_v1/timeline.py"

    run_check "non-custodial: no money/bank primitives in the timeline" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\biban\\b|import +dwolla|from +dwolla|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/timeline.py"

    run_check "tests: pytest test_sol_v1_timeline (classifiers + labels)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_timeline.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: member stream (contributions + payout + ordering) on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_timeline.py::test_timeline_end_to_end_on_real_db -v'
    ;;
  24)
    section "Sol Stage 24 — late policy (grace period + organizer delinquency escalation)"

    run_check "model: grace_period_days on group + template + 'member_delinquent' kind" \
      python -c "from app.models.sol import SolGroup, SolCircleTemplate, NOTIFICATION_KINDS as K; assert 'grace_period_days' in SolGroup.__table__.c and 'grace_period_days' in SolCircleTemplate.__table__.c; assert 'member_delinquent' in K"
    run_check "migration: 0020 revises 0019 and is additive (ADD COLUMN, no DROP COLUMN in upgrade)" \
      bash -c "grep -qE 'down_revision.*0019_sol_dispute_resolution' backend/alembic/versions/0020_sol_late_policy.py && grep -qE 'ADD COLUMN IF NOT EXISTS grace_period_days' backend/alembic/versions/0020_sol_late_policy.py && ! sed -n '/def upgrade/,/def downgrade/p' backend/alembic/versions/0020_sol_late_policy.py | grep -qE 'DROP COLUMN'"
    run_check "service: delinquency detect + escalate + pure classifiers present" \
      python -c "from app.services.sol_v1 import delinquency as d; d.find_delinquencies; d.notify_organizer_delinquencies; d.is_delinquent; d.days_overdue"
    run_check "pure: grace boundary (strictly past grace = delinquent)" \
      python -c "from app.services.sol_v1 import delinquency as d; from datetime import date; t=date(2026,6,1); assert d.is_delinquent(due_date=date(2026,5,26),today=t,grace_days=5) is True; assert d.is_delinquent(due_date=date(2026,5,27),today=t,grace_days=5) is False"
    run_check "authz: find_delinquencies is organizer-only" \
      bash -c "grep -A16 'def find_delinquencies' backend/app/services/sol_v1/delinquency.py | grep -qE 'organizer_id != actor_id'"
    run_check "endpoint: GET /sol/v1/groups/{id}/delinquencies registered" \
      python -c "import app.main as m; assert '/sol/v1/groups/{group_id}/delinquencies' in {r.path for r in m.app.routes}"
    run_check "loop: the daily scan escalates delinquents (fail-soft)" \
      bash -c "grep -qE 'notify_organizer_delinquencies' backend/app/services/sol_v1/reminders.py"

    run_check "non-custodial: no money/bank primitives in the late-policy code" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\biban\\b|import +dwolla|from +dwolla|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/delinquency.py"

    run_check "tests: pytest test_sol_v1_delinquency (classifiers + validation)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_delinquency.py -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: grace-aware detection + authz + settle-drops-off + escalation on real DB (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_delinquency.py::test_delinquency_end_to_end_on_real_db -v'
    ;;
  25)
    section "Sol Stage 25 — invite-code rotation (organizer resets the invite link)"

    run_check "service: rotate_invite_code present" \
      python -c "from app.services.sol_v1 import lifecycle as l; l.rotate_invite_code"
    run_check "authz: organizer-only + open-circle-only" \
      bash -c "grep -A16 'def rotate_invite_code' backend/app/services/sol_v1/lifecycle.py | grep -qE 'organizer_id != actor_id' && grep -A16 'def rotate_invite_code' backend/app/services/sol_v1/lifecycle.py | grep -qE \"status != .open.\""
    run_check "invalidation: rotation mints a fresh code (generate_invite_code) under the group-row lock" \
      bash -c "grep -A16 'def rotate_invite_code' backend/app/services/sol_v1/lifecycle.py | grep -qE 'invite_code = generate_invite_code' && grep -A16 'def rotate_invite_code' backend/app/services/sol_v1/lifecycle.py | grep -qE 'with_for_update=True'"
    run_check "endpoint: POST /sol/v1/groups/{id}/invite-code/rotate registered" \
      python -c "import app.main as m; assert '/sol/v1/groups/{group_id}/invite-code/rotate' in {r.path for r in m.app.routes}"

    run_check "non-custodial: no money/bank primitives touched by rotation" \
      bash -c "! grep -A16 'def rotate_invite_code' backend/app/services/sol_v1/lifecycle.py | grep -qE 'routing_number|account_number|card_number|amount|\\.charge\\(|\\.transfer\\('"

    run_check "tests: pytest test_sol_v1_invite_rotation (router wiring)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_invite_rotation.py::test_router_registers_rotate_route -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: rotate invalidates old link + new link joins + authz + post-lock 409 (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_invite_rotation.py::test_invite_rotation_end_to_end_on_real_db -v'
    ;;
  26)
    section "Sol Stage 26 — SOL profile + badges (derived read-only achievements)"

    run_check "service: award_badges + member_profile + compute_member_stats present" \
      python -c "from app.services.sol_v1 import badges as b; b.award_badges; b.member_profile; b.compute_member_stats"
    run_check "pure: a new member earns nothing; a veteran earns the wall" \
      python -c "from app.services.sol_v1 import badges as b; new={'circles_completed':0,'circles_organized':0,'actionable':0,'on_time':0,'reputation_label':'unrated'}; assert not any(x['earned'] for x in b.award_badges(new)); vet={'circles_completed':5,'circles_organized':2,'actionable':10,'on_time':10,'reputation_label':'excellent'}; assert all(x['earned'] for x in b.award_badges(vet))"
    run_check "read-only: the projection never writes (no add/commit/delete/flush)" \
      bash -c "! grep -qE 'db.add\\(|db.commit\\(|db.delete\\(|db.flush\\(' backend/app/services/sol_v1/badges.py"
    run_check "endpoint: GET /sol/v1/badges/me registered" \
      python -c "import app.main as m; assert '/sol/v1/badges/me' in {r.path for r in m.app.routes}"

    run_check "non-custodial: no money/bank primitives in the badges projection" \
      bash -c "! grep -rnE 'routing_number|account_number|card_number|\\biban\\b|import +dwolla|from +dwolla|\\.charge\\(|\\.debit\\(|\\.transfer\\(' backend/app/services/sol_v1/badges.py"

    run_check "tests: pytest test_sol_v1_badges (catalog + thresholds)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_badges.py -k "not real_db" -v --tb=short'
    run_or_defer '[ -n "${TEST_DATABASE_URL:-}" ]' \
      "e2e: complete a circle → first_circle/reliable/perfect + organizer badge (TEST_DATABASE_URL only)" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_badges.py::test_badges_end_to_end_on_real_db -v'
    ;;
  27)
    section "Sol Stage 27 — multi-tier payer reminders (7d / 3d / tomorrow / due / overdue)"

    run_check "service: reminder_tier + REMINDER_TIERS present" \
      python -c "from app.services.sol_v1 import reminders as r; r.reminder_tier; assert r.REMINDER_TIERS == ('due_7d','due_3d','due_1d','due_today','overdue')"
    run_check "pure: the escalation bands (7d/3d/tomorrow/today/overdue + far=None)" \
      python -c "from app.services.sol_v1 import reminders as r; from datetime import date,timedelta; t=date(2026,6,1); f=lambda d: r.reminder_tier(t+timedelta(days=d),t); assert [f(-1),f(0),f(1),f(3),f(7),f(8)]==['overdue','due_today','due_1d','due_3d','due_7d',None]"
    run_check "distinct dedup keys per tier (the ladder can't self-swallow)" \
      python -c "from app.services.sol_v1 import notifications as n; from datetime import date; from decimal import Decimal; from uuid import uuid4; pid=uuid4(); ks={n.content_for_payer_obligation(payment_id=pid,amount=Decimal('5'),due_date=date(2026,6,1),bucket=b)['dedup_key'] for b in ('due_7d','due_3d','due_1d','due_today','overdue')}; assert len(ks)==5, ks"
    run_check "scan drives the tiers (emit_due_overdue_scan uses reminder_tier)" \
      bash -c "grep -qE 'reminder_tier' backend/app/services/sol_v1/notifications.py && grep -A14 'def emit_due_overdue_scan' backend/app/services/sol_v1/notifications.py | grep -qE 'reminder_tier'"

    run_check "non-custodial: no money/bank primitives in the reminder tiers" \
      bash -c "! grep -A20 'def reminder_tier' backend/app/services/sol_v1/reminders.py | grep -qE 'routing_number|account_number|card_number|\\.charge\\(|\\.transfer\\('"

    run_check "tests: pytest reminder tiers + content ladder" \
      bash -c 'cd backend && python -m pytest tests/test_sol_v1_reminders.py tests/test_sol_v1_notifications.py -k "tier or far_future or overdue" -v --tb=short'
    ;;
  *)
    log "ERROR: no Sol checks defined for stage \$STAGE (stages 1-7, Connect A-D(8-11), notifications(12), admin(13), security(14), supervisor(15), observability(16), templates(17), waitlist(18), auto-spawn(19), email(20), dispute-resolution(21), membership-mgmt(22), timeline(23), late-policy(24), invite-rotation(25), badges(26), multi-tier-reminders(27) exist so far)"
    exit 3
    ;;
esac

section "Summary"
log "Total checks:  $TOTAL_CHECKS"; log "Passed:        $PASSED"; log "Failed:        $FAILED"; log "Deferred:      $DEFERRED"
if [ ${#FAILED_NAMES[@]} -gt 0 ]; then log ""; log "FAILED CHECKS:"; for n in "${FAILED_NAMES[@]}"; do log "  - $n"; done; fi
if [ ${#DEFERRED_NAMES[@]} -gt 0 ]; then log ""; log "DEFERRED CHECKS:"; for e in "${DEFERRED_NAMES[@]}"; do log "  - $e"; done; fi

HASH="$(shasum -a 256 "$LOG" | awk '{print $1}')"
{ echo ""; echo "─── INTEGRITY ───"; echo "SHA256 of log above this line: $HASH"; echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"; } >> "$LOG"
log ""; log "Evidence written to: $LOG"; log "SHA256: $HASH"

if [ $FAILED -gt 0 ]; then log ""; log "VERDICT: SOL STAGE $STAGE — FAIL ($FAILED failed)"; exit 1; fi
if [ $DEFERRED -gt 0 ]; then log ""; log "VERDICT: SOL STAGE $STAGE — INCOMPLETE ($DEFERRED deferred)"; exit 4; fi
log ""; log "VERDICT: SOL STAGE $STAGE — PASS (all $TOTAL_CHECKS checks verified)"; exit 0
