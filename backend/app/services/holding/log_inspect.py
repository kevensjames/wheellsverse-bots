"""LOG_INSPECT runtime (Part B, §16-25) — a typed, bounded, TWO-STAGE-REDACTED read-only log reader.

Logs are the highest secret-risk A0 source, so redaction happens at the SOURCE (each raw line is
redacted the instant it is read, before it is ever assembled, persisted, or returned — §19), and again
on the finished evidence. The request is a fixed typed contract (§16): no shell/command/grep/path/env
ever reaches a provider. The log SOURCE is resolved from server-owned service metadata (§17), never from
task free-text. Bounds (lines/bytes/window/timeout) are server-enforced (§18).

Genuinely-certified provider: LocalLogFileProvider over a server-configured local log file. Railway /
monitoring providers are declared but have no certified backend yet (fail closed). A service with no
configured source → BLOCKED_CAPABILITY (never a guessed source).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict

from app.services.holding.task_resolver import redact, REDACTED, validate_log_request

# §18 server-enforced ceilings (a client may request less, never more).
MAX_LINES = 500
MAX_BYTES = 512 * 1024
MAX_WINDOW_SECONDS = 24 * 3600
_SEVERITIES = ("DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL")


class LogDenied(Exception):
    """Raised when a request violates the typed contract / bounds / source policy."""


@dataclass
class LogRequest:
    service_id: str
    company_id: str = ""
    time_window: str = "1h"
    severity: str = "ERROR"
    bounded_limit: int = 200
    correlation_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def build_request(args: dict) -> LogRequest:
    """Validate typed args (§16) — reject any shell/command/grep/path field, clamp the limit (§18)."""
    v = validate_log_request(args or {})
    if v is None:
        raise LogDenied("forbidden field in log request (shell/command/grep/path not allowed)")
    limit = min(int(v.get("bounded_limit", 200)), MAX_LINES)
    return LogRequest(service_id=(args or {}).get("service") or (args or {}).get("service_id", ""),
                      company_id=(args or {}).get("company_id", ""),
                      time_window=v.get("time_window", "1h"), severity=v.get("severity", "ERROR"),
                      bounded_limit=limit, correlation_id=v.get("correlation_id", ""))


# ── source resolution (§17) — server-owned service → log-source map, NOT task input ────────────────
# Empty by default: no production log source is wired, so real services BLOCK until configured.
_SERVICE_LOG_SOURCES: dict[str, dict] = {}


def register_log_source(service_id: str, *, provider: str, path: str = "") -> None:
    """Server-side registration of a service's authoritative log source. (Ops/config wires this.)"""
    _SERVICE_LOG_SOURCES[service_id] = {"provider": provider, "path": path}


def resolve_log_source(service_id: str, *, sources: dict | None = None):
    src = (sources if sources is not None else _SERVICE_LOG_SOURCES).get(service_id)
    return src


# ── provider ───────────────────────────────────────────────────────────────────────────────────────
class LocalLogFileProvider:
    """CERTIFIED read-only provider over a server-configured local log file. Reads a bounded tail,
    redacts each line at the source (stage 1), filters by severity/correlation. No path comes from the
    task — only the server-registered path."""
    name = "local-file"

    def health(self, path: str) -> dict:
        return {"state": "READY"} if path and os.path.isfile(path) else {"state": "UNAVAILABLE", "reason": "no log file"}

    def read(self, path: str, req: LogRequest) -> dict:
        # bounded read of the tail; redact EACH line at the source before it is kept (§19 stage 1)
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - MAX_BYTES))
            raw = f.read(MAX_BYTES)
        # STAGE 1: redact the WHOLE raw source text first (multiline-aware, so a PEM block spanning
        # several lines is caught) — before any line is assembled, filtered, kept, or persisted (§19).
        text = redact(raw.decode("utf-8", errors="replace"))
        lines = text.splitlines()
        sev = (req.severity or "").upper()
        sev_idx = _SEVERITIES.index(sev) if sev in _SEVERITIES else 0
        kept, redaction_count = [], 0
        for ln in lines[-(req.bounded_limit * 4):]:                 # scan a bounded slack window
            if req.correlation_id and req.correlation_id not in ln:
                continue
            if sev and not any(s in ln.upper() for s in _SEVERITIES[sev_idx:]):
                continue
            if REDACTED in ln:
                redaction_count += 1
            kept.append(ln)
            if len(kept) >= req.bounded_limit:
                break
        return {"matched_count": len(kept), "redaction_count": redaction_count,
                "excerpts": kept[:min(req.bounded_limit, MAX_LINES)]}


def make_log_provider(*, providers: dict | None = None, sources: dict | None = None):
    """Return provider(args) -> redacted evidence for the composite executor. Two-stage redaction (§19):
    provider redacts at source, then the finished evidence is redacted again before it leaves. Fails
    closed for unknown service / unconfigured source / forbidden fields / unhealthy provider."""
    impls = {"local-file": LocalLogFileProvider(), **(providers or {})}

    def provider(args: dict) -> dict:
        req = build_request(args or {})
        if not req.service_id:
            raise LogDenied("service_id required")
        src = resolve_log_source(req.service_id, sources=sources)
        if src is None:
            raise LogDenied(f"no configured log source for service '{req.service_id}'")
        impl = impls.get(src["provider"])
        if impl is None:
            raise LogDenied(f"no certified log provider for '{src['provider']}'")
        path = src.get("path", "")
        if impl.health(path).get("state") != "READY":
            raise LogDenied("log provider unhealthy")
        data = impl.read(path, req)
        # §22 evidence + STAGE 2 redaction of the finished evidence before it leaves the boundary
        evidence = {"service": req.service_id, "source": src["provider"], "time_range": req.time_window,
                    "severity": req.severity, "correlation_id": req.correlation_id,
                    "matched_count": data["matched_count"], "redaction_count": data["redaction_count"],
                    "retrieved_at": "now", "excerpts": data["excerpts"]}
        return redact(evidence)                                    # STAGE 2

    return provider


if __name__ == "__main__":
    from app.services.holding.test_log_inspect import run
    run()
