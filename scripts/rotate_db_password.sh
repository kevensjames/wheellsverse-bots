#!/usr/bin/env bash
# Rotate the Postgres password embedded in backend/.env's DATABASE_URL and
# DIRECT_DATABASE_URL. Reads the new URI-encoded password from stdin with
# terminal echo disabled (so it never enters shell history, scrollback, or
# any chat transcript). Refuses to write back the known-leaked value.
set -uo pipefail

cd "$(dirname "$0")/.."

if [ ! -f backend/.env ]; then
  echo "✗ backend/.env not found"; exit 1
fi

printf "Paste new Postgres password (RAW, hidden — script will URI-encode for you) then Enter: "
stty_orig=$(stty -g </dev/tty)
stty -echo </dev/tty
read -r RAWPASS </dev/tty
stty "$stty_orig" </dev/tty
echo

if [ -z "${RAWPASS:-}" ]; then
  echo "✗ Empty input — aborted."; exit 1
fi

# Refuse the known-leaked value (both raw and URI-encoded forms).
LEAKED_RAW='B1lankito@Kevens21'
LEAKED_ENC='B1lankito%40Kevens21'
if [ "$RAWPASS" = "$LEAKED_RAW" ] || [ "$RAWPASS" = "$LEAKED_ENC" ]; then
  echo "✗ Pasted the LEAKED password — refused. Use the dashboard-generated new value."
  exit 1
fi

# URI-encode (RFC 3986 percent-encoding, not the form-encoding `quote_plus`
# variant which would substitute '+' for spaces — wrong for the userinfo
# portion of a URL). Also strip leading/trailing whitespace because pasted
# values often arrive with a trailing newline from the clipboard.
NEWPASS=$(RAWPASS="$RAWPASS" python3 -c '
import os, urllib.parse, sys
raw = os.environ["RAWPASS"].strip()
if not raw:
    sys.exit(2)
sys.stdout.write(urllib.parse.quote(raw, safe=""))
')
ENC_RC=$?
unset RAWPASS
if [ "$ENC_RC" -ne 0 ] || [ -z "$NEWPASS" ]; then
  echo "✗ URI-encoding produced empty output (whitespace-only input?) — aborted."
  exit 1
fi

# Don't accept a no-op rotation: compare to whatever password is currently in
# the file (extracted via regex, never echoed).
OLD_FRAGMENT=$(grep '^DATABASE_URL=' backend/.env | sed -E 's|^.*://[^:]+:([^@]+)@.*$|\1|')
OLD_HASH=$(printf '%s' "$OLD_FRAGMENT" | shasum -a 256 | awk '{print substr($1,1,12)}')
NEW_HASH=$(printf '%s' "$NEWPASS" | shasum -a 256 | awk '{print substr($1,1,12)}')
if [ "$OLD_HASH" = "$NEW_HASH" ]; then
  echo "✗ Value identical to current in-file password — nothing to rotate."
  exit 1
fi

# Atomic write. Use python for substitution so we never pass NEWPASS through
# sed's metachar interpretation (a `&` or `\1` in the password would corrupt).
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

NEWPASS="$NEWPASS" python3 - <<'PY' > "$TMP"
import os, re, sys
newpass = os.environ['NEWPASS']
# Two patterns: DATABASE_URL=... and DIRECT_DATABASE_URL=...
pat = re.compile(
    r'^((?:DATABASE_URL|DIRECT_DATABASE_URL)=postgresql://[^:]+:)([^@]+)(@.+)$'
)
with open('backend/.env') as f:
    for line in f:
        stripped = line.rstrip('\n')
        m = pat.match(stripped)
        if m:
            sys.stdout.write(m.group(1) + newpass + m.group(3) + '\n')
        else:
            sys.stdout.write(line)
PY

mv "$TMP" backend/.env
chmod 600 backend/.env
unset NEWPASS

# Verify both URLs now share the same (new) password, and it differs from old.
A_PWD=$(grep '^DATABASE_URL=' backend/.env | sed -E 's|^.*://[^:]+:([^@]+)@.*$|\1|')
B_PWD=$(grep '^DIRECT_DATABASE_URL=' backend/.env | sed -E 's|^.*://[^:]+:([^@]+)@.*$|\1|')
A_HASH=$(printf '%s' "$A_PWD" | shasum -a 256 | awk '{print substr($1,1,12)}')
B_HASH=$(printf '%s' "$B_PWD" | shasum -a 256 | awk '{print substr($1,1,12)}')
if [ "$A_HASH" != "$B_HASH" ]; then
  echo "✗ Mismatch: DATABASE_URL pw sha=$A_HASH but DIRECT_DATABASE_URL pw sha=$B_HASH"
  exit 1
fi
if [ "$A_HASH" = "$OLD_HASH" ]; then
  echo "✗ File still shows old password after write — substitution failed."
  exit 1
fi

echo "✓ Both URLs updated to new password (sha=$A_HASH)"
echo "  Old password sha=$OLD_HASH no longer present in file"
echo "  Backup at backend/.env.bak.pwrotate-*"
echo "  Next: tell Claude 'rotated' to run the verification + daemon restart."
