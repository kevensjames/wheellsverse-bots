"""Security posture — the holding_deployment.py ANALOG for data-protection & identity (arch §22/§23).

Same deployed!=enabled honesty twin as holding_deployment.Feature.record: a Control's code being
DEPLOYED (``present``) is distinct from its being ENFORCED at runtime (``enforced``). Unlike
holding_deployment (which defaults a missing flag to False), posture NEVER guesses: a missing signal
is ``enforced="UNKNOWN"``, not a fabricated False (§49).

Evidence sources per control:
  - "settings"      : ``enforced`` = a live bool flag (real ENFORCED/DISABLED signal). Absent attr -> UNKNOWN.
  - "config"        : presence-only of a config setting (bool of non-empty). The VALUE is never read or
                      returned — a DB/redis/key is "configured" or not, its contents never leave (§22).
  - "app_a_status"  : App A's SELF-REPORTED TLS/headers/audit/api-key status. When the App A adapter is
                      present these are recorded CLAIMED (self-reported, NOT independently attested);
                      when absent they are NOT_CONNECTED — never assumed enforced (§22/§23).
  - anything else    : no runtime-introspection source (e.g. §24 process tree) -> UNKNOWN, never faked.

Pure/injectable: ``settings`` + an optional ``app_a`` adapter passed in, so this is a plain python3 self-test.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from app.services.security.models import SourceState

_MISSING = object()   # sentinel: distinguishes "attribute absent" (UNKNOWN) from a real False signal


@dataclass
class Control:
    control_id: str
    name: str
    category: str            # transport | identity | access | data_protection | audit | runtime
    runtime_flag: str        # the runtime signal name: a settings attr, or an App A status key ("" = none)
    evidence_source: str     # settings | config | app_a_status | runtime_introspection

    def record(self, settings, *, app_a_signals=None) -> dict:
        d = asdict(self)
        d["present"] = True   # if this code is running, the control's code path is deployed
        enforced, attestation = self._enforced(settings, app_a_signals)
        d["enforced"] = enforced        # bool (real signal) | "UNKNOWN" (no signal — never guessed)
        d["attestation"] = attestation  # LIVE_FLAG | CONFIG_PRESENT | CLAIMED | NOT_CONNECTED | NO_SIGNAL
        return d

    def _enforced(self, settings, app_a_signals):
        src = self.evidence_source
        if src == "settings":
            val = getattr(settings, self.runtime_flag, _MISSING) if self.runtime_flag else _MISSING
            if val is _MISSING:
                return "UNKNOWN", "NO_SIGNAL"
            return bool(val), "LIVE_FLAG"
        if src == "config":
            # presence only — bool(non-empty). The setting's VALUE is never read into the record (§22).
            val = getattr(settings, self.runtime_flag, _MISSING) if self.runtime_flag else _MISSING
            if val is _MISSING:
                return "UNKNOWN", "NO_SIGNAL"
            return bool(val), "CONFIG_PRESENT"
        if src == "app_a_status":
            if not app_a_signals:
                return "UNKNOWN", "NOT_CONNECTED"          # App A adapter absent — never assume enforced
            if self.runtime_flag not in app_a_signals:
                return "UNKNOWN", "NO_SIGNAL"              # connected but did not report this control
            return bool(app_a_signals[self.runtime_flag]), "CLAIMED"  # self-reported, not attested (§22/§23)
        return "UNKNOWN", "NO_SIGNAL"                       # e.g. runtime_introspection — no source (§24)


# Grounded in REAL settings (§22/§23). Settings-flag + config-presence controls read live; App-A controls
# are NOT_CONNECTED until the App A security adapter is wired (Phase A default: no base URL/key).
CONTROL_REGISTRY: list[Control] = [
    # identity / access — enforced from a LIVE settings flag (real ENFORCED/DISABLED signal)
    Control("operator_session", "Operator session enforcement", "identity", "OPERATOR_SESSION_ENABLED", "settings"),
    Control("cyber_ops_gate", "Cyber Operations surface gate", "access", "KAI_CYBER_OPS_ENABLED", "settings"),
    # data protection — CONFIG PRESENCE only (value never read/returned)
    Control("db_configured", "Database connection configured", "data_protection", "DATABASE_URL", "config"),
    Control("app_a_owner_key", "App A security owner key configured", "data_protection", "APP_A_SECURITY_API_KEY", "config"),
    # App A self-reported (CLAIMED, not attested) — NOT_CONNECTED without the App A adapter
    Control("tls_https", "TLS / HTTPS transport", "transport", "https", "app_a_status"),
    Control("security_headers", "HTTP security headers", "transport", "security_headers", "app_a_status"),
    Control("audit_logging", "Audit logging enabled", "audit", "audit_logging", "app_a_status"),
    Control("api_key_auth", "API key authentication", "identity", "api_key_auth", "app_a_status"),
    # runtime introspection unavailable this sprint (§24) — honest UNKNOWN, never a faked process tree
    Control("process_isolation", "Process / service isolation", "runtime", "", "runtime_introspection"),
]


def control_registry(settings) -> list:
    return [c.record(settings) for c in CONTROL_REGISTRY]


def _app_a_signals(app_a, settings):
    """Duck-type the App A adapter into a signals dict, fail-open to None (NOT_CONNECTED) on any error."""
    if app_a is None:
        return None
    try:
        if hasattr(app_a, "read"):
            data = app_a.read(settings)
        elif callable(app_a):
            data = app_a(settings)
        else:
            data = app_a
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def posture_view(settings, *, app_a=None) -> dict:
    """Assemble the §22/§23 posture section. App A transport/header/audit controls are self-reported
    (CLAIMED), not independently attested; absent App A adapter -> NOT_CONNECTED (never assumed enforced)."""
    signals = _app_a_signals(app_a, settings)
    controls = [c.record(settings, app_a_signals=signals) for c in CONTROL_REGISTRY]
    return {
        "app_a_status": SourceState.NOT_CONNECTED.value if signals is None else SourceState.WORKING.value,
        "controls": controls,
        "note": ("App A transport/header/audit controls are self-reported (CLAIMED), not independently "
                 "attested; a missing signal is UNKNOWN, never a guessed enforcement."),
    }


def demo() -> None:
    from types import SimpleNamespace

    # settings with a real True flag, a real False flag, DB present, App A owner key empty (real "not configured")
    s = SimpleNamespace(OPERATOR_SESSION_ENABLED=True, KAI_CYBER_OPS_ENABLED=False,
                        DATABASE_URL="postgresql://u:p@h/db", APP_A_SECURITY_API_KEY="")

    # --- app_a absent -> App A controls NOT_CONNECTED / UNKNOWN, never assumed enforced ---
    v = posture_view(s)
    assert v["app_a_status"] == SourceState.NOT_CONNECTED.value
    byid = {c["control_id"]: c for c in v["controls"]}

    # live settings flags: real bool signals (not UNKNOWN)
    assert byid["operator_session"]["enforced"] is True and byid["operator_session"]["attestation"] == "LIVE_FLAG"
    assert byid["cyber_ops_gate"]["enforced"] is False and byid["cyber_ops_gate"]["attestation"] == "LIVE_FLAG"

    # config presence: DB configured True (value never in record); owner key empty -> real False, not UNKNOWN
    assert byid["db_configured"]["enforced"] is True and byid["db_configured"]["attestation"] == "CONFIG_PRESENT"
    assert "postgresql://" not in str(byid["db_configured"])          # the VALUE never leaves
    assert byid["app_a_owner_key"]["enforced"] is False               # empty key = honest "not configured"

    # App A controls with no adapter: enforced UNKNOWN, attestation NOT_CONNECTED (never guessed enforced)
    for cid in ("tls_https", "security_headers", "audit_logging", "api_key_auth"):
        assert byid[cid]["enforced"] == "UNKNOWN" and byid[cid]["attestation"] == "NOT_CONNECTED", byid[cid]

    # control with NO signal source (runtime introspection, §24) -> UNKNOWN, never a guess
    assert byid["process_isolation"]["enforced"] == "UNKNOWN" and byid["process_isolation"]["present"] is True

    # every control is present (deployed) yet enforcement is separately, honestly reported
    assert all(c["present"] is True for c in v["controls"])

    # --- app_a present (self-reported signals) -> CLAIMED, not attested ---
    signals = {"https": True, "security_headers": False, "audit_logging": True}  # api_key_auth NOT reported
    v2 = posture_view(s, app_a=signals)
    assert v2["app_a_status"] == SourceState.WORKING.value
    byid2 = {c["control_id"]: c for c in v2["controls"]}
    assert byid2["tls_https"]["enforced"] is True and byid2["tls_https"]["attestation"] == "CLAIMED"
    assert byid2["security_headers"]["enforced"] is False and byid2["security_headers"]["attestation"] == "CLAIMED"
    # reported-but-connected-yet-missing key -> UNKNOWN/NO_SIGNAL (App A connected but silent on this control)
    assert byid2["api_key_auth"]["enforced"] == "UNKNOWN" and byid2["api_key_auth"]["attestation"] == "NO_SIGNAL"

    # a broken adapter fails open to NOT_CONNECTED, never raises, never fakes enforcement
    class Boom:
        def read(self, settings):
            raise RuntimeError("app A unreachable")
    v3 = posture_view(s, app_a=Boom())
    assert v3["app_a_status"] == SourceState.NOT_CONNECTED.value

    print("posture.demo OK — deployed!=enforced; live flags real; config presence (value hidden); "
          "App A CLAIMED-not-attested; missing signal UNKNOWN (never guessed); fail-open honest")


if __name__ == "__main__":
    demo()
