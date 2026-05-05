#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# WheellsVerse — Export secrets bundle (run on the OLD Mac)
#
# WHAT THIS DOES
#   Creates an encrypted tarball of:
#     • All real .env files (root + backend/ + trade-app/ + narai/marketing/)
#     • data/ runtime state (autopilot queues, registries, calendars, cookies)
#     • Token / credential files (canva, youtube, etc.)
#     • The .python-version pin (so the new mini matches)
#
#   Encryption: GPG symmetric (AES-256). You set a passphrase, type it on
#   the new mini once. Nothing in cleartext ever lands on iCloud / AirDrop /
#   Spotlight index.
#
# OUTPUT
#   wheellsverse-secrets-YYYYMMDD-HHMMSS.tar.gz.gpg
#   Saved to the repo root by default — copy to the new mini via the
#   external drive, USB, or `scp`. Never via AirDrop or iCloud Drive.
#
# WHEN TO RUN
#   Right before you set up the new mini, while the old Mac is still
#   authoritative.  Re-run if you change any .env between now and migration.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

log()  { printf "\033[1;36m▸\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m✗\033[0m %s\n" "$*"; exit 1; }

# Resolve repo root (this script lives at <repo>/scripts/mac-mini/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
log "Repo root: $REPO_ROOT"

# Prerequisite: gpg
if ! command -v gpg >/dev/null 2>&1; then
  die "gpg not installed. Run: brew install gnupg"
fi

# ── Build the file list ─────────────────────────────────────────────────────
# We list explicit paths rather than using --include to keep the bundle small
# and the manifest auditable.
INCLUDES=()

# 1. Real .env files (skip .env.example since those are git-tracked)
while IFS= read -r f; do
  [[ -n "$f" ]] && INCLUDES+=("$f")
done < <(
  find . -maxdepth 4 -type f \
    \( -name '.env' -o -name '.env.bak.*' \) \
    -not -path './.git/*' \
    -not -path './.venv*/*' \
    -not -path './node_modules/*' 2>/dev/null
)

# 2. Runtime state directories (gitignored — NarAI's actual memory lives here)
#    data/                — top-level autopilot queues, registries, calendars
#    narai/data/          — narai.db SQLite, chroma vector store, memory_store
#    bots/data/           — bot health, activity, knowledge bases
[[ -d data ]]       && INCLUDES+=("data")
[[ -d narai/data ]] && INCLUDES+=("narai/data")
[[ -d bots/data ]]  && INCLUDES+=("bots/data")

# 3. Specific credential files that may live outside data/
for f in \
  canva_token.json \
  canva_backup_codes.txt \
  youtube_client_secret.json \
  client_secret.json
do
  [[ -f "$f" ]] && INCLUDES+=("$f")
done

# 4. Python version pin (we'll create one in this PR; export if it exists)
[[ -f .python-version ]] && INCLUDES+=(".python-version")

# 5. Local Claude config that's worth preserving (skill state, hooks)
[[ -d .claude ]] && INCLUDES+=(".claude")

# 6. Remember/state from session helper
[[ -d .remember ]] && INCLUDES+=(".remember")

# Deduplicate (portable across bash 3.2 on stock macOS)
DEDUPED=()
declare -a SEEN_KEYS=()
for f in "${INCLUDES[@]}"; do
  already=0
  for k in "${SEEN_KEYS[@]:-}"; do
    [[ "$k" == "$f" ]] && { already=1; break; }
  done
  if [[ $already -eq 0 ]]; then
    DEDUPED+=("$f")
    SEEN_KEYS+=("$f")
  fi
done
INCLUDES=("${DEDUPED[@]}")

if [[ ${#INCLUDES[@]} -eq 0 ]]; then
  die "Nothing to export. Are you in the right repo?"
fi

# ── Show manifest, get confirmation ─────────────────────────────────────────
echo
log "Will bundle the following ($(echo ${#INCLUDES[@]}) entries):"
for f in "${INCLUDES[@]}"; do
  if [[ -d "$f" ]]; then
    sz=$(du -sh "$f" 2>/dev/null | awk '{print $1}')
    printf "  📁 %-50s %s\n" "$f" "$sz"
  else
    sz=$(du -h "$f" 2>/dev/null | awk '{print $1}')
    printf "  📄 %-50s %s\n" "$f" "$sz"
  fi
done
echo

read -r -p "Proceed? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || die "Aborted."

# ── Build tarball ───────────────────────────────────────────────────────────
TS="$(date +%Y%m%d-%H%M%S)"
TAR="wheellsverse-secrets-${TS}.tar.gz"
GPG_OUT="${TAR}.gpg"

log "Creating $TAR…"
# Use -c (gzip), -f (file), -- to terminate options.
tar -czf "$TAR" -- "${INCLUDES[@]}"
ok "Tarball: $(du -h "$TAR" | awk '{print $1}')"

# ── Encrypt ─────────────────────────────────────────────────────────────────
log "Encrypting with GPG (you'll be prompted for a passphrase — TWICE)…"
warn "Use a long passphrase you can recall. Diceware or a sentence works well."
warn "You'll type this exact passphrase ONCE on the new mini to decrypt."

# AES-256, no compression (already gzipped), batch mode off so the user is prompted
gpg --symmetric --cipher-algo AES256 --output "$GPG_OUT" "$TAR"

# Wipe the cleartext tarball
rm -f "$TAR"
ok "Encrypted bundle: $GPG_OUT ($(du -h "$GPG_OUT" | awk '{print $1}'))"

# ── Final ───────────────────────────────────────────────────────────────────
echo
ok "Done."
echo
echo "Bundle saved to:"
echo "  $REPO_ROOT/$GPG_OUT"
echo
echo "To restore on the new mini (after running 01-bootstrap.sh):"
echo "  bash $REPO_ROOT/scripts/mac-mini/03-restore-on-mini.sh \\"
echo "       $REPO_ROOT/$GPG_OUT"
echo
warn "Transfer the bundle via the external drive or scp — NOT AirDrop/iCloud."
warn "After the new mini is fully verified, securely delete the bundle:"
warn "  rm -P $GPG_OUT"
