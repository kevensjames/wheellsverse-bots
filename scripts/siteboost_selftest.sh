#!/usr/bin/env bash
# SiteBoost — full system self-test.
#
# Runs the entire pipeline end-to-end in dry-run mode + all validation scripts,
# producing a single PASS/FAIL verdict. Safe to run anytime — uses fake data,
# no API spend, no emails sent.
#
# Use cases:
#   - Daily sanity check while waiting for warmup
#   - After making any code change to verify nothing broke
#   - Before deploying preview pages to confirm system is healthy
#   - Onboarding documentation for new contributors
#
# Exit codes:
#   0 = all checks pass
#   1 = one or more checks failed (see output)
#   2 = environment issue (Python missing, etc.)

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

# ── Python auto-detection ─────────────────────────────────────────────────
# Find a $PY that has requests + pytest installed. Order:
#   1. $SITEBOOST_PYTHON env var (manual override)
#   2. ./.venv/bin/$PY (project-local venv)
#   3. ../wheellsverse_bots.OLD_PRE_MIGRATION/.venv/bin/$PY (legacy venv)
#   4. whatever's in PATH
_find_python() {
    if [ -n "${SITEBOOST_PYTHON:-}" ] && "$SITEBOOST_PYTHON" -c "import requests, pytest" 2>/dev/null; then
        echo "$SITEBOOST_PYTHON"; return
    fi
    for candidate in ./.venv/bin/python3 ../wheellsverse_bots.OLD_PRE_MIGRATION/.venv/bin/python3 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import requests, pytest" 2>/dev/null; then
            echo "$candidate"; return
        fi
    done
    # No python with deps found — fall back to bare $PY so we can still report
    echo "python3"
}
PY=$(_find_python)
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

# Colors (skipped if NO_COLOR is set or stdout isn't a TTY)
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; BLUE="\033[36m"; RESET="\033[0m"; BOLD="\033[1m"
else
    GREEN=""; RED=""; YELLOW=""; BLUE=""; RESET=""; BOLD=""
fi

PASS_COUNT=0
FAIL_COUNT=0
FAILED_CHECKS=()

run() {
    local label="$1"; shift
    printf "  ${BLUE}▸${RESET} %-50s" "$label"
    if "$@" >/tmp/siteboost_selftest_last.log 2>&1; then
        echo -e "${GREEN}✓${RESET}"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "${RED}✗${RESET}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_CHECKS+=("$label")
    fi
}

echo ""
echo -e "${BOLD}  ═══════════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  SiteBoost — Full System Self-Test${RESET}"
echo -e "${BOLD}  ═══════════════════════════════════════════════════════════════${RESET}"
echo ""

# ── Section 1: Environment ──────────────────────────────────────────────────
echo -e "${BOLD}  1. ENVIRONMENT${RESET}"
run "Python 3 available"               $PY --version
run "pytest installed"                  $PY -m pytest --version
run "dig installed (for DNS checks)"    command -v dig

# ── Section 2: Artifacts present ────────────────────────────────────────────
echo ""
echo -e "${BOLD}  2. ARTIFACTS${RESET}"
run "core/places_scanner.py"            test -f core/places_scanner.py
run "core/email_enricher.py"            test -f core/email_enricher.py
run "core/site_generator.py"            test -f core/site_generator.py
run "core/cold_outreach.py"             test -f core/cold_outreach.py
run "core/siteboost_onboarding.py"      test -f core/siteboost_onboarding.py
run "core/siteboost_state.py"           test -f core/siteboost_state.py
run "scripts/local_prospect_run.py"     test -f scripts/local_prospect_run.py
run "scripts/siteboost_stripe_setup.py" test -f scripts/siteboost_stripe_setup.py
run "scripts/verify_dns.py"             test -f scripts/verify_dns.py
run "scripts/wait_for_dns.py"           test -f scripts/wait_for_dns.py
run "scripts/siteboost_status.py"       test -f scripts/siteboost_status.py
run "scripts/export_sequences_csv.py"   test -f scripts/export_sequences_csv.py
run "scripts/export_mailmeteor.py"      test -f scripts/export_mailmeteor.py
run "scripts/deploy_previews.sh"        test -f scripts/deploy_previews.sh
run "Template: restaurant"              test -f local_prospect/templates/site_restaurant.html
run "Template: service"                 test -f local_prospect/templates/site_service.html
run "Template: retail"                  test -f local_prospect/templates/site_retail.html
run "Intake form HTML"                  test -f local_prospect/intake.html
run "Marketing site: index"             test -f local_prospect/site/index.html
run "Marketing site: pricing"           test -f local_prospect/site/pricing.html
run "Marketing site: work"              test -f local_prospect/site/work.html
run "Marketing site: thanks"            test -f local_prospect/site/thanks.html
run "Cloudflare Pages config"           test -f local_prospect/site/wrangler.toml
run "Skill manifest in repo"            test -f local_prospect/SKILL.md

# ── Section 3: Documentation ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  3. DOCUMENTATION${RESET}"
for doc in README-MORNING.md PRODUCT-BRIEF.md SALES-PLAYBOOK.md DNS-CHEATSHEET.md \
           TASK-4-API-KEYS.md WARMUP-TRACKER.md ZERO-BUDGET-PATH.md env-additions.txt; do
    run "doc: $doc"  test -f "data/launches/siteboost/$doc"
done

# ── Section 4: Module imports (syntax sanity) ──────────────────────────────
echo ""
echo -e "${BOLD}  4. MODULES IMPORT CLEANLY${RESET}"
run "core.places_scanner"     $PY -c "from core import places_scanner"
run "core.email_enricher"     $PY -c "from core import email_enricher"
run "core.site_generator"     $PY -c "from core import site_generator"
run "core.cold_outreach"      $PY -c "from core import cold_outreach"
run "core.siteboost_onboarding"   $PY -c "from core import siteboost_onboarding"
run "core.siteboost_state"    $PY -c "from core import siteboost_state"
run "narai.tools.local_prospect_tool"   $PY -c "from narai.tools import local_prospect_tool"

# ── Section 5: Dry-run pipeline ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}  5. DRY-RUN PIPELINE (no API spend)${RESET}"
rm -rf data/launches/siteboost/runs/* data/launches/siteboost/scans/*.json 2>/dev/null
run "Stage 1-4 (--all)"  $PY scripts/local_prospect_run.py --all --location "Boston, MA" --limit 10

LATEST=$(ls -t data/launches/siteboost/runs/*/04-sequences.json 2>/dev/null | head -1 || true)
if [ -n "$LATEST" ]; then
    run "Sequences file present"  test -f "$LATEST"
    run "Has ≥1 sequence"          $PY -c "import json,sys; d=json.load(open('$LATEST')); sys.exit(0 if d['sequences'] else 1)"
fi

# ── Section 6: Exporters ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  6. EXPORTERS${RESET}"
if [ -n "$LATEST" ]; then
    run "Instantly CSV exporter"   $PY scripts/export_sequences_csv.py --sequences "$LATEST" --out /tmp/_st_inst.csv
    run "Mailmeteor CSV exporter"  $PY scripts/export_mailmeteor.py --sequences "$LATEST" --out /tmp/_st_mm.csv
    rm -f /tmp/_st_inst.csv /tmp/_st_mm.csv 2>/dev/null
fi

# ── Section 7: Pytest ───────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  7. PYTEST SUITE${RESET}"
run "tests/test_siteboost_pipeline.py"  $PY -m pytest tests/test_siteboost_pipeline.py -q

# ── Section 8: Status dashboard ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}  8. STATUS DASHBOARD${RESET}"
# Status dashboard returns 1 when blocked (expected pre-launch), 0 when ready.
# Either is fine for the self-test — we just want it to run without crashing.
run "Dashboard executes"  $PY -c "import subprocess,sys; r=subprocess.run([sys.executable,'scripts/siteboost_status.py'],capture_output=True); exit(0 if r.returncode in (0,1) else 2)"

# ── Verdict ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ═══════════════════════════════════════════════════════════════${RESET}"
TOTAL=$((PASS_COUNT + FAIL_COUNT))
if [ "$FAIL_COUNT" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}✓ ALL CHECKS PASSED${RESET}  (${PASS_COUNT}/${TOTAL})"
    echo ""
    echo "  System is healthy. Next:"
    echo "    ./.venv/bin/python3 scripts/siteboost_status.py     # launch-readiness dashboard"
    echo "    source .venv/bin/activate                            # then \`python3\` works as you'd expect"
    echo ""
    echo "  Discovered Python: $PY"
else
    echo -e "  ${RED}${BOLD}✗ ${FAIL_COUNT} CHECK(S) FAILED${RESET}  (${PASS_COUNT}/${TOTAL} passed)"
    echo ""
    echo "  Failed checks:"
    for f in "${FAILED_CHECKS[@]}"; do
        echo "    • $f"
    done
    echo ""
    echo "  Last failed-check log saved to: /tmp/siteboost_selftest_last.log"
fi
echo -e "${BOLD}  ═══════════════════════════════════════════════════════════════${RESET}"
echo ""

exit $([ "$FAIL_COUNT" -eq 0 ] && echo 0 || echo 1)
