# NarAI Godmode

Encrypted credential vault + browser automation for NarAI. Lets her log into your
accounts and run tasks the way you would.

## What works vs what will get you banned

**Safe with password login (browser automation):**
- Amazon KDP
- Printify admin
- Shopify admin
- Etsy, Canva
- Most CMS, dashboards, and vendor admin panels

**DO NOT use password login for these — they ban automated sign-ins:**
- Gmail / Google (use OAuth2 + Gmail API)
- Facebook / Instagram (use Graph API)
- X / Twitter (use X API v2)
- LinkedIn (use LinkedIn API)

For those, the vault stores an `api_token` instead. You wire the API client per service.

## Install

```bash
pip install playwright cryptography
playwright install chromium
```

## First setup

Generate a master key and export it — never commit it:

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"
export NARAI_VAULT_KEY="paste-the-long-string-here"
```

Add to `~/.zshrc` so NarAI reads it on boot.

## Usage

```bash
# Store creds
.venv/bin/python -m narai.godmode.cli set amazon_kdp
.venv/bin/python -m narai.godmode.cli set printify

# List
.venv/bin/python -m narai.godmode.cli list

# Open (first run: fills login. Later runs: cookies stick)
.venv/bin/python -m narai.godmode.cli open amazon_kdp create_paperback
.venv/bin/python -m narai.godmode.cli open printify
```

### Call from NarAI

```python
from narai.godmode import godmode
godmode("open amazon_kdp create_book")
```

## Security rules

1. `NARAI_VAULT_KEY` goes in env only. Never commit it.
2. `~/.narai/vault.db` is encrypted but back it up off-machine.
3. `~/.narai/profiles/` contains live session cookies. Treat as sensitive.
4. Lose the master key = all creds are toast. Keep a paper backup in a safe.
