#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# WheellsVerse — New Mac mini bootstrap (Apple Silicon)
#
# WHAT THIS DOES
#   Installs the base dev environment on a clean macOS install:
#   Xcode CLT → Homebrew (/opt/homebrew) → mise (Python/Node/Ruby pin) →
#   git/gh/railway/vercel CLIs → Claude Code → media tooling (ffmpeg) →
#   GPG (for the secrets bundle restore step).
#
# WHEN TO RUN
#   On the NEW Mac mini, AFTER:
#     1. First-boot setup (Apple ID sign-in, FileVault, Touch ID).
#     2. Plugging in the WheellsVerse external drive.
#   Then in Terminal:
#     bash /Volumes/Wheellsverse/wheellsverse_bots/scripts/mac-mini/01-bootstrap.sh
#
# IDEMPOTENT
#   Safe to re-run. Each step checks if the tool is already present and skips.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── pretty logging ──────────────────────────────────────────────────────────
log()  { printf "\033[1;36m▸\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m✗\033[0m %s\n" "$*"; exit 1; }

# ── sanity: must be Apple Silicon ───────────────────────────────────────────
ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
  warn "uname -m reports '$ARCH'. This script targets Apple Silicon (arm64)."
  warn "If this is intentional (Intel Mac mini), the brew prefix will differ."
  read -r -p "Continue anyway? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || die "Aborted."
fi

# ── 1. Xcode Command Line Tools ─────────────────────────────────────────────
if ! xcode-select -p >/dev/null 2>&1; then
  log "Installing Xcode Command Line Tools (a GUI dialog will appear)…"
  xcode-select --install || true
  warn "After the GUI install finishes, re-run this script."
  exit 0
else
  ok "Xcode CLT present: $(xcode-select -p)"
fi

# ── 2. Homebrew (Apple Silicon prefix) ──────────────────────────────────────
BREW_PREFIX="/opt/homebrew"
if ! command -v brew >/dev/null 2>&1; then
  log "Installing Homebrew at ${BREW_PREFIX}..."
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Add brew to shell PATH for this session AND future logins
eval "$("$BREW_PREFIX/bin/brew" shellenv)"
if ! grep -q "brew shellenv" "$HOME/.zprofile" 2>/dev/null; then
  printf '\n# Homebrew (Apple Silicon)\neval "$(/opt/homebrew/bin/brew shellenv)"\n' \
    >> "$HOME/.zprofile"
  ok "Added brew shellenv to ~/.zprofile"
fi
ok "Homebrew $(brew --version | head -1)"

# ── 3. CLI tools via brew ───────────────────────────────────────────────────
BREW_FORMULAE=(
  git
  gh                # GitHub CLI
  mise              # multi-language version manager (Python/Node/Ruby)
  uv                # fast Python package installer
  gnupg             # for decrypting the secrets bundle
  ffmpeg            # NarAI media pipeline
  jq                # JSON munging
  ripgrep           # fast grep (Claude Code uses it)
  fd                # fast find
  tmux              # detached sessions for long-running bots
  watch             # for tailing scheduled jobs
  shellcheck        # lints these very scripts
)

log "Installing brew formulae: ${BREW_FORMULAE[*]}"
for f in "${BREW_FORMULAE[@]}"; do
  if brew list --formula "$f" >/dev/null 2>&1; then
    ok "$f already installed"
  else
    brew install "$f"
  fi
done

# Railway + Vercel CLIs (these are casks for some, taps for others; railway is via brew)
if ! command -v railway >/dev/null 2>&1; then
  log "Installing Railway CLI…"
  brew install railway || warn "Railway brew install failed; fall back to: curl -fsSL cli.new | sh"
fi
if ! command -v vercel >/dev/null 2>&1; then
  log "Installing Vercel CLI via npm (after mise+node ready)…"
fi

# ── 4. Language runtimes via mise ───────────────────────────────────────────
# mise reads .tool-versions in the repo. We pin Python here to match prod
# (Dockerfile + CI both use 3.11). Node 22 LTS for Shopify theme + dashboards.
log "Configuring mise…"
if ! grep -q "mise activate" "$HOME/.zshrc" 2>/dev/null; then
  printf '\n# mise — language version manager\neval "$(mise activate zsh)"\n' \
    >> "$HOME/.zshrc"
  ok "Added mise activate to ~/.zshrc"
fi
eval "$(mise activate bash)"  # for this script's session

# Pin global versions (overridable per-project by .tool-versions)
mise use --global python@3.11
mise use --global node@22
ok "mise: python $(mise exec -- python3 --version 2>&1 | tail -1), node $(mise exec -- node --version 2>&1 | tail -1)"

# Now we have node → install Vercel CLI globally
if ! command -v vercel >/dev/null 2>&1; then
  mise exec -- npm install -g vercel
  ok "Vercel CLI installed"
fi

# ── 5. Claude Code ──────────────────────────────────────────────────────────
if ! command -v claude >/dev/null 2>&1; then
  log "Installing Claude Code…"
  mise exec -- npm install -g @anthropic-ai/claude-code
  ok "Claude Code installed: $(claude --version 2>&1 || echo unknown)"
else
  ok "Claude Code present: $(claude --version 2>&1 | head -1)"
fi

# ── 6. Optional GUI apps (cask) ─────────────────────────────────────────────
# ✋ CUSTOMIZATION SLOT — see scripts/mac-mini/CUSTOMIZE.sh
# That file is sourced if it exists. Put your personal preferences there
# (extra brew casks, dotfile aliases, app installs).
CUSTOMIZE="$(dirname "$0")/CUSTOMIZE.sh"
if [[ -f "$CUSTOMIZE" ]]; then
  log "Sourcing your CUSTOMIZE.sh…"
  # shellcheck disable=SC1090
  source "$CUSTOMIZE"
else
  warn "No CUSTOMIZE.sh found — skipping personal customizations."
  warn "Create $CUSTOMIZE to add casks/aliases. See CUSTOMIZE.example.sh"
fi

# ── 7. SSH key for GitHub (optional, recommended) ───────────────────────────
SSH_KEY="$HOME/.ssh/id_ed25519"
if [[ ! -f "$SSH_KEY" ]]; then
  log "Generating ed25519 SSH key for GitHub…"
  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  ssh-keygen -t ed25519 -f "$SSH_KEY" -C "$(git config --global user.email 2>/dev/null || echo wheellsverse)-mac-mini" -N ""
  ok "Key generated. Add the public key to GitHub:"
  echo
  cat "$SSH_KEY.pub"
  echo
  warn "After adding to https://github.com/settings/keys, run: ssh -T git@github.com"
else
  ok "SSH key already exists: $SSH_KEY"
fi

# ── 8. Final ────────────────────────────────────────────────────────────────
echo
ok "Bootstrap complete."
echo
echo "Next steps:"
echo "  1. Open a NEW terminal so PATH/mise/brew take effect."
echo "  2. Run:  bash $(dirname "$0")/03-restore-on-mini.sh <secrets.tar.gz.gpg>"
echo "     (the encrypted bundle was created by 02-export-secrets.sh on the old Mac.)"
echo "  3. Authenticate CLIs:"
echo "       gh auth login        # GitHub"
echo "       railway login         # Railway"
echo "       claude               # Claude Code (will prompt for OAuth)"
echo
