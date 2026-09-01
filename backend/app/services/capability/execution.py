"""KAI Capability Fabric — the single CapabilityExecutionService (§29/§30).

The missing production execution boundary. ONE authoritative service that both the owner-only HTTP
admin route AND KAI's internal Brain flow call — never two implementations. It is THIN: it resolves
the principal (from KAI identity, never the request body §4), resolves the manifest, validates the
operation against a SERVER-OWNED allowlist (never an arbitrary tool/command/shell/path §23), applies
the V1 read-only/compute envelope (§7), health-gates the runtime (§13), then delegates the actual
policy + execution to the existing ``governed_invoke`` (§2 — no duplicated logic). Results come back
normalized, UNTRUSTED, injection-scanned, size-bounded, and audited by that core.

Pure stdlib. Clocks/counters are injectable so it is testable as a plain ``python3`` script.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from .manifest import ActionClass
from .risk import Principal
from .registry import CapabilityRegistry
from .invocation import InvocationContext, governed_invoke
from .results import NormalizedResult, ResultKind
from .adapter import ExternalBlockedAdapter
from .live_adapters import MarkItDownAdapter, YtDlpAdapter, CodebaseMemoryMcpAdapter


# ── normalized execution statuses (§5/§26) ───────────────────────────────────
class Status:
    OK = "OK"
    DENIED = "DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    OPERATION_NOT_ENABLED = "OPERATION_NOT_ENABLED"     # exists but outside the V1 envelope
    CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
    OPERATION_UNKNOWN = "OPERATION_UNKNOWN"             # not on the server allowlist (incl. delete/install)
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"   # runtime health not READY (§13)
    INPUT_REJECTED = "INPUT_REJECTED"                   # SSRF / arbitrary path / bad input (§9/§10)
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


class InputRejected(Exception):
    """Raised by an operation's build_request when the caller input is unsafe/invalid."""


# ── §10/§24 SSRF guard: only public http(s), never private/loopback/link-local/metadata ──
_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {"localhost", "metadata", "metadata.google.internal", "instance-data",
                      "metadata.goog"}


def _ip_forbidden(ip) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified)


def validate_public_url(url: str, *, resolver: Callable[[str], list[str]] | None = None) -> tuple[bool, str]:
    """True only for a public http(s) URL. Rejects non-http schemes (file://, ftp://, gopher://…),
    literal private/loopback/link-local/metadata IPs, and hostnames that RESOLVE to any such IP.
    ``resolver`` is injectable so tests need no DNS; the default uses getaddrinfo."""
    if not isinstance(url, str) or not url:
        return False, "empty url"
    try:
        parts = urlsplit(url)
    except Exception:
        return False, "unparseable url"
    if parts.scheme not in _ALLOWED_SCHEMES:
        return False, f"scheme {parts.scheme or '(none)'!r} not allowed — http/https only"
    host = parts.hostname
    if not host:
        return False, "no host"
    if host.lower() in _BLOCKED_HOSTNAMES:
        return False, "blocked internal hostname"
    try:                                            # literal IP → check directly (no DNS)
        return (False, "private/loopback/link-local ip") if _ip_forbidden(ipaddress.ip_address(host)) else (True, "ok")
    except ValueError:
        pass                                        # a hostname → resolve + check every A/AAAA
    resolve = resolver or (lambda h: [ai[4][0] for ai in socket.getaddrinfo(h, None)])
    try:
        ips = resolve(host)
    except Exception:
        return False, "host does not resolve"
    if not ips:
        return False, "host does not resolve"
    for raw in ips:
        try:
            ip = ipaddress.ip_address(str(raw).split("%")[0])
        except ValueError:
            return False, "unresolvable address"
        if _ip_forbidden(ip):
            return False, "hostname resolves to a private/loopback/link-local address"
    return True, "ok"


# ── §9/§45 MarkItDown file boundary: server-owned fixtures ONLY (no arbitrary path) ──
_FIXTURE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "fixtures"))
_MARKITDOWN_FIXTURES = {"sample-report"}   # name -> <name>.html under the fixtures dir


def resolve_fixture(name: Any) -> str:
    """Map an allowlisted fixture NAME to a contained file path. Any arbitrary/traversal path is
    rejected — there is no managed user-file mechanism wired yet (USER_FILE_INPUT_PENDING, §9)."""
    if name not in _MARKITDOWN_FIXTURES:
        raise InputRejected("markitdown V1 accepts only an allowlisted fixture id (no filesystem paths)")
    p = os.path.realpath(os.path.join(_FIXTURE_DIR, str(name) + ".html"))
    if not (p == _FIXTURE_DIR or p.startswith(_FIXTURE_DIR + os.sep)) or not os.path.isfile(p):
        raise InputRejected("fixture not found within the contained fixtures directory")
    return p


# ── §8 operation allowlist — each capability declares its OPERATIONS (server-owned, typed) ──
@dataclass
class OperationSpec:
    action_class: ActionClass
    v1_eligible: bool                                   # in the V1 read-only/compute envelope? (§7)
    network_profile: str                                # NONE | PUBLIC_INTERNET_READ | APPROVED_API | INTERNAL
    build_request: Callable[[dict], dict]               # validate caller input → adapter request (raises InputRejected)
    evidence: Callable[[dict, NormalizedResult], dict]  # derive non-secret evidence (§21)
    safe_test: dict | None = None                       # a server-owned safe test input for the Nexus TEST action (§31)


def _ytdlp_metadata_request(inp: dict) -> dict:
    url = (inp or {}).get("url")
    ok, why = validate_public_url(url)
    if not ok:
        raise InputRejected(f"url rejected: {why}")
    return {"url": url, "action": "extract_info"}


def _ytdlp_metadata_evidence(inp: dict, r: NormalizedResult) -> dict:
    d = r.data if isinstance(r.data, dict) else {}
    return {"source_url": (inp or {}).get("url"), "title": d.get("title"),
            "extractor": d.get("extractor"), "duration_s": d.get("duration"),
            "provenance": r.provenance.value}


def _markitdown_request(inp: dict) -> dict:
    if (inp or {}).get("path") is not None:
        raise InputRejected("arbitrary filesystem paths are not accepted (§9)")
    return {"path": resolve_fixture((inp or {}).get("fixture"))}


def _markitdown_evidence(inp: dict, r: NormalizedResult) -> dict:
    d = r.data if isinstance(r.data, dict) else {}
    return {"input_fixture": (inp or {}).get("fixture"), "output_chars": d.get("chars"),
            "converter": "markitdown", "provenance": r.provenance.value}


def _cbm_search_request(inp: dict) -> dict:
    project = (inp or {}).get("project")
    query = (inp or {}).get("query")
    if not isinstance(project, str) or not isinstance(query, str) or not project or not query:
        raise InputRejected("search requires string 'project' and 'query'")
    return {"tool": "search_graph", "flags": {"project": project, "query": query}}


def _cbm_search_evidence(inp: dict, r: NormalizedResult) -> dict:
    return {"project": (inp or {}).get("project"), "query": (inp or {}).get("query"),
            "provenance": r.provenance.value}


OPERATIONS: dict[str, dict[str, OperationSpec]] = {
    "yt-dlp": {
        "metadata": OperationSpec(ActionClass.READ_ONLY, True, "PUBLIC_INTERNET_READ",
                                  _ytdlp_metadata_request, _ytdlp_metadata_evidence),
        # download stays an ActionProposal, never directly executable in V1 (§8/§11)
        "download": OperationSpec(ActionClass.REVERSIBLE_WRITE, False, "PUBLIC_INTERNET_READ",
                                  lambda inp: {"url": (inp or {}).get("url"), "action": "download"},
                                  _ytdlp_metadata_evidence),
    },
    "markitdown": {
        "convert": OperationSpec(ActionClass.READ_ONLY, True, "NONE",
                                 _markitdown_request, _markitdown_evidence,
                                 safe_test={"fixture": "sample-report"}),
    },
    "codebase-memory-mcp": {
        "search": OperationSpec(ActionClass.READ_ONLY, True, "NONE",
                                _cbm_search_request, _cbm_search_evidence),
    },
}


def default_adapter_resolver(cap_id: str):
    """cap_id → the live adapter, or the honest ExternalBlockedAdapter for everything else (§2/§46)."""
    if cap_id == "markitdown":
        return MarkItDownAdapter()
    if cap_id == "yt-dlp":
        return YtDlpAdapter()
    if cap_id == "codebase-memory-mcp":
        return CodebaseMemoryMcpAdapter()
    return ExternalBlockedAdapter(cap_id, "no live adapter built for this capability")


@dataclass
class ExecutionResult:
    capability_id: str
    operation: str
    status: str
    result: Any = None
    evidence: dict = field(default_factory=dict)
    provenance: str = "UNAVAILABLE"
    duration_ms: int = 0
    correlation_id: str = ""
    reason: str = ""
    injection_flags: list = field(default_factory=list)
    replayed: bool = False

    def to_dict(self) -> dict:
        return {"capability_id": self.capability_id, "operation": self.operation, "status": self.status,
                "result": self.result, "evidence": self.evidence, "provenance": self.provenance,
                "duration_ms": self.duration_ms, "correlation_id": self.correlation_id,
                "reason": self.reason, "injection_flags": self.injection_flags, "replayed": self.replayed}


# default per-capability timeout ceilings (ms) applied when the manifest declares none (§15)
_DEFAULT_TIMEOUT_MS = {"yt-dlp": 30000, "markitdown": 30000, "codebase-memory-mcp": 120000}
_FALLBACK_TIMEOUT_MS = 30000


class CapabilityExecutionService:
    """The one execution implementation (§29/§30). HTTP route and Brain both call ``invoke``."""

    def __init__(self, registry: CapabilityRegistry, *, adapter_resolver=default_adapter_resolver,
                 audit: Callable | None = None, clock: Callable[[], float] | None = None,
                 rate_limit_per_min: int = 30):
        self.registry = registry
        self._resolve_adapter = adapter_resolver
        self.audit = audit
        self._clock = clock or time.monotonic
        self._seq = 0
        self._idem: dict[tuple, ExecutionResult] = {}
        self._rate: dict[tuple, list[float]] = {}
        self._rate_limit = rate_limit_per_min

    def _next_corr(self, mission_id: str, cap: str, op: str) -> str:
        self._seq += 1
        return f"{mission_id or 'nomiss'}-{cap}-{op}-{self._seq}"

    def _rate_ok(self, principal_id: str, cap: str) -> bool:
        now = self._clock()
        key = (principal_id, cap)
        window = [t for t in self._rate.get(key, []) if now - t < 60.0]
        if len(window) >= self._rate_limit:
            self._rate[key] = window
            return False
        window.append(now)
        self._rate[key] = window
        return True

    def operations(self, cap_id: str) -> list[str]:
        return sorted(OPERATIONS.get(cap_id, {}).keys())

    def invoke(self, capability_id: str, operation: str, input: dict, principal: Principal, *,
               mission_id: str = "", context: dict | None = None, idempotency_key: str = "",
               timeout_ms: int | None = None) -> ExecutionResult:
        corr = self._next_corr(mission_id, capability_id, operation)

        def done(status, *, result=None, evidence=None, provenance="UNAVAILABLE", reason="",
                 flags=None, t0=None, replayed=False):
            dur = int((self._clock() - t0) * 1000) if t0 is not None else 0
            er = ExecutionResult(capability_id, operation, status, result=result, evidence=evidence or {},
                                 provenance=provenance, duration_ms=dur, correlation_id=corr, reason=reason,
                                 injection_flags=list(flags or []), replayed=replayed)
            self._emit("capability.invoke_" + ("completed" if status == Status.OK else
                       ("denied" if status in (Status.DENIED, Status.OPERATION_NOT_ENABLED, Status.INPUT_REJECTED,
                                               Status.OPERATION_UNKNOWN, Status.CAPABILITY_UNKNOWN,
                                               Status.CAPABILITY_UNAVAILABLE, Status.RATE_LIMITED) else "failed")),
                       principal, capability_id, operation, status, corr, mission_id)
            return er

        # §20 request event
        self._emit("capability.invoke_requested", principal, capability_id, operation, "requested", corr, mission_id)

        # 1. rate limit (owner-scoped, per capability) — §18
        if not self._rate_ok(principal.id, capability_id):
            return done(Status.RATE_LIMITED, reason="rate limit exceeded")
        # 2. idempotency replay — §19
        idem_key = (principal.id, capability_id, operation, idempotency_key) if idempotency_key else None
        if idem_key and idem_key in self._idem:
            prior = self._idem[idem_key]
            return ExecutionResult(**{**prior.to_dict(), "correlation_id": corr, "replayed": True})
        # 3. capability resolves through the registry — §3
        if not self.registry.has(capability_id):
            return done(Status.CAPABILITY_UNKNOWN, reason="unknown capability")
        # 4. operation on the SERVER allowlist — §8/§23 (delete/install/etc. are simply not here)
        spec = OPERATIONS.get(capability_id, {}).get(operation)
        if spec is None:
            return done(Status.OPERATION_UNKNOWN, reason="operation not on the capability allowlist")
        # 5. V1 envelope — only read-only/compute operations execute now (§7)
        if not spec.v1_eligible or spec.action_class not in (ActionClass.READ_ONLY,):
            return done(Status.OPERATION_NOT_ENABLED,
                        reason=f"'{operation}' ({spec.action_class.value}) is outside the V1 read-only/compute envelope")
        # 6. validate + build the adapter request (SSRF / fixtures / typed input) — §4/§9/§10
        try:
            request = spec.build_request(input or {})
        except InputRejected as e:
            return done(Status.INPUT_REJECTED, reason=str(e))
        # 7. health gate — never speculatively execute an unhealthy runtime (§13)
        adapter = self._resolve_adapter(capability_id)
        h = adapter.health()
        if h.get("state") != "READY":
            return done(Status.CAPABILITY_UNAVAILABLE, reason=h.get("reason", "not ready"))
        # 8. delegate to the existing governed core — principal from ctx, NOT input (§2/§4)
        t0 = self._clock()
        ctx = InvocationContext(principal=principal, mission_id=mission_id, correlation_id=corr)
        eff_timeout = min(timeout_ms, _DEFAULT_TIMEOUT_MS.get(capability_id, _FALLBACK_TIMEOUT_MS)) \
            if timeout_ms else _DEFAULT_TIMEOUT_MS.get(capability_id, _FALLBACK_TIMEOUT_MS)
        r = governed_invoke(self.registry, adapter, capability_id, spec.action_class, request, ctx,
                            audit=self._gov_audit, timeout_ms=eff_timeout)
        # 9. map the normalized result → an execution status (§5)
        if r.kind == ResultKind.ACTION_PROPOSAL:
            return done(Status.APPROVAL_REQUIRED, reason=r.summary, provenance=r.provenance.value,
                        flags=r.injection_flags, t0=t0)
        if r.kind == ResultKind.FAILURE:
            status = Status.TIMEOUT if "timeout" in (r.summary or "") else \
                     (Status.DENIED if (r.summary or "").startswith("denied") else Status.FAILED)
            return done(status, reason=r.summary, provenance=r.provenance.value, flags=r.injection_flags, t0=t0)
        er = done(Status.OK, result=r.data, evidence=spec.evidence(input or {}, r),
                  provenance=r.provenance.value, flags=r.injection_flags, t0=t0)
        if idem_key:
            self._idem[idem_key] = er
        return er

    def _emit(self, event, principal, cap, op, status, corr, mission_id):
        if self.audit is None:
            return
        try:
            self.audit({"event": event, "principal": principal.id, "role": principal.role,
                        "capability": cap, "operation": op, "status": status,
                        "correlation_id": corr, "mission_id": mission_id})
        except Exception:   # noqa: BLE001 — audit must never break execution
            pass

    def _gov_audit(self, ev):
        """Adapt governed_invoke's AuditEvent → the SAME dict shape the service emits (one sink)."""
        if self.audit is None:
            return
        try:
            self.audit({"event": ev.event, "capability": ev.capability, "action_class": ev.action_class,
                        "decision": ev.decision, "status": ev.status, **ev.context})
        except Exception:   # noqa: BLE001
            pass
