# Self-host Twenty CRM (for KAI to use)

Two separate things:

- **KAI's `twenty_crm` tool** (already built, in `backend/app/services/tools/twenty_crm.py`)
  lets KAI read/write contacts, companies, and opportunities over Twenty's REST
  API. It's **inert until configured** — it registers only when `TWENTY_API_URL`
  + `TWENTY_API_KEY` are set in KAI's `.env`.
- **The Twenty CRM server itself** — a full app stack (Postgres + Redis + server
  + worker + frontend). This folder deploys it on a **separate host**.

> ⚠️ **Do not run Twenty on the KAI Mac mini.** That box (16GB) already runs the
> KAI daemon, Ollama, and several Login Items. Twenty wants its own host — a
> small VPS (2–4 GB RAM) is plenty.

## Deploy (on a fresh VPS)

1. Point a DNS A record (e.g. `crm.yourdomain.com`) at the VPS IP.
2. Install Docker + Docker Compose v2, and Caddy (for HTTPS).
3. Run the deploy script:
   ```bash
   SERVER_URL=https://crm.yourdomain.com bash deploy-twenty.sh
   ```
   It fetches Twenty's **official** docker-compose + env, generates `APP_SECRET`
   + a Postgres password, and starts the stack (frontend on `:3000`).
4. Front it with HTTPS — edit the domain in `Caddyfile`, then:
   ```bash
   sudo caddy run --config ./Caddyfile
   ```
5. Open `https://crm.yourdomain.com`, create the workspace + admin user, then
   **Settings → Developers → API key**.

## Wire KAI to it

In KAI's root `.env` (ABOVE the `WORDPRESS_TOKEN` line — see the .env landmine
note), add:

```
TWENTY_API_URL=https://crm.yourdomain.com
TWENTY_API_KEY=<the API key from Settings → Developers>
```

Restart the KAI daemon. `twenty_crm` registers automatically (it's whitelisted
on the Marketing Strategist preset and available to bare operator chat). Ask KAI
things like *"list my latest 10 people in the CRM"* or *"create a company
'Acme'"*.

## Notes

- Twenty's self-host setup evolves — if the compose/env URLs or steps drift,
  follow the current official docs:
  <https://twenty.com/developers/section/self-hosting>.
- KAI talks to Twenty over HTTP only; it never runs Twenty's code. This is the
  safe split: KAI *integrates with* the CRM, the CRM runs as its own service.
