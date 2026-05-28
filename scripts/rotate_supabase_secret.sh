#!/usr/bin/env bash
# Reads the new SUPABASE_SECRET_KEY from stdin (hidden) and updates
# backend/.env in place. Safe for zsh and bash — runs via the bash shebang.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f backend/.env ]; then
  echo "✗ backend/.env not found"; exit 1
fi

printf "Paste new sb_secret_ value (hidden) then Enter: "
# bash-portable hidden read; works regardless of caller shell.
stty_orig=$(stty -g </dev/tty)
stty -echo </dev/tty
read -r NEW </dev/tty
stty "$stty_orig" </dev/tty
echo

if [ -z "${NEW:-}" ]; then
  echo "✗ Empty input — aborted."; exit 1
fi

case "$NEW" in
  sb_secret_*) ;;
  *) echo "✗ Wrong prefix (expected sb_secret_…) — aborted."; exit 1;;
esac

cp backend/.env backend/.env.before-rotation
awk -v val="$NEW" '
  /^SUPABASE_SECRET_KEY=/ { print "SUPABASE_SECRET_KEY=" val; next }
  { print }
' backend/.env.before-rotation > backend/.env

chmod 600 backend/.env backend/.env.before-rotation
unset NEW

# Verify it actually changed
LIVE_HASH=$(awk -F= '/^SUPABASE_SECRET_KEY=/{print $2}' backend/.env | shasum -a 256 | awk '{print substr($1,1,12)}')
if [ "$LIVE_HASH" = "499e5b97f415" ]; then
  echo "⚠ Updated file but value is still the dead key (you pasted the old one again)."
  exit 2
fi

echo "✓ Updated backend/.env (fingerprint: $LIVE_HASH)"
echo "  Backup at backend/.env.before-rotation"
echo "  Now tell Claude: verify"
