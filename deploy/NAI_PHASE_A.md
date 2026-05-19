# NAI Phase A — Mac mini daemonization runbook

Stage 5 of the NAI Companion AI MVP. This is **ops scaffolding only** — no
business logic — running the code Stages 0–4 produced.

For the broader WheellsVerse bot deployment (Docker / Railway / Fly), see
`README.md` in the same directory. The two are independent.

> **TCC heads-up:** the repo lives at `/Volumes/Wheellsverse/wheellsverse_bots`.
> macOS Transparency, Consent, and Control may block LaunchAgents whose
> executable lives on an external volume. See "TCC mitigation" below before
> `launchctl load -w`.

---

## Artifacts in this directory

| File | Role |
|---|---|
| `start_nai.sh` | Wrapper invoked by `com.wheellsverse.nai.plist`. Loads `.env`, validates secrets, exec's uvicorn. |
| `launchd/com.wheellsverse.nai.plist` | LaunchAgent: keeps NAI running, restarts on crash. |
| `launchd/com.wheellsverse.ollama.plist` | LaunchAgent: keeps Ollama running. **Skip if you use `brew services start ollama` instead.** |
| `health_check.sh` | Cron-driven liveness check, log-only. Phase A has no alerting. |
| `status.sh` | One-command Phase A snapshot. Worth aliasing as `nai-status`. |
| `newsyslog.wheellsverse.conf` | Log rotation — install via `sudo cp` to `/etc/newsyslog.d/`. |

---

## Install sequence (on the Mac mini)

### 1. Pre-flight (manual — do not skip)

Before installing any LaunchAgent, confirm NAI runs by hand end-to-end:

```bash
cd /Volumes/Wheellsverse/wheellsverse_bots
source .venv/bin/activate
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8001
# Wait for "Application startup complete"
```

In another terminal: hit `/docs`, grab a JWT from `POST /auth/login`, send a
`POST /nai/chat` and a `GET /nai/chat/stream`, then open
`http://127.0.0.1:8001/nai-ui/` and run the memory save/recall flow with
**Use tools** on. If any of that fails, fix it before daemonizing.

### 2. Log directory

```bash
mkdir -p ~/Library/Logs/wheellsverse
touch ~/Library/Logs/wheellsverse/{nai,ollama}.{stdout,stderr}.log
touch ~/Library/Logs/wheellsverse/health.log
```

### 3. Make scripts executable

```bash
chmod +x deploy/start_nai.sh deploy/health_check.sh deploy/status.sh
```

### 4. Sanity-run the wrapper outside launchd

```bash
./deploy/start_nai.sh
# Ctrl-C after "Application startup complete"
```

### 5. Pick an Ollama strategy

**Option A — Homebrew** (if `which ollama` is `/opt/homebrew/bin/ollama`):
```bash
brew services start ollama
```

**Option B — Custom plist** (this Mac mini: `which ollama` is `/usr/local/bin/ollama`):
```bash
cp deploy/launchd/com.wheellsverse.ollama.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.wheellsverse.ollama.plist
```

### 6. Load the NAI plist

```bash
cp deploy/launchd/com.wheellsverse.nai.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.wheellsverse.nai.plist

launchctl list | grep -E "(wheellsverse|ollama)"

sleep 5
curl -sf http://127.0.0.1:8001/docs >/dev/null && echo "nai OK"
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && echo "ollama OK"
```

### 7. Log rotation (newsyslog)

```bash
sudo cp deploy/newsyslog.wheellsverse.conf /etc/newsyslog.d/wheellsverse.conf
sudo newsyslog -nv     # dry-run; lists every log without errors
```

### 8. Health-check cron

```bash
(crontab -l 2>/dev/null; \
 echo "*/5 * * * * /Volumes/Wheellsverse/wheellsverse_bots/deploy/health_check.sh") \
 | crontab -

crontab -l | grep health_check
# Wait 5 min:
tail -3 ~/Library/Logs/wheellsverse/health.log
```

### 9. Sleep policy

The Mac mini will otherwise sleep its CPU and stall HTTP.

```bash
sudo pmset -c sleep 0
sudo pmset -c disksleep 0
sudo pmset -c displaysleep 30   # display sleep is fine
sudo pmset -g                   # verify
```

### 10. The reboot test

```bash
launchctl list | grep wheellsverse    # snapshot before
sudo reboot
```

After reboot + login (or autologin):

```bash
sleep 30
launchctl list | grep -E "(wheellsverse|ollama)"
curl -sf http://127.0.0.1:8001/docs >/dev/null && echo "nai OK"
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && echo "ollama OK"
./deploy/status.sh
# Open http://127.0.0.1:8001/nai-ui/ → "you alive?"
```

If both endpoints come back and the browser chat works → **Phase A is shipped.**

```bash
git tag phase-a-complete
git push --tags
```

---

## TCC mitigation (the /Volumes/ wrinkle)

macOS may refuse to execute LaunchAgent scripts living on external volumes.
Symptom: `launchctl list | grep wheellsverse` shows a non-zero exit code, or
the agent doesn't appear at all. Three options:

1. **Grant access (simplest).** System Settings → Privacy & Security →
   Files and Folders → "External Volumes" → enable for launchd if prompted.
   Or grant "Full Disk Access" to `/usr/sbin/launchd` (or to your terminal,
   if installing interactively).
2. **Move the wrapper off /Volumes/.**
   ```bash
   mkdir -p ~/bin
   cp deploy/start_nai.sh ~/bin/start_nai.sh
   ```
   Edit `~/Library/LaunchAgents/com.wheellsverse.nai.plist` so
   `ProgramArguments` points at `/Users/jhonwheeler/bin/start_nai.sh`. The
   wrapper still cd's into `/Volumes/Wheellsverse/wheellsverse_bots` to run
   uvicorn from the venv there.
3. **Pivot to a Login Item .app bundle.** The user's existing NarAI Supreme
   v1 already uses this pattern. More setup than a plist but TCC-clean. See
   the `narai_supreme_v1` memory for the recipe.

---

## Operations cheat sheet

```bash
# Status
./deploy/status.sh
tail -f ~/Library/Logs/wheellsverse/nai.stderr.log
crontab -l | grep health_check

# Restart
launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai

# Stop (this actually stops because KeepAlive is a dict, not a bare true)
launchctl stop com.wheellsverse.nai

# Unload (permanent until reload)
launchctl unload ~/Library/LaunchAgents/com.wheellsverse.nai.plist

# Force log rotation
sudo newsyslog -v
```
