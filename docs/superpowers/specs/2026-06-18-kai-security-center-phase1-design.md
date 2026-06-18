# KAI Security Center — Phase 1 Design

- **Date:** 2026-06-18
- **Status:** Approved design (brainstorming complete) → next: implementation plan
- **Author:** Claude (with operator)
- **Repo:** `~/wheellsverse_bots` (live daemon) · **Branch:** `nexora/phase1-auth`
- **Scope of this spec:** Phase 1 only. Phases 2–4 get their own specs.

---

## 1. Purpose

Add a **Security Center** module to KAI/NarAI that genuinely hardens *this* deployment
(a single Apple M4 Mac mini, 16 GB RAM, running the bot fleet 24/7; prod on Railway).
Phase 1 delivers three real capabilities plus an honest score, surfaced on a new
`/admin/security` dashboard tab:

1. **Secret Scanner** — find leaked credentials in repos, working tree, and `.env`/`.bak`.
2. **Vulnerability Scanner** — find Critical/High CVEs in dependencies + IaC misconfig.
3. **Backup Monitoring** — set up encrypted off-site backups (restic → Backblaze B2) and monitor freshness.
4. **Security Score** — a 6-category posture score computed entirely from real signals.

This is **defensive hardening of the real system**, not an enterprise SOC/SIEM product.

## 2. Non-goals (and why)

These were in the original brief but are explicitly **out** because they do not fit the host
or solve a problem this deployment has:

- **Wazuh / OSSEC / Elastic / OpenSearch / OpenVAS** — multi-GB SIEM/scanner stacks; will not
  fit in 16 GB alongside the fleet; built for fleets of network hosts, not one Mac.
- **Falco** — Linux kernel/eBPF only; **cannot run on macOS**.
- **Suricata / Zeek** — network IDS needing a tap/SPAN port; low value behind a home router.
- **Keycloak / Authelia** — full IdP for a solo operator with one admin is massive overkill;
  MFA + RBAC will be built *inside* KAI in **Phase 2** instead.
- **Velero** — Kubernetes-only; there is no k8s here.
- **Dockle / OWASP Dependency-Check** — Dockle needs images (engine is off); Trivy supersedes
  Dependency-Check for our ecosystems.
- **CrowdSec / Prometheus / Grafana / Loki** — deferred to an optional **Phase 4** (observability).

Phase 1 also does **not** change authentication (that is Phase 2) or add the Agent Permission
Manager (Phase 3).

## 3. Constraints / reality baseline

- Host: Apple M4, **16 GB RAM**, 10 CPUs, fleet running 24/7. Docker **engine not running**.
- Prod on Railway (operator does not control that edge).
- Live daemon: `~/wheellsverse_bots`, launchd `com.wheellsverse.nai`. A clone lives at `/Volumes/Wheellsverse`.
- **Existing, reused machinery (do not rebuild):**
  - `services/governance/` — `@audited(scope, destructive)`, `is_scope_enabled()`,
    approval gates (`PendingApproval`), kill-switches, append-only `data/governance/audit.jsonl`.
  - `services/audit/auditor.py` — self-audit; `SUBSYSTEMS` registry drives dashboard tabs;
    `GET /admin/audit/run`.
  - `tools/wvkey` — AES-256-GCM secrets vault (master key in macOS Keychain; 217 keys).
  - Auth today: static `X-Admin-Token` via `require_admin_token` (no MFA/RBAC — a known gap).
  - Data stores: house style is JSON/JSONL under `data/`.
  - Scheduling: in-process `services/*/scheduler.py` **and** standalone launchd jobs
    (e.g. `com.wheellsverse.kai.tier-heal`).
  - Tests: pytest under `backend/tests/`, conftest production-DB guard.
- Binaries: `gitleaks` installed; `trivy`, `restic`, `trufflehog` need `brew install`.
- **No backups exist anywhere yet** — Phase 1 sets them up.

## 4. Architecture — isolated worker, daemon reads only

The decisive property: the FastAPI **money daemon never executes a scanner**. Scanners run in a
**separate launchd-managed process**, write results to files, and the daemon only **reads** those
files (and writes a 1-byte trigger marker for on-demand scans).

```text
┌─────────────────────────────────────────────────────────────┐
│  ISOLATED WORKER  (separate process, launchd-managed)         │
│  scripts/security_worker.py                                   │
│   • invoked by launchd (daily) OR by the trigger job when     │
│     data/security/.request is present; lockfile-guarded       │
│   • shells out to:  gitleaks · trivy · trufflehog · restic    │
│   • normalizes → Finding records (REDACTED), computes nothing │
│   • writes findings → data/security/*.jsonl + latest.json     │
│   • is NEVER imported by the daemon                           │
└───────────────┬─────────────────────────────────────────────┘
                │  files only — one-way boundary
                ▼
   data/security/  secrets.jsonl  vulns.jsonl  backup.jsonl
                   scans.jsonl    latest.json   .request (trigger)
                ▲
                │  read-only
┌───────────────┴─────────────────────────────────────────────┐
│  KAI DAEMON  (FastAPI — READ ONLY w.r.t. security)            │
│  services/security/store.py    → load latest.json / *.jsonl   │
│  services/security/score.py    → compute Security Score       │
│  routers/admin_security.py     → GET endpoints + @audited     │
│                                  "queue scan" (writes .request)│
│  auditor.SUBSYSTEMS            → adds "security" tab #14       │
│  frontend/admin/index.html     → Security tab UI              │
└──────────────────────────────────────────────────────────────┘
```

**Why the file boundary:** the daemon can read JSON and write a trigger, but cannot be coerced into
running a scanner with attacker-influenced arguments (no command-injection surface), and a scanner
CPU spike or hang cannot stall request handling. Same collector/query trust boundary a SIEM uses,
realized with files.

## 5. Components

Each unit is small, single-purpose, and independently testable.

| Unit | Path | Responsibility | Depends on |
|---|---|---|---|
| Worker entrypoint | `scripts/security_worker.py` | Orchestrate runners; honor schedule + `.request`; atomic-write store; Telegram on new Critical/verified | runners, store, B2 env |
| Runner: secrets | `backend/app/services/security/runners/secrets.py` | Build argv for gitleaks + trufflehog; parse JSON → `Finding[]` (redacted) | gitleaks, trufflehog CLIs |
| Runner: vulns | `backend/app/services/security/runners/vulns.py` | Trivy `fs --scanners vuln,secret,misconfig`; parse → `Finding[]` | trivy CLI |
| Runner: backup | `backend/app/services/security/runners/backup.py` | restic init/backup/check; emit snapshot age + check result | restic CLI, B2 env |
| Store | `backend/app/services/security/store.py` | Read/write `data/security/` JSONL + `latest.json`; atomic writes; redaction enforced | filesystem |
| Score | `backend/app/services/security/score.py` | **Pure** fn: findings + posture facts → `SecurityScore` breakdown | store, auditor facts |
| Models | `backend/app/services/security/models.py` | `Finding`, `ScanResult`, `SecurityScore` dataclasses/Pydantic | — |
| Router | `backend/app/routers/admin_security.py` | `GET /admin/security/{summary,findings,score}`; `POST /admin/security/scan` (@audited) | store, score, `require_admin_token` |
| launchd (scheduled) | `deploy/com.wheellsverse.kai.security-scan.plist` | Daily scan | — |
| launchd (on-demand) | `deploy/com.wheellsverse.kai.security-trigger.plist` | ~5-min marker check | — |
| Tab wiring | `auditor.SUBSYSTEMS` + `frontend/admin/index.html` | Register tab #14 + UI | auditor |
| Docs | `SECURITY_RULES.md` (repo root) | Standing rules + security-architect review prompt | — |

Runner adapters live under `services/security/runners/` so they are importable by both the worker
(to run) and tests (to parse fixtures), but the **worker is the only process that invokes them**.

## 6. Data model & store

Directory: `data/security/`

- `secrets.jsonl`, `vulns.jsonl`, `backup.jsonl`, `scans.jsonl` — append-only history (one record per line).
- `latest.json` — the most recent consolidated snapshot the daemon reads for the dashboard.
- `.request` — trigger marker (presence = "operator queued a scan"); cleared by the worker.

`Finding` (redacted by construction):

```text
{ "id", "ts", "category": "secret|vuln|backup",
  "severity": "critical|high|medium|low|info",
  "tool": "gitleaks|trufflehog|trivy|restic",
  "title", "location": "<file:line or pkg>",
  "fingerprint": "<sha256 of secret/identity>",   # NEVER the secret value
  "verified": true|false,                          # trufflehog live-credential check
  "metadata": { ... non-sensitive ... } }
```

`latest.json`: `{ generated_at, by: "scheduled|on-demand", counts_by_severity,
findings[], backup: {last_snapshot_age_s, check_ok, repo}, runner_status, score }`.

**Redaction is a store-layer invariant**, enforced and unit-tested: the store rejects/strips any raw
secret value before persisting. The security store must never become the file an attacker reads to
harvest keys.

## 7. Security Score model

Six categories (kept from the original brief), each scored 0–100 from real signals, combined into a
weighted overall score. A category with no data reports **"unknown"** (rendered as such, weighted
out of the overall) — it is **never** silently treated as 100.

| Category | Phase-1 signals |
|---|---|
| Authentication | static `X-Admin-Token`, no MFA, no user table → low (raised in Phase 2) |
| Encryption / secrets-at-rest | wvkey vault present (+); plaintext `.env`/`.bak` on disk (−); gitleaks/trufflehog findings (−) |
| Backups | restic last-snapshot age + `restic check` result (0% until a fresh B2 snapshot exists) |
| API Security | Railway HTTPS (+), bearer-key tiers (+), rate-limiting present? (flag if absent) |
| Agent Security | scopes + `@audited` + kill-switches + approval gates + RCE classifier → high |
| Infrastructure / Vulns | Trivy Critical/High CVE count |

**Integrity rules (tested):** (1) *unknown ≠ pass* — a runner that did not complete drops its category
to "unmonitored," so a broken worker cannot inflate the score; (2) the score is a **pure function** of
inputs (deterministic, table-testable).

**Operator-owned configuration:** category **weights** and Critical/High **thresholds** encode the
operator's risk appetite. They live in `score.py` as `_category_weights()` / penalty constants. During
implementation the operator fills these (~8 lines) with the author's defaults as a starting point.

## 8. Scan targets

- **Secrets:** gitleaks (git history + working tree) and trufflehog (`--only-verified` to confirm live
  creds) over `~/wheellsverse_bots`, `.env` / `.env.*` / `.bak`, **and** the `/Volumes/Wheellsverse`
  clone (it sits on an external SSD and can hold stale secrets — worth covering).
- **Vulns:** Trivy `fs --scanners vuln,secret,misconfig` over `~/wheellsverse_bots` (Python reqs,
  lockfiles) + IaC/plist misconfig.
- **Backup:** restic repo on B2; back up `data/`, the wvkey vault (`~/.config/wvkey/vault.enc`), and key
  configs; monitor via `restic check` + snapshot age.

## 9. Error handling

- Each runner isolated in try/except — a missing/failed tool records `status: error` for *that*
  category (→ "unknown"); other runners still complete.
- Missing binary surfaces as a **setup task** in the UI (`trivy not installed → brew install trivy`),
  not a crash.
- **Atomic writes** (tmp file + `os.rename`) so the daemon never reads a half-written `latest.json`.
- Daemon read path is **fail-soft**: no `latest.json` yet → "no data" state, never a 500.
- Worker is idempotent and safe to run concurrently-guarded by a lockfile (`data/security/.lock`).

## 10. Testing (pytest, `backend/tests/` conventions)

- **Runner adapters:** unit tests against captured fixture JSON from each tool — no live scan.
- **`score.py`:** table-driven cases incl. the "honest low" baseline and "unknown ≠ 100".
- **`store.py`:** tmp-dir round-trip **+ redaction test** asserting no raw secret is ever persisted.
- **Router:** TestClient asserts `X-Admin-Token` gating, `@audited` scope, and that `POST /scan` only
  writes `.request` (spawns no process).
- Respect conftest production-DB guard; security stores are file-based (no DB migration needed).

## 11. Setup / deploy deltas

- `brew install trivy restic trufflehog` (gitleaks already present). Worker reports any missing binary.
- **Backblaze B2:** operator creates a bucket + application key, then stores `B2_ACCOUNT_ID`,
  `B2_ACCOUNT_KEY`, and `RESTIC_PASSWORD` in **wvkey** (not `.env`). Worker reads them from the
  environment injected at startup.
- Two launchd plists in `deploy/`: scheduled daily scan + ~5-min trigger check. Operator must grant
  Full Disk Access if scanning paths require it (consistent with the host's TCC posture).
- New scope flags: `KAI_SCOPE_SECURITY` (parent), `KAI_SCOPE_SECURITY_SCAN`.
- `SECURITY_RULES.md` + the security-architect review prompt committed at repo root.

## 12. Relationship to existing governance

- The `POST /admin/security/scan` endpoint uses `@audited(scope="security.scan", destructive=False)`,
  so every operator-triggered scan is recorded in the existing `audit.jsonl` with the same redaction.
- The Security Center **reads** auditor posture facts for the Agent Security and Authentication
  categories rather than duplicating them.
- Tab #14 is registered by adding a row to `auditor.SUBSYSTEMS` (`tab: "security"`), matching how all
  existing tabs are wired.

## 13. Phasing (future specs)

- **Phase 2 — Identity hardening:** user table + TOTP MFA + real RBAC, replacing static `X-Admin-Token`.
- **Phase 3 — Agent Permission Manager:** per-agent allowed tools/APIs/commands/files via scopes/@audited.
- **Phase 4 (optional) — Observability:** Prometheus + Grafana + Loki + CrowdSec at the local tunnel edge.

## 14. Open decisions resolved during brainstorming

- Intent: **harden this deployment** (not SOC product).
- First phase: **Scanners + Backup + Score**.
- Execution: **isolated worker; daemon reads results, never shells out**.
- Backup destination: **Backblaze B2** (off-site DR).
- Score categories: **keep the original 6** (real-signal-derived).
- Scan targets: include **both** the live repo and the `/Volumes/Wheellsverse` clone.
- Backup contents: `data/` + wvkey vault + key configs (as listed in §8).
- Remaining operator input at implementation time: **score weights/thresholds** in `score.py`.

## 15. Success criteria

- Security tab #14 renders an honest score with per-category breakdown and "unknown" where unmonitored.
- A scheduled scan and an on-demand "Scan now" both produce a fresh `latest.json` without the daemon
  spawning any process.
- Secret/vuln findings appear with redacted fingerprints (no raw secrets in any persisted file —
  verified by test).
- restic backs up to B2 and the Backup category reflects real snapshot freshness + `restic check`.
- All new units covered by passing pytest tests; no regression in existing suite.
