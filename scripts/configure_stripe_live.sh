#!/usr/bin/env bash
# Configure Stripe live keys in backend/.env.
#
# Reads each value via stty -echo so they never enter shell history,
# scrollback, or chat transcripts. Pattern matches rotate_supabase_secret.sh
# and rotate_db_password.sh.
#
# Values prompted:
#   STRIPE_SECRET_KEY        (rk_live_… or sk_live_…)
#   STRIPE_WEBHOOK_SECRET    (whsec_…)
#   STRIPE_PRICE_PRO         (price_…  — recurring price ID for "Pro" plan)
#   STRIPE_PRICE_ELITE       (price_…  — recurring price ID for "Elite" plan)
#
# After writing, runs a live Stripe API probe with the secret key to confirm
# the credential authenticates against the real API.
set -uo pipefail

cd "$(dirname "$0")/.."

if [ ! -f backend/.env ]; then
  echo "✗ backend/.env not found"; exit 1
fi

# ── Hidden stdin reader (zsh-portable; bash works too) ─────────────────
read_hidden() {
  local prompt="$1"
  printf "%s" "$prompt"
  local stty_orig
  stty_orig=$(stty -g </dev/tty)
  stty -echo </dev/tty
  local val
  read -r val </dev/tty
  stty "$stty_orig" </dev/tty
  echo
  printf '%s' "$val"
}

read_visible() {
  # For non-sensitive values (price IDs are public per Stripe — they're in
  # checkout URLs — so visible echo is fine).
  local prompt="$1"
  printf "%s" "$prompt" >&2
  local val
  read -r val </dev/tty
  printf '%s' "$val"
}

echo "════════ Stripe live-keys configuration ════════"
echo "Each value will replace the matching line in backend/.env."
echo "Secrets are read with terminal echo OFF (won't appear in scrollback)."
echo
echo "Need these from your Stripe dashboard:"
echo "  - Developers → API keys → Reveal LIVE 'Secret key' (rk_live_… or sk_live_…)"
echo "  - Developers → Webhooks → your endpoint → 'Signing secret' (whsec_…)"
echo "  - Products → your Pro product → live recurring price → ID (price_…)"
echo "  - Products → your Elite product → live recurring price → ID (price_…)"
echo

SECRET=$(read_hidden "STRIPE_SECRET_KEY (hidden): ")
case "$SECRET" in
  rk_live_*|sk_live_*) : ;;
  rk_test_*|sk_test_*)
    echo "✗ that's a TEST key (rk_test_/sk_test_). Use the LIVE key from the dashboard."
    exit 1
    ;;
  *)
    echo "✗ wrong prefix. Live Stripe secrets start with rk_live_ or sk_live_."
    exit 1
    ;;
esac
[ -n "${SECRET:-}" ] || { echo "✗ empty"; exit 1; }

WHSEC=$(read_hidden "STRIPE_WEBHOOK_SECRET (hidden, whsec_…): ")
case "$WHSEC" in
  whsec_*) : ;;
  *) echo "✗ wrong prefix (need whsec_…)"; exit 1 ;;
esac

PRO_ID=$(read_visible "STRIPE_PRICE_PRO (price_…): ")
case "$PRO_ID" in
  price_*) : ;;
  *) echo "✗ wrong prefix (need price_…)"; exit 1 ;;
esac

ELITE_ID=$(read_visible "STRIPE_PRICE_ELITE (price_…): ")
case "$ELITE_ID" in
  price_*) : ;;
  *) echo "✗ wrong prefix (need price_…)"; exit 1 ;;
esac

# ── Backup ──
TS=$(date +%Y%m%d_%H%M%S)
BACKUP="backend/.env.bak.stripe-$TS"
cp backend/.env "$BACKUP"
chmod 600 "$BACKUP"
echo "✓ backup at $BACKUP"

# ── Atomic write (python regex; never passes values through sed metachars) ──
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
SECRET="$SECRET" WHSEC="$WHSEC" PRO_ID="$PRO_ID" ELITE_ID="$ELITE_ID" \
  python3 - <<'PY' > "$TMP"
import os, sys
new = {
    "STRIPE_SECRET_KEY":     os.environ["SECRET"],
    "STRIPE_WEBHOOK_SECRET": os.environ["WHSEC"],
    "STRIPE_PRICE_PRO":      os.environ["PRO_ID"],
    "STRIPE_PRICE_ELITE":    os.environ["ELITE_ID"],
}
seen = {k: False for k in new}
with open("backend/.env") as f:
    for line in f:
        s = line.rstrip("\n")
        wrote = False
        for k, v in new.items():
            if s.startswith(f"{k}="):
                sys.stdout.write(f"{k}={v}\n")
                seen[k] = True; wrote = True; break
        if not wrote:
            sys.stdout.write(line if line.endswith("\n") else line + "\n")
# Append any keys that didn't exist
for k, v in new.items():
    if not seen[k]:
        sys.stdout.write(f"{k}={v}\n")
PY

mv "$TMP" backend/.env
chmod 600 backend/.env
unset SECRET WHSEC PRO_ID ELITE_ID

# ── Verify file state by fingerprint (no values printed) ──
echo
echo "════════ Fingerprints (sha-256 prefix only) ════════"
for k in STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PRICE_PRO STRIPE_PRICE_ELITE; do
  v=$(grep "^${k}=" backend/.env | cut -d= -f2-)
  h=$(printf '%s' "$v" | shasum -a 256 | awk '{print substr($1,1,12)}')
  printf "  %-25s len=%-4d sha=%s\n" "$k" "${#v}" "$h"
done

# ── Live Stripe API probe (read-only: list balance) ──
echo
echo "════════ Live Stripe API probe ════════"
set -a; source backend/.env 2>/dev/null; set +a
HTTP=$(curl -s -o /tmp/stripe_probe.txt -w "%{http_code}" \
  -u "$STRIPE_SECRET_KEY:" \
  https://api.stripe.com/v1/balance)
echo "  GET https://api.stripe.com/v1/balance  HTTP $HTTP"
if [ "$HTTP" = "200" ]; then
  # Just confirm body is parseable — don't print balance details
  if grep -q "object" /tmp/stripe_probe.txt; then
    echo "  ✓ Stripe LIVE API accepted the secret key (balance object returned)"
  fi
elif [ "$HTTP" = "401" ]; then
  echo "  ✗ Stripe rejected the secret key (401 Unauthorized) — re-run with the correct value"
else
  echo "  ⚠ unexpected HTTP $HTTP — first 120 chars of body:"
  head -c 120 /tmp/stripe_probe.txt 2>/dev/null
  echo
fi
rm -f /tmp/stripe_probe.txt

echo
echo "════════ Done ════════"
echo "Next: restart the NAI daemon so /billing/checkout picks up the live keys:"
echo "  launchctl kickstart -k gui/\$(id -u)/com.wheellsverse.nai"
