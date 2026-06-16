#!/bin/bash
# One-shot reminder (set 2026-06-15): Telegram-ping the operator to rotate the
# Twenty CRM API key, then remove its own LaunchAgent so it never recurs.
# Reads the Telegram creds from .env at runtime — no secret is stored here.
cd "$HOME/wheellsverse_bots" 2>/dev/null || exit 0

TOKEN=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2- | tr -d "\"' ")
CHAT=$(grep -m1 '^TELEGRAM_CHAT_ID=' .env | cut -d= -f2- | tr -d "\"' ")
MSG="⏰ Reminder: rotate your Twenty CRM API key (it was exposed in chat on 6/15). Regenerate it in Twenty → Settings → Developers, update TWENTY_API_KEY in .env (above the WORDPRESS_TOKEN line), then restart KAI."

if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
  curl -s -m 15 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT}" \
    --data-urlencode "text=${MSG}" >/dev/null 2>&1
fi

# Self-clean: unload + delete the LaunchAgent so it fires exactly once.
launchctl bootout "gui/$(id -u)/com.wheellsverse.rotate-reminder" 2>/dev/null
rm -f "$HOME/Library/LaunchAgents/com.wheellsverse.rotate-reminder.plist" 2>/dev/null
exit 0
