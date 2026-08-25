# KAI Security & Governance Source Inventory (Phase 8A)

Ground truth for the **Security & Governance Posture** mode. Built from a 6-reader
audit of App A (`core/api.py` + `core/kai_bridge.py`) and App B (`backend/app`).
**This is NOT a threat-intel/SOC surface** — there is no CVE/SAST/IDS feed at
runtime (Phase 6 finding confirmed). It surfaces *governance posture, governance
denials, and host/ops health* — honestly labeled. Provenance per datum:
`REAL` · `DERIVED` · `DEMO` · `UNAVAILABLE`.

## Severity reality (drives the whole design)
Only **two** sources carry a **measured** severity IN the data:
- **KAI Supreme host/ops scanner** — `Finding.severity` low/medium/high/critical (`backend/app/services/supreme/scanner.py:57`). **Host/ops health, not threat intel** (process/port/log/api-reachability/env-presence/disk/git).
- **App A defensive file scanner** — per-pattern severity CRITICAL…INFO (`core/security_scanner.py:53`). Malware-hash + 17 code-pattern signatures. Malware DB is EICAR-only ⇒ `known_malware` ≈ DEMO/UNAVAILABLE.

**Everything else has NO severity** — governance denials, auth/rate-limit/spend/quota events all lack a severity field. Any severity shown for them is **inferred** by one explicit rule (`inferGovernanceSeverity`, `kai-nexus-security.js`) and is always tagged `severity_origin:'inferred'`, never `measured`.

## REAL, queryable feeds
| Feed | Endpoint / location | Provenance | Notes |
|---|---|---|---|
| Governance action log + **denials** | `GET /admin/briefing/audit` → `data/governance/audit.jsonl` (`admin_briefing.py:54`, `audit_log.py:44`) | REAL (facts) | Richest security signal: every `@audited` call incl. **ScopeDenied** + **PendingApproval** (destructive-without-approval). No severity → inferred. App B `require_admin_token`. |
| Host/ops scan proposals | `GET /admin/supreme/{status,history,latest,proposal,scan}` (`admin_supreme.py`) | REAL (measured severity) | Persisted `data/supreme/proposals/scan-*.json`. **Empty until a scan runs** (`KAI_SUPREME_ENABLED` default OFF). App B `require_admin_token`. |
| Failure memory | `GET /admin/failures/{recent,stats,similar}` | REAL (no severity) | Tool/LLM errors; file may not exist yet. |
| Self-audit posture | `GET /admin/audit/run` (`auditor.py:72`) | DERIVED | Runtime key flags + subsystem `scope_enabled`/`store_exists`/record counts + `issues[]` strings. Booleans REAL, aggregate DERIVED. |
| Current principal | `GET /admin/session/whoami` (`operator_session_web.py:126`) | REAL | Authoritative role/scopes/source. **Open** (not `/api/`-gated). |
| Governed-bridge health | `GET /admin/kai-bridge/health` (`kai_bridge.py:145`) | REAL | enabled/upstream_configured/allowlists, no secrets. **Open**. |
| Owner-gate armed? | `verify_api_key`/`api_key_middleware` (`core/api.py:227,1006`) | REAL | The `/api` owner gate is **INERT when `API_KEY` env unset** → an INERT gate is a CRITICAL posture. |
| On-demand defensive scan | `POST /api/security/scan` → `security_scanner.py` | REAL (measured severity) | Owner-gated + path allowlist. On-demand only, not persisted. |
| SUPREMA autorepair | `GET /api/suprema/status` (`core/api.py:3031`) | REAL when daily cron state exists, else UNAVAILABLE | Severity from external `suprema` pkg. |

## App-A-reachable vs App-B-blocked (live-path honesty)
The Nexus is served by **App A** (same-origin cookie session). Reachable live:
`/admin/session/whoami`, `/admin/kai-bridge/health`, `/api/security/status`,
`/api/suprema/status`, `/api/security/scan`. **App B `/admin/*` security feeds**
(governance audit.jsonl, Supreme scanner, failures) are **cross-app → EXTERNAL_BLOCKED**:
they'd require the governed bridge `/admin/kai/*` allowlist to include them *and* App B
running (Docker down). Coded fail-soft; surfaced UNAVAILABLE until then.

## Honesty landmines (must NOT present as REAL)
- **`GET /api/security/status`** — `security_headers`/`audit_logging`/`https` are **hard-coded strings** (`core/api.py:3593`), not measured. Only `api_key_auth` is a real bool.
- **Header Security stat** (`nx-h-security`) was hard-coded `CLEAR` at init, never updated — a placeholder. **Fixed this phase**: driven by real posture worst-severity, else UNAVAILABLE.
- **`alerts` DB table** (`backend/app/models/alert.py`) is **trading** price alerts — NOT security. Decoy.
- **Bridge/stream audit** (`kai.bridge.audit`, `kai.stream.audit`) are **logger-only, no store/read path** → can't replay as a feed (UNAVAILABLE without a sink).
- **Rate-limit / auth-failure / redaction-hit** events are ephemeral HTTP responses or **silent scrubs** — NOT persisted. An "auth-failures/redaction-hits" alert stream would be fabricated.
- **`actor`** on audit rows is a caller-supplied string (default `'operator'`), **not** the authenticated identity — the pane caveats this.
- **Audit log is NOT tamper-evident** despite the registry label; plain append-only JSONL.

## Does NOT exist — do not fake
- No CVE/GHSA/NVD/OSV runtime feed; Semgrep (pre-commit) / pip-audit (CI, report-only) / gitleaks (CI) are **gate-time & ephemeral** (temp logs / CI logs). Aikido is external-MCP-only (no in-app config/feed).
- No unified security-alert store, no SIEM/correlation, no login-attempt/lockout/WAF, no SBOM, no posture *score*.
- No persisted auth/rate-limit/quota events; no redaction-hit counter.
- No self-heal scheduler status endpoint (Supreme scheduler status IS exposed).

## What the pane honestly shows
Posture header (gate armed / bridge / principal — REAL, else UNKNOWN) · governance
event & denial stream (REAL facts, **inferred** severity, labeled) · host/ops scan
findings (REAL measured severity, labeled "host/ops") · on-demand defensive scan.
Alerts feed the existing `store.alerts` strip; the header goes CRITICAL only for a
**measured** critical (or an INERT owner gate) — an inferred severity never screams CRITICAL.
