#!/bin/bash
# Add WheellsVerse to macOS cron
# Run: bash setup_cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
MAIN_PY="$SCRIPT_DIR/main.py"

# Daily morning run (9am) — marketing category
CRON_DAILY="0 9 * * * cd $SCRIPT_DIR && $VENV_PYTHON $MAIN_PY --category marketing >> $SCRIPT_DIR/logs/cron.log 2>&1"

# Weekly report (Monday 7am)
CRON_WEEKLY="0 7 * * 1 cd $SCRIPT_DIR && $VENV_PYTHON $MAIN_PY --run specialized/70_reporting_dashboard >> $SCRIPT_DIR/logs/cron.log 2>&1"

# Reminder check (every 30 min)
CRON_REMINDERS="*/30 * * * * cd $SCRIPT_DIR && $VENV_PYTHON $MAIN_PY --run assistant/55_reminder_bot >> $SCRIPT_DIR/logs/cron.log 2>&1"

echo "Adding cron jobs..."
(crontab -l 2>/dev/null; echo "$CRON_DAILY") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_WEEKLY") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_REMINDERS") | crontab -

echo "✅ Cron jobs added! View with: crontab -l"
