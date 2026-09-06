"""Configuration flag integrity — the silent-drop hazard, closed. Zero-framework (mirrors test_brakes.py).

``Settings`` uses ``extra="ignore"``, so an env var that matches no declared field is SILENTLY DROPPED:
no error, no log, and every surface honestly reports the DEFAULT. An operator can set a flag, see no
effect, and be told the feature is off while believing they enabled it. These checks prove:

  (i)   each of the nine authority flags round-trips env -> Settings -> the reported state
  (ii)  a misspelled variant is DETECTED and reported as a suspected misconfiguration
  (iii) an unknown/misspelled flag never flips a real one (fail closed)
  (iv)  the reported state of every flag matches the effective runtime value

Run (from backend/):  python3 -m app.services.holding.test_flag_integrity
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))   # repo root so `core.*` resolves

from app.config import Settings                                                        # noqa: E402
from app.services.holding import self_model as sm                                      # noqa: E402
from app.services.holding.self_model import (                                          # noqa: E402
    FLAG_KEYS, OperationalSelfModel, flag_misconfigurations, declared_env_names, SUSPECTED_MISCONFIGURATION)
from app.services.holding.holding_deployment import (                                  # noqa: E402
    FEATURE_REGISTRY, feature_registry, deployment_view, _reset_hosted_route_verification)
from app.services.holding.brakes import brakes, InMemoryStopStore                       # noqa: E402

res = []
def ck(n, ok):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


# The nine authority flags this release must never report dishonestly. The four on the left were already
# declared on the production lineage; the five on the right were NOT — setting one of those against
# production was silently dropped, which is exactly the hazard under test.
PROD_DECLARED = ("KAI_HOLDING_ENABLED", "KAI_HOLDING_BRIEFING_ENABLED", "KAI_HOLDING_DELIVERY_ENABLED",
                 "KAI_HOLDING_WATCH_ENABLED")
PROD_MISSING = ("KAI_HOLDING_COMMAND_ENABLED", "KAI_VOICE_ENABLED", "KAI_CAMERA_ENABLED",
                "KAI_HOLDING_CYCLE_ENABLED", "KAI_PROACTIVE_ENABLED")
NINE = PROD_DECLARED + PROD_MISSING
BASE_ENV = {"DATABASE_URL": "postgresql://u:p@localhost:5432/x"}


def _settings_from(env: dict):
    """A REAL Settings built from a REAL process environment — the actual env->config binding, not a stub.
    _env_file=None so a developer's local .env can never change what these checks measure."""
    import os
    from unittest.mock import patch
    with patch.dict(os.environ, {**BASE_ENV, **env}, clear=True):
        return Settings(_env_file=None)


def reported(settings) -> dict:
    """The state the surfaces REPORT for each flag, from the three real reporting surfaces:
    the brakes board's flag block, the dashboard's feature registry, and the one flag reader."""
    board = brakes(settings=settings, stop_store=InMemoryStopStore({}), env={}, now="NOW")
    feats = {f["runtime_flag"]: f["runtime_enabled"] for f in feature_registry(settings) if f["runtime_flag"]}
    return {"board": board["flags"], "features": feats, "board_full": board}


# ── (a) all nine DECLARED, secure default False, honest comment each ─────────────────────────────
_CFG_SRC = (Path(__file__).resolve().parents[2] / "config.py").read_text().splitlines()
_fields = Settings.model_fields

ck("(a) all nine authority flags are DECLARED in Settings (an undeclared name is silently dropped)",
   all(f in _fields for f in NINE))
ck("(a) every one defaults to False — secure default, never enabled by omission",
   all(_fields[f].default is False for f in NINE))
ck("(a) every one is typed bool (a str default would make 'false' truthy somewhere downstream)",
   all(_fields[f].annotation is bool for f in NINE))


def _comment_above(flag: str) -> bool:
    for i, line in enumerate(_CFG_SRC):
        if line.strip().startswith(f"{flag}:"):
            j = i - 1
            while j >= 0 and not _CFG_SRC[j].strip():
                j -= 1
            return j >= 0 and _CFG_SRC[j].strip().startswith("#")
    return False

ck("(a) each of the nine carries an honest explanatory comment in config.py", all(_comment_above(f) for f in NINE))
ck("(a) the five absent from the production lineage are present here (the cherry-picks landed them)",
   all(f in _fields for f in PROD_MISSING))

# ── the reporting surfaces must COVER every flag: an omitted flag has no reported state at all ───
ck("every one of the nine is in the ONE flag vocabulary (self_model.FLAG_KEYS)", all(f in FLAG_KEYS for f in NINE))
_reg_flags = {f.runtime_flag for f in FEATURE_REGISTRY}
ck("every one of the nine has a dashboard feature-registry row (deployed vs enabled is visible per flag)",
   all(f in _reg_flags for f in NINE))
ck("KAI_CAMERA_ENABLED is reported at all — it is declared+enforced (gesture_policy) and was missing here",
   "KAI_CAMERA_ENABLED" in FLAG_KEYS and "KAI_CAMERA_ENABLED" in _reg_flags)

# ── (i) each of the nine round-trips env -> Settings -> reported state ───────────────────────────
_rt_ok, _iso_ok, _rep_ok = True, True, True
for flag in NINE:
    s_on = _settings_from({flag: "true"})
    s_off = _settings_from({})
    if not (getattr(s_on, flag) is True and getattr(s_off, flag) is False):
        _rt_ok = False; print(f"       round-trip failed for {flag}")
    if any(getattr(s_on, other) is not False for other in NINE if other != flag):
        _iso_ok = False; print(f"       {flag} leaked into another flag")
    r = reported(s_on)
    if not (r["board"][flag] is True and r["features"][flag] is True):
        _rep_ok = False; print(f"       reported state wrong for {flag}: {r['board'][flag]}/{r['features'][flag]}")

ck("(i) each of the nine round-trips from env to the effective Settings value (set -> True, unset -> False)", _rt_ok)
ck("(i) setting one flag never sets another (no cross-talk)", _iso_ok)
ck("(i) each of the nine round-trips all the way to the REPORTED state (brakes board + feature registry)", _rep_ok)

# ── (iv) reported state == effective runtime value, for every flag, in both directions ───────────
_all_on = _settings_from({f: "true" for f in NINE})
_all_off = _settings_from({})
_match = True
for s in (_all_on, _all_off):
    r = reported(s)
    for flag in r["board"]:
        if r["board"][flag] != bool(getattr(s, flag, False)):
            _match = False; print(f"       board disagrees with runtime for {flag}")
    for flag, val in r["features"].items():
        if val != bool(getattr(s, flag, False)):
            _match = False; print(f"       feature registry disagrees with runtime for {flag}")
ck("(iv) every reported flag state EQUALS the effective runtime value (all-on and all-off)", _match)

# This check previously asserted deployed is True on every row — it was pinning the hardcode, so the
# registry could have claimed a production deployment from a laptop and this suite would have passed.
# It now asserts the separation that actually matters: the flag moves ENABLEMENT and never DEPLOYMENT.
_reset_hosted_route_verification()
_SHA_ENV = {"GIT_COMMIT_SHA": "abcdef123456"}     # a real release SHA, still not a deployment on its own
_on_rows = {f["runtime_flag"]: f for f in feature_registry(_all_on, env=_SHA_ENV) if f["runtime_flag"] in NINE}
_off_rows = {f["runtime_flag"]: f for f in feature_registry(_all_off, env=_SHA_ENV) if f["runtime_flag"] in NINE}
ck("(iv) deployed != enabled for the nine: runtime_enabled tracks the flag",
   all(_on_rows[f]["runtime_enabled"] and not _off_rows[f]["runtime_enabled"] for f in NINE))
ck("(iv) turning a flag ON does not move its deployment state — enablement is not deployment",
   all(_on_rows[f]["deployment_state"] == _off_rows[f]["deployment_state"] for f in NINE))
ck("(iv) no flag setting produces a deployed claim from an unserved build",
   not any(_on_rows[f]["deployed"] or _off_rows[f]["deployed"] for f in NINE))

# ── (ii) a misspelled variant is DETECTED and reported as a suspected misconfiguration ───────────
NEAR = {"KAI_VOICE_ENABLE": "KAI_VOICE_ENABLED",     # missing suffix character
        "KAI_VOICE": "KAI_VOICE_ENABLED",            # suffix dropped entirely
        "KAI_VOCIE_ENABLED": "KAI_VOICE_ENABLED",    # transposition
        "KAI_CAMERA_ENABLE": "KAI_CAMERA_ENABLED",
        "KAI_PROACTIVE": "KAI_PROACTIVE_ENABLED",
        "KAI_HOLDING_CYCLE": "KAI_HOLDING_CYCLE_ENABLED"}
_rows = {r["env_var"]: r for r in flag_misconfigurations({k: "true" for k in NEAR})}
ck("(ii) every near-miss variant is DETECTED (typo, dropped suffix, transposition)", set(_rows) == set(NEAR))
ck("(ii) each row names the flag the operator meant", all(_rows[k]["suspected_flag"] == v for k, v in NEAR.items()))
ck("(ii) each row is explicitly a SUSPECTED_MISCONFIGURATION, not a state",
   all(r["state"] == SUSPECTED_MISCONFIGURATION for r in _rows.values()))
ck("(ii) each row says the var is silently dropped AND gives the real effective value — a reader cannot "
   "conclude it took effect",
   all("SILENTLY DROPPED" in r["detail"] and "effective value" in r["detail"]
       and r["effective_value"] is False for r in _rows.values()))
_secret = flag_misconfigurations({"KAI_VOICE_ENABLE": "s3cr3t-value-must-never-appear"})
ck("(ii) the unknown var's VALUE is never read into the report (it may be a secret) — names only",
   _secret and not any("s3cr3t" in str(v) for v in _secret[0].values()))
ck("(ii) a correctly-named var is NOT reported (no false alarm)",
   flag_misconfigurations({f: "true" for f in NINE}) == [])
ck("(ii) an unrelated env var is NOT reported (no noise)",
   flag_misconfigurations({"PATH": "/bin", "HOME": "/root", "TELEGRAM_BOT_TOKEN": "x"}) == [])
ck("(ii) real undeclared env vars this repo genuinely reads are NOT flagged (KAI_SCOPE_*, OS-lab, schedulers)",
   flag_misconfigurations({k: "1" for k in ("KAI_SCOPE_SOL_TRANSFER", "KAI_SCOPE_DIGEST", "KAI_SUPREME_ENABLED",
                                            "KAI_RESEARCH_ENABLED", "KAI_OS_LAB_ENABLED", "KAI_SOL_AUTOPILOT",
                                            "KAI_OS_LAB_VIRTME_NG_ENABLED", "KAI_DIGEST_HOUR_UTC")}) == [])
# case_sensitive=False, so a correctly-named var in ANY case genuinely BINDS. Reporting it as a
# misconfiguration would itself be a false report — so it must round-trip, not warn.
_lower = _settings_from({"kai_voice_enabled": "true"})
ck("(ii) correct name / wrong case genuinely binds (case_sensitive=False) → reported ON, and is NOT "
   "mis-reported as a misconfiguration",
   _lower.KAI_VOICE_ENABLED is True and reported(_lower)["board"]["KAI_VOICE_ENABLED"] is True
   and flag_misconfigurations({"kai_voice_enabled": "true"}) == [])

# ── (iii) an unknown / misspelled flag NEVER flips a real one (fail closed) ──────────────────────
_bad_env = {**{k: "true" for k in NEAR}, "TOTALLY_UNRELATED_THING": "true", "KAI_ENABLE_EVERYTHING": "true"}
_s_bad = _settings_from(_bad_env)
_r_bad = reported(_s_bad)
ck("(iii) with every near-miss set, all nine real flags stay False in Settings (silently dropped, never bound)",
   all(getattr(_s_bad, f) is False for f in NINE))
ck("(iii) ...and every reporting surface still reports them OFF (never a flipped or invented ON)",
   all(_r_bad["board"][f] is False for f in NINE) and all(_r_bad["features"][f] is False for f in NINE))
ck("(iii) an unknown var creates no new flag and no new brake row",
   "TOTALLY_UNRELATED_THING" not in _r_bad["board"] and "KAI_ENABLE_EVERYTHING" not in _r_bad["board"]
   and len(_r_bad["board_full"]["brakes"]) == 10)
ck("(iii) the detector is pure: it never mutates settings, and the flag it names is unchanged after the scan",
   [getattr(_s_bad, f) for f in NINE] == [False] * 9
   and (flag_misconfigurations(_bad_env) or True) and all(getattr(_s_bad, f) is False for f in NINE))
_det_src = inspect.getsource(flag_misconfigurations)
ck("(iii) the detector only READS — no setattr/os.environ write/setdefault anywhere in it",
   not any(t in _det_src for t in ("setattr", "environ[", "setdefault", "putenv")))

# ── the report is LOUD: it appears in every surface that reports flag state, plus a startup WARNING ──
_board_bad = brakes(settings=_s_bad, stop_store=InMemoryStopStore({}), env=_bad_env, now="NOW")
ck("LOUD: the brakes board carries the suspected misconfigurations beside the flags they contradict",
   len(_board_bad["flag_misconfigurations"]) == len(NEAR))
_dv = deployment_view(_s_bad, env={**_bad_env, "GIT_COMMIT_SHA": "abcdef123456"})
ck("LOUD: the dashboard deployment view (the feature-registry surface) carries them too",
   len(_dv["flag_misconfigurations"]) == len(NEAR) and _dv["features"])
_snap = OperationalSelfModel(sources={"flag_misconfigurations": lambda: flag_misconfigurations(_bad_env),
                                      "flags": lambda: {"MONEY_MODE": "MOCK"}}).snapshot()
ck("LOUD: the self-model snapshot reports them AND raises each into known_limitations (the rendered list)",
   len(_snap["flag_misconfigurations"]) == len(NEAR)
   and sum(1 for l in _snap["known_limitations"] if l.startswith("CONFIG WARNING")) == len(NEAR))
_main_src = (Path(__file__).resolve().parents[2] / "main.py").read_text()
ck("LOUD: startup logs a WARNING per suspected misconfiguration, using the ONE detector",
   "flag_misconfigurations" in _main_src and 'CONFIG WARNING' in _main_src and '_log.warning' in _main_src)
_html = (Path(__file__).resolve().parents[4] / "frontend" / "admin" / "holding.html").read_text()
ck("LOUD: the dashboard renders them above the feature registry, so DISABLED is never shown unexplained",
   "flag_misconfigurations" in _html and "CONFIG WARNING" in _html)

# ── ONE flag vocabulary: the detector invents no second list ─────────────────────────────────────
_vocab = set(FLAG_KEYS) | declared_env_names()
ck("ONE vocabulary: every flag the detector can name comes from FLAG_KEYS ∪ declared Settings fields",
   all(r["suspected_flag"] in _vocab for r in _rows.values()) and set(NINE) <= _vocab)
ck("ONE vocabulary: declared_env_names() is derived from Settings itself, not a hand-written list",
   "Settings.model_fields" in inspect.getsource(declared_env_names))
ck("the flag reader covers the whole vocabulary — _flags() returns a value for every FLAG_KEYS entry",
   set(sm._flags()) == set(FLAG_KEYS))


def run() -> bool:
    n = len(res); ok = sum(res)
    print(f"\nFLAG INTEGRITY TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
