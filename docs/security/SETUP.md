# Security Center — Setup

Phase 1 ships the code; these are the one-time operator steps to make it live.
Until they're done, the dashboard honestly shows "unknown"/"not configured" and
the score stays low — that is correct, not a bug.

## 1. Install scanners

```bash
brew install trivy restic trufflehog   # gitleaks is already installed
```

The worker reports any missing binary as a setup task rather than crashing.

## 2. Backblaze B2 (encrypted off-site backups)

- Create a private B2 bucket (e.g. `kai-backups`) and an application key.
- Store the credentials in **wvkey** (NOT `.env` — that is the whole point):

```bash
wvkey set B2_ACCOUNT_ID   <keyID>
wvkey set B2_ACCOUNT_KEY  <appKey>
wvkey set RESTIC_PASSWORD <strong-passphrase>
```

- Point restic at the bucket and initialize it once:

```bash
export RESTIC_REPOSITORY="b2:kai-backups"
restic init
```

`RESTIC_REPOSITORY`, `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`, and `RESTIC_PASSWORD`
must be present in the worker's environment when it runs.

## 3. Enable the scopes

```bash
export KAI_SCOPE_SECURITY=1        # parent — enables security.*
export KAI_SCOPE_SECURITY_SCAN=1   # the audited "queue a scan" action
```

## 4. Load the launchd jobs

```bash
cp deploy/com.wheellsverse.kai.security-*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wheellsverse.kai.security-scan.plist
launchctl load ~/Library/LaunchAgents/com.wheellsverse.kai.security-trigger.plist
```

- `security-scan` runs a full scan daily at 13:00 UTC.
- `security-trigger` checks every ~5 min for a `data/security/.request` marker
  (written by the dashboard "scan now" button) and runs the worker on demand.
- Grant the worker Full Disk Access if scanning paths require it (consistent
  with the host's TCC posture for `/Volumes/*`).

## 5. Verify

```bash
python3 scripts/security_worker.py        # one manual run
# then open the KAI Command Center → Security tab (🔐)
#   /kai-ui/admin.html  → paste ADMIN_TOKEN → Security
```

You should see an honest score with per-category breakdown ("unknown" where a
category isn't monitored yet) and any redacted findings.

## Scan targets (defaults; override via env)

- `KAI_SECURITY_SCAN_PATHS` — colon-separated; defaults to the repo root.
  Recommended: `~/wheellsverse_bots:/Volumes/Wheellsverse` (live repo + clone).
- `KAI_SECURITY_BACKUP_PATHS` — colon-separated; defaults to `<repo>/data`.
  Recommended: add `~/.config/wvkey/vault.enc` and key configs.
- `KAI_SECURITY_DIR` — where results are stored; defaults to `<repo>/data/security`.
