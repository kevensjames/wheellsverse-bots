# KAI Security Center — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Security Center to KAI that scans for secrets/vulns, monitors encrypted backups, and shows an honest security score — without the money-handling daemon ever executing a scanner.

**Architecture:** A standalone launchd-managed worker (`scripts/security_worker.py`) shells out to gitleaks/trivy/trufflehog/restic, normalizes results into **redacted** findings, and writes them to `data/security/*.jsonl` + `latest.json`. The FastAPI daemon only **reads** those files (via `services/security/store.py`) and serves them on a new `/admin/security` tab; an on-demand "Scan now" button writes a 1-byte `.request` marker the worker picks up. The daemon never spawns a scanner process.

**Tech Stack:** Python 3 / FastAPI / Pydantic, pytest, SQLAlchemy (unused here — security stores are file-based), gitleaks · trivy · trufflehog · restic CLIs, launchd, Backblaze B2.

## Global Constraints

- Repo: `~/wheellsverse_bots`. Work on branch `nexora/phase1-auth` (already checked out). Spec: `docs/superpowers/specs/2026-06-18-kai-security-center-phase1-design.md`.
- The daemon (`backend/app/**`) MUST NOT import `scripts/security_worker.py` and MUST NOT invoke any scanner subprocess. Only the worker runs scanners.
- All persisted finding records MUST be redacted: store a `fingerprint` (sha256), NEVER a raw secret value. This is enforced in `store.py` and unit-tested.
- A category with no scan data scores **"unknown"** (Python `None`), never 100.
- Reuse existing governance: `from app.services.governance import audited, is_scope_enabled`. New scopes: `KAI_SCOPE_SECURITY` (parent), `KAI_SCOPE_SECURITY_SCAN`.
- Reuse existing admin auth: `from app.dependencies.admin import require_admin_token`.
- Atomic writes everywhere the worker writes a file the daemon reads (`tmp` + `os.replace`).
- Tests live under `backend/tests/security/`. Run from `~/wheellsverse_bots/backend` with `pytest`. Respect the conftest production-DB guard (these tests touch no DB).
- Python imports inside `backend/` are rooted at `app.*` (e.g. `from app.services.security.store import ...`), matching existing routers.

---

## File Structure

**Created (daemon, read-only w.r.t. security):**
- `backend/app/services/security/__init__.py` — package exports
- `backend/app/services/security/models.py` — `Finding`, `BackupStatus`, `RunnerStatus`, `Posture`, `CategoryScore`, `SecurityScore`, `SecuritySnapshot`
- `backend/app/services/security/store.py` — read/write `data/security/`, atomic, redaction guard
- `backend/app/services/security/score.py` — pure `compute_score(findings, posture, backup) -> SecurityScore`
- `backend/app/services/security/runners/__init__.py`
- `backend/app/services/security/runners/base.py` — `run_cmd()`, `sha256_fingerprint()`
- `backend/app/services/security/runners/secrets.py` — `scan_secrets(paths) -> list[Finding]`
- `backend/app/services/security/runners/vulns.py` — `scan_vulns(paths) -> list[Finding]`
- `backend/app/services/security/runners/backup.py` — `run_backup_and_check(...) -> tuple[BackupStatus, RunnerStatus]`
- `backend/app/routers/admin_security.py` — GET summary/findings/score + POST scan

**Created (worker, isolated):**
- `scripts/security_worker.py` — orchestrator
- `deploy/com.wheellsverse.kai.security-scan.plist` — daily scan
- `deploy/com.wheellsverse.kai.security-trigger.plist` — ~5-min marker check
- `deploy/security_trigger.sh` — tiny marker-check wrapper

**Created (docs/UI):**
- `SECURITY_RULES.md` — standing rules + security-architect review prompt
- `docs/security/SETUP.md` — brew + B2 runbook

**Modified:**
- `backend/app/main.py` — `app.include_router(admin_security.router)`
- `backend/app/services/audit/auditor.py` — add a `SUBSYSTEMS` row (`tab: "security"`)
- `frontend/admin/index.html` — Security tab UI

**Tests + fixtures:**
- `backend/tests/security/__init__.py`
- `backend/tests/security/test_models.py`
- `backend/tests/security/test_store.py`
- `backend/tests/security/test_score.py`
- `backend/tests/security/test_runner_secrets.py`
- `backend/tests/security/test_runner_vulns.py`
- `backend/tests/security/test_runner_backup.py`
- `backend/tests/security/test_admin_security.py`
- `backend/tests/security/fixtures/gitleaks.json`, `trufflehog.jsonl`, `trivy.json`, `restic_snapshots.json`

---

## Task 1: Models + scope flags + package scaffold

**Files:**
- Create: `backend/app/services/security/__init__.py`, `backend/app/services/security/models.py`
- Create: `backend/tests/security/__init__.py`, `backend/tests/security/test_models.py`

**Interfaces:**
- Produces:
  - `Finding(id:str, ts:str, category:str, severity:str, tool:str, title:str, location:str, fingerprint:str, verified:bool, metadata:dict)` — Pydantic model. `severity ∈ {"critical","high","medium","low","info"}`, `category ∈ {"secret","vuln","backup"}`.
  - `Finding.create(category, severity, tool, title, location, secret=None, verified=False, metadata=None) -> Finding` classmethod: computes `fingerprint = sha256(secret or title+location)`, generates `id` (uuid4 hex), `ts` (UTC ISO8601). **Never stores `secret`.**
  - `BackupStatus(repo:str, configured:bool, last_snapshot_age_s:int|None, check_ok:bool|None, snapshot_count:int)`
  - `RunnerStatus(tool:str, ok:bool, error:str|None, duration_ms:int)`
  - `Posture(mfa_enabled:bool, user_table_present:bool, plaintext_secret_files:list[str], rate_limiting_present:bool|None, governance_ok:bool, scopes_enabled:list[str])`
  - `CategoryScore(name:str, score:int|None, detail:str)` — `score=None` means "unknown".
  - `SecurityScore(overall:int|None, categories:list[CategoryScore])`
  - `SecuritySnapshot(generated_at:str, by:str, findings:list[Finding], backup:BackupStatus, runner_status:list[RunnerStatus], posture:Posture, score:SecurityScore)`

- [ ] **Step 1: Write the failing test**

`backend/tests/security/test_models.py`:
```python
from app.services.security.models import Finding


def test_finding_create_redacts_secret_and_fingerprints():
    f = Finding.create(
        category="secret",
        severity="critical",
        tool="gitleaks",
        title="AWS access key",
        location="data/.env:12",
        secret="AKIAIOSFODNN7EXAMPLE",
        verified=True,
    )
    dumped = f.model_dump()
    # the raw secret never appears anywhere in the persisted record
    assert "AKIAIOSFODNN7EXAMPLE" not in str(dumped)
    assert f.fingerprint and len(f.fingerprint) == 64  # sha256 hex
    assert f.verified is True
    assert f.id and f.ts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.security'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/security/__init__.py`:
```python
"""KAI Security Center — read-only daemon side (worker writes the stores)."""
```

`backend/app/services/security/models.py`:
```python
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

SEVERITIES = ("critical", "high", "medium", "low", "info")
CATEGORIES = ("secret", "vuln", "backup")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Finding(BaseModel):
    id: str
    ts: str
    category: str
    severity: str
    tool: str
    title: str
    location: str
    fingerprint: str
    verified: bool = False
    metadata: dict = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        category: str,
        severity: str,
        tool: str,
        title: str,
        location: str,
        secret: str | None = None,
        verified: bool = False,
        metadata: dict | None = None,
    ) -> "Finding":
        basis = secret if secret is not None else f"{title}|{location}"
        fingerprint = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        return cls(
            id=uuid.uuid4().hex,
            ts=_now_iso(),
            category=category,
            severity=severity,
            tool=tool,
            title=title,
            location=location,
            fingerprint=fingerprint,
            verified=verified,
            metadata=metadata or {},
        )


class BackupStatus(BaseModel):
    repo: str = ""
    configured: bool = False
    last_snapshot_age_s: int | None = None
    check_ok: bool | None = None
    snapshot_count: int = 0


class RunnerStatus(BaseModel):
    tool: str
    ok: bool
    error: str | None = None
    duration_ms: int = 0


class Posture(BaseModel):
    mfa_enabled: bool = False
    user_table_present: bool = False
    plaintext_secret_files: list[str] = Field(default_factory=list)
    rate_limiting_present: bool | None = None
    governance_ok: bool = True
    scopes_enabled: list[str] = Field(default_factory=list)


class CategoryScore(BaseModel):
    name: str
    score: int | None  # None == "unknown"
    detail: str = ""


class SecurityScore(BaseModel):
    overall: int | None
    categories: list[CategoryScore] = Field(default_factory=list)


class SecuritySnapshot(BaseModel):
    generated_at: str = Field(default_factory=_now_iso)
    by: str = "scheduled"
    findings: list[Finding] = Field(default_factory=list)
    backup: BackupStatus = Field(default_factory=BackupStatus)
    runner_status: list[RunnerStatus] = Field(default_factory=list)
    posture: Posture = Field(default_factory=Posture)
    score: SecurityScore = Field(default_factory=lambda: SecurityScore(overall=None))
```

`backend/tests/security/__init__.py`:
```python
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
git add backend/app/services/security/__init__.py backend/app/services/security/models.py backend/tests/security/__init__.py backend/tests/security/test_models.py
git commit -m "feat(security): redacted Finding + Security Center models"
```

---

## Task 2: Store (atomic + redaction guard)

**Files:**
- Create: `backend/app/services/security/store.py`
- Test: `backend/tests/security/test_store.py`

**Interfaces:**
- Consumes: `models.Finding`, `models.SecuritySnapshot`.
- Produces:
  - `SecurityStore(base_dir: Path)` with:
    - `append_findings(findings: list[Finding]) -> None` — appends to per-category `*.jsonl`; **raises `ValueError` if any record's serialized form is missing a `fingerprint` or contains a key named `secret`/`raw`** (redaction guard).
    - `write_latest(snapshot: SecuritySnapshot) -> None` — atomic write of `latest.json`.
    - `read_latest() -> SecuritySnapshot | None` — returns None if absent.
    - `request_scan() -> None` — `touch` `.request` marker.
    - `consume_request() -> bool` — returns True and deletes `.request` if present.
    - `default_dir() -> Path` staticmethod — `os.environ.get("KAI_SECURITY_DIR")` or `<repo>/data/security`.

- [ ] **Step 1: Write the failing test**

`backend/tests/security/test_store.py`:
```python
import json

import pytest

from app.services.security.models import Finding, SecuritySnapshot
from app.services.security.store import SecurityStore


def test_write_then_read_latest_roundtrip(tmp_path):
    store = SecurityStore(tmp_path)
    snap = SecuritySnapshot(by="on-demand")
    store.write_latest(snap)
    got = store.read_latest()
    assert got is not None
    assert got.by == "on-demand"


def test_read_latest_missing_returns_none(tmp_path):
    assert SecurityStore(tmp_path).read_latest() is None


def test_request_marker_lifecycle(tmp_path):
    store = SecurityStore(tmp_path)
    assert store.consume_request() is False
    store.request_scan()
    assert store.consume_request() is True
    assert store.consume_request() is False


def test_append_findings_rejects_raw_secret_key(tmp_path):
    store = SecurityStore(tmp_path)
    bad = Finding.create("secret", "high", "gitleaks", "k", "f:1")
    # smuggle a raw secret into metadata under a forbidden key
    bad.metadata["secret"] = "AKIA-LEAK"
    with pytest.raises(ValueError):
        store.append_findings([bad])
    # nothing should have been written
    assert not (tmp_path / "secrets.jsonl").exists()


def test_append_findings_writes_jsonl(tmp_path):
    store = SecurityStore(tmp_path)
    f = Finding.create("vuln", "critical", "trivy", "CVE-2024-0001", "pkg:requests")
    store.append_findings([f])
    line = (tmp_path / "vulns.jsonl").read_text().strip()
    assert json.loads(line)["fingerprint"] == f.fingerprint
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.security.store'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/security/store.py`:
```python
from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Finding, SecuritySnapshot

_FORBIDDEN_KEYS = {"secret", "raw", "raw_secret", "password", "value"}
_CATEGORY_FILE = {"secret": "secrets.jsonl", "vuln": "vulns.jsonl", "backup": "backup.jsonl"}


class SecurityStore:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def default_dir() -> Path:
        env = os.environ.get("KAI_SECURITY_DIR")
        if env:
            return Path(env)
        # backend/app/services/security/store.py -> repo root is parents[4]
        return Path(__file__).resolve().parents[4] / "data" / "security"

    def _check_redacted(self, record: dict) -> None:
        if not record.get("fingerprint"):
            raise ValueError("finding missing fingerprint — refusing to persist")
        meta = record.get("metadata") or {}
        for k in meta:
            if str(k).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"forbidden raw-secret key in finding metadata: {k}")

    def append_findings(self, findings: list[Finding]) -> None:
        # validate ALL before writing ANY (no partial writes)
        records = [f.model_dump() for f in findings]
        for r in records:
            self._check_redacted(r)
        buckets: dict[str, list[str]] = {}
        for r in records:
            fname = _CATEGORY_FILE.get(r["category"], "other.jsonl")
            buckets.setdefault(fname, []).append(json.dumps(r))
        for fname, lines in buckets.items():
            with (self.base / fname).open("a", encoding="utf-8") as fh:
                for ln in lines:
                    fh.write(ln + "\n")

    def write_latest(self, snapshot: SecuritySnapshot) -> None:
        tmp = self.base / "latest.json.tmp"
        tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.base / "latest.json")

    def read_latest(self) -> SecuritySnapshot | None:
        p = self.base / "latest.json"
        if not p.exists():
            return None
        return SecuritySnapshot.model_validate_json(p.read_text(encoding="utf-8"))

    def request_scan(self) -> None:
        (self.base / ".request").write_text("1", encoding="utf-8")

    def consume_request(self) -> bool:
        p = self.base / ".request"
        if p.exists():
            p.unlink()
            return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_store.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
git add backend/app/services/security/store.py backend/tests/security/test_store.py
git commit -m "feat(security): file store with atomic writes + redaction guard"
```

---

## Task 3: Score engine (pure, honest, unknown≠pass)

**Files:**
- Create: `backend/app/services/security/score.py`
- Test: `backend/tests/security/test_score.py`

**Interfaces:**
- Consumes: `models.Finding`, `models.Posture`, `models.BackupStatus`, `models.SecurityScore`, `models.CategoryScore`.
- Produces:
  - `compute_score(findings: list[Finding], posture: Posture, backup: BackupStatus, *, secrets_scanned: bool, vulns_scanned: bool) -> SecurityScore`
  - `_category_weights() -> dict[str, float]` — **operator-owned**; defaults below.
  - Overall = weighted mean of categories whose `score is not None`; if a category is unknown it is excluded from the mean AND its absence is reflected by capping overall at 95 (so an unmonitored system can never show a perfect 100).

- [ ] **Step 1: Write the failing test**

`backend/tests/security/test_score.py`:
```python
from app.services.security.models import BackupStatus, Finding, Posture
from app.services.security.score import compute_score


def _posture(**kw):
    base = dict(mfa_enabled=False, user_table_present=False,
                plaintext_secret_files=[".env"], rate_limiting_present=None,
                governance_ok=True, scopes_enabled=["security"])
    base.update(kw)
    return Posture(**base)


def test_unknown_category_is_none_not_100():
    score = compute_score([], _posture(), BackupStatus(configured=False),
                           secrets_scanned=False, vulns_scanned=False)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Infrastructure / Vulns"] is None      # never scanned -> unknown
    assert cats["Backups"] == 0                          # not configured -> real 0
    # overall is capped below 100 while anything is unmonitored
    assert score.overall is not None and score.overall < 100


def test_honest_low_baseline_today():
    # today's reality: no MFA, plaintext .env on disk, no backups, no scans
    score = compute_score([], _posture(), BackupStatus(configured=False),
                          secrets_scanned=False, vulns_scanned=False)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Authentication"] <= 50
    assert cats["Backups"] == 0


def test_critical_findings_sink_categories():
    crit_secret = Finding.create("secret", "critical", "gitleaks", "AWS key", "x:1")
    crit_vuln = Finding.create("vuln", "critical", "trivy", "CVE", "pkg")
    score = compute_score([crit_secret, crit_vuln], _posture(plaintext_secret_files=[]),
                          BackupStatus(configured=True, check_ok=True, last_snapshot_age_s=3600),
                          secrets_scanned=True, vulns_scanned=True)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Infrastructure / Vulns"] < 60
    assert cats["Encryption / secrets-at-rest"] < 60


def test_strong_agent_security_when_governance_ok():
    score = compute_score([], _posture(), BackupStatus(configured=True, check_ok=True,
                          last_snapshot_age_s=3600), secrets_scanned=True, vulns_scanned=True)
    cats = {c.name: c.score for c in score.categories}
    assert cats["Agent Security"] >= 80
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.security.score'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/security/score.py`:
```python
from __future__ import annotations

from .models import BackupStatus, CategoryScore, Finding, Posture, SecurityScore

# ── OPERATOR-OWNED CONFIG ─────────────────────────────────────────────
# Weights encode YOUR risk appetite. Edit these. They must sum > 0.
_WEIGHTS = {
    "Authentication": 1.0,
    "Encryption / secrets-at-rest": 1.0,
    "Backups": 1.0,
    "API Security": 0.8,
    "Agent Security": 1.0,
    "Infrastructure / Vulns": 1.0,
}
# Penalty per finding severity (points subtracted from the 100 baseline).
_PENALTY = {"critical": 45, "high": 25, "medium": 10, "low": 3, "info": 0}
# Backup freshness: snapshot older than this many seconds is stale.
_BACKUP_STALE_S = 36 * 3600
# ──────────────────────────────────────────────────────────────────────


def _category_weights() -> dict[str, float]:
    return dict(_WEIGHTS)


def _penalize(base: int, findings: list[Finding]) -> int:
    score = base
    for f in findings:
        score -= _PENALTY.get(f.severity, 0)
    return max(0, min(100, score))


def compute_score(
    findings: list[Finding],
    posture: Posture,
    backup: BackupStatus,
    *,
    secrets_scanned: bool,
    vulns_scanned: bool,
) -> SecurityScore:
    secrets = [f for f in findings if f.category == "secret"]
    vulns = [f for f in findings if f.category == "vuln"]
    cats: list[CategoryScore] = []

    # Authentication — static token today; MFA/user-table raise it (Phase 2)
    auth = 30
    if posture.mfa_enabled:
        auth += 40
    if posture.user_table_present:
        auth += 20
    cats.append(CategoryScore(name="Authentication", score=min(100, auth),
                              detail="static admin token; no MFA" if not posture.mfa_enabled else "MFA on"))

    # Encryption / secrets-at-rest — vault good, plaintext files + secret findings bad
    if not secrets_scanned and not posture.plaintext_secret_files:
        enc = None
        enc_detail = "not scanned"
    else:
        enc_base = 100 - 20 * len(posture.plaintext_secret_files)
        enc = _penalize(max(0, enc_base), secrets)
        enc_detail = f"{len(posture.plaintext_secret_files)} plaintext secret file(s), {len(secrets)} finding(s)"
    cats.append(CategoryScore(name="Encryption / secrets-at-rest", score=enc, detail=enc_detail))

    # Backups — real freshness
    if not backup.configured:
        cats.append(CategoryScore(name="Backups", score=0, detail="no restic repo configured"))
    elif backup.last_snapshot_age_s is None:
        cats.append(CategoryScore(name="Backups", score=20, detail="configured but no snapshot yet"))
    else:
        b = 100
        if backup.check_ok is False:
            b -= 50
        if backup.last_snapshot_age_s > _BACKUP_STALE_S:
            b -= 40
        cats.append(CategoryScore(name="Backups", score=max(0, b),
                                  detail=f"age={backup.last_snapshot_age_s}s check_ok={backup.check_ok}"))

    # API Security — HTTPS via Railway + bearer tiers; rate-limit unknown unless asserted
    api = 80
    if posture.rate_limiting_present is True:
        api = 95
    elif posture.rate_limiting_present is False:
        api = 65
    cats.append(CategoryScore(name="API Security", score=api,
                              detail="HTTPS+bearer tiers; rate-limit "
                                     + {True: "on", False: "MISSING", None: "unknown"}[posture.rate_limiting_present]))

    # Agent Security — governance is KAI's strength
    agent = 90 if posture.governance_ok else 40
    cats.append(CategoryScore(name="Agent Security", score=agent,
                              detail="scopes+@audited+kill-switches" if posture.governance_ok else "governance degraded"))

    # Infrastructure / Vulns
    if not vulns_scanned:
        cats.append(CategoryScore(name="Infrastructure / Vulns", score=None, detail="not scanned"))
    else:
        cats.append(CategoryScore(name="Infrastructure / Vulns", score=_penalize(100, vulns),
                                  detail=f"{len(vulns)} vuln finding(s)"))

    # Overall: weighted mean of KNOWN categories; cap below 100 if anything unknown
    weights = _category_weights()
    known = [(c, weights.get(c.name, 1.0)) for c in cats if c.score is not None]
    has_unknown = any(c.score is None for c in cats)
    if not known:
        overall = None
    else:
        total_w = sum(w for _, w in known) or 1.0
        overall = round(sum(c.score * w for c, w in known) / total_w)
        if has_unknown:
            overall = min(overall, 95)
    return SecurityScore(overall=overall, categories=cats)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_score.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
git add backend/app/services/security/score.py backend/tests/security/test_score.py
git commit -m "feat(security): pure, honest 6-category score engine"
```

---

## Task 4: Runner base + secrets runner (gitleaks + trufflehog)

**Files:**
- Create: `backend/app/services/security/runners/__init__.py`, `backend/app/services/security/runners/base.py`, `backend/app/services/security/runners/secrets.py`
- Test: `backend/tests/security/test_runner_secrets.py`, fixtures `backend/tests/security/fixtures/gitleaks.json`, `trufflehog.jsonl`

**Interfaces:**
- Consumes: `models.Finding`.
- Produces:
  - `base.run_cmd(argv: list[str], cwd: str | None = None, timeout: int = 600) -> tuple[int, str, str]` — returns `(returncode, stdout, stderr)`; never raises on non-zero exit.
  - `secrets.parse_gitleaks(stdout: str) -> list[Finding]`
  - `secrets.parse_trufflehog(stdout: str) -> list[Finding]`
  - `secrets.scan_secrets(paths: list[str]) -> tuple[list[Finding], list[RunnerStatus]]` — runs both tools over each path; tool-isolated.

- [ ] **Step 1: Write the failing test (parsers, fixture-driven — no live scan)**

`backend/tests/security/fixtures/gitleaks.json`:
```json
[
  {"RuleID":"aws-access-token","Description":"AWS Access Key","File":"data/.env","StartLine":12,"Secret":"AKIAIOSFODNN7EXAMPLE","Match":"AKIA...","Fingerprint":"data/.env:aws-access-token:12"}
]
```

`backend/tests/security/fixtures/trufflehog.jsonl`:
```json
{"DetectorName":"AWS","Verified":true,"Raw":"AKIAIOSFODNN7EXAMPLE","Redacted":"AKIA...","SourceMetadata":{"Data":{"Filesystem":{"file":"data/.env","line":12}}}}
```

`backend/tests/security/test_runner_secrets.py`:
```python
from pathlib import Path

from app.services.security.runners.secrets import parse_gitleaks, parse_trufflehog

FIX = Path(__file__).parent / "fixtures"


def test_parse_gitleaks_redacts():
    findings = parse_gitleaks((FIX / "gitleaks.json").read_text())
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "secret" and f.tool == "gitleaks"
    assert "AKIAIOSFODNN7EXAMPLE" not in str(f.model_dump())
    assert f.location == "data/.env:12"


def test_parse_trufflehog_verified_flag():
    findings = parse_trufflehog((FIX / "trufflehog.jsonl").read_text())
    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "trufflehog" and f.verified is True
    assert f.severity == "critical"  # verified live cred
    assert "AKIAIOSFODNN7EXAMPLE" not in str(f.model_dump())


def test_parse_gitleaks_empty():
    assert parse_gitleaks("") == []
    assert parse_gitleaks("[]") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_runner_secrets.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/security/runners/__init__.py`:
```python
```

`backend/app/services/security/runners/base.py`:
```python
from __future__ import annotations

import hashlib
import subprocess


def run_cmd(argv: list[str], cwd: str | None = None, timeout: int = 600) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"binary not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {argv[0]}"


def sha256_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
```

`backend/app/services/security/runners/secrets.py`:
```python
from __future__ import annotations

import json
import time

from ..models import Finding, RunnerStatus
from .base import run_cmd


def parse_gitleaks(stdout: str) -> list[Finding]:
    stdout = stdout.strip()
    if not stdout:
        return []
    data = json.loads(stdout)
    out: list[Finding] = []
    for item in data:
        loc = f"{item.get('File','?')}:{item.get('StartLine','?')}"
        out.append(Finding.create(
            category="secret", severity="high", tool="gitleaks",
            title=item.get("Description") or item.get("RuleID") or "secret",
            location=loc, secret=item.get("Secret") or item.get("Fingerprint") or loc,
            verified=False,
            metadata={"rule": item.get("RuleID")},
        ))
    return out


def parse_trufflehog(stdout: str) -> list[Finding]:
    out: list[Finding] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if "DetectorName" not in item:
            continue
        fs = (item.get("SourceMetadata") or {}).get("Data", {}).get("Filesystem", {})
        loc = f"{fs.get('file','?')}:{fs.get('line','?')}"
        verified = bool(item.get("Verified"))
        out.append(Finding.create(
            category="secret", severity="critical" if verified else "high",
            tool="trufflehog", title=f"{item.get('DetectorName','secret')} credential",
            location=loc, secret=item.get("Raw") or item.get("Redacted") or loc,
            verified=verified, metadata={"detector": item.get("DetectorName")},
        ))
    return out


def scan_secrets(paths: list[str]) -> tuple[list[Finding], list[RunnerStatus]]:
    findings: list[Finding] = []
    statuses: list[RunnerStatus] = []
    for tool, argv_fn, parser in (
        ("gitleaks", lambda p: ["gitleaks", "detect", "--no-git", "-f", "json", "-r", "/dev/stdout", "-s", p], parse_gitleaks),
        ("trufflehog", lambda p: ["trufflehog", "filesystem", p, "--json", "--no-update"], parse_trufflehog),
    ):
        t0 = time.time()
        ok, err = True, None
        try:
            for p in paths:
                rc, out, serr = run_cmd(argv_fn(p))
                if rc == 127:
                    ok, err = False, serr
                    break
                findings.extend(parser(out))
        except Exception as e:  # parser/IO failure is isolated to this tool
            ok, err = False, str(e)
        statuses.append(RunnerStatus(tool=tool, ok=ok, error=err,
                                     duration_ms=int((time.time() - t0) * 1000)))
    return findings, statuses
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_runner_secrets.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
git add backend/app/services/security/runners/ backend/tests/security/test_runner_secrets.py backend/tests/security/fixtures/gitleaks.json backend/tests/security/fixtures/trufflehog.jsonl
git commit -m "feat(security): secrets runner (gitleaks + trufflehog) with redacting parsers"
```

---

## Task 5: Vulnerability runner (trivy)

**Files:**
- Create: `backend/app/services/security/runners/vulns.py`
- Test: `backend/tests/security/test_runner_vulns.py`, fixture `backend/tests/security/fixtures/trivy.json`

**Interfaces:**
- Produces: `vulns.parse_trivy(stdout: str) -> list[Finding]`; `vulns.scan_vulns(paths: list[str]) -> tuple[list[Finding], list[RunnerStatus]]`. Severity maps trivy `CRITICAL/HIGH/MEDIUM/LOW/UNKNOWN` → our lowercase set (`unknown→info`).

- [ ] **Step 1: Write the failing test**

`backend/tests/security/fixtures/trivy.json`:
```json
{"Results":[{"Target":"requirements.txt","Vulnerabilities":[
  {"VulnerabilityID":"CVE-2024-0001","PkgName":"requests","InstalledVersion":"2.0.0","Severity":"CRITICAL","Title":"RCE in requests"},
  {"VulnerabilityID":"CVE-2024-0002","PkgName":"urllib3","InstalledVersion":"1.0","Severity":"LOW","Title":"info leak"}
]}]}
```

`backend/tests/security/test_runner_vulns.py`:
```python
from pathlib import Path

from app.services.security.runners.vulns import parse_trivy

FIX = Path(__file__).parent / "fixtures"


def test_parse_trivy_maps_severity_and_pkg():
    findings = parse_trivy((FIX / "trivy.json").read_text())
    assert len(findings) == 2
    crit = [f for f in findings if f.severity == "critical"][0]
    assert crit.category == "vuln" and crit.tool == "trivy"
    assert "requests" in crit.location
    assert crit.title.startswith("CVE-2024-0001")


def test_parse_trivy_empty_results():
    assert parse_trivy('{"Results":[]}') == []
    assert parse_trivy("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_runner_vulns.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/security/runners/vulns.py`:
```python
from __future__ import annotations

import json
import time

from ..models import Finding, RunnerStatus
from .base import run_cmd

_SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "UNKNOWN": "info"}


def parse_trivy(stdout: str) -> list[Finding]:
    stdout = stdout.strip()
    if not stdout:
        return []
    data = json.loads(stdout)
    out: list[Finding] = []
    for res in data.get("Results") or []:
        target = res.get("Target", "?")
        for v in res.get("Vulnerabilities") or []:
            vid = v.get("VulnerabilityID", "CVE-?")
            loc = f"{v.get('PkgName','?')}@{v.get('InstalledVersion','?')} ({target})"
            out.append(Finding.create(
                category="vuln", severity=_SEV.get(v.get("Severity", "UNKNOWN"), "info"),
                tool="trivy", title=f"{vid}: {v.get('Title','')}".strip(), location=loc,
                secret=None, metadata={"cve": vid, "pkg": v.get("PkgName")},
            ))
    return out


def scan_vulns(paths: list[str]) -> tuple[list[Finding], list[RunnerStatus]]:
    findings: list[Finding] = []
    t0 = time.time()
    ok, err = True, None
    for p in paths:
        rc, out, serr = run_cmd(["trivy", "fs", "--quiet", "--format", "json",
                                 "--scanners", "vuln,secret,misconfig", p])
        if rc == 127:
            ok, err = False, serr
            break
        try:
            findings.extend(parse_trivy(out))
        except Exception as e:
            ok, err = False, str(e)
            break
    return findings, [RunnerStatus(tool="trivy", ok=ok, error=err,
                                   duration_ms=int((time.time() - t0) * 1000))]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_runner_vulns.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
git add backend/app/services/security/runners/vulns.py backend/tests/security/test_runner_vulns.py backend/tests/security/fixtures/trivy.json
git commit -m "feat(security): trivy vulnerability runner"
```

---

## Task 6: Backup runner (restic → B2)

**Files:**
- Create: `backend/app/services/security/runners/backup.py`
- Test: `backend/tests/security/test_runner_backup.py`, fixture `backend/tests/security/fixtures/restic_snapshots.json`

**Interfaces:**
- Produces:
  - `backup.parse_snapshots(stdout: str, now_epoch: float) -> tuple[int, int|None]` — returns `(snapshot_count, newest_age_seconds_or_None)`.
  - `backup.run_backup_and_check(repo: str, backup_paths: list[str], now_epoch: float) -> tuple[BackupStatus, RunnerStatus]` — if `restic` missing or repo env unset, returns `configured=False`. (Live restic calls are exercised only via the worker; unit test covers the pure parser.)

- [ ] **Step 1: Write the failing test**

`backend/tests/security/fixtures/restic_snapshots.json`:
```json
[
  {"time":"2026-06-18T00:00:00Z","id":"aaaa","paths":["/Users/jhonwheeler/wheellsverse_bots/data"]},
  {"time":"2026-06-17T00:00:00Z","id":"bbbb","paths":["/Users/jhonwheeler/wheellsverse_bots/data"]}
]
```

`backend/tests/security/test_runner_backup.py`:
```python
from datetime import datetime, timezone
from pathlib import Path

from app.services.security.runners.backup import parse_snapshots

FIX = Path(__file__).parent / "fixtures"


def test_parse_snapshots_counts_and_age():
    now = datetime(2026, 6, 18, 1, 0, 0, tzinfo=timezone.utc).timestamp()  # 1h after newest
    count, age = parse_snapshots((FIX / "restic_snapshots.json").read_text(), now)
    assert count == 2
    assert 3500 < age < 3700  # ~3600s


def test_parse_snapshots_empty():
    assert parse_snapshots("[]", 0.0) == (0, None)
    assert parse_snapshots("", 0.0) == (0, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_runner_backup.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/security/runners/backup.py`:
```python
from __future__ import annotations

import json
import os
import time
from datetime import datetime

from ..models import BackupStatus, RunnerStatus
from .base import run_cmd


def parse_snapshots(stdout: str, now_epoch: float) -> tuple[int, int | None]:
    stdout = stdout.strip()
    if not stdout:
        return 0, None
    snaps = json.loads(stdout)
    if not snaps:
        return 0, None
    newest = None
    for s in snaps:
        t = datetime.fromisoformat(s["time"].replace("Z", "+00:00")).timestamp()
        newest = t if newest is None else max(newest, t)
    return len(snaps), int(now_epoch - newest)


def run_backup_and_check(repo: str, backup_paths: list[str], now_epoch: float) -> tuple[BackupStatus, RunnerStatus]:
    t0 = time.time()
    if not repo or not os.environ.get("RESTIC_PASSWORD"):
        return (BackupStatus(repo=repo, configured=False),
                RunnerStatus(tool="restic", ok=False, error="repo or RESTIC_PASSWORD unset",
                             duration_ms=int((time.time() - t0) * 1000)))
    env_repo = ["-r", repo]
    run_cmd(["restic", *env_repo, "backup", *backup_paths])  # best effort
    rc_chk, _, chk_err = run_cmd(["restic", *env_repo, "check"])
    rc_snap, snap_out, snap_err = run_cmd(["restic", *env_repo, "snapshots", "--json"])
    if rc_snap == 127:
        return (BackupStatus(repo=repo, configured=False),
                RunnerStatus(tool="restic", ok=False, error="restic not installed",
                             duration_ms=int((time.time() - t0) * 1000)))
    count, age = parse_snapshots(snap_out, now_epoch)
    status = BackupStatus(repo=repo, configured=True, snapshot_count=count,
                          last_snapshot_age_s=age, check_ok=(rc_chk == 0))
    return (status, RunnerStatus(tool="restic", ok=(rc_snap == 0),
                                 error=(snap_err or chk_err or None) if rc_snap else None,
                                 duration_ms=int((time.time() - t0) * 1000)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_runner_backup.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
git add backend/app/services/security/runners/backup.py backend/tests/security/test_runner_backup.py backend/tests/security/fixtures/restic_snapshots.json
git commit -m "feat(security): restic backup runner + snapshot-age parser"
```

---

## Task 7: Worker orchestrator

**Files:**
- Create: `scripts/security_worker.py`
- Test: `backend/tests/security/test_worker.py`

**Interfaces:**
- Consumes: runners (`scan_secrets`, `scan_vulns`, `run_backup_and_check`), `SecurityStore`, `compute_score`, models, `is_scope_enabled`.
- Produces:
  - `security_worker.build_posture(plaintext_files: list[str]) -> Posture`
  - `security_worker.run_scan(store: SecurityStore, *, by: str, scan_paths: list[str], backup_repo: str, backup_paths: list[str], now_epoch: float) -> SecuritySnapshot` — orchestrates runners, persists findings + latest.json, returns the snapshot. **Pure of argv**: it calls the runner functions (which are monkeypatched in tests).
  - `security_worker.main()` — entrypoint: resolves config from env, acquires lockfile, honors `.request`, calls `run_scan`, notifies Telegram on new critical/verified.

- [ ] **Step 1: Write the failing test (monkeypatch runners — no real scanners)**

`backend/tests/security/test_worker.py`:
```python
import importlib.util
from pathlib import Path

from app.services.security.models import BackupStatus, Finding, RunnerStatus
from app.services.security.store import SecurityStore

# load scripts/security_worker.py by path (it lives outside the app package)
_WORKER = Path(__file__).resolve().parents[3] / "scripts" / "security_worker.py"
spec = importlib.util.spec_from_file_location("security_worker", _WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_run_scan_persists_findings_and_score(tmp_path, monkeypatch):
    crit = Finding.create("vuln", "critical", "trivy", "CVE-X", "pkg")
    monkeypatch.setattr(worker, "scan_secrets", lambda paths: ([], [RunnerStatus(tool="gitleaks", ok=True)]))
    monkeypatch.setattr(worker, "scan_vulns", lambda paths: ([crit], [RunnerStatus(tool="trivy", ok=True)]))
    monkeypatch.setattr(worker, "run_backup_and_check",
                        lambda repo, paths, now: (BackupStatus(configured=False), RunnerStatus(tool="restic", ok=False)))

    store = SecurityStore(tmp_path)
    snap = worker.run_scan(store, by="on-demand", scan_paths=["x"], backup_repo="",
                           backup_paths=[], now_epoch=1000.0)

    assert snap.by == "on-demand"
    assert snap.score.overall is not None
    # findings persisted + latest.json written + redaction held
    assert (tmp_path / "vulns.jsonl").exists()
    assert worker.SecuritySnapshot is not None
    reloaded = store.read_latest()
    assert reloaded is not None and len(reloaded.findings) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_worker.py -v`
Expected: FAIL — `FileNotFoundError`/`spec is None` because `scripts/security_worker.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

`scripts/security_worker.py`:
```python
#!/usr/bin/env python3
"""KAI Security Center worker — runs scanners OUT OF PROCESS from the daemon.

Invoked by launchd (scheduled) or by the trigger wrapper when data/security/.request
exists. Writes redacted findings + latest.json that the daemon reads. The daemon
never imports or runs this file.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

# make `app.*` importable when run as a standalone script
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "backend"))

from app.services.security.models import Posture, SecuritySnapshot  # noqa: E402
from app.services.security.runners.backup import run_backup_and_check  # noqa: E402
from app.services.security.runners.secrets import scan_secrets  # noqa: E402
from app.services.security.runners.vulns import scan_vulns  # noqa: E402
from app.services.security.score import compute_score  # noqa: E402
from app.services.security.store import SecurityStore  # noqa: E402

try:
    from app.services.governance import is_scope_enabled  # noqa: E402
except Exception:  # governance import must never crash the worker
    def is_scope_enabled(scope: str) -> bool:  # type: ignore
        return os.environ.get("KAI_SCOPE_SECURITY", "") in ("1", "true", "yes", "on")


def _plaintext_secret_files(repo: Path) -> list[str]:
    found = []
    for pat in (".env", ".env.bak", ".env.local"):
        p = repo / pat
        if p.exists():
            found.append(str(p))
    return found


def build_posture(plaintext_files: list[str]) -> Posture:
    scopes = [s.replace("KAI_SCOPE_", "").lower() for s in os.environ if s.startswith("KAI_SCOPE_")]
    return Posture(
        mfa_enabled=False,
        user_table_present=False,
        plaintext_secret_files=plaintext_files,
        rate_limiting_present=None,
        governance_ok=True,
        scopes_enabled=scopes,
    )


def run_scan(store, *, by, scan_paths, backup_repo, backup_paths, now_epoch) -> SecuritySnapshot:
    sec_findings, sec_status = scan_secrets(scan_paths)
    vuln_findings, vuln_status = scan_vulns(scan_paths)
    backup_status, restic_status = run_backup_and_check(backup_repo, backup_paths, now_epoch)

    findings = sec_findings + vuln_findings
    store.append_findings(findings)

    posture = build_posture(_plaintext_secret_files(_REPO))
    score = compute_score(findings, posture, backup_status,
                          secrets_scanned=all(s.ok for s in sec_status),
                          vulns_scanned=all(s.ok for s in vuln_status))
    snap = SecuritySnapshot(by=by, findings=findings, backup=backup_status,
                            runner_status=sec_status + vuln_status + [restic_status],
                            posture=posture, score=score)
    store.write_latest(snap)
    return snap


def _notify(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass


def main() -> int:
    if not is_scope_enabled("security.scan"):
        print("security.scan scope disabled; exiting")
        return 0
    base = SecurityStore.default_dir()
    store = SecurityStore(base)
    lock = base / ".lock"
    if lock.exists():
        print("another scan in progress; exiting")
        return 0
    lock.write_text(str(os.getpid()))
    try:
        by = "on-demand" if store.consume_request() else "scheduled"
        scan_paths = [p for p in os.environ.get(
            "KAI_SECURITY_SCAN_PATHS", str(_REPO)).split(":") if p]
        backup_repo = os.environ.get("RESTIC_REPOSITORY", "")
        backup_paths = [p for p in os.environ.get(
            "KAI_SECURITY_BACKUP_PATHS", str(_REPO / "data")).split(":") if p]
        snap = run_scan(store, by=by, scan_paths=scan_paths, backup_repo=backup_repo,
                        backup_paths=backup_paths, now_epoch=time.time())
        crit = [f for f in snap.findings if f.severity == "critical" or f.verified]
        if crit:
            _notify(f"🔐 KAI Security: {len(crit)} critical/verified finding(s). "
                    f"Score={snap.score.overall}. Check the Security tab.")
        print(f"scan complete: {len(snap.findings)} findings, score={snap.score.overall}")
        return 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    import urllib.parse  # local import keeps top clean
    raise SystemExit(main())
```

(Note: move `import urllib.parse` to the top imports block alongside `urllib.request` when implementing — shown here at bottom only to flag the dependency. Final file should have both at top.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
chmod +x scripts/security_worker.py
git add scripts/security_worker.py backend/tests/security/test_worker.py
git commit -m "feat(security): isolated scan worker (orchestrates runners, persists snapshot)"
```

---

## Task 8: Admin router + tab registration + main wiring

**Files:**
- Create: `backend/app/routers/admin_security.py`
- Modify: `backend/app/main.py` (add `app.include_router(admin_security.router)` next to the other admin routers)
- Modify: `backend/app/services/audit/auditor.py` (add a `SUBSYSTEMS` entry)
- Test: `backend/tests/security/test_admin_security.py`

**Interfaces:**
- Consumes: `SecurityStore`, `models`, `require_admin_token`, `audited`.
- Produces routes (all under `require_admin_token`):
  - `GET /admin/security/summary` → `{score, counts_by_severity, backup, runner_status, generated_at, by}` (reads `latest.json`; fail-soft `{"status":"no-data"}` if absent).
  - `GET /admin/security/findings?category=&severity=` → filtered findings from `latest.json`.
  - `GET /admin/security/score` → the `SecurityScore`.
  - `POST /admin/security/scan` → `@audited(scope="security.scan", destructive=False)`; writes `.request`; returns `{"queued": true}`. **Never spawns a process.**

- [ ] **Step 1: Write the failing test**

`backend/tests/security/test_admin_security.py`:
```python
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ["KAI_SCOPE_SECURITY"] = "1"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KAI_SECURITY_DIR", str(tmp_path))
    from app.main import app  # imported after env is set
    return TestClient(app)


def _h():
    return {"X-Admin-Token": "test-admin-token"}


def test_summary_no_data_is_soft(client):
    r = client.get("/admin/security/summary", headers=_h())
    assert r.status_code == 200
    assert r.json().get("status") == "no-data"


def test_summary_requires_token(client):
    assert client.get("/admin/security/summary").status_code in (401, 403)


def test_scan_queues_marker_without_spawning(client, tmp_path):
    r = client.post("/admin/security/scan", headers=_h())
    assert r.status_code == 200 and r.json().get("queued") is True
    assert (tmp_path / ".request").exists()  # only a marker was written
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_admin_security.py -v`
Expected: FAIL — route 404 / import error for `admin_security`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/routers/admin_security.py`:
```python
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query

from app.dependencies.admin import require_admin_token
from app.services.governance import audited
from app.services.security.store import SecurityStore

router = APIRouter(prefix="/admin/security", tags=["security"],
                   dependencies=[Depends(require_admin_token)])


def _store() -> SecurityStore:
    return SecurityStore(SecurityStore.default_dir())


@router.get("/summary")
def summary():
    snap = _store().read_latest()
    if snap is None:
        return {"status": "no-data"}
    counts = Counter(f.severity for f in snap.findings)
    return {
        "generated_at": snap.generated_at,
        "by": snap.by,
        "score": snap.score.model_dump(),
        "counts_by_severity": dict(counts),
        "backup": snap.backup.model_dump(),
        "runner_status": [s.model_dump() for s in snap.runner_status],
    }


@router.get("/findings")
def findings(category: str | None = Query(None), severity: str | None = Query(None)):
    snap = _store().read_latest()
    if snap is None:
        return {"findings": []}
    items = snap.findings
    if category:
        items = [f for f in items if f.category == category]
    if severity:
        items = [f for f in items if f.severity == severity]
    return {"findings": [f.model_dump() for f in items]}


@router.get("/score")
def score():
    snap = _store().read_latest()
    return (snap.score.model_dump() if snap else {"overall": None, "categories": []})


@audited(scope="security.scan", destructive=False)
def _queue_scan() -> dict:
    _store().request_scan()
    return {"queued": True}


@router.post("/scan")
def scan():
    # @audited enforces KAI_SCOPE_SECURITY_SCAN and records the action
    return _queue_scan()
```

Modify `backend/app/main.py` — add to the security/admin import group and registration block (next to `admin_audit`):
```python
from app.routers import admin_security  # add near the other admin router imports
# ...
app.include_router(admin_security.router)  # add near app.include_router(admin_audit.router)
```

Modify `backend/app/services/audit/auditor.py` — add one row to the `SUBSYSTEMS` list:
```python
    {
        "key": "security",
        "name": "Security Center",
        "scope": "security",
        "tab": "security",
        "router": "/admin/security",
        "store": None,
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_admin_security.py -v`
Expected: PASS (3 passed).

Then run the full security suite + a smoke of the existing suite:
Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/ -v && python -m pytest tests/test_audit*.py -q`
Expected: all PASS, no regression in the audit tests.

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
git add backend/app/routers/admin_security.py backend/app/main.py backend/app/services/audit/auditor.py backend/tests/security/test_admin_security.py
git commit -m "feat(security): admin_security router + tab #14 registration + main wiring"
```

---

## Task 9: launchd jobs + trigger wrapper

**Files:**
- Create: `deploy/security_trigger.sh`, `deploy/com.wheellsverse.kai.security-scan.plist`, `deploy/com.wheellsverse.kai.security-trigger.plist`
- Test: `backend/tests/security/test_trigger_marker.py` (verifies the daemon→marker→worker contract at the store level — the shell glue itself is verified manually)

**Interfaces:**
- The scheduled plist runs the worker daily. The trigger plist runs `security_trigger.sh` every 300s; the script runs the worker **only if** `data/security/.request` exists.

- [ ] **Step 1: Write the failing test (marker contract)**

`backend/tests/security/test_trigger_marker.py`:
```python
from app.services.security.store import SecurityStore


def test_daemon_writes_marker_worker_consumes_it(tmp_path):
    daemon_side = SecurityStore(tmp_path)
    daemon_side.request_scan()                 # what POST /scan does
    worker_side = SecurityStore(tmp_path)      # separate process, same dir
    assert worker_side.consume_request() is True
    assert worker_side.consume_request() is False
```

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `cd ~/wheellsverse_bots/backend && python -m pytest tests/security/test_trigger_marker.py -v`
Expected: PASS immediately (exercises Task 2 code — this task's deliverable is the glue files; the test pins the contract they depend on).

- [ ] **Step 3: Write the glue files**

`deploy/security_trigger.sh`:
```bash
#!/bin/bash
# Runs the security worker ONLY when an on-demand scan was requested.
set -euo pipefail
REPO="$HOME/wheellsverse_bots"
DIR="${KAI_SECURITY_DIR:-$REPO/data/security}"
if [ -f "$DIR/.request" ]; then
  exec /usr/bin/python3 "$REPO/scripts/security_worker.py"
fi
```

`deploy/com.wheellsverse.kai.security-scan.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.wheellsverse.kai.security-scan</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/jhonwheeler/wheellsverse_bots/scripts/security_worker.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/jhonwheeler/wheellsverse_bots/data/logs/security-scan.log</string>
  <key>StandardErrorPath</key><string>/Users/jhonwheeler/wheellsverse_bots/data/logs/security-scan.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

`deploy/com.wheellsverse.kai.security-trigger.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.wheellsverse.kai.security-trigger</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string>
    <string>/Users/jhonwheeler/wheellsverse_bots/deploy/security_trigger.sh</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardErrorPath</key><string>/Users/jhonwheeler/wheellsverse_bots/data/logs/security-trigger.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

- [ ] **Step 4: Manual verification (documented, not run by CI)**

```bash
chmod +x deploy/security_trigger.sh
# (operator) load jobs once secrets/B2 are configured:
#   cp deploy/com.wheellsverse.kai.security-*.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.wheellsverse.kai.security-scan.plist
#   launchctl load ~/Library/LaunchAgents/com.wheellsverse.kai.security-trigger.plist
```

- [ ] **Step 5: Commit**

```bash
cd ~/wheellsverse_bots
chmod +x deploy/security_trigger.sh
git add deploy/security_trigger.sh deploy/com.wheellsverse.kai.security-scan.plist deploy/com.wheellsverse.kai.security-trigger.plist backend/tests/security/test_trigger_marker.py
git commit -m "feat(security): launchd scheduled scan + on-demand trigger wrapper"
```

---

## Task 10: Security tab UI

**Files:**
- Modify: `frontend/admin/index.html`

**Interfaces:** consumes `GET /admin/security/summary`, `/findings`, and `POST /admin/security/scan` with the `X-Admin-Token` header the dashboard already attaches to admin calls.

- [ ] **Step 1: Add the tab nav entry + panel**

Find the tab nav list and the tab-content container in `frontend/admin/index.html` (same place the other tabs like `browser`, `twin` are declared). Add a nav button:
```html
<button class="tab-btn" data-tab="security">🔐 Security</button>
```
And a panel:
```html
<section id="tab-security" class="tab-panel" hidden>
  <h2>Security Center</h2>
  <div id="sec-score" class="card">Loading…</div>
  <button id="sec-scan-now" class="btn">Scan now</button>
  <div id="sec-findings" class="card"></div>
</section>
```

- [ ] **Step 2: Add the fetch/render script**

In the dashboard's script section (reuse the existing `adminFetch`/token helper if present; otherwise use the pattern below):
```html
<script>
async function loadSecurity() {
  const h = { 'X-Admin-Token': localStorage.getItem('adminToken') || '' };
  const s = await fetch('/admin/security/summary', { headers: h }).then(r => r.json());
  const scoreEl = document.getElementById('sec-score');
  if (s.status === 'no-data') { scoreEl.textContent = 'No scan yet — click “Scan now”.'; return; }
  const cats = (s.score.categories || []).map(c =>
    `<li>${c.name}: <b>${c.score === null ? 'unknown' : c.score + '%'}</b> <small>${c.detail}</small></li>`).join('');
  scoreEl.innerHTML = `<h3>Overall: ${s.score.overall ?? '—'}/100</h3><ul>${cats}</ul>`;
  const f = await fetch('/admin/security/findings', { headers: h }).then(r => r.json());
  document.getElementById('sec-findings').innerHTML =
    '<h3>Findings</h3>' + (f.findings.length
      ? '<ul>' + f.findings.map(x => `<li>[${x.severity}] ${x.title} — <code>${x.location}</code></li>`).join('') + '</ul>'
      : '<p>None 🎉</p>');
}
document.getElementById('sec-scan-now')?.addEventListener('click', async () => {
  const h = { 'X-Admin-Token': localStorage.getItem('adminToken') || '' };
  await fetch('/admin/security/scan', { method: 'POST', headers: h });
  alert('Scan queued — results appear within ~5 min.');
});
// hook into the dashboard's existing tab-switch dispatcher so loadSecurity() runs when the tab opens
</script>
```

- [ ] **Step 3: Manual verification**

Run the daemon locally, open the dashboard, click the Security tab → it shows "No scan yet"; click "Scan now" → a `.request` marker is written (verify with `ls data/security/.request`). After a manual `python3 scripts/security_worker.py`, reload → score + findings render with "unknown" where unmonitored.

- [ ] **Step 4: Commit**

```bash
cd ~/wheellsverse_bots
git add frontend/admin/index.html
git commit -m "feat(security): Security Center dashboard tab #14"
```

---

## Task 11: SECURITY_RULES.md + setup runbook

**Files:**
- Create: `SECURITY_RULES.md` (repo root), `docs/security/SETUP.md`

- [ ] **Step 1: Write `SECURITY_RULES.md`**

Use the operator's original SECURITY RULES content verbatim as the body, prepended with a short "How KAI enforces these" mapping (scopes/@audited → AI-agent rules; wvkey → secrets; this module → scanning/backups). Append the security-architect review prompt (the 10-point checklist from the original brief) under a `## Security-Architect Review Prompt` heading.

- [ ] **Step 2: Write `docs/security/SETUP.md`** — the operator runbook:
```markdown
# Security Center — Setup

## 1. Install scanners
brew install trivy restic trufflehog   # gitleaks already installed

## 2. Backblaze B2
- Create a private bucket (e.g. kai-backups) + an application key.
- Store in wvkey (NOT .env):
    wvkey set B2_ACCOUNT_ID <keyID>
    wvkey set B2_ACCOUNT_KEY <appKey>
    wvkey set RESTIC_PASSWORD <strong-passphrase>
- Set RESTIC_REPOSITORY=b2:kai-backups in the worker's environment.
- Initialize once:  restic init

## 3. Scopes
export KAI_SCOPE_SECURITY=1
export KAI_SCOPE_SECURITY_SCAN=1

## 4. Load launchd jobs
cp deploy/com.wheellsverse.kai.security-*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wheellsverse.kai.security-scan.plist
launchctl load ~/Library/LaunchAgents/com.wheellsverse.kai.security-trigger.plist

## 5. Verify
python3 scripts/security_worker.py   # one manual run
# open dashboard → Security tab → score + findings render
```

- [ ] **Step 3: Commit**

```bash
cd ~/wheellsverse_bots
git add SECURITY_RULES.md docs/security/SETUP.md
git commit -m "docs(security): SECURITY_RULES.md + Security Center setup runbook"
```

---

## Self-Review (completed by author)

**1. Spec coverage:**
- Secret Scanner → Tasks 4, 7 ✓ · Vulnerability Scanner → Tasks 5, 7 ✓ · Backup Monitoring (restic→B2) → Tasks 6, 7, 11 ✓ · Security Score → Task 3 ✓ · isolated-worker/file-boundary → Tasks 2, 7, 9 ✓ · daemon read-only + `.request` → Tasks 8, 9 ✓ · tab #14 → Tasks 8, 10 ✓ · redaction invariant → Tasks 1, 2 (tested) ✓ · governance reuse (`@audited`, scopes) → Task 8 ✓ · error handling (tool-isolated, atomic, fail-soft) → Tasks 2, 4, 5, 6, 8 ✓ · SECURITY_RULES.md → Task 11 ✓ · setup deltas (brew, B2, scopes, launchd) → Tasks 9, 11 ✓.
- Score weights left as operator-owned config in `score.py` (Task 3) — intentional per spec §7.

**2. Placeholder scan:** No TBD/TODO. Every code step has real code. The one annotation (worker `urllib.parse` import) is an explicit implementation note, not a placeholder — the engineer is told to put both `urllib` imports at top.

**3. Type consistency:** `Finding.create(...)`, `SecurityStore` method names, `compute_score(findings, posture, backup, *, secrets_scanned, vulns_scanned)`, `run_scan(store, *, by, scan_paths, backup_repo, backup_paths, now_epoch)`, `parse_gitleaks/parse_trufflehog/parse_trivy/parse_snapshots`, `BackupStatus`/`RunnerStatus`/`Posture`/`SecuritySnapshot` — all defined in Task 1 and used consistently in Tasks 2–10. Router `_queue_scan` wraps `@audited` so scope `security.scan` is enforced.

**Known integration risks the executor must verify against the live tree (do not assume):**
- `auditor.py SUBSYSTEMS` row shape — match the EXACT keys the existing rows use (the row above is illustrative; copy a real neighbor's schema).
- `main.py` router-registration style — match how `admin_audit` is imported/registered.
- `frontend/admin/index.html` tab dispatcher — wire `loadSecurity()` into whatever tab-switch mechanism already exists (don't assume `data-tab`).
- `require_admin_token` header name (`X-Admin-Token`) and `is_scope_enabled` normalization (`security.scan` → `KAI_SCOPE_SECURITY_SCAN`, with parent `KAI_SCOPE_SECURITY`) — confirm in `dependencies/admin.py` and `governance/actions.py`.
