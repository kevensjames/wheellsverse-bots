"""Wheellsverse production monitor — pure alert-pipeline core (no network, fully testable).

Envelope + redaction + severity + thresholds + dedup/cooldown/recovery.
This module NEVER imports network/secrets; all live I/O lives in collectors.py / delivery.py.
Design invariants:
  - No alert payload may ever carry a secret (see SECRET_KEYS / SECRET_PATTERNS + redact()).
  - Distinct CRITICAL incidents are never suppressed by another signal's cooldown.
  - Recovery is emitted once when a firing signal clears; a later re-breach is a NEW alert.
"""
from __future__ import annotations
import json, re, hashlib
from dataclasses import dataclass, field, asdict

# ---- severity ----------------------------------------------------------------
INFO, WARNING, HIGH, CRITICAL = "INFO", "WARNING", "HIGH", "CRITICAL"
_SEV_RANK = {INFO: 0, WARNING: 1, HIGH: 2, CRITICAL: 3}

# ---- redaction ---------------------------------------------------------------
# Values of these envelope/context keys are always fully redacted.
SECRET_KEYS = {
    "authorization", "cookie", "set-cookie", "x-api-key", "api_key",
    "session_signing_secret", "openai_api_key", "database_url", "redis_url",
    "telegram_bot_token", "stripe_secret_key", "wv_session",
}
# Substring patterns scrubbed from ANY free-text field.
SECRET_PATTERNS = [
    re.compile(r"wv_session=[^\s;\"']+", re.I),
    re.compile(r"api[_-]?key=[^\s&\"']+", re.I),
    re.compile(r"bearer\s+[A-Za-z0-9._\-]+", re.I),
    re.compile(r"(?:postgres|postgresql)://[^\s\"']+", re.I),
    re.compile(r"redis://[^\s\"']+", re.I),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),                     # OpenAI-style key (incl. sk-proj-…)
    re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}\b"),            # telegram bot token id:hash
    re.compile(r"\b[0-9a-fA-F]{40,}\b"),                       # long hex secret/token
]
_REDACTED = "[REDACTED]"

def _scrub_text(s: str) -> str:
    for pat in SECRET_PATTERNS:
        s = pat.sub(_REDACTED, s)
    return s

def redact(obj):
    """Recursively redact secrets from a dict/list/str destined for an alert payload."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in SECRET_KEYS:
                out[k] = _REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return _scrub_text(obj)
    return obj

# ---- alert envelope ----------------------------------------------------------
@dataclass
class Alert:
    signal: str                 # e.g. "app_b_5xx"
    severity: str               # INFO|WARNING|HIGH|CRITICAL
    summary: str
    environment: str = "production"
    service: str = ""           # app_a | app_b | bridge | monitor
    observed_value: object = None
    threshold: object = None
    window: str = ""
    correlation_id: str = ""
    runbook: str = ""
    recovery_state: str = "firing"   # firing | recovered
    context: dict = field(default_factory=dict)
    alert_id: str = ""
    timestamp: str = ""         # set by caller (ISO); core stays clock-free for determinism

    def dedup_key(self) -> str:
        return f"{self.environment}:{self.service}:{self.signal}:{self.severity}"

    def compute_id(self) -> str:
        h = hashlib.sha1(f"{self.dedup_key()}:{self.timestamp}".encode()).hexdigest()[:12]
        return f"alrt_{h}"

    def safe_payload(self) -> dict:
        """The dict actually sent — fully redacted, secret-free by construction."""
        d = asdict(self)
        return redact(d)

    def render_text(self) -> str:
        tag = "✅ RECOVERED" if self.recovery_state == "recovered" else f"🚨 {self.severity}"
        lines = [
            f"WHEELLSVERSE {self.environment.upper()} — {tag}",
            f"signal: {self.signal}  service: {self.service or '-'}",
            f"summary: {self.summary}",
        ]
        if self.observed_value is not None:
            lines.append(f"observed: {self.observed_value}  threshold: {self.threshold}")
        if self.window:
            lines.append(f"window: {self.window}")
        if self.correlation_id:
            lines.append(f"correlation_id: {self.correlation_id}")
        if self.runbook:
            lines.append(f"runbook: {self.runbook}")
        if self.alert_id:
            lines.append(f"alert_id: {self.alert_id}")
        return _scrub_text("\n".join(lines))


# ---- thresholds (grounded in ALERT_THRESHOLDS.md + soak baseline) -------------
# Baseline p95: App A ~274ms, App B ~209ms.
THRESHOLDS = {
    "health_latency_ms": {"warn": 2000, "crit": 5000},
    "openai_daily_cost_usd": {"warn": 5.0, "crit": 20.0},
    "openai_hourly_cost_usd": {"crit": 2.0},
    "provider_failure_rate_pct": {"warn": 10.0, "crit": 30.0},
    "auth_fail_burst_5min": {"warn": 10},
}
RUNBOOKS = {
    "app_a_5xx": "APP_A_5XX: check Railway wheellsverse-v2 logs + /api/health; if bridge-linked, KAI_BRIDGE_ENABLED=false; else redeploy production@462adff.",
    "app_b_5xx": "APP_B_UNAVAILABLE: check App B /health + correlation IDs; if governance path unstable, KAI_BRIDGE_ENABLED=false (App A degrades to fail-closed 404).",
    "auth_bypass": "AUTHORIZATION_BYPASS: KAI_BRIDGE_ENABLED=false immediately; contain; preserve evidence; investigate. Do not continue governed traffic.",
    "audit_gap": "AUDIT_WRITE_FAILURE: stop privileged governed execution (KAI_BRIDGE_ENABLED=false); preserve logs; investigate llm_call_log/audit persistence.",
    "db_redis": "DATABASE_UNAVAILABLE: do NOT auto-remediate destructively; verify Railway PG/Redis (kai-production); fail closed.",
    "provider": "PROVIDER_DEGRADED: check OpenAI key budget/validity; provider failure must not become fake KAI success; if runaway, KAI_BRIDGE_ENABLED=false.",
    "spend": "SPEND_THRESHOLD: review /admin/spend; money mode is MOCK — this is API cost, not user money; if runaway, contain via kill-switch.",
    "sse": "SSE_DEGRADED: check App B health + bridge timeout; 502/504 sustained → KAI_BRIDGE_ENABLED=false. Client cancellations are normal, exclude them.",
    "latency": "LATENCY: investigate App B/OpenAI latency; contain if user-facing. Baseline A~274ms / B~209ms.",
    "monitor_self": "MONITOR_SELF_FAILURE: collection or delivery failed — do NOT trust 'healthy'; check monitor host + channel creds.",
}


# ---- dedup / cooldown / recovery state --------------------------------------
class AlertState:
    """Tracks firing signals to dedup, apply cooldown, and emit recovery.

    State shape per dedup_key: {"first": tick, "last_sent": tick, "count": n, "sev": sev}.
    `tick` is a monotonic integer the caller supplies (e.g. unix seconds) — core stays clock-free.
    """
    def __init__(self, path=None, cooldown_ticks=900):
        self.path = path
        self.cooldown = cooldown_ticks
        self.firing = {}
        if path:
            try:
                with open(path) as f:
                    raw = json.load(f).get("firing", {})
                # tolerate a corrupt/tampered state file: keep only well-typed entries
                self.firing = {k: v for k, v in raw.items()
                               if isinstance(k, str) and k.count(":") >= 3 and isinstance(v, dict)}
            except (OSError, ValueError, AttributeError):
                self.firing = {}

    def save(self):
        if not self.path:
            return
        try:
            with open(self.path, "w") as f:
                json.dump({"firing": self.firing}, f)
        except OSError:
            pass

    def decide(self, alerts, now_tick):
        """Given the alerts observed THIS tick, return the list to actually deliver.

        - new breach for a key            -> deliver (firing)
        - continued breach within cooldown -> suppress
        - continued breach past cooldown   -> re-deliver (still firing, re-notify)
        - key that was firing but absent now -> deliver a single RECOVERY, clear it
        CRITICAL always delivers on first sight regardless of any other key's cooldown.
        """
        deliver = []
        seen = set()
        for a in alerts:
            a.alert_id = a.compute_id()
            key = a.dedup_key()
            seen.add(key)
            st = self.firing.get(key)
            if st is None:
                self.firing[key] = {"first": now_tick, "last_sent": now_tick, "count": 1, "sev": a.severity}
                deliver.append(a)
            else:
                st["count"] += 1
                if a.severity == CRITICAL and st.get("sev") != CRITICAL:
                    # escalation to CRITICAL is a new, always-delivered event
                    st["sev"] = CRITICAL; st["last_sent"] = now_tick
                    deliver.append(a)
                elif now_tick - st["last_sent"] >= self.cooldown:
                    st["last_sent"] = now_tick
                    deliver.append(a)
                # else: suppressed within cooldown
        # recovery: any key that was firing but not seen this tick
        for key in list(self.firing.keys()):
            if key not in seen:
                st = self.firing.pop(key)
                env, svc, sig, sev = key.split(":", 3)
                rec = Alert(signal=sig, severity=INFO, summary=f"{sig} recovered", environment=env,
                            service=svc, recovery_state="recovered",
                            runbook=RUNBOOKS.get(sig, ""))
                rec.timestamp = ""  # caller stamps
                deliver.append(rec)
        return deliver


# ---- self-check --------------------------------------------------------------
def _demo():
    # redaction: no secret pattern survives (synthetic REDACTME fixtures — NO real secret)
    dirty = Alert(signal="x", severity=HIGH, summary="cookie wv_session=REDACTMEexample and sk-REDACTMEexample123",
                  context={"Authorization": "Bearer REDACTMEexample", "DATABASE_URL": "postgres://REDACTME@example/db", "ok": "keep"})
    dirty.timestamp = "T"
    p = dirty.safe_payload()
    blob = json.dumps(p) + dirty.render_text()
    for bad in ["wv_session=REDACTME", "Bearer REDACTME", "postgres://REDACTME", "sk-REDACTME", "REDACTME@example"]:
        assert bad not in blob, f"secret leaked: {bad}"
    assert p["context"]["Authorization"] == _REDACTED
    assert p["context"]["DATABASE_URL"] == _REDACTED
    assert p["context"]["ok"] == "keep"

    # dedup + cooldown + recovery
    st = AlertState(cooldown_ticks=100)
    a1 = Alert(signal="app_b_5xx", severity=HIGH, summary="down", service="app_b"); a1.timestamp = "T"
    d = st.decide([a1], now_tick=0); assert len(d) == 1, "first breach delivers"
    d = st.decide([a1], now_tick=50); assert len(d) == 0, "within cooldown suppressed"
    d = st.decide([a1], now_tick=150); assert len(d) == 1, "past cooldown re-notifies"
    d = st.decide([], now_tick=200)
    assert len(d) == 1 and d[0].recovery_state == "recovered", "recovery emitted once"
    d = st.decide([], now_tick=250); assert len(d) == 0, "no repeat recovery"
    a2 = Alert(signal="app_b_5xx", severity=HIGH, summary="down again", service="app_b"); a2.timestamp = "T"
    d = st.decide([a2], now_tick=300); assert len(d) == 1, "re-breach after recovery is a new alert"

    # CRITICAL escalation always delivers even within cooldown
    st2 = AlertState(cooldown_ticks=1000)
    w = Alert(signal="provider", severity=WARNING, summary="warn", service="app_b"); w.timestamp = "T"
    c = Alert(signal="provider", severity=CRITICAL, summary="crit", service="app_b"); c.timestamp = "T"
    st2.decide([w], now_tick=0)
    d = st2.decide([c], now_tick=1)
    assert any(x.severity == CRITICAL for x in d), "escalation to CRITICAL delivers within cooldown"
    print("core self-check: PASS")

if __name__ == "__main__":
    _demo()
