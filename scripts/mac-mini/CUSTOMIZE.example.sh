#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Personal customization slot for 01-bootstrap.sh
#
# 01-bootstrap.sh sources scripts/mac-mini/CUSTOMIZE.sh if it exists.
# Copy this file to CUSTOMIZE.sh and edit the THREE blocks below to taste.
#
#   cp CUSTOMIZE.example.sh CUSTOMIZE.sh
#
# This is the ONLY hand-edited piece of the migration. Everything else is
# scripted and reproducible. Don't commit CUSTOMIZE.sh (it's per-machine);
# you can keep it on the external drive next to the bundle.
# ─────────────────────────────────────────────────────────────────────────────

# ── BLOCK 1: GUI apps (brew casks) ──────────────────────────────────────────
# Comment OUT what you don't want. Add others. These are NOT installed by
# default in 01-bootstrap.sh because tastes vary.
GUI_CASKS=(
  # — editors / terminals —
  # visual-studio-code
  # cursor
  # warp                # AI-native terminal (alternative to Terminal.app)
  # iterm2

  # — dev infra —
  # docker              # Docker Desktop
  # orbstack            # lighter Docker Desktop alternative (Apple Silicon native)
  # tableplus           # SQL GUI

  # — productivity —
  # raycast             # better Spotlight + clipboard history
  # rectangle           # window snapping
  # obsidian            # notes / second brain

  # — comms / browsers —
  # arc                 # browser
  # google-chrome
  # discord
  # slack

  # — media (NarAI / Shopify work) —
  # figma
  # obs                 # streaming/screen recording
)

for cask in "${GUI_CASKS[@]}"; do
  if brew list --cask "$cask" >/dev/null 2>&1; then
    ok "$cask cask already installed"
  else
    log "Installing cask: $cask"
    brew install --cask "$cask" || warn "$cask failed (may need manual download)"
  fi
done

# ── BLOCK 2: Shell aliases / functions ──────────────────────────────────────
# These get appended to ~/.zshrc only if the marker line isn't already there.
# Edit to your style. Common ones for this project below.
ALIAS_MARKER="# WheellsVerse aliases — added by CUSTOMIZE.sh"

if ! grep -qF "$ALIAS_MARKER" "$HOME/.zshrc" 2>/dev/null; then
  cat >> "$HOME/.zshrc" <<'ZSHRC'

# WheellsVerse aliases — added by CUSTOMIZE.sh
alias wv='cd /Volumes/Wheellsverse/wheellsverse_bots && source .venv-mini/bin/activate'
alias wvtest='wv && python -m pytest -q'
alias wvup='wv && railway up'
alias wvlogs='wv && railway logs --service wheellsverse-v2'
alias narai='wv && python -m narai.api.main'

# Quick Claude Code from the repo
alias cclaude='wv && claude'

# Git shortcuts
alias gs='git status -sb'
alias gd='git diff'
alias gp='git pull --rebase'

ZSHRC
  ok "Added WheellsVerse aliases to ~/.zshrc"
else
  ok "Aliases already in ~/.zshrc — skipping"
fi

# ── BLOCK 3: Extra brew formulae beyond the bootstrap defaults ──────────────
# 01-bootstrap.sh installs the essentials. Add anything else you rely on.
EXTRA_FORMULAE=(
  # postgresql@16
  # redis
  # imagemagick          # image manipulation (covers + Pillow fallbacks)
  # poppler              # PDF rendering for KDP previews
  # lazygit              # TUI git client
  # bat                  # better cat
  # eza                  # better ls
  # gnu-tar              # for bundles produced by GNU systems
)

for f in "${EXTRA_FORMULAE[@]}"; do
  if brew list --formula "$f" >/dev/null 2>&1; then
    ok "$f already installed"
  else
    brew install "$f"
  fi
done
