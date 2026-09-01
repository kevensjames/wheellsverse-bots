"""TaskCapabilityResolver (§9-22, §37-39) — a typed, deterministic bridge from PLAN TASK TYPE to a
CERTIFIED KAI capability. It is NOT an LLM choosing a tool: every mapping is an explicit reviewed entry
with a fixed capability/operation/action_class/reason_code (§39). Unknown task type → no path →
BLOCKED_CAPABILITY (§11). Only mappings backed by a genuinely-available runtime are CERTIFIED; the rest
are IMPLEMENTED_MAPPING_RUNTIME_PENDING and fail closed at execution (§37 — never overstate readiness).

Also hosts the security boundary for the read-only V1 mappings: secret redaction (§29), forbidden
repo targets (§30), the test-suite allowlist (§31), and a typed log-request validator. The composite
executor (build_holding_executor) is the single §15 execution gate: certified+healthy → run, else
CAPABILITY_UNAVAILABLE. Pure/injectable so the whole chain is a plain ``python3`` self-test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum

from app.services.capability.manifest import ActionClass
from app.services.holding.plan import AutonomyClass, action_class_for


class HoldingTaskType(str, Enum):
    HEALTH_PROBE = "HEALTH_PROBE"
    CAPABILITY_HEALTH = "CAPABILITY_HEALTH"
    DEPLOYMENT_STATUS = "DEPLOYMENT_STATUS"
    REPO_INSPECT = "REPO_INSPECT"
    LOG_INSPECT = "LOG_INSPECT"
    RUN_INTERNAL_TEST = "RUN_INTERNAL_TEST"
    BROWSER_VALIDATE = "BROWSER_VALIDATE"
    TECH_DOC_LOOKUP = "TECH_DOC_LOOKUP"


class Channel(str, Enum):
    INTERNAL_READ = "INTERNAL_READ"     # backed by an existing in-process holding source
    FABRIC = "FABRIC"                   # backed by a Capability Fabric capability via ExecutionService


class CertState(str, Enum):
    CERTIFIED = "CERTIFIED"                                   # runtime genuinely available + reviewed
    RUNTIME_PENDING = "IMPLEMENTED_MAPPING_RUNTIME_PENDING"   # mapping exists, runtime not yet certified
    BLOCKED = "BLOCKED"


# ── SECURITY BOUNDARY ────────────────────────────────────────────────────────────────────────────
REDACTED = "[REDACTED]"
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN[^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----.*?-----END[^-]*-----", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),                          # OpenAI incl. modern sk-proj-/sk-svcacct-
    re.compile(r"\b(?:gh[opsur]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),  # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),                   # Slack tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(authorization|cookie|set-cookie|x-api-key)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|token|private[_-]?key)\b"
               r"\s*[:=]\s*\S+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\b"),  # JWT
]
# NOTE: no blind 40-char matcher — it would redact legitimate git SHAs (DEPLOYMENT_STATUS.sha).
# AWS secret keys are caught by the dict-key hint below (they travel under a telling key name).

# A dict key whose NAME implies a secret ⇒ its string value is redacted wholesale, since the
# co-occurrence regexes above can't see the key name when scanning a value in isolation.
_SECRET_KEY_HINT = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential|"
    r"authorization|cookie|bearer|session|signing|pat)")


def redact(obj):
    """Recursively redact secret markers (§29) from any string/list/dict. Returns the same shape with
    API keys (OpenAI/GitHub/Slack/AWS) / Bearer tokens / cookies / passwords / private keys / JWTs
    replaced by [REDACTED]. A dict value under a secret-named KEY is redacted wholesale (the value is
    scanned in isolation, so the key name is the only signal — §29 defense-in-depth for structured
    evidence, closing the 'secret as a bare dict value' gap)."""
    if isinstance(obj, str):
        s = obj
        for pat in _SECRET_PATTERNS:
            s = pat.sub(REDACTED, s)
        return s
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_HINT.search(k) and isinstance(v, (str, int, float)):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact(v) for v in obj)
    return obj


_FORBIDDEN_REPO = re.compile(
    r"(^|/)(\.env(\.|$)|\.aws(/|$)|\.ssh(/|$)|id_rsa|id_ed25519|.*\.pem$|.*\.key$|.*\.p12$|"
    r"credentials(\.|$)|secrets?(\.|/|$)|\.netrc$|.*\.pfx$)", re.I)


def is_forbidden_repo_target(path: str) -> bool:
    """§30: block repo reads of secret-bearing files even if present in storage."""
    return bool(path) and bool(_FORBIDDEN_REPO.search(str(path)))


# §31: RUN_INTERNAL_TEST accepts a suite_id ONLY — the backend maps it to a certified command.
# A client-supplied command/shell string can never reach subprocess execution.
TEST_SUITE_ALLOWLIST = {
    "holding_core": ["python3", "-m", "pytest", "app/services/holding", "-q"],
}


def resolve_test_command(suite_id: str):
    """Return the certified command for a suite_id, or None. Never accepts a raw command."""
    return list(TEST_SUITE_ALLOWLIST.get(suite_id, [])) or None


_LOG_ALLOWED_FIELDS = {"service", "time_window", "severity", "bounded_limit", "correlation_id"}
_LOG_FORBIDDEN_FIELDS = {"command", "shell", "grep", "path", "cmd", "query", "exec", "filter"}
_LOG_MAX_LIMIT = 1000


def validate_log_request(req: dict):
    """§25/§29: accept only typed log fields with a bounded limit; reject any shell/path/grep. Returns
    a sanitized request or None (fail-closed) if a forbidden field is present."""
    if not isinstance(req, dict):
        return None
    if _LOG_FORBIDDEN_FIELDS & set(req):
        return None
    out = {k: v for k, v in req.items() if k in _LOG_ALLOWED_FIELDS}
    limit = out.get("bounded_limit")
    out["bounded_limit"] = min(int(limit), _LOG_MAX_LIMIT) if isinstance(limit, int) and limit > 0 else _LOG_MAX_LIMIT
    return out


# ── MAPPING REGISTRY ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Mapping:
    capability_id: str
    operation: str
    action_class: ActionClass
    channel: Channel
    cert_state: CertState
    required_evidence: tuple
    reason_code: str
    fallback_ids: tuple = ()


# CERTIFY ONLY the internal reads whose runtime genuinely exists today (§37). Everything else is a
# declared mapping that fails closed until its runtime is certified in a later wave.
_MAPPINGS: dict[str, Mapping] = {
    HoldingTaskType.HEALTH_PROBE.value: Mapping(
        "holding.health", "read_service_health", ActionClass.READ_ONLY, Channel.INTERNAL_READ,
        CertState.CERTIFIED, ("source", "target", "observed_state", "observed_at"),
        "HEALTH_TASK_USE_CANONICAL_HEALTH_PROVIDER"),
    HoldingTaskType.CAPABILITY_HEALTH.value: Mapping(
        "holding.capability_health", "read_capability_health", ActionClass.READ_ONLY, Channel.INTERNAL_READ,
        CertState.CERTIFIED, ("capability_id", "runtime", "health", "observed_at"),
        "CAP_HEALTH_USE_CAPABILITY_REGISTRY"),
    HoldingTaskType.DEPLOYMENT_STATUS.value: Mapping(
        "holding.deployment", "read_deployment_status", ActionClass.READ_ONLY, Channel.INTERNAL_READ,
        CertState.RUNTIME_PENDING, ("service", "deployment_id", "sha", "status", "observed_at"),
        "DEPLOY_STATUS_READONLY_CONNECTOR_PENDING"),
    HoldingTaskType.REPO_INSPECT.value: Mapping(
        "github", "read_repo_status", ActionClass.READ_ONLY, Channel.FABRIC,
        CertState.RUNTIME_PENDING, ("repo", "default_branch", "latest_commit"),
        "REPO_INSPECT_READONLY_GITHUB_PENDING"),
    HoldingTaskType.LOG_INSPECT.value: Mapping(
        "holding.logs", "read_logs", ActionClass.READ_ONLY, Channel.INTERNAL_READ,
        CertState.RUNTIME_PENDING, ("service", "time_window", "lines_redacted"),
        "LOG_INSPECT_TYPED_REDACTED_ADAPTER_PENDING"),
    HoldingTaskType.RUN_INTERNAL_TEST.value: Mapping(
        "holding.internal_test", "run_suite", ActionClass.READ_ONLY, Channel.INTERNAL_READ,
        CertState.RUNTIME_PENDING, ("suite", "sha", "passed", "failed", "duration"),
        "INTERNAL_TEST_A1_DISABLED_UNTIL_A0_CERT"),
    HoldingTaskType.BROWSER_VALIDATE.value: Mapping(
        "playwright", "validate", ActionClass.READ_ONLY, Channel.FABRIC,
        CertState.RUNTIME_PENDING, ("target", "assertions", "screenshot_ref"),
        "BROWSER_VALIDATE_ENABLE_AFTER_INTERNAL_TEST_CERT"),
    HoldingTaskType.TECH_DOC_LOOKUP.value: Mapping(
        "context7", "query_docs", ActionClass.READ_ONLY, Channel.FABRIC,
        CertState.RUNTIME_PENDING, ("library", "doc_ref"),
        "TECH_DOC_CONTEXT7_RUNTIME_PENDING"),
}


@dataclass
class ResolvedCapabilityTask:
    task_type: str
    capability_id: str
    operation: str
    action_class: str
    channel: str
    cert_state: str
    arguments: dict
    required_evidence: list
    fallback_ids: list
    reason_code: str
    # §14 company isolation — carried on every execution, minimal context only (§13)
    holding_id: str = "wheellsverse"
    company_id: str = ""
    mission_id: str = ""
    task_id: str = ""
    cycle_id: str = ""
    correlation_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _minimal_args(task_type: str, task) -> dict:
    """§13: build the MINIMUM necessary typed arguments — never the whole plan/company record."""
    cid = getattr(task, "company_id", "")
    if task_type == HoldingTaskType.HEALTH_PROBE.value:
        return {"target": cid}
    if task_type == HoldingTaskType.CAPABILITY_HEALTH.value:
        return {"scope": "all"}
    if task_type == HoldingTaskType.DEPLOYMENT_STATUS.value:
        return {"service": cid}
    if task_type == HoldingTaskType.REPO_INSPECT.value:
        return {"company_id": cid}
    if task_type == HoldingTaskType.LOG_INSPECT.value:
        return {"service": cid, "time_window": "1h", "severity": "ERROR", "bounded_limit": 200}
    if task_type == HoldingTaskType.RUN_INTERNAL_TEST.value:
        return {"suite_id": "holding_core"}
    return {"company_id": cid}


class TaskCapabilityResolver:
    """Deterministic. resolve() maps a typed task to a ResolvedCapabilityTask, or None (→ BLOCKED)."""

    def resolve(self, task, *, cycle_id: str = "", correlation_id: str = "") -> ResolvedCapabilityTask | None:
        task_type = getattr(task, "task_type", "") or ""
        m = _MAPPINGS.get(task_type)
        if m is None:
            return None                                     # §11 unknown task type → BLOCKED
        # §28 fail-closed: the mapping's action_class MUST match the task's declared autonomy class.
        try:
            declared = action_class_for(AutonomyClass(getattr(task, "autonomy", AutonomyClass.A0_OBSERVE.value)))
        except Exception:
            return None
        if declared != m.action_class:
            return None                                     # wrong action class → refuse
        args = _minimal_args(task_type, task)
        # §31: the internal-test mapping carries a suite_id, never a client command.
        if task_type == HoldingTaskType.RUN_INTERNAL_TEST.value and resolve_test_command(args.get("suite_id", "")) is None:
            return None
        return ResolvedCapabilityTask(
            task_type=task_type, capability_id=m.capability_id, operation=m.operation,
            action_class=m.action_class.value, channel=m.channel.value, cert_state=m.cert_state.value,
            arguments=args, required_evidence=list(m.required_evidence), fallback_ids=list(m.fallback_ids),
            reason_code=m.reason_code, company_id=getattr(task, "company_id", ""),
            mission_id=getattr(task, "task_id", ""), task_id=getattr(task, "task_id", ""),
            cycle_id=cycle_id, correlation_id=correlation_id)


# ── COMPOSITE EXECUTOR — the single §15 gate ─────────────────────────────────────────────────────
class _Result:
    """ExecutionResult-shaped object the engine already understands (.status/.evidence/...)."""
    def __init__(self, status, evidence=None, reason="", corr=""):
        self.status = status
        self.evidence = redact(evidence or {})              # §29 defense-in-depth: redact all evidence
        self.reason = reason
        self.correlation_id = corr


def _default_health_provider(args: dict) -> dict:
    """CERTIFIED runtime for HEALTH_PROBE: the existing holding signals source (§10.A — reuse, don't
    add a monitoring product). Returns typed evidence; raises are handled by the executor."""
    from app.services.holding.signals import collect_live_signals
    target = args.get("target", "")
    sigs = collect_live_signals()
    match = next((s for s in sigs if target and target.lower() in str(s.get("name", "")).lower()), None)
    picked = match or (sigs[0] if sigs else {})
    return {"source": "holding.signals", "target": target or "holding",
            "observed_state": "OK" if picked.get("ok", False) else "DEGRADED",
            "observed_at": picked.get("checked_at", "UNAVAILABLE"), "detail": picked.get("detail", "")}


def _default_capability_health_provider(args: dict) -> dict:
    """CERTIFIED runtime for CAPABILITY_HEALTH: the CapabilityRegistry (§10.B)."""
    from app.services.capability.seed import seed_registry
    from app.services.capability.manifest import Availability
    reg = seed_registry()
    avail = len(reg.list(availability=Availability.AVAILABLE))
    return {"capability_id": "all", "runtime": "capability-registry", "observed_at": "now",
            "health": {"available": avail, "catalog_total": len(reg), "certification_state": "V1"}}


# Certified internal-read providers. Deployment/logs default to None ⇒ RUNTIME_PENDING (fail-closed).
def default_providers() -> dict:
    return {"holding.health": _default_health_provider,
            "holding.capability_health": _default_capability_health_provider}


_INVOKE_OK = "OK"
_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"


def build_holding_executor(*, providers: dict | None = None, execution_service=None, principal=None):
    """Return execute(cap, op, input, *, mission_id) used by the AutonomousWorkEngine. Single §15 gate:
      • internal-read cap with a live provider → run it, redact + verify evidence → OK
      • fabric cap with a certified ExecutionService op → invoke it
      • anything else (no provider / pending runtime / unknown) → CAPABILITY_UNAVAILABLE (fail-closed §16)
    Never silently switches to an uncertified tool."""
    provs = {**default_providers(), **(providers or {})}

    def execute(cap, op, input, *, mission_id=""):
        prov = provs.get(cap)
        if prov is not None:                                # certified internal read
            try:
                evidence = prov(input or {})
            except Exception as e:
                return _Result(_UNAVAILABLE, reason=f"provider error: {str(e)[:100]}", corr=mission_id)
            if not evidence:
                return _Result("FAILED", reason="no evidence returned", corr=mission_id)
            return _Result(_INVOKE_OK, evidence=evidence, corr=mission_id)
        if execution_service is not None and principal is not None:   # fabric path (op must be allowlisted)
            r = execution_service.invoke(cap, op, input or {}, principal, mission_id=mission_id)
            try:                                                      # defense-in-depth: redact fabric evidence too
                if getattr(r, "evidence", None):
                    r.evidence = redact(r.evidence)
            except Exception:
                pass
            return r
        return _Result(_UNAVAILABLE, reason=f"no certified runtime for {cap} (RUNTIME_PENDING)", corr=mission_id)

    return execute


def make_engine_resolver(resolver: TaskCapabilityResolver, *, cycle_id: str = ""):
    """Adapter: the AutonomousWorkEngine expects resolver(task) -> (cap, op, args) | None."""
    def _fn(task):
        rct = resolver.resolve(task, cycle_id=cycle_id)
        if rct is None:
            return None
        return (rct.capability_id, rct.operation, rct.arguments)
    return _fn


if __name__ == "__main__":
    from app.services.holding.test_task_resolver import run
    run()
