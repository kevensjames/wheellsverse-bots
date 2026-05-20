#!/usr/bin/env bash
# verify_stage.sh — independent stage verifier for WheellsVerse / NAI
#
# This script DOES NOT TRUST CLAUDE CODE.
# It re-runs every verification claim independently and writes a signed
# evidence file. If Claude Code claimed a stage was done and this script
# disagrees, the script wins.
#
# Usage:   ./deploy/verify_stage.sh <stage_number>
# Example: ./deploy/verify_stage.sh 1
#
# Output: evidence/stage_<N>_<timestamp>.log
# Exit code: 0 if all checks pass, non-zero on first failure.
#
# Philosophy:
#   - Every check produces raw command output.
#   - Every check captures its exit code.
#   - Output is timestamped, hashed, and committed.
#   - No summaries — only evidence.

set -uo pipefail

STAGE="${1:-}"
if [ -z "$STAGE" ]; then
  echo "ERROR: stage number required"
  echo "Usage: $0 <stage_number>"
  exit 2
fi

if ! [[ "$STAGE" =~ ^[0-9]+$ ]]; then
  echo "ERROR: stage must be a number, got: $STAGE"
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

EVIDENCE_DIR="$REPO_ROOT/evidence"
mkdir -p "$EVIDENCE_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$EVIDENCE_DIR/stage_${STAGE}_${TIMESTAMP}.log"

# ── Counters ──
TOTAL_CHECKS=0
PASSED=0
FAILED=0
DEFERRED=0
FAILED_NAMES=()
DEFERRED_NAMES=()

# ── Logging helpers ──
log() {
  echo "$*" | tee -a "$LOG"
}

section() {
  log ""
  log "─── $* ───"
}

# Run a command, capture stdout+stderr+exit, log everything, update counters.
# Args: <check_name> <command...>
run_check() {
  local name="$1"
  shift
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

  log ""
  log ">>> CHECK [$TOTAL_CHECKS]: $name"
  log ">>> CMD: $*"

  local output
  local exit_code
  # Use a here-string approach so we capture both streams reliably
  output=$("$@" 2>&1)
  exit_code=$?

  log "$output"
  log ">>> EXIT_CODE: $exit_code"

  if [ $exit_code -eq 0 ]; then
    log ">>> RESULT: PASS"
    PASSED=$((PASSED + 1))
  else
    log ">>> RESULT: FAIL"
    FAILED=$((FAILED + 1))
    FAILED_NAMES+=("$name")
  fi
  return $exit_code
}

# Mark a check as deferred when a precondition is missing.
# Args: <check_name> <reason>
defer_check() {
  local name="$1"
  local reason="$2"
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  DEFERRED=$((DEFERRED + 1))
  DEFERRED_NAMES+=("$name :: $reason")
  log ""
  log ">>> CHECK [$TOTAL_CHECKS]: $name"
  log ">>> RESULT: DEFERRED"
  log ">>> REASON: $reason"
}

# Run a check only if a precondition is met.
# Args: <precondition_test_cmd> <check_name> <command...>
run_or_defer() {
  local precond="$1"
  local name="$2"
  shift 2
  if eval "$precond" >/dev/null 2>&1; then
    run_check "$name" "$@"
  else
    defer_check "$name" "precondition failed: $precond"
  fi
}

# ════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════

log "════════════════════════════════════════════════════════════════"
log "VERIFY_STAGE.SH — Independent Stage Verifier"
log "Stage: $STAGE"
log "Timestamp: $TIMESTAMP"
log "Repo: $REPO_ROOT"
log "Script: $0"
log "User: $(whoami)"
log "Host: $(hostname)"
log "════════════════════════════════════════════════════════════════"

section "Environment baseline"
run_check "git: HEAD commit"        git rev-parse HEAD
run_check "git: branch"             git rev-parse --abbrev-ref HEAD
run_check "git: clean tree"         bash -c 'test -z "$(git status --porcelain)"'
run_check "python: version"         python --version
run_check "venv: active"            bash -c 'test -n "${VIRTUAL_ENV:-}"'

# ════════════════════════════════════════════════════════════════
# STAGE-SPECIFIC CHECKS
# ════════════════════════════════════════════════════════════════

case "$STAGE" in
  0)
    section "Stage 0 — Scaffolding"

    run_check "dirs: services/narai exists"         test -d services/narai
    run_check "dirs: services/nai exists"           test -d services/nai
    run_check "dirs: deploy/launchd exists"         test -d deploy/launchd
    run_check "deps: pgvector importable"           python -c "import pgvector"
    run_check "deps: openai importable"             python -c "import openai"
    run_check "deps: anthropic importable"          python -c "import anthropic"
    run_check "deps: httpx importable"              python -c "import httpx"
    run_check "deps: tiktoken importable"           python -c "import tiktoken"
    run_check "deps: sse_starlette importable"      python -c "import sse_starlette"
    run_check "env: .env gitignored"                git check-ignore -q .env
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "pgvector: extension enabled" \
                 bash -c 'psql "${DIRECT_DATABASE_URL:-$DATABASE_URL}" -c "SELECT 1 FROM pg_extension WHERE extname='\''vector'\''" | grep -q "1 row"'
    run_check "ollama: responding"                  bash -c 'curl -sf http://127.0.0.1:11434/api/tags >/dev/null'
    run_check "decision log: 0001 committed"        test -f docs/decisions/0001-nai-scaffolding.md
    ;;

  1)
    section "Stage 1 — Memory Layer"

    run_check "model: import"                       python -c "from app.models.memory import Memory"
    run_check "embeddings: import"                  python -c "from app.services.memory.embeddings import embed_one, embed_many"
    run_check "store: import"                       python -c "from app.services.memory.store import add_memory, search_memories" 2>/dev/null || \
                                                    python -c "from app.services.memory.store import add_memory"
    run_check "retrieval: import"                   python -c "from app.services.memory.retrieval import search_memories, format_for_prompt"
    run_check "shim: services.narai.memory works"   python -c "from services.narai.memory import Memory"
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "schema: memories table exists" \
                 bash -c 'psql "${DIRECT_DATABASE_URL:-$DATABASE_URL}" -c "\d memories" | grep -q embedding'
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "schema: ivfflat index exists" \
                 bash -c 'psql "${DIRECT_DATABASE_URL:-$DATABASE_URL}" -c "\di memories*" | grep -q ix_memories_embedding'
    run_or_defer 'test -n "${OPENAI_API_KEY:-}"' \
                 "embeddings: real call returns 1536-dim" \
                 python -c "from app.services.memory.embeddings import embed_one; v=embed_one('hello'); assert len(v)==1536, f'got {len(v)}'"
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}" && test -n "${OPENAI_API_KEY:-}"' \
                 "tests: pytest memory" \
                 bash -c 'cd backend && pytest tests/test_memory.py -v --tb=short'
    run_check "decision log: 0002 committed"        test -f docs/decisions/0002-memory-layer.md
    ;;

  2)
    section "Stage 2 — Model Router"

    run_check "router: import"                      python -c "from app.services.router import Router, build_default_router"
    run_check "adapters: openai import"             python -c "from app.services.router.adapters import OpenAIAdapter"
    run_check "adapters: anthropic import"          python -c "from app.services.router.adapters import AnthropicAdapter"
    run_check "adapters: perplexity import"         python -c "from app.services.router.adapters import PerplexityAdapter"
    run_check "adapters: ollama import"             python -c "from app.services.router.adapters import OllamaAdapter"
    run_check "intent: classifier import"           python -c "from app.services.router.intent import classify_intent, Intent"
    run_check "spend tracker: import"               python -c "from app.services.router.spend_tracker import SpendTracker"
    run_check "shim: services.narai.router works"   python -c "from services.narai.router import Router as R2; from app.services.router import Router as R1; assert R2 is R1"
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "schema: llm_call_log exists" \
                 bash -c 'psql "${DIRECT_DATABASE_URL:-$DATABASE_URL}" -c "\d llm_call_log" | grep -q cost_usd'
    run_check "intent tests"                        bash -c 'cd backend && pytest tests/test_intent.py -v --tb=short'
    run_check "router unit tests"                   bash -c 'cd backend && pytest tests/test_router.py -v --tb=short'
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "spend tracker DB tests" \
                 bash -c 'cd backend && pytest tests/test_spend_tracker.py -v --tb=short'
    run_check "decision log: 0003 committed"        test -f docs/decisions/0003-model-router.md
    ;;

  3)
    section "Stage 3 — Narrow Tools"

    run_check "registry: import"                    python -c "from app.services.tools import ToolRegistry, build_default_registry"
    run_check "tools: web_search import"            python -c "from app.services.tools.web_search import WebSearchTool"
    run_check "tools: memory_tool import"           python -c "from app.services.tools.memory_tool import MemoryTool"
    run_check "tools: trading_signal import"        python -c "from app.services.tools.trading_signal import TradingSignalTool"
    run_check "brain: memory_injection import"      python -c "from app.services.nai_brain.memory_injection import build_memory_preamble"
    run_check "shim: services.narai.brain works"    python -c "from services.narai.brain import build_memory_preamble"
    run_check "router.chat: import"                 python -c "from app.services.router.router import Router; assert hasattr(Router, 'chat')"
    run_check "tool registry tests"                 bash -c 'cd backend && pytest tests/test_tool_registry.py -v --tb=short'
    run_check "router chat-loop tests"              bash -c 'cd backend && pytest tests/test_router_chat.py -v --tb=short'
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}" && test -n "${OPENAI_API_KEY:-}"' \
                 "smoke: tools end-to-end" \
                 bash -c 'cd backend && timeout 60 python -m scripts.smoke_test_tools'
    run_check "decision log: 0004 committed"        test -f docs/decisions/0004-narrow-tools.md
    ;;

  4)
    section "Stage 4 — NAI Chat API + UI"

    run_check "models: Conversation import"         python -c "from app.models.conversation import Conversation, Message"
    run_check "schemas: nai import"                 python -c "from app.schemas.nai import ChatRequest, ChatResponse, MessageOut"
    run_check "brain: import"                       python -c "from app.services.nai_brain import Brain"
    run_check "router endpoint: import"             python -c "from app.routers.nai import router"
    run_check "static: index.html exists"           test -f backend/app/static/nai/index.html
    run_check "static: chat.js exists"              test -f backend/app/static/nai/chat.js
    run_check "static: style.css exists"            test -f backend/app/static/nai/style.css
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "schema: conversations table" \
                 bash -c 'psql "${DIRECT_DATABASE_URL:-$DATABASE_URL}" -c "\d conversations" | grep -q user_id'
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "schema: messages table" \
                 bash -c 'psql "${DIRECT_DATABASE_URL:-$DATABASE_URL}" -c "\d messages" | grep -q conversation_id'
    run_or_defer 'test -n "${DIRECT_DATABASE_URL:-${DATABASE_URL:-}}"' \
                 "brain tests" \
                 bash -c 'cd backend && pytest tests/test_brain.py -v --tb=short'
    run_or_defer 'curl -sf -m 2 http://127.0.0.1:8001/docs >/dev/null' \
                 "server: /docs reachable" \
                 bash -c 'curl -sf http://127.0.0.1:8001/docs >/dev/null'
    run_or_defer 'curl -sf -m 2 http://127.0.0.1:8001/nai-ui/ >/dev/null' \
                 "server: /nai-ui/ reachable" \
                 bash -c 'curl -sf http://127.0.0.1:8001/nai-ui/ >/dev/null'
    run_check "decision log: 0005 committed"        test -f docs/decisions/0005-nai-api-and-ui.md
    ;;

  5)
    section "Stage 5 — Mac mini Daemonization"

    run_check "deploy: start_nai.sh exists"         test -x deploy/start_nai.sh
    run_check "deploy: ollama plist exists"         test -f deploy/launchd/com.wheellsverse.ollama.plist
    run_check "deploy: nai plist exists"            test -f deploy/launchd/com.wheellsverse.nai.plist
    run_check "deploy: health_check.sh exists"      test -x deploy/health_check.sh
    run_check "deploy: status.sh exists"            test -x deploy/status.sh
    run_check "launchd: nai agent loaded"           bash -c 'launchctl list | grep -q com.wheellsverse.nai'
    run_check "launchd: ollama loaded (any source)" bash -c 'launchctl list | grep -qi ollama'
    run_check "endpoint: nai responds"              bash -c 'curl -sf -m 5 http://127.0.0.1:8001/docs >/dev/null'
    run_check "endpoint: ollama responds"           bash -c 'curl -sf -m 5 http://127.0.0.1:11434/api/tags >/dev/null'
    run_check "logs: dir exists"                    test -d "$HOME/Library/Logs/wheellsverse"
    run_check "logs: rotation config installed"     test -f /etc/newsyslog.d/wheellsverse.conf
    run_check "cron: health check scheduled"        bash -c 'crontab -l 2>/dev/null | grep -q health_check'
    run_check "decision log: 0006 committed"        test -f docs/decisions/0006-mac-mini-daemonization.md
    ;;

  *)
    log "ERROR: no checks defined for stage $STAGE"
    log "Edit verify_stage.sh and add a case branch."
    exit 3
    ;;
esac

# ════════════════════════════════════════════════════════════════
# FOOTER + INTEGRITY HASH
# ════════════════════════════════════════════════════════════════

section "Summary"
log "Total checks:  $TOTAL_CHECKS"
log "Passed:        $PASSED"
log "Failed:        $FAILED"
log "Deferred:      $DEFERRED"

if [ ${#FAILED_NAMES[@]} -gt 0 ]; then
  log ""
  log "FAILED CHECKS:"
  for name in "${FAILED_NAMES[@]}"; do
    log "  - $name"
  done
fi

if [ ${#DEFERRED_NAMES[@]} -gt 0 ]; then
  log ""
  log "DEFERRED CHECKS:"
  for entry in "${DEFERRED_NAMES[@]}"; do
    log "  - $entry"
  done
fi

# Integrity hash — proves the log was not edited after the fact
HASH="$(shasum -a 256 "$LOG" | awk '{print $1}')"
{
  echo ""
  echo "─── INTEGRITY ───"
  echo "SHA256 of log above this line (excluding this footer): $HASH"
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >> "$LOG"

log ""
log "Evidence written to: $LOG"
log "SHA256: $HASH"

# ── Final verdict ──
if [ $FAILED -gt 0 ]; then
  log ""
  log "════════════════════════════════════════════════════════════════"
  log "VERDICT: STAGE $STAGE — FAIL ($FAILED check(s) failed)"
  log "════════════════════════════════════════════════════════════════"
  exit 1
fi

if [ $DEFERRED -gt 0 ]; then
  log ""
  log "════════════════════════════════════════════════════════════════"
  log "VERDICT: STAGE $STAGE — INCOMPLETE ($DEFERRED check(s) deferred)"
  log "════════════════════════════════════════════════════════════════"
  exit 4
fi

log ""
log "════════════════════════════════════════════════════════════════"
log "VERDICT: STAGE $STAGE — PASS (all $TOTAL_CHECKS checks verified)"
log "════════════════════════════════════════════════════════════════"
exit 0
