#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# WheellsVerse — Restore on the new Mac mini (Apple Silicon)
#
# WHAT THIS DOES
#   1. Decrypts the secrets bundle from 02-export-secrets.sh.
#   2. Extracts .env / data/ / .claude / .remember into the repo.
#   3. Pins Python 3.11 via mise (matches Dockerfile + CI).
#   4. Creates a fresh ARM-native venv (.venv-mini) and installs deps via uv.
#   5. Runs a smoke test: import NarAI's API app + a couple of bot modules.
#
# PREREQS
#   01-bootstrap.sh already ran. New terminal opened so PATH/mise/brew live.
#   The repo exists on this mini (either on the external drive at
#   /Volumes/Wheellsverse/wheellsverse_bots, or freshly cloned).
#
# USAGE
#   bash 03-restore-on-mini.sh /path/to/wheellsverse-secrets-*.tar.gz.gpg
#
#   Optional env vars:
#     REPO_ROOT  — path to the repo (auto-detected if omitted)
#     VENV_DIR   — venv path (default: $REPO_ROOT/.venv-mini)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

log()  { printf "\033[1;36m▸\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m✗\033[0m %s\n" "$*"; exit 1; }

BUNDLE="${1:-}"
[[ -z "$BUNDLE" ]] && die "Usage: $0 <secrets.tar.gz.gpg>"
[[ -f "$BUNDLE" ]] || die "Bundle not found: $BUNDLE"

# Resolve repo root — auto-detect from this script's location, or env override
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv-mini}"

[[ -d "$REPO_ROOT/.git" ]] || die "Not a git repo: $REPO_ROOT"
cd "$REPO_ROOT"
log "Repo root: $REPO_ROOT"
log "Venv dir : $VENV_DIR"

# ── Sanity: required tools ──────────────────────────────────────────────────
for tool in gpg tar mise uv git; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool missing — re-run 01-bootstrap.sh and open a new terminal."
done

# ── 1. Decrypt + extract ────────────────────────────────────────────────────
log "Decrypting bundle (you'll be prompted for the passphrase)…"
TMP_TAR="$(mktemp -t wv-secrets).tar.gz"
trap 'rm -f "$TMP_TAR"' EXIT

gpg --decrypt --output "$TMP_TAR" "$BUNDLE" \
  || die "Decrypt failed (wrong passphrase, or bundle corrupted)."

ok "Decrypted: $(du -h "$TMP_TAR" | awk '{print $1}')"

# Show manifest before extracting so user knows what's about to land
log "Bundle contains:"
tar -tzf "$TMP_TAR" | head -40
total_entries=$(tar -tzf "$TMP_TAR" | wc -l | tr -d ' ')
echo "  … ($total_entries entries total)"
echo

# Backup any existing .env at repo root before overwriting
if [[ -f .env ]]; then
  bak=".env.before-restore.$(date +%s)"
  cp .env "$bak"
  warn "Existing .env backed up to $bak"
fi

read -r -p "Extract into $REPO_ROOT now? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || die "Aborted."

tar -xzf "$TMP_TAR" -C "$REPO_ROOT"
ok "Extracted."

# ── 2. Pin Python 3.11 via mise ─────────────────────────────────────────────
log "Pinning Python via mise…"
if [[ ! -f .python-version ]]; then
  echo "3.11" > .python-version
  ok "Created .python-version (3.11)"
fi
PY_PIN="$(cat .python-version)"
mise use python@"$PY_PIN"
ok "Active Python: $(mise exec -- python3 --version)"

# ── 3. Build venv ───────────────────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
  warn "Venv exists at $VENV_DIR — removing for a clean ARM build."
  rm -rf "$VENV_DIR"
fi

log "Creating ARM-native venv at $VENV_DIR…"
mise exec -- python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
ok "Venv active: $(which python) ($(python --version))"

# ── 4. Install deps via uv (much faster than pip) ───────────────────────────
log "Upgrading pip + installing uv into venv…"
python -m pip install --upgrade pip wheel >/dev/null
python -m pip install uv >/dev/null

REQ_FILES=(requirements.txt requirements-server.txt requirements-kdp.txt)
for req in "${REQ_FILES[@]}"; do
  if [[ -f "$req" ]]; then
    log "Installing $req via uv…"
    uv pip install -r "$req"
  fi
done
ok "Dependencies installed."

# ── 5. Smoke test ───────────────────────────────────────────────────────────
log "Smoke-testing NarAI imports…"
python - <<'PY' || die "Smoke test FAILED — see traceback above."
import sys
print(f"Python: {sys.version.split()[0]} on {sys.platform} ({sys.implementation.name})")

failures = []
modules_to_check = [
    ("narai.api.main",        "NarAI FastAPI app"),
    ("infra.brain.memory",    "Brain memory layer"),
    ("infra.brain.rag",       "Brain RAG"),
    ("core.discord_bot",      "Discord bot"),
    ("core.telegram_bot",     "Telegram bot"),
    ("core.printify_client",  "Printify client"),
]
for mod, label in modules_to_check:
    try:
        __import__(mod)
        print(f"  ✓ {label} ({mod})")
    except Exception as e:
        failures.append((mod, repr(e)))
        print(f"  ✗ {label} ({mod}): {e}")

if failures:
    print("\nSome imports failed. The venv may need extra system libs (ffmpeg, libpq, etc.)")
    sys.exit(1)
print("\nAll imports OK.")
PY
ok "Smoke test passed."

# ── 6. Final ────────────────────────────────────────────────────────────────
echo
ok "Restore complete. NarAI dev env is ready."
echo
echo "Activate the venv in any new shell:"
echo "  source $VENV_DIR/bin/activate"
echo
echo "Next:"
echo "  • gh auth status            # confirm GitHub CLI"
echo "  • railway login             # link Railway"
echo "  • claude                    # boot Claude Code in the repo"
echo "  • python -m pytest -q       # run the test suite"
echo
warn "Once everything is verified, securely delete the encrypted bundle:"
warn "  rm -P $BUNDLE"
