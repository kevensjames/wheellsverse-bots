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
  *)
    log "ERROR: no Sol checks defined for stage $STAGE (only Stage 1 exists so far)"
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
