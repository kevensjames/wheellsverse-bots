#!/usr/bin/env bash
# Signing acceptance gate for the KAI desktop helper.
#
# Run this BEFORE granting TCC and before enabling any mutating desktop verb. It exits
# non-zero unless every criterion holds, so "we verified the helper" is a command with an
# exit code rather than a claim in a document.
#
#   ops/computer-ops/helper/verify_signing.sh /path/to/KaiDesktopBridge[.app]
#
# It reads only. It never creates, imports, exports or requests a signing credential, and
# it never grants TCC.
set -uo pipefail

TARGET="${1:-}"
EXPECTED_ID="com.wheellsverse.kai.desktopbridge"
GATE_SUITE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/test_helper_gate.py"

[ -n "$TARGET" ] || { echo "usage: $0 /path/to/KaiDesktopBridge[.app]"; exit 2; }
[ -e "$TARGET" ] || { echo "no such target: $TARGET"; exit 2; }

PASS=0; FAIL=0
ok(){ printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL  %s\n     -> %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }

INFO="$(codesign -dvv "$TARGET" 2>&1)"
REQ="$(codesign -d -r- "$TARGET" 2>&1)"

echo "=== signing acceptance gate: $TARGET ==="

# 1. identifier must be exactly the reserved bundle id
ID="$(printf '%s\n' "$INFO" | sed -n 's/^Identifier=//p' | head -1)"
[ "$ID" = "$EXPECTED_ID" ] && ok "identifier is $EXPECTED_ID" \
  || no "identifier must be $EXPECTED_ID" "got '${ID:-<none>}'"

# 2. not ad-hoc. An ad-hoc DR is a content hash, so every rebuild changes it and any TCC
#    grant made against the previous build silently stops matching.
#    codesign -dvv prints "Signature=adhoc" (and a flags=...(adhoc) line) ONLY for an
#    ad-hoc signature. A REAL signature prints no "Signature=" line at all -- it prints
#    "Signature size=NNNN" plus "Authority=" lines. So detect ad-hoc explicitly, accept a
#    real Authority chain, and only then call it unsigned. (An earlier version grepped
#    "^Signature=" and mis-read a real signature's ABSENCE of that line as ad-hoc.)
if printf '%s\n' "$INFO" | grep -qiE '^Signature=adhoc|flags=0x[0-9a-fA-F]+\([^)]*adhoc'; then
  no "signature must not be ad-hoc" "ad-hoc signature (rebuild breaks any TCC grant)"
elif printf '%s\n' "$INFO" | grep -q '^Authority='; then
  AUTH="$(printf '%s\n' "$INFO" | sed -n 's/^Authority=//p' | head -1)"
  ok "signature is not ad-hoc (Authority: $AUTH)"
else
  no "signature must not be ad-hoc" "no signing authority found (unsigned)"
fi

# 3. a Team ID must be present
TEAM="$(printf '%s\n' "$INFO" | sed -n 's/^TeamIdentifier=//p' | head -1)"
case "$TEAM" in
  ""|"not set") no "TeamIdentifier must be set" "got '${TEAM:-<none>}'" ;;
  *) ok "TeamIdentifier present ($TEAM)" ;;
esac

# 4. the designated requirement must be certificate-anchored, never a cdhash
if printf '%s\n' "$REQ" | grep -q 'cdhash H"'; then
  no "designated requirement must not pin a cdhash" "ad-hoc DR: rebuild breaks TCC"
elif printf '%s\n' "$REQ" | grep -q 'anchor apple generic'; then
  ok "designated requirement is certificate-anchored"
else
  no "designated requirement is not certificate-anchored" "$(printf '%s' "$REQ" | head -2 | tr '\n' ' ')"
fi

# 5. hardened runtime
printf '%s\n' "$INFO" | grep -q 'flags=.*runtime' \
  && ok "hardened runtime enabled" \
  || no "hardened runtime must be enabled" "sign with --options runtime"

# 6. Gatekeeper. Only decisive if the helper will ever be downloaded; a locally built
#    binary is never quarantined, so this is reported and NOT counted as a failure.
if spctl -a -vvv "$TARGET" >/dev/null 2>&1; then
  ok "Gatekeeper accepts the target (notarized)"
else
  printf '  NOTE  Gatekeeper rejects the target. Not fatal for a helper that is built\n'
  printf '        here and never downloaded (no quarantine attribute); REQUIRED before\n'
  printf '        distributing it. Notarize and staple in that case.\n'
fi

# 7. the helper must agree, from inside, that its identity is acceptable
BIN="$TARGET"
[ -d "$TARGET" ] && BIN="$TARGET/Contents/MacOS/KaiDesktopBridge"
if [ -x "$BIN" ]; then
  PROBE="$(printf '{"id":"1","verb":"desktop.probe"}\n' | "$BIN" 2>/dev/null | tail -1)"
  case "$PROBE" in
    *'"identity_acceptable":"true"'*) ok "helper self-reports an acceptable identity" ;;
    *) no "helper refuses its own identity" "probe: ${PROBE:0:120}" ;;
  esac
else
  no "helper binary not executable at $BIN" "cannot self-verify"
fi

# 8. the behavioural gate suite must pass against THIS artefact
if [ -f "$GATE_SUITE" ] && [ -x "$BIN" ]; then
  if python3 "$GATE_SUITE" "$BIN" >/dev/null 2>&1; then
    ok "helper gate suite passes against this artefact"
  else
    no "helper gate suite fails against this artefact" "run: python3 $GATE_SUITE $BIN"
  fi
fi

echo
echo "$PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  echo "RESULT: BLOCKED — do NOT grant TCC and do NOT enable mutating desktop verbs."
  exit 1
fi
echo "RESULT: SIGNED_HELPER_VERIFIED — TCC may now be granted to this bundle only."
