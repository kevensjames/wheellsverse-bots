#!/bin/bash
# One-command Phase A health snapshot. Run anytime:
#   ./deploy/status.sh
# or alias it:
#   alias nai-status='/Users/jhonwheeler/wheellsverse_bots/deploy/status.sh'
set +e

REPO_ROOT="/Users/jhonwheeler/wheellsverse_bots"
LOG_DIR="/Users/jhonwheeler/Library/Logs/wheellsverse"

echo "─── NAI Phase A status ──────────────────────────────"
echo "Time: $(date)"
echo ""

echo "● launchd agents:"
launchctl list | grep -E "(wheellsverse|ollama)" \
    || echo "  (none loaded — check launchctl list)"
echo ""

echo "● Endpoints:"
if curl -sf -m 3 http://127.0.0.1:8001/docs >/dev/null; then
    echo "  nai     OK"
else
    echo "  nai     FAIL"
fi
if curl -sf -m 3 http://127.0.0.1:11434/api/tags >/dev/null; then
    echo "  ollama  OK"
else
    echo "  ollama  FAIL"
fi
echo ""

echo "● Last 5 health checks:"
if [ -f "$LOG_DIR/health.log" ]; then
    tail -5 "$LOG_DIR/health.log" | sed 's/^/  /'
else
    echo "  (no health log yet — wait 5 min after first cron tick)"
fi
echo ""

echo "● Most recent NAI errors (stderr tail):"
if [ -f "$LOG_DIR/nai.stderr.log" ]; then
    tail -10 "$LOG_DIR/nai.stderr.log" | sed 's/^/  /' || echo "  (empty)"
else
    echo "  (no stderr log yet)"
fi
echo ""

echo "● Disk:"
df -h "$LOG_DIR" | tail -1 | awk '{print "  Logs partition: " $4 " free"}'
du -sh "$LOG_DIR" 2>/dev/null | awk '{print "  Log dir size:   " $1}'
echo ""

# Cost summary requires DATABASE_URL exported in the calling shell.
# Source .env first if running interactively:  set -a; . .env; set +a
echo "● Today's NAI cost (USD):"
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
    psql "$DATABASE_URL" -tA -c "
        SELECT COALESCE(SUM(cost_usd), 0)::text || ' (' || COUNT(*)::text || ' calls)'
        FROM llm_call_log
        WHERE created_at >= DATE_TRUNC('day', NOW());
    " 2>/dev/null | awk '{print "  " $0}' || echo "  (query failed)"
else
    echo "  (DATABASE_URL or psql unavailable — \`set -a; . $REPO_ROOT/.env; set +a\`)"
fi
echo "─────────────────────────────────────────────────────"
