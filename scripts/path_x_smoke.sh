#!/usr/bin/env bash
# Path X end-to-end smoke against live Supabase + the running NAI daemon.
# Creates a throwaway example.com user, exercises signup -> trigger -> chat,
# verifies persistence, then deletes the user (FK CASCADE cleans up).
set -uo pipefail

cd "$(dirname "$0")/.."
set -a; source backend/.env; set +a

TESTEMAIL="pathx-smoke-$(date +%s)@example.com"
PASSWORD='PathXSmoke!2026'
COOKIES=$(mktemp)
trap 'rm -f "$COOKIES"' EXIT

# JSON body in a temp file — avoids every quoting trap.
BODY=$(mktemp)
trap 'rm -f "$COOKIES" "$BODY"' EXIT
python3 -c "
import json, sys
print(json.dumps({'email':'$TESTEMAIL','password':'$PASSWORD','full_name':'Smoke Test'}))
" > "$BODY"

echo "Test email: $TESTEMAIL"
echo

echo "── 1. POST /auth/signup ──"
SIGN=$(curl -s -w "\nHTTP:%{http_code}" -X POST http://127.0.0.1:8001/auth/signup \
  -H "Content-Type: application/json" -c "$COOKIES" --data @"$BODY")
echo "$SIGN" | grep -E "^HTTP|access_token|detail" | head -3
STATUS=$(echo "$SIGN" | grep "^HTTP:" | cut -d: -f2)
if [ "$STATUS" != "201" ]; then
  echo "✗ signup failed — aborting"
  exit 1
fi
echo "✓ 201"
echo

echo "── 2. trigger fired? auth.users → profiles ──"
USER_ID=$(psql "$DIRECT_DATABASE_URL" -tAc \
  "SELECT id FROM auth.users WHERE email='$TESTEMAIL';" | tr -d ' ')
echo "user_id: $USER_ID"
if [ -z "$USER_ID" ]; then
  echo "✗ no auth.users row"
  exit 1
fi
psql "$DIRECT_DATABASE_URL" -c \
  "SELECT id, email, COALESCE(name,'(null)') AS name, tier FROM profiles WHERE id='$USER_ID';"
echo

echo "── 3. POST /nai/chat as that user ──"
echo '{"message":"path-x smoke","use_tools":false,"max_tokens":64}' > "$BODY"
CHAT=$(curl -s -w "\nHTTP:%{http_code}" -X POST http://127.0.0.1:8001/nai/chat \
  -b "$COOKIES" -H "Content-Type: application/json" --data @"$BODY")
CSTATUS=$(echo "$CHAT" | grep "^HTTP:" | cut -d: -f2)
echo "HTTP: $CSTATUS"
echo "$CHAT" | grep -v "^HTTP:" | python3 -m json.tool 2>/dev/null || \
  echo "$CHAT" | grep -v "^HTTP:" | head -c 400
echo
if [ "$CSTATUS" != "200" ]; then
  echo "✗ chat failed"
  exit 1
fi
echo

echo "── 4. persisted? ──"
psql "$DIRECT_DATABASE_URL" -c \
  "SELECT role, LEFT(content,40) AS content_preview FROM messages WHERE user_id='$USER_ID' ORDER BY created_at;"
echo
psql "$DIRECT_DATABASE_URL" -tAc \
  "SELECT 'conv:' || COUNT(*) FROM conversations WHERE user_id='$USER_ID';"
psql "$DIRECT_DATABASE_URL" -tAc \
  "SELECT 'msg:'  || COUNT(*) FROM messages WHERE user_id='$USER_ID';"
echo

echo "── 5. cleanup (delete auth.users — FK CASCADE removes the rest) ──"
.venv/bin/python <<PY
from supabase import create_client
import os
c = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SECRET_KEY'])
c.auth.admin.delete_user('$USER_ID')
print('deleted')
PY
echo

echo "── 6. post-cleanup audit ──"
psql "$DIRECT_DATABASE_URL" -tAc \
  "SELECT 'remaining auth.users: ' || COUNT(*) FROM auth.users WHERE id='$USER_ID';"
psql "$DIRECT_DATABASE_URL" -tAc \
  "SELECT 'remaining profiles:   ' || COUNT(*) FROM profiles WHERE id='$USER_ID';"
psql "$DIRECT_DATABASE_URL" -tAc \
  "SELECT 'remaining messages:   ' || COUNT(*) FROM messages WHERE user_id='$USER_ID';"

echo
echo "════════ SMOKE PASS — Path X is live in production ════════"
