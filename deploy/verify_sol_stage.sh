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
  *)
    log "ERROR: no Sol checks defined for stage $STAGE (stages 1-4 exist so far)"
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
