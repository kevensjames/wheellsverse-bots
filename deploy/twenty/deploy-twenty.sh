#!/usr/bin/env bash
# Deploy a self-hosted Twenty CRM on a SEPARATE host (a small VPS or spare box).
#
# Do NOT run this on the Mac mini that hosts KAI — that box is already maxed
# (KAI daemon + Ollama + Login Items on 16GB). Twenty is a full stack
# (Postgres + Redis + server + worker + frontend) and wants its own host.
#
# This pulls Twenty's OFFICIAL docker-compose + env template (it does not run
# any code from this repo). Versions evolve — if anything drifts, follow the
# current docs at https://twenty.com/developers/section/self-hosting
#
# Usage:  SERVER_URL=https://crm.yourdomain.com bash deploy-twenty.sh
set -euo pipefail

SERVER_URL="${SERVER_URL:-}"
TWENTY_DIR="${TWENTY_DIR:-$HOME/twenty}"
COMPOSE_URL="https://raw.githubusercontent.com/twentyhq/twenty/main/packages/twenty-docker/docker-compose.yml"
ENV_URL="https://raw.githubusercontent.com/twentyhq/twenty/main/packages/twenty-docker/.env.example"

if [ -z "$SERVER_URL" ]; then
  echo "Set SERVER_URL to your public HTTPS URL, e.g.:"
  echo "  SERVER_URL=https://crm.yourdomain.com bash deploy-twenty.sh"
  exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "Install Docker first: https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 required (docker compose)."; exit 1; }

mkdir -p "$TWENTY_DIR" && cd "$TWENTY_DIR"
echo "→ fetching Twenty's official compose + env into $TWENTY_DIR"
curl -fsSL "$COMPOSE_URL" -o docker-compose.yml
curl -fsSL "$ENV_URL"     -o .env

# Generate secrets + wire SERVER_URL into .env (idempotent-ish; edits in place).
APP_SECRET="$(openssl rand -base64 32)"
PG_PW="$(openssl rand -base64 24 | tr -d '/+=')"
set_kv() { # set_kv KEY VALUE  → upsert KEY=VALUE in .env
  if grep -q "^$1=" .env; then
    # use a non-/ delimiter since values contain base64 chars
    sed -i.bak "s|^$1=.*|$1=$2|" .env && rm -f .env.bak
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
set_kv SERVER_URL  "$SERVER_URL"
set_kv APP_SECRET  "$APP_SECRET"
set_kv PG_DATABASE_PASSWORD "$PG_PW"

echo "→ starting Twenty (Postgres + Redis + server + worker + frontend)"
docker compose up -d

cat <<EOF

✅ Twenty is starting at $TWENTY_DIR (frontend listens on :3000 by default).

Next:
  1. Put a reverse proxy in front for HTTPS (see Caddyfile in this folder):
       sudo caddy run --config ./Caddyfile     # or run caddy as a service
  2. Open $SERVER_URL, create the workspace + admin user.
  3. Settings → Developers → generate an API key.
  4. Point KAI at it — in KAI's root .env (ABOVE the WORDPRESS_TOKEN landmine):
       TWENTY_API_URL=$SERVER_URL
       TWENTY_API_KEY=<the API key>
     then restart the KAI daemon. KAI's twenty_crm tool registers automatically.

Secrets generated (store them): APP_SECRET + PG_DATABASE_PASSWORD are in .env.
EOF
