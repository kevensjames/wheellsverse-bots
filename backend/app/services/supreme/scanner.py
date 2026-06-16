"""KAI Supreme scanner — ported from the standalone NarAI Supreme .app.

Differences from the original:
  - Lives inside KAI's uvicorn daemon (no separate Login Item)
  - Paths come from KAI_SUPREME_MAP_PATH env (no hardcoded /Volumes/...)
  - Module-level logger uses the daemon's standard logger
  - No __main__ — scheduler.py drives the loop

Scanners (carried over 1:1):
  ProcessHealthScanner    — pgrep for critical service signatures
  PortHealthScanner       — TCP connect to critical ports
  LogErrorScanner         — ERROR/CRITICAL lines in logs (last hour)
  ApiReachabilityScanner  — HTTP probe of Stripe / Telegram / etc.
  EnvCompletenessScanner  — required env vars present + non-empty
  DiskSpaceScanner        — disk usage threshold breach
  GitStateScanner         — uncommitted file count
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── paths & config ──────────────────────────────────────────────────

# Repo root = .../wheellsverse_bots/. Walk up from this file:
# backend/app/services/supreme/scanner.py → backend/app/services/supreme → backend/app/services → backend/app → backend → REPO
_REPO_ROOT = Path(__file__).resolve().parents[4]

MAP_PATH = Path(
    os.environ.get("KAI_SUPREME_MAP_PATH", str(_REPO_ROOT / "SUPPREMA_MAP.yaml"))
)
SUPREME_ROOT = Path(
    os.environ.get("KAI_SUPREME_ROOT", str(_REPO_ROOT / "data" / "supreme"))
)
PROPOSALS_DIR = SUPREME_ROOT / "proposals"
LOG_DIR = Path(os.environ.get("KAI_SUPREME_LOG_DIR", str(_REPO_ROOT / "logs")))

PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)


# ─── data models ─────────────────────────────────────────────────────

SEVERITY_LEVELS = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class Finding:
    id: str
    severity: str            # low | medium | high | critical
    category: str            # process_health, port_health, log_errors, etc.
    title: str
    detail: str
    evidence: str = ""
    proposed_fix: str = ""
    auto_fixable: bool = False
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ─── map loader ──────────────────────────────────────────────────────

def load_map() -> dict[str, Any]:
    """Read SUPPREMA_MAP.yaml. Returns {} if missing — scanners then run with
    safe defaults rather than crashing the daemon."""
    if not MAP_PATH.exists():
        logger.warning("KAI Supreme map not found at %s — running with defaults", MAP_PATH)
        return {}
    try:
        import yaml
    except ImportError:
        logger.error("pyyaml not installed — KAI Supreme map disabled")
        return {}
    try:
        with MAP_PATH.open() as fp:
            m = yaml.safe_load(fp) or {}
        logger.info(
            "supreme: map loaded v%s last_updated=%s",
            m.get("version"), m.get("last_updated"),
        )
        return m
    except Exception as e:
        logger.exception("supreme: could not parse map: %s", e)
        return {}


# ─── scanners ────────────────────────────────────────────────────────

class Scanner:
    def __init__(self, smap: dict[str, Any]):
        self.smap = smap

    def scan(self) -> list[Finding]:
        raise NotImplementedError


class ProcessHealthScanner(Scanner):
    def scan(self) -> list[Finding]:
        findings: list[Finding] = []
        for svc in self.smap.get("services", []):
            if not svc.get("critical"):
                continue
            if not self._is_running(svc.get("process", "")):
                findings.append(Finding(
                    id=f"proc-{svc['name']}",
                    severity="high",
                    category="process_health",
                    title=f"Critical service down: {svc['name']}",
                    detail=f"Process '{svc.get('process')}' is not running.",
                    proposed_fix=svc.get("restart_command", "no restart_command in map"),
                    auto_fixable=bool(svc.get("restart_command")),
                ))
        return findings

    @staticmethod
    def _is_running(process_signature: str) -> bool:
        if not process_signature:
            return True
        try:
            r = subprocess.run(
                ["pgrep", "-f", process_signature],
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0 and r.stdout.strip() != ""
        except Exception:
            return True  # don't false-alarm if pgrep itself fails


class PortHealthScanner(Scanner):
    def scan(self) -> list[Finding]:
        findings: list[Finding] = []
        for svc in self.smap.get("services", []):
            port = svc.get("port")
            if not port:
                continue
            if not self._port_open(int(port)):
                sev = "critical" if svc.get("critical") else "low"
                findings.append(Finding(
                    id=f"port-{svc['name']}",
                    severity=sev,
                    category="port_health",
                    title=f"Port {port} ({svc['name']}) not listening",
                    detail=f"TCP connect to localhost:{port} failed.",
                ))
        return findings

    @staticmethod
    def _port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except Exception:
            return False


class LogErrorScanner(Scanner):
    def scan(self) -> list[Finding]:
        findings: list[Finding] = []
        if not LOG_DIR.exists():
            return findings
        cutoff = time.time() - 3600
        for log_file in LOG_DIR.glob("*.log"):
            try:
                if log_file.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            errors = self._tail_errors(log_file, limit=5)
            if errors:
                findings.append(Finding(
                    id=f"log-{log_file.stem}",
                    severity="medium",
                    category="log_errors",
                    title=f"Errors in {log_file.name}",
                    detail=f"{len(errors)} ERROR/CRITICAL line(s) in the last hour.",
                    evidence="\n".join(errors[-3:]),
                ))
        return findings

    @staticmethod
    def _tail_errors(path: Path, limit: int = 5) -> list[str]:
        hits: list[str] = []
        try:
            with path.open(errors="replace") as fp:
                for line in fp:
                    if "ERROR" in line or "CRITICAL" in line:
                        hits.append(line.strip()[:300])
                        if len(hits) >= limit * 4:
                            hits = hits[-limit:]
        except Exception:
            pass
        return hits


class ApiReachabilityScanner(Scanner):
    REACHABLE_TESTS = {
        "stripe":   "https://api.stripe.com/v1",
        "telegram": "https://api.telegram.org",
        "openai":   "https://api.openai.com/v1/models",
        "anthropic": "https://api.anthropic.com/v1/messages",
    }

    def scan(self) -> list[Finding]:
        findings: list[Finding] = []
        for name, url in self.REACHABLE_TESTS.items():
            if not self._reachable(url):
                findings.append(Finding(
                    id=f"api-{name}",
                    severity="medium",
                    category="api_reachability",
                    title=f"{name} API unreachable",
                    detail=f"GET {url} failed.",
                ))
        return findings

    @staticmethod
    def _reachable(url: str) -> bool:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kai-supreme/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return 200 <= resp.status < 500
        except urllib.error.HTTPError as e:
            # 4xx = server up, rejecting unauthenticated probe — that's healthy.
            return 200 <= e.code < 500
        except Exception:
            return False


class EnvCompletenessScanner(Scanner):
    """Check that required env vars are present in the DAEMON's live env.

    Reads os.environ directly rather than parsing .env files — KAI may
    pull env from multiple files (root .env + backend/.env), shell
    inheritance, or launchd plist. os.environ is the only place that
    reflects what the code actually sees.
    """

    def scan(self) -> list[Finding]:
        findings: list[Finding] = []
        for api_name, cfg in self.smap.get("apis", {}).items():
            if not cfg.get("critical"):
                continue
            missing = [
                k for k in cfg.get("env_keys", [])
                if not (os.environ.get(k) or "").strip()
            ]
            if missing:
                findings.append(Finding(
                    id=f"env-{api_name}",
                    severity="high",
                    category="env_completeness",
                    title=f"{api_name} env vars missing or empty",
                    detail=f"Missing/empty in os.environ: {', '.join(missing)}",
                ))
        return findings


class DiskSpaceScanner(Scanner):
    def scan(self) -> list[Finding]:
        findings: list[Finding] = []
        try:
            total, used, free = shutil.disk_usage(str(_REPO_ROOT))
            free_gb = free / 1024**3
            pct = used / total * 100
            # Alert on FREE GB, not %, on a big disk: 82% of 228GB still leaves
            # ~42GB free, which is not an incident. Only genuinely-low free space
            # is actionable.
            if free_gb < 5:
                sev = "critical"
            elif free_gb < 15:
                sev = "high"
            elif free_gb < 30:
                sev = "medium"
            else:
                return findings
            findings.append(Finding(
                id="disk-space",
                severity=sev,
                category="disk_space",
                title=f"Low disk: {free_gb:.0f} GB free",
                detail=f"{free_gb:.0f} GB free of {total // 1024**3} GB total ({pct:.0f}% used).",
                proposed_fix="Clean __pycache__ and old logs.",
                auto_fixable=True,
            ))
        except Exception as e:
            logger.warning("supreme: disk check failed: %s", e)
        return findings


class GitStateScanner(Scanner):
    def scan(self) -> list[Finding]:
        findings: list[Finding] = []
        try:
            r = subprocess.run(
                ["git", "-C", str(_REPO_ROOT), "status", "-s"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                return findings
            # Count only TRACKED modifications — untracked output (??) is bot
            # churn (data/outputs/logs), not "work at risk of being lost".
            lines = [l for l in r.stdout.splitlines() if l.strip() and not l.startswith("??")]
            count = len(lines)
            if count > 50:
                findings.append(Finding(
                    id="git-dirty-large",
                    severity="high",
                    category="git_state",
                    title=f"Working tree has {count} uncommitted changes",
                    detail="Large diff = risk of losing work. Commit or stash.",
                ))
            elif count > 20:
                findings.append(Finding(
                    id="git-dirty",
                    severity="medium",
                    category="git_state",
                    title=f"Working tree has {count} uncommitted changes",
                    detail="Consider committing soon.",
                ))
        except Exception as e:
            logger.warning("supreme: git check failed: %s", e)
        return findings


SCANNER_REGISTRY: dict[str, type[Scanner]] = {
    "process_health":   ProcessHealthScanner,
    "port_health":      PortHealthScanner,
    "log_errors":       LogErrorScanner,
    "api_reachability": ApiReachabilityScanner,
    "env_completeness": EnvCompletenessScanner,
    "disk_space":       DiskSpaceScanner,
    "git_state":        GitStateScanner,
}


# ─── orchestration ───────────────────────────────────────────────────

def scan_once(smap: dict[str, Any] | None = None) -> list[Finding]:
    """Run all configured scanners once. Each scanner failure is isolated —
    one broken scanner doesn't block the others."""
    if smap is None:
        smap = load_map()
    active = set(
        smap.get("supreme", {}).get("scans", list(SCANNER_REGISTRY.keys()))
    )
    scanners = [
        cls(smap) for name, cls in SCANNER_REGISTRY.items() if name in active
    ]
    findings: list[Finding] = []
    for s in scanners:
        try:
            hits = s.scan()
            findings.extend(hits)
            logger.info("supreme:   %s: %d finding(s)", s.__class__.__name__, len(hits))
        except Exception as e:
            logger.exception("supreme: scanner %s crashed: %s", s.__class__.__name__, e)
    return findings


def save_proposal(findings: list[Finding]) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = PROPOSALS_DIR / f"scan-{ts}.json"
    payload = {
        "scanned_at": ts,
        "finding_count": len(findings),
        "severity_counts": _severity_counts(findings),
        "findings": [asdict(f) for f in findings],
    }
    out.write_text(json.dumps(payload, indent=2))
    logger.info("supreme: proposal saved: %s", out.name)
    return out


def _severity_counts(findings: list[Finding]) -> dict[str, int]:
    out = {k: 0 for k in SEVERITY_LEVELS}
    for f in findings:
        if f.severity in out:
            out[f.severity] += 1
    return out


# ─── telegram notifier ───────────────────────────────────────────────

def telegram_send(text: str) -> bool:
    """Fire-and-forget Telegram notification. Returns True on success.

    Reuses the operator's existing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env.
    Failure is logged but never raises — supreme cycles must continue even if
    Telegram is down.
    """
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat_id):
        logger.info("supreme: telegram disabled (token/chat_id missing)")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.error("supreme: telegram send failed: %s", e)
        return False


def format_findings_for_telegram(
    findings: list[Finding], min_severity: str = "medium"
) -> str | None:
    threshold = SEVERITY_LEVELS.get(min_severity, 2)
    important = [
        f for f in findings
        if SEVERITY_LEVELS.get(f.severity, 0) >= threshold
    ]
    if not important:
        return None

    important.sort(key=lambda f: -SEVERITY_LEVELS.get(f.severity, 0))
    lines = [f"*KAI Supreme — {len(important)} issue(s) found*", ""]
    emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
    for f in important[:8]:
        lines.append(f"{emoji.get(f.severity, '⚪')} *{f.severity.upper()}* — {f.title}")
        if f.detail:
            lines.append(f"  _{f.detail[:200]}_")
        if f.proposed_fix:
            lines.append(f"  → Fix: `{f.proposed_fix[:150]}`")
        lines.append("")
    if len(important) > 8:
        lines.append(f"... and {len(important) - 8} more. Check the admin panel.")
    return "\n".join(lines)


def run_full_cycle(smap: dict[str, Any] | None = None) -> tuple[Path, list[Finding]]:
    """One full cycle: scan → save proposal → telegram on medium+. Returns
    (proposal_path, findings) so callers (the manual 'scan now' endpoint)
    can return the proposal path to the operator immediately."""
    if smap is None:
        smap = load_map()
    logger.info("supreme: === scan cycle start ===")
    findings = scan_once(smap)
    path = save_proposal(findings)
    min_sev = smap.get("supreme", {}).get("telegram_notify_severity", "medium")
    msg = format_findings_for_telegram(findings, min_sev)
    if msg:
        sent = telegram_send(msg)
        logger.info("supreme: telegram sent: %s", sent)
    else:
        logger.info("supreme: all clear (or below %s threshold)", min_sev)
    logger.info("supreme: === scan cycle end ===")
    return path, findings
