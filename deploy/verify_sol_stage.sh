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
  *)
    log "ERROR: no Sol checks defined for stage \$STAGE (stages 1-7, Connect A-D(8-11), notifications(12), admin(13) exist so far)"
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
