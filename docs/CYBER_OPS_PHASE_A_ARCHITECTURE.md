Verified. One correction to the discovery maps: `ops/monitor/` **is present on this branch** (`feat/kai-cyber-operations`) — importable as a pure mapper — though its live probes still read NOT_CONNECTED from an isolated worktree. Everything else in the maps holds. Here is the architecture.

---

# KAI CYBER OPERATIONS — Phase A + Phase B Architecture

Worktree: `/private/tmp/.../scratchpad/cyberops` · branch `feat/kai-cyber-operations` · **isolated: no merge, no prod deploy, no MONEY_MODE change, no privileged capability enable** (§59). App B = `backend/app/main.py` (governed brain); App A = `core/api.py` (public shell); bridge = `core/kai_bridge.py`. Everything Phase A is read-only, owner-gated, flag-dormant.

Grounding facts confirmed against the tree: `ops/monitor/{collectors,core,run,delivery}.py` present; `backend/app/config.py:57 KAI_HOLDING_ENABLED: bool = False` (mirror target); `app.services.governance` exports `list_actions`; `core/security_scanner.py` is a pure importable module; `admin_holding.py:15` is the router template (and carries POST execution endpoints we deliberately **omit**).

---

## 1. MODULE PLAN

All new, mirroring `holding_deployment.py`'s pure/injectable/`demo()`-tested truth pattern. **7 files.** No file fabricates; each source returns real data or a typed `NOT_CONNECTED`/`UNKNOWN`/`UNAVAILABLE` marker.

| File | Responsibility |
|---|---|
| `backend/app/services/security/__init__.py` | Public read API re-exports (mirror `governance/__init__.py`): `graph_view`, `events`, `posture_view`, `aikido_view`, `risk_view`, `capability_view`, `overview`. Nothing else imports internals. |
| `backend/app/services/security/models.py` | Pure dataclasses + enums: `SecurityEvent` (§10), `EvidenceReference` (§54), `Incident` (§14), `Node`/`Edge` (§6); `Severity`, `Confidence`, `TriageStatus`, `SourceState` enums. `.as_dict()` on each (asdict + enum→.value), like `HoldingEntity.as_dict()`. No I/O. |
| `backend/app/services/security/evidence_bus.py` | The bus. Read-only joiners over the **real** in-process sources: `graph_nodes()` (holding `all_entities()` + `entity_status.collect_live_entity_status()`), `graph_edges()` (config-derived edges only), `capability_nodes()` (`seed_registry()`), `security_events(limit)` (`list_actions()` → `SecurityEvent`), `scan_findings(path)` (`core.security_scanner`), `monitor_signals()` (vendored `ops.monitor` `collect()`→`evaluate()`). Each returns `(data, SourceState)`. Aggregators `graph_view()`, `events()`, `overview()`. |
| `backend/app/services/security/posture.py` | **The `holding_deployment.py` analog** for §22/§23. `@dataclass Control(control_id, name, category, runtime_flag, evidence_source)` with `.record(settings)` adding `present: bool` (code deployed) vs `enforced: bool|"UNKNOWN"` (live flag / live probe) — the ENFORCED/DISABLED honesty twin of deployed≠enabled. `CONTROL_REGISTRY: list[Control]`, `control_registry(settings)`, `posture_view(settings, *, app_a=None)`. `compute_drift`-style: any missing signal → `"UNKNOWN"`, never guessed. `demo()` self-test. |
| `backend/app/services/security/aikido_adapter.py` | Mirror `holding/deployment_status.py`'s `RailwayDeploymentReadAdapter`. `AikidoReadAdapter(api=None)`: `health(settings)→{"state":"READY"\|"UNAVAILABLE","reason"}` (UNAVAILABLE when `AIKIDO_CLIENT_ID/SECRET` empty → source honestly `NOT_CONNECTED`, never fabricated zero, §16); `read()` **whitelists** Aikido issue fields (id/severity/type/status/first_seen/repository), drops all else, routes through a `redact()` scrub. Carries **no** `ignore_issue`/`scan`/mutation method (test asserts `not hasattr`). `api` is the injection seam (httpx OAuth client-credentials); absent → UNAVAILABLE. |
| `backend/app/services/security/risk_score.py` | §26 deterministic, versioned, explainable score. `RISK_FORMULA_VERSION = "1.0.0"`; `compute_risk(*, criticals, highs, internet_exposed, active_incidents, auth_anomalies, audit_gaps, stale_findings) -> {"score":0-100,"band":LOW/MODERATE/HIGH/CRITICAL,"version","components":[{"reason","points"}]}`. Pure integer arithmetic — **no LLM**. Inputs that are `NOT_CONNECTED` contribute `0` **and** append a `components[]` note `"aikido NOT_CONNECTED — criticals not counted"` so the score is never silently understated. `demo()` asserts determinism + component sum. |
| `backend/app/routers/admin_security.py` | `APIRouter(prefix="/admin/cyber", dependencies=[Depends(require_kai_ultra)])`, GET-only, thin — each endpoint calls one `security.*` function. No POST (execution stays out this sprint). |

Plus the test file (§8): `backend/app/services/security/test_security.py` — zero-framework, `python3 -m app.services.security.test_security`, `res=[]; ck(name, ok)` pattern from `holding/test_registry.py`.

**Edits to existing files (surgical, flag-gated):**
- `backend/app/config.py` — add flags (§7).
- `backend/app/main.py` — `if settings.KAI_CYBER_OPS_ENABLED: from app.routers import admin_security; app.include_router(admin_security.router)` (mirror `main.py:211-213`).
- `core/kai_bridge.py` — add `"cyber"` to `allow_prefixes` **and** `ultra_prefixes` (one line each).
- `core/api.py` — `@app.get("/admin/security/cyber-operations")` FileResponse (Phase B).

---

## 2. DATA MODELS

Field → **real source** (from the maps) or explicit `UNKNOWN`/`NOT_CONNECTED`/`PHASE_C_PENDING`.

### `SecurityEvent` (§10) — populated from `list_actions()` audit records (WORKING, 258 real local records)
```python
event_id:       str   # ← audit id (uuid4 hex, stable dedup key)
timestamp:      str   # ← audit ts (ISO-8601 UTC)
source:         str   # ← const "governance.audit_log"
company:        str   # ← derive from scope prefix ("sol.transfer"→sol) mapped to holding entity_id; UNKNOWN if unmappable
system:         str   # ← scope-derived / "app_b"; UNKNOWN if unmappable
environment:    str   # ← settings.APP_ENV
category:       str   # ← derived: "audit_action"; "authz_denial" when approved==False and destructive
severity:       Severity  # ← derived: destructive&!success→HIGH, destructive→MEDIUM, else INFO
actor:          str   # ← audit actor ("operator" in live data)
resource:       str   # ← audit scope
action:         str   # ← audit action
result:         str   # ← audit success → "success"/"failure"
correlation_id: str   # ← UNKNOWN — audit_log record has NO correlation_id (only monitor Alert has one; see gap)
ip:             str   # ← UNKNOWN — audit_log carries no IP; omit per §10 "where policy permits"
evidence_refs:  list[EvidenceReference]  # ← synthesized, pointing at this audit line (source_id=audit id)
confidence:     Confidence  # ← const CONFIRMED (a recorded action is a logged fact, not an inference)
```
Untrusted-data rule (§10/§52): `inputs`/`outputs` are already redacted+truncated at write time; carried as opaque `detail`, **never** interpreted as instructions.

### `EvidenceReference` (§54) — real per source
```python
source_type:    str   # ← "audit" | "capability_registry" | "holding_registry" | "aikido" | "scanner" | "app_a_status" | "monitor" | "config"
source_id:      str   # ← underlying id: audit id / cap id / entity_id / aikido issue id / file sha256 / signal name
timestamp:      str   # ← record's own ts (audit ts, scanner scanned_at, aikido first_seen); UNKNOWN if source has none
digest:         str   # ← sha256 of the raw record (scanner gives a real file sha256; else hashlib over canonical json)
system:         str   # ← entity/system id the evidence is about; UNKNOWN if unmapped
retrieval_time: str   # ← now, injected by the bus at read time (no clock in the pure modules)
```

### `Incident` (§14) — **NOT populated in Phase A** (correlation/triage = Phase C, §58)
```python
incident_id, title, severity, status(TriageStatus), affected_systems, affected_companies,
first_seen, last_seen, detection_sources, evidence(list[EvidenceReference]),
likely_root_cause, confidence(Confidence), attack_techniques, recommended_actions,
approval_required=True, remediation_state="NOT_STARTED", verification_state="NOT_STARTED"
```
Phase A source = **none**. `/admin/cyber/incidents` returns `{"incidents": [], "state": "PHASE_C_PENDING", "reason": "correlation/triage engine not built (spec §58 Phase C)"}`. Zero real incidents shown as zero real; **no fabricated incidents** (§49, §55 — never emit "ATTACK DETECTED" without evidence).

### `Node` (§6) — holding `all_entities()` (11 real) + `entity_status` overlay
```python
node_id:        str   # ← entity.entity_id (WORKING)
system:         str   # ← entity.brand_name (WORKING)
company:        str   # ← ownership/holding-parent map; UNKNOWN where not modeled (do NOT invent)
asset_type:     str   # ← entity.entity_type (product/company/project/LLC/holding) (WORKING)
environment:    str   # ← derived from operational_status (LIVE/DEPLOYED) or APP_ENV for app_a/app_b; UNKNOWN else
trust_zone:     str   # ← deterministic: "internet_facing" if entity.domains else "internal" (WORKING — from real domains)
health:         str   # ← collect_live_entity_status()[id].ok → healthy/degraded; UNKNOWN for solcircle,nurtelle (NO probe — honest gap)
security_state: str   # ← from aikido per-repo (NOT_CONNECTED) → UNKNOWN this sprint
exposure:       str   # ← "public" if domains present + App A status reachable; else UNKNOWN
findings_count: int|str  # ← aikido (NOT_CONNECTED → "UNAVAILABLE"); separate documented_risks = len(entity.risks) is real & static
incident_count: int|str  # ← "PHASE_C_PENDING" (no incident engine in Phase A)
last_seen:      str   # ← entity.last_verified_at or entity_status probe time; UNKNOWN if neither
```
Money/customer/banking/legal_name attributes are **never** placed on a node — routed through `registry.report_value(eid, field)` and the `None`/provenance-string honored (enforced honesty invariant).

### `Edge` (§6) — **config-evidence only; fabricate no topology** (§4)
```python
source, target: str
relationship:   str
protocol:       str
trust_boundary: bool
authorization:  str
exposure:       str
evidence:       EvidenceReference   # every edge cites real config, else the edge is not drawn
```
Provable edges Phase A: `App A → App B` (bridge: `KAI_BRIDGE_ENABLED` + `KAI_UPSTREAM_URL`, auth `kai.ultra`, `trust_boundary=True`); `App B → PostgreSQL` (`settings.DATABASE_URL` present — bool only, value never read); `App B → Redis` (`settings.REDIS_URL` present); `Railway → App` (`RAILWAY_GIT_COMMIT_SHA` env present); `Monitor → App A/App B` (monitor probe targets, marked `NOT_CONNECTED` state in isolation). Cloudflare/GitHub/Aikido→repos edges are **UNKNOWN** (no config evidence in settings) — omitted, not drawn, per §4.

---

## 3. EVIDENCE BUS

`evidence_bus.py` reads only real sources, in-process where possible. State per source:

| Source | How read | Genuinely available? |
|---|---|---|
| **Holding registry → nodes** | `from app.services.holding import registry, entity_status`; `registry.all_entities()` (11 static) joined on `entity_id` with `entity_status.collect_live_entity_status()` overlay; money/legal via `report_value()` | **WORKING** in-process. Live overlay best-effort (8s timeout, fail-open); solcircle/nurtelle deploy-state honestly **UNKNOWN** (no probe). |
| **Capability registry → capability nodes** | `from app.services.capability.seed import seed_registry, seed_graph`; `reg.list(...)`, `reg.health(id)` (4-key dict), `reg.list(type=CapabilityType.SECURITY_ROUTER/...)` for the security family; edges from `seed_graph()` | **WORKING** in-process. 126 caps, 7 selectable; `selectable()` gate respected so read-only display never implies executability. |
| **Audit → SecurityEvents** | `from app.services.governance import list_actions`; `list_actions(limit=N, scope=?, actor=?)` → normalize to `SecurityEvent` | **WORKING** in-process (258 real local records). Gaps: no time-range/pagination/correlation_id/ip — `correlation_id`/`ip` map to `UNKNOWN`; incremental consumption de-dups on `event_id`. |
| **Monitor → posture/incident signals + §25 telemetry** | Vendor-import `ops.monitor`: `collectors.collect()` → `run.evaluate(snap)` → `Alert` list; map `Alert`→`SecurityEvent` (`auth_bypass`→authz, `audit_gap`→integrity, `*_5xx`→availability, `spend`→cost) | **Code present & importable** on this branch. But `collect()` HTTP-polls **production** — from the isolated worktree (no network/no prod URLs) probes fail-open → snapshot degraded → honestly surfaces `monitor_self`/`NOT_CONNECTED`, **never a fake "healthy"**. Live telemetry = **NOT_CONNECTED in isolation** until operator supplies prod base URLs + network. |
| **App A `/api/security/status` → data-protection posture** | HTTP `GET {APP_A_SECURITY_BASE_URL}/api/security/status` with shared `X-API-Key` (§22/§23 evidence) | **NOT_CONNECTED** by default (no base URL/key in isolation). When wired: only `api_key_auth` is a live probe; `security_headers/audit_logging/https` are **self-reported constants** → recorded as *claimed controls* with App B's own `observed_at`, not attestation. |
| **`core/security_scanner.py` → findings** | `from core.security_scanner import scan_file, scan_directory` (pure module) on **local authorized paths only** (its own allow-list: `/tmp`,`/private/tmp`,`/var/folders`,`~/Downloads`,`~/Desktop`,cwd) | **WORKING in-process if `core` is on App B's path** (same repo root) — real signal for the isolated workspace. Honest ceiling: EICAR-hash-only unless `data/malware_hashes.json` present + fixed 18-regex heuristic (no CVE/AV feed) — a low-fidelity secondary source, labeled as such. The App A **HTTP** scan endpoint = NOT_CONNECTED without base URL/key. |
| **Aikido → vuln intelligence** | `AikidoReadAdapter(api=None)` OAuth client-credentials REST read | **NOT_CONNECTED** — zero in-app integration, no `AIKIDO_*` config, no adapter today. Buildable only when operator provisions `AIKIDO_CLIENT_ID`/`AIKIDO_CLIENT_SECRET` (+region). Until then surfaces `NOT_CONNECTED`, never fake zero (§16). |

Every emitted datum carries an `EvidenceReference`; the bus stamps its own `retrieval_time`. Correlation across sources (§9/§11) is **Phase C** — Phase A only normalizes and lists.

---

## 4. ZERO-FAKE HONESTY MATRIX (§49)

State when the source is empty: **WORKING** (real value) · **DISABLED_WITH_REASON** (control present but not enforced/enabled) · **NOT_CONNECTED** (external source unprovisioned) · **UNKNOWN** (no probe/no evidence).

| Displayed value | Real source | State when source empty |
|---|---|---|
| System graph nodes (11) | `holding.registry.all_entities()` | **WORKING** |
| Node live health | `entity_status.collect_live_entity_status()` | **UNKNOWN** for solcircle/nurtelle (no probe); degraded/fail-open otherwise |
| Node money/customer/banking | `registry.report_value()` | Renders provenance string / hidden — **never** the sentinel (enforced in code) |
| Graph edges | `settings` (bridge/DB/Redis/Railway env) | Edge **not drawn** if no config evidence (UNKNOWN, §4) |
| Capability nodes + health | `seed_registry()`, `reg.health(id)` | **WORKING** (126 caps); executability gated by `selectable()` |
| Security events | `governance.list_actions()` | **WORKING** (258 real); `[]` honestly if log absent |
| event.correlation_id / event.ip | — | **UNKNOWN** (audit schema has neither) |
| Incidents | correlation/triage engine | **PHASE_C_PENDING** — `[]`, never fabricated (§55) |
| Data-protection posture (TLS/secrets/session) | App A `/api/security/status` (+ App B `settings`) | **NOT_CONNECTED** (no base URL/key); `security_headers` etc. = *claimed*, not attested |
| `api_key_auth` control | App A live probe / App B `settings` | Actionable finding when `"disabled"`; **WORKING** live |
| Scanner findings | `core.security_scanner` | **WORKING** on local authorized paths; EICAR/heuristic ceiling labeled |
| **Aikido (critical/high/open/repos/last-sync)** | `AikidoReadAdapter` | **NOT_CONNECTED** (no secrets, no adapter) — *proven by the map*; never fake zero (§16) |
| Monitor telemetry (§25: events/hr, 5xx, auth fails, latency) | `ops.monitor collect()`→`evaluate()` | **NOT_CONNECTED in isolation** (prod-poll, no network); `monitor_self` surfaced, never fake healthy |
| Risk score + band | `risk_score.compute_risk()` v1.0.0 | Deterministic; NOT_CONNECTED inputs → `0` **with an explicit `components[]` caveat**; **never LLM-invented** (§26) |
| Process/service tree (§24) | runtime introspection | **UNKNOWN** — not faked |
| Attack path steps (§7) | config + Aikido + auth tests | Per-step `reachable/protected/...` from config; `unknown` where no evidence — never proven by attacking prod |

---

## 5. CAPABILITIES (§32)

Register the logical security capabilities as **new `CapabilityManifest`s** (via `manifest_from_dict`), all `type=CapabilityType.NATIVE_KAI_TOOL` (or `SECURITY_ROUTER` for the router-like ones), `availability=AVAILABLE` only for reads, `default_action_class=READ_ONLY`, `activation=ON_DEMAND`, `security_tier=0` (knowledge/read), `permissions=["security.read"]`. These are **non-executable read surfaces** — they describe what the read endpoints do; they do not gain the Brain new powers. This satisfies §1 "register new capabilities as non-executable."

**READ_ONLY → register AVAILABLE this sprint:**
`SECURITY_OVERVIEW`, `SECURITY_EVENTS_READ`, `SECURITY_INCIDENTS_READ`, `SECURITY_ATTACK_GRAPH`, `SECURITY_ASSET_GRAPH`, `SECURITY_AIKIDO_STATUS`, `SECURITY_AIKIDO_FINDINGS`, `SECURITY_AUTH_ANALYSIS`, `SECURITY_DEPLOYMENT_RISK`, `SECURITY_AUDIT_ANALYSIS`.

**STANDARD (analysis-producing, still no mutation) → register DISCOVERED/DISABLED this sprint** (deployed dark, enabled later): `SECURITY_GENERATE_REPORT`, `SECURITY_PREPARE_REMEDIATION`, `SECURITY_BEHAVIOR_ANALYSIS`. These are Phase C/D; ship non-selectable (`availability=DISABLED`).

**PRIVILEGED → confirmed DISABLED (never registered AVAILABLE):**
`SECURITY_CONTAIN`, `SECURITY_BLOCK_RESOURCE`, `SECURITY_REVOKE_SESSION`, `SECURITY_ROLLBACK_DEPLOYMENT` — register with `availability=DISABLED`, `default_action_class=DESTRUCTIVE`/`HIGH_IMPACT`, `risk_class=RESTRICTED`, `automatic_activation_allowed=False`, `operator_approval_required=True`, `sandbox_required=True`, `target_allowlist_required=True`. `selectable()` returns **False** → the Brain cannot plan them. This preserves §1 invariants (privileged executable = 0, restricted executable = 0) and §33 (KAI cannot self-promote past SEC0–SEC4; SEC5/SEC6 future-only).

Authorization is described, not exercised: read endpoints reuse `risk.evaluate_policy(manifest, action_class, Principal(...))` and `security.authorize_security_capability(...)` to *show what WOULD be allowed* — pure, side-effect-free. `Principal` is built from KAI RBAC (role/scopes/authorized_targets), never from capability output; a hostname is never authorization (§35).

---

## 6. ENDPOINTS

### App B — `backend/app/routers/admin_security.py` (owner-gated, GET-only)
`APIRouter(prefix="/admin/cyber", dependencies=[Depends(require_kai_ultra)])` — mirrors `admin_holding.py:15` exactly; **omits** all POST/execution endpoints that `admin_holding` has (self-cert, a2-dispatch, run-cycle) since cyber is read-only.

| Route | Returns | Spec |
|---|---|---|
| `GET /admin/cyber/overview` | `security.overview()` — state + counts for the §36 card and §4 home | §4, §36 |
| `GET /admin/cyber/graph` | `{nodes, edges}` from `evidence_bus.graph_view()` | §6 |
| `GET /admin/cyber/events?limit=N` | `security.events(limit)` (audit→SecurityEvent) | §10 |
| `GET /admin/cyber/posture` | `security.posture_view(settings, app_a=<adapter>)` (controls: present vs enforced) | §22, §23 |
| `GET /admin/cyber/aikido` | `security.aikido_view()` → `NOT_CONNECTED` payload until secrets | §16 |
| `GET /admin/cyber/risk` | `security.risk_view()` (score + versioned components) | §26 |
| `GET /admin/cyber/capabilities` | security manifests + `reg.health(id)` + selectable gate | §32, §35 |
| `GET /admin/cyber/incidents` | `{"incidents":[], "state":"PHASE_C_PENDING"}` | §14 |

Mount (dormant): `backend/app/main.py` — `if settings.KAI_CYBER_OPS_ENABLED: app.include_router(admin_security.router)`.

### Bridge — `core/kai_bridge.py`
Add `"cyber"` to `allow_prefixes` (else 404) **and** to `ultra_prefixes` (bridge forces `kai.ultra`, defense-in-depth; App B's `require_kai_ultra` remains the authoritative gate). Path map: `/admin/kai/cyber/<rest>` → `<upstream>/admin/cyber/<rest>`. GET-only; `x-api-key` stripped; `wv_session` forwarded; correlation-id + audit per hop; no host from request (no SSRF).

### App A — Cyber Operations page (Phase B)
`core/api.py`: `@app.get("/admin/security/cyber-operations")` → `FileResponse(frontend/admin/cyber-operations.html, headers={"Cache-Control":"no-store"})` (mirror `_admin_holding_page`). **Honest caveat:** this bare path does **not** run `_inject_kai_presence` (only `_serve_frontend()` for `admin/`-prefixed injects) — add the two presence tags manually if the orb is wanted.

### Dashboard nav integration (Phase B, §3/§36)
No nav component exists in `holding.html` (stacked `<div class="panel">` blocks). So: (a) the SECURITY section renders as appended panels in `cyber-operations.html`, and (b) a compact **CYBER OPERATIONS** card (Security State / Active Incidents / Critical Findings / Auth Anomalies / Aikido State / Last Security Event) appended to `holding.html`'s `#out` IIFE, linking to `/admin/security/cyber-operations`.

---

## 7. CONFIG FLAGS

`backend/app/config.py`, single `Settings(BaseSettings)`, mirroring `KAI_HOLDING_ENABLED: bool = False` (line 57) and the empty-string secret-ref convention:

```python
KAI_CYBER_OPS_ENABLED: bool = False   # master: OFF → admin_security router never mounted, zero new surface
AIKIDO_CLIENT_ID: str = ""            # empty → Aikido source reports NOT_CONNECTED (never errors, never fakes)
AIKIDO_CLIENT_SECRET: str = ""
AIKIDO_REGION: str = "eu"             # eu|us — pins the public REST base URL
APP_A_SECURITY_BASE_URL: str = ""     # empty → App A status/scan adapter = NOT_CONNECTED
APP_A_SECURITY_API_KEY: str = ""      # shared owner key for App A /api/security/*; empty → NOT_CONNECTED
```
Convention (already in this file): empty secret ⇒ feature fails **soft** to `NOT_CONNECTED`, never raises. All default OFF/empty ⇒ isolated: no route mounted, no external call, no prod touch (§59).

---

## 8. PHASE A BUILD TASK LIST (backend-first; each with a one-line verify)

1. **Config flags** — add the 6 settings above. *Verify:* `python3 -c "from app.config import settings; assert settings.KAI_CYBER_OPS_ENABLED is False and settings.AIKIDO_CLIENT_ID==''"`.
2. **`models.py`** — dataclasses + enums + `.as_dict()`. *Verify:* `SecurityEvent(...).as_dict()["severity"]` is a plain string (enum coerced).
3. **`risk_score.py`** — `compute_risk` + `RISK_FORMULA_VERSION` + `demo()`. *Verify:* `python3 backend/app/services/security/risk_score.py` prints OK; same inputs → identical score; `NOT_CONNECTED` input adds a caveat component.
4. **`evidence_bus.graph_nodes()/graph_edges()`** — holding registry + entity_status join; config-only edges. *Verify:* returns 11 nodes; solcircle/nurtelle health `UNKNOWN`; no money field leaks (`report_value` honored); every edge has an `EvidenceReference` or isn't present.
5. **`evidence_bus.security_events()`** — `list_actions()` → `SecurityEvent`; `correlation_id`/`ip` = `UNKNOWN`. *Verify:* against a sample audit record, `destructive&!success` → `HIGH`; `event_id`==audit `id`.
6. **`evidence_bus.capability_nodes()`** — `seed_registry()` + `reg.health`. *Verify:* 126 total, exactly 7 `selectable()`; privileged security caps `selectable()==False`.
7. **`evidence_bus.scan_findings()` + `monitor_signals()`** — import `core.security_scanner`; vendor-import `ops.monitor`. *Verify:* a `/tmp` scan returns the scanner dict; monitor from isolation yields `monitor_self`/`NOT_CONNECTED`, never `healthy`.
8. **`aikido_adapter.py`** — `AikidoReadAdapter(api=None)`, whitelist `read()`, no mutation method. *Verify:* `health(settings)["state"]=="UNAVAILABLE"` when secrets empty; `not hasattr(AikidoReadAdapter, "ignore_issue")`.
9. **`posture.py`** — `Control` registry (present vs enforced), `posture_view`, `demo()`. *Verify:* `python3 backend/app/services/security/posture.py` OK; a control with no signal reports `enforced="UNKNOWN"`, not a guess.
10. **Security capability manifests** — register READ_ONLY AVAILABLE, STANDARD DISABLED, PRIVILEGED DISABLED. *Verify:* privileged 4 have `availability==DISABLED`, `automatic_activation_allowed==False`, `selectable()==False`; certified registry count otherwise unchanged (§1).
11. **`__init__.py` aggregators + `overview()`** — assemble graph+events+posture+risk+aikido+capabilities. *Verify:* `overview()` returns a dict where every value is real or a typed `NOT_CONNECTED`/`UNKNOWN`/`PHASE_C_PENDING`.
12. **`admin_security.py` router** — 8 GET endpoints, `require_kai_ultra`, no POST. *Verify:* `grep -c "@router.post" admin_security.py` == 0; every endpoint `Depends(require_kai_ultra)`.
13. **Mount + bridge** — `main.py` flag-gated include; `"cyber"` in `allow_prefixes`+`ultra_prefixes`. *Verify:* flag OFF → route absent (404); flag ON + anon → 403; bridge maps `/admin/kai/cyber/overview`→`/admin/cyber/overview`.
14. **`test_security.py`** (§50 subset) — no-fabrication, adapter no-mutation, secret redaction (`"AIKIDO_TOKEN" not in str(ev)`), event normalization, risk determinism, owner-gate present. *Verify:* `python3 -m app.services.security.test_security` exits 0, all PASS.

**Phase A exit gate:** all self-tests green; `KAI_CYBER_OPS_ENABLED=False` by default (zero new surface); MONEY_MODE untouched; privileged=0/restricted=0 executable; Aikido + monitor-live + App A status honestly `NOT_CONNECTED`; no fabricated node/edge/event/incident/finding. **Phase B** (dashboard `cyber-operations.html`, system graph, Aikido panels, event timeline, §36 card, SECURITY nav) builds only after Phase A tests pass.

---

## Spec requirements that CANNOT be grounded in real data (ship as NOT_CONNECTED / UNKNOWN, never faked)

- **§16/§17 Aikido findings, severities, repos, SBOM, autofix** — no adapter, no `AIKIDO_*` secrets. `NOT_CONNECTED` until operator provisions credentials.
- **§25 telemetry + §39 monitor alerts (live)** — `ops.monitor` polls production; from an isolated worktree with no network/prod URLs → `NOT_CONNECTED`/`monitor_self`, never a fake healthy series.
- **§22/§23 data-protection & identity posture via App A** — needs `APP_A_SECURITY_BASE_URL`+key; and even connected, `security_headers/audit_logging/https` are App A **self-reported constants**, recorded as *claimed*, not attested.
- **§14/§13/§11/§12 incidents, triage, correlation, behavior** — Phase C engines; Phase A returns `[]`/`PHASE_C_PENDING`. No "ATTACK DETECTED" without evidence (§55).
- **§10 `correlation_id` and `ip`** — absent from the audit schema → `UNKNOWN` on audit-sourced events (only monitor Alerts carry a correlation_id).
- **§24 process/service tree** — no runtime introspection source → `UNKNOWN`, not faked.
- **§4/§6 Cloudflare/GitHub topology edges** — no config evidence in `settings` → omitted (UNKNOWN), never drawn (§4 "never fabricate topology").
- **§29–§31 physical/ghost-drive/display threat models** — knowledge/detection-model only; no host-inventory source in this repo → `UNKNOWN`/knowledge-only, no real device control (§0).

Files to create are all under `backend/app/services/security/` (+ `backend/app/routers/admin_security.py`); edits limited to `backend/app/config.py`, `backend/app/main.py`, `core/kai_bridge.py`, and (Phase B) `core/api.py` + `frontend/admin/cyber-operations.html`.