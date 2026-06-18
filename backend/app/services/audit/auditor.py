"""KAI self-audit — introspects every KAI subsystem and reports live health.

Pure-ish introspection: reads governance scope flags (env), counts each
subsystem's sidecar store, and reports runtime facts (LLM keys configured,
browser kill-switches). No external calls, no mutation. Powers the Audit
dashboard tab + the audit_query tool, and is the single source of truth for
"what can KAI do right now and is it wired up."

The SUBSYSTEMS registry is the declarative inventory — add a row when a new
KAI feature ships so the audit stays complete.
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# backend/app/services/audit/auditor.py → parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
# Overridable so tests can point at a temp data dir.
DATA_ROOT = _REPO_ROOT / "data"


# Declarative inventory of KAI subsystems. Keep in sync as features ship.
SUBSYSTEMS: list[dict[str, Any]] = [
    {"key": "governance", "name": "Governance + audit log", "scope": None,
     "tab": "brief", "router": "/admin/briefing", "store": "governance/audit.jsonl",
     "kind": "jsonl", "desc": "@audited scope/approval gate + tamper-evident action log"},
    {"key": "presets", "name": "Expert-agent presets", "scope": "presets",
     "tab": "chat", "router": "/admin/presets", "store": None, "kind": None,
     "desc": "SWE/Marketing/Finance/Research/Legal personas + tool whitelists"},
    {"key": "kg", "name": "Knowledge graph", "scope": "kg",
     "tab": "kg", "router": "/admin/kg", "store": "kg/kg.db", "kind": "sqlite",
     "table": "entities", "desc": "SQLite entity+relation store KAI can query"},
    {"key": "failures", "name": "Failure memory", "scope": None,
     "tab": "failures", "router": "/admin/failures", "store": "failures.jsonl",
     "kind": "jsonl", "desc": "remembers + warns about past tool failures"},
    {"key": "research", "name": "Continuous research", "scope": "research",
     "tab": "research", "router": "/admin/research", "store": "research/digests.jsonl",
     "kind": "jsonl", "desc": "daily HN+arXiv+GH scan → digest"},
    {"key": "self_correction", "name": "Self-correction", "scope": "self_correction",
     "tab": "self-correction", "router": "/admin/self-correction",
     "store": "self_correction/events.jsonl", "kind": "jsonl",
     "desc": "critic+reviser pass on KAI's drafts"},
    {"key": "planning", "name": "Long-term planning", "scope": "planning",
     "tab": "planning", "router": "/admin/planning", "store": "planning/planning.db",
     "kind": "sqlite", "table": "plans", "desc": "goal→steps, execute one at a time, revise"},
    {"key": "browser", "name": "Computer-control / browser", "scope": "browser",
     "tab": "browser", "router": "/admin/browser", "store": "browser/actions.jsonl",
     "kind": "jsonl", "desc": "read + propose + (approved) execute, allowlisted"},
    {"key": "learning", "name": "Continuous learning", "scope": "learning",
     "tab": "learning", "router": "/admin/learning", "store": "learning/learning.db",
     "kind": "sqlite", "table": "lessons", "desc": "feedback→lessons→approved prompt injection"},
    {"key": "twin", "name": "Digital twin", "scope": "twin",
     "tab": "twin", "router": "/admin/twin", "store": "twin/twin.db", "kind": "sqlite",
     "table": "entries", "desc": "operator self-model injected to prompt + draft-in-voice"},
    {"key": "briefing", "name": "Daily brief", "scope": "briefing",
     "tab": "brief", "router": "/admin/briefing", "store": None, "kind": None,
     "desc": "operator daily brief (audited)"},
    {"key": "supreme", "name": "Supreme scanner", "scope": None,
     "tab": "scanner", "router": "/admin/supreme", "store": None, "kind": None,
     "desc": "15-min empire health scan (process/port/log/api/disk/git)"},
    {"key": "digest", "name": "Operator Digest", "scope": "digest",
     "tab": "brief", "router": "/admin/digest", "store": "digest/digests.jsonl",
     "kind": "jsonl", "desc": "proactive cross-subsystem synthesis pushed to Telegram"},
    {"key": "security", "name": "Security Center", "scope": "security",
     "tab": "security", "router": "/admin/security", "store": None, "kind": None,
     "desc": "scanners (gitleaks/trivy/trufflehog) + restic backups + honest score"},
]


def run_audit() -> dict[str, Any]:
    """Introspect all subsystems + runtime. Returns a structured report."""
    subs: list[dict[str, Any]] = []
    for s in SUBSYSTEMS:
        scope_enabled = _scope_enabled(s["scope"]) if s.get("scope") else None
        records, store_exists = _count_store(s)
        subs.append({
            "key": s["key"], "name": s["name"], "desc": s["desc"],
            "scope": s.get("scope"), "scope_enabled": scope_enabled,
            "tab": s.get("tab"), "router": s.get("router"),
            "store": s.get("store"), "store_exists": store_exists, "records": records,
        })
    runtime = _runtime()
    issues = _dynamic_issues(subs, runtime)
    enabled = [x for x in subs if x["scope_enabled"]]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "subsystems_total": len(subs),
            "scoped_total": len([x for x in subs if x["scope"]]),
            "scoped_enabled": len(enabled),
            "total_records": sum(x["records"] for x in subs),
            "tabs": sorted({x["tab"] for x in subs if x["tab"]}),
        },
        "runtime": runtime,
        "subsystems": subs,
        "issues": issues,
    }


# ─── internals ──────────────────────────────────────────────────────


def _scope_enabled(scope: str) -> bool:
    try:
        from app.services.governance import is_scope_enabled
        return bool(is_scope_enabled(scope))
    except Exception:
        norm = scope.replace(".", "_").replace("-", "_").upper()
        return (os.environ.get(f"KAI_SCOPE_{norm}") or "").strip().lower() in ("1", "true", "yes", "on")


def _count_store(s: dict[str, Any]) -> tuple[int, bool]:
    store = s.get("store")
    if not store:
        return 0, False
    path = DATA_ROOT / store
    if not path.exists():
        return 0, False
    kind = s.get("kind")
    if kind == "jsonl":
        try:
            return sum(1 for ln in path.read_text().splitlines() if ln.strip()), True
        except Exception:
            return 0, True
    if kind == "sqlite":
        table = s.get("table")
        if not table:
            return 0, True
        try:
            with contextlib.closing(sqlite3.connect(str(path))) as c:
                row = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                return int(row[0]) if row else 0, True
        except Exception:
            return 0, True
    return 0, True


def _runtime() -> dict[str, Any]:
    rt: dict[str, Any] = {
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "ollama_base_set": bool(os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")),
    }
    try:
        from app.services.browser import config as bcfg
        rt["browser_enabled"] = bcfg.browser_enabled()
        rt["browser_write_enabled"] = bcfg.write_enabled()
        rt["browser_allowlist"] = bcfg.allowlist()
    except Exception:
        pass
    return rt


def _dynamic_issues(subs: list[dict[str, Any]], runtime: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not runtime.get("openai_key_set") and not runtime.get("anthropic_key_set"):
        issues.append("No OpenAI or Anthropic key set — KAI has no cloud LLM.")
    for x in subs:
        if x["scope_enabled"] is False:
            issues.append(f"{x['name']}: scope '{x['scope']}' is OFF (feature inactive).")
        if x.get("store") and not x["store_exists"]:
            issues.append(f"{x['name']}: store {x['store']} missing (not yet used).")
    return issues
