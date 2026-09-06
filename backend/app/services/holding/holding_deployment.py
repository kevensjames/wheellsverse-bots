"""Holding deployment TRUTH (§7-10) — the dashboard's source of truth for what is DEPLOYED vs ENABLED.

Read-only. Exposes: this app's deployed commit SHA (from the platform-injected build var), a FEATURE REGISTRY
that reports, per Holding-OS feature, whether its code is present and whether its runtime authority is ENABLED
(deployed != enabled — a high-risk capability can be DEPLOYED + DISABLED and must still show truthfully), and
a deterministic drift state from a set of SHAs. Nothing here mutates or enables anything. Pure/injectable
(settings + env passed in where it matters) so it is a plain python3 self-test.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict


def deployed_sha(env: dict | None = None) -> str:
    e = env if env is not None else os.environ
    return (e.get("RAILWAY_GIT_COMMIT_SHA") or e.get("GIT_COMMIT_SHA") or "UNKNOWN")[:12]


# ── Deployment state (§7-10). NEVER a bare boolean, and never self-asserted. ───────────────────────
# "this module imported", "its flag is True" and "its unit tests pass" are each evidence that CODE
# EXISTS. None of them is evidence that anything was RELEASED anywhere, so none of them may mint a
# deployed claim. A claim needs platform release evidence, and it is environment-specific: the same
# build is PRE_DEPLOY on a laptop, LIVE_STAGING on staging and LIVE_PROD in production.
PRE_DEPLOY = "PRE_DEPLOY"                 # code is in this build; no verified hosted release here
LIVE_STAGING = "LIVE_STAGING"
LIVE_PROD = "LIVE_PROD"
DEPLOYMENT_UNAVAILABLE = "UNAVAILABLE"    # cannot be determined -> never a deployed claim
LIVE_STATES = (LIVE_STAGING, LIVE_PROD)

_ENV_STATE = {"staging": LIVE_STAGING, "stage": LIVE_STAGING,
              "production": LIVE_PROD, "prod": LIVE_PROD}

# Hosted-route verification. The last piece of evidence a LIVE_* claim needs is that this build is
# actually SERVING its hosted routes. The single writer is the admin router, which is reachable only
# over a route mounted on the running app — so importing the package, running the self-tests or
# setting a flag cannot reach it. Process-level (not per-call-site) so every consumer of the view
# reports the SAME state; a per-caller argument is how the view ends up contradicting itself.
_HOSTED = {"verified": False, "route": ""}


def mark_hosted_route_served(route: str) -> None:
    """Called from inside a served hosted request. Observation, not assertion."""
    _HOSTED["verified"] = True
    _HOSTED["route"] = str(route)


def hosted_route_verified() -> tuple[bool, str]:
    return bool(_HOSTED["verified"]), str(_HOSTED["route"])


def _reset_hosted_route_verification() -> None:
    """Test-only. Present so the self-test can prove the default is unverified."""
    _HOSTED["verified"], _HOSTED["route"] = False, ""


def release_evidence(settings, env: dict | None = None) -> dict:
    """The ONE place a deployment claim can be minted. Fails to PRE_DEPLOY/UNAVAILABLE, never to LIVE."""
    sha = deployed_sha(env)
    app_env = str(getattr(settings, "APP_ENV", "") or "").strip().lower()
    verified, route = hosted_route_verified()
    base = {"sha": sha, "environment": app_env or "UNKNOWN", "hosted_route": route}
    if sha == "UNKNOWN":
        return {**base, "state": DEPLOYMENT_UNAVAILABLE,
                "reason": "no platform-injected release SHA (RAILWAY_GIT_COMMIT_SHA/GIT_COMMIT_SHA)"}
    if app_env not in _ENV_STATE:
        return {**base, "state": PRE_DEPLOY,
                "reason": f"APP_ENV '{app_env or '(unset)'}' is not a hosted environment"}
    if not verified:
        return {**base, "state": PRE_DEPLOY,
                "reason": "no hosted route of this build has served a request yet"}
    return {**base, "state": _ENV_STATE[app_env],
            "reason": f"release {sha} serving hosted route {route} in {app_env}"}


# ── Flag state. A flag that is not DECLARED binds to nothing, so it can never be active. ───────────
FLAG_ALWAYS_ON = "ALWAYS_ON"          # runtime_flag "" — presentation, there is no authority to enable
FLAG_ENABLED = "ENABLED"
FLAG_DISABLED = "DISABLED"
FLAG_NOT_DECLARED = "NOT_DECLARED"    # misspelled or removed: reads OFF, but must not look like a real OFF
_MISSING = object()


def flag_state(settings, flag: str) -> tuple[str, bool]:
    if not flag:
        return FLAG_ALWAYS_ON, True
    val = getattr(settings, flag, _MISSING)
    if val is _MISSING:
        return FLAG_NOT_DECLARED, False
    return (FLAG_ENABLED if bool(val) else FLAG_DISABLED), bool(val)


# Risk classes (§4): P0 safe presentation, P1 safe read-only backend, P2 dormant execution capability
# (deployed dark), P3 authority enablement (never implied by deployment).
@dataclass
class Feature:
    feature_id: str
    name: str
    risk_class: str          # P0 | P1 | P2 | P3
    certification: str
    runtime_flag: str        # settings attribute that ENABLES runtime authority ("" = always-on presentation)
    introduced_sha: str

    def record(self, settings, evidence: dict | None = None) -> dict:
        d = asdict(self)
        # runtime_enabled: for a flag-gated capability, read the live flag; for pure presentation ("") there
        # is no authority to enable. flag_state distinguishes a real OFF from a flag that binds to nothing.
        d["flag_state"], d["runtime_enabled"] = flag_state(settings, self.runtime_flag)
        # deployment_state is COPIED from release evidence, never asserted from the fact that this record
        # is being built. No evidence supplied -> UNAVAILABLE, which is not a deployed claim.
        ev = evidence or {"state": DEPLOYMENT_UNAVAILABLE, "reason": "no release evidence supplied"}
        d["deployment_state"] = ev.get("state", DEPLOYMENT_UNAVAILABLE)
        d["deployment_reason"] = ev.get("reason", "")
        d["deployed"] = d["deployment_state"] in LIVE_STATES    # derived from evidence, never hardcoded
        return d


# The Holding-OS feature truth records. introduced_sha is the commit that first shipped the feature.
FEATURE_REGISTRY = [
    Feature("improvement_watch_ui", "KAI Improvement Watch (dashboard)", "P0", "ui-contract", "", "9f3f6a8"),
    Feature("deployment_truth", "Deployment drift + feature registry", "P0", "self-test", "", "HEAD"),
    Feature("detect_only", "Continuous DETECT_ONLY detection", "P1", "DETECT_ONLY 23/23", "KAI_SELF_IMPROVEMENT_DETECT_ENABLED", "dcb2b33"),
    Feature("signal_repeated_job_failure", "Repeated-job-failure signal", "P1", "43/43 + adversarial", "KAI_SI_SIGNAL_REPEATED_JOB_FAILURE_ENABLED", "0a369e9"),
    Feature("signal_capability_health", "Capability-health signal", "P1", "43/43 + adversarial", "KAI_SI_SIGNAL_CAPABILITY_HEALTH_ENABLED", "0a369e9"),
    Feature("prepare_guardrails", "PREPARE_ALLOWED admission guardrails", "P2", "12/12", "", "2f0801d"),
    Feature("self_improvement_prepare", "Self-improvement PREPARE authority", "P2", "HOSTED_CERTIFIED_NONPROD + before/after", "KAI_SELF_IMPROVEMENT_ENABLED", "3714564"),
    Feature("a2_execution", "A2 prepare-only execution", "P2", "LIMITED_A2_HOSTED_CERTIFIED", "KAI_A2_EXECUTION_ENABLED", "16322c6"),
    Feature("holding_autonomy", "Holding autonomy engine", "P2", "certified", "HOLDING_AUTONOMY_ENABLED", "prior"),
    Feature("capability_execution", "Capability execution", "P2", "certified", "KAI_CAPABILITY_EXECUTION_ENABLED", "prior"),
    # The Holding-OS surface flags. Their code ships in this release, so their state MUST be visible here:
    # this registry is the dashboard's only per-feature "deployed vs enabled" row, and a flag it omits has
    # no reported state at all — the operator cannot tell an OFF feature from an unreported one.
    Feature("holding_api", "Holding read-only API (/admin/holding)", "P1", "read-only router", "KAI_HOLDING_ENABLED", "9913c32"),
    Feature("holding_command", "Holding Command API (§90)", "P1", "classify→existing Brain, never exec'd", "KAI_HOLDING_COMMAND_ENABLED", "c640260"),
    Feature("holding_watch", "Continuous watch loop", "P1", "read-only detection", "KAI_HOLDING_WATCH_ENABLED", "9913c32"),
    Feature("holding_cycle", "Bounded holding cycle beat (§30)", "P1", "read-only; the 3 engine brakes stay authoritative", "KAI_HOLDING_CYCLE_ENABLED", "1f2c45b"),
    Feature("holding_briefing", "Daily morning briefing", "P1", "report-only", "KAI_HOLDING_BRIEFING_ENABLED", "9913c32"),
    Feature("holding_delivery", "Briefing/alert delivery to Telegram", "P2", "opt-in; also needs a configured channel", "KAI_HOLDING_DELIVERY_ENABLED", "9913c32"),
    Feature("proactive_engine", "ProactiveBriefingEngine funnel (§11)", "P1", "adds no sender; routes via NotificationPolicy", "KAI_PROACTIVE_ENABLED", "b543521"),
    Feature("voice_command", "Voice Command Center (§7)", "P2", "same §8 resolver; can never approve a consequential action", "KAI_VOICE_ENABLED", "d22aa8c"),
    Feature("camera_gesture", "Camera + gesture (§8/§94)", "P2", "NO certified local recognizer — RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED; also needs a per-session owner enable", "KAI_CAMERA_ENABLED", "7f1103a"),
]


def feature_registry(settings, *, env: dict | None = None, evidence: dict | None = None) -> list:
    ev = evidence if evidence is not None else release_evidence(settings, env)
    return [f.record(settings, ev) for f in FEATURE_REGISTRY]


_DRIFT_STATES = ("IN_SYNC", "STAGING_BEHIND", "PRODUCTION_BEHIND", "BOTH_BEHIND", "UNKNOWN")


def compute_drift(*, source: str = "", staging: str = "", prod_a: str = "", prod_b: str = "") -> dict:
    """Deterministic drift from known SHAs. Any missing/UNKNOWN input -> UNKNOWN (never guess, §8)."""
    def known(x): return bool(x) and x != "UNKNOWN"
    if not known(source):
        return {"state": "UNKNOWN", "reason": "source head not known at runtime"}
    st_behind = known(staging) and staging[:12] != source[:12]
    pr_behind = (known(prod_a) and prod_a[:12] != source[:12]) or (known(prod_b) and prod_b[:12] != source[:12])
    if not known(staging) and not (known(prod_a) or known(prod_b)):
        return {"state": "UNKNOWN", "reason": "no deployed SHAs known"}
    if st_behind and pr_behind:
        state = "BOTH_BEHIND"
    elif st_behind:
        state = "STAGING_BEHIND"
    elif pr_behind:
        state = "PRODUCTION_BEHIND"
    else:
        state = "IN_SYNC"
    return {"state": state, "source": source[:12], "staging": (staging or "UNKNOWN")[:12],
            "prod_app_a": (prod_a or "UNKNOWN")[:12], "prod_app_b": (prod_b or "UNKNOWN")[:12]}


def _misconfigurations(env: dict | None) -> list:
    """The ONE detector (self_model.flag_misconfigurations) — env vars that near-miss a declared flag and
    are therefore silently dropped. Fail-soft to [] so a broken detector can never break the view; it
    reports only, and can never enable anything."""
    try:
        from app.services.holding.self_model import flag_misconfigurations
        return flag_misconfigurations(env)
    except Exception:      # noqa: BLE001
        return []


def deployment_view(settings, *, env: dict | None = None, peer_shas: dict | None = None,
                    source_head: str = "") -> dict:
    """Assemble the deployment-truth section. this_sha = the SHA this app is running; peer_shas carries any
    cross-app SHAs the caller resolved (e.g. App A knows App B's SHA via the bridge). Read-only."""
    this = deployed_sha(env)
    peers = dict(peer_shas or {})
    money = getattr(settings, "MONEY_MODE", "MOCK")
    ev = release_evidence(settings, env)     # resolved ONCE so every row and the header agree
    return {
        "this_app_sha": this,
        "environment": str(getattr(settings, "APP_ENV", "")),
        "money_mode": money,
        "deployment_state": ev["state"],
        "deployment_reason": ev["reason"],
        # NEVER default a peer to this app's own sha. self_model._deployment() deliberately passes
        # peer_shas={} so a staging box cannot mislabel its own sha as the PRODUCTION sha — that
        # guard was defeated here, one layer down, by this default. An unknown peer is UNKNOWN.
        "shas": {"source_head": source_head or "UNKNOWN", "app_b": peers.get("app_b", "UNKNOWN"),
                 "app_a": peers.get("app_a", "UNKNOWN"), "staging": peers.get("staging", "UNKNOWN")},
        "drift": compute_drift(source=source_head, staging=peers.get("staging", ""),
                               prod_a=peers.get("app_a", ""), prod_b=peers.get("app_b", "")),
        "features": feature_registry(settings, evidence=ev),
        # Reported beside the flag state it contradicts: a near-miss env var binds to NOTHING, so a
        # feature can read DISABLED here while the operator believes they enabled it.
        "flag_misconfigurations": _misconfigurations(env),
    }


_res = []


def ck(name, ok):
    _res.append((name, bool(ok)))


def demo() -> None:
    from types import SimpleNamespace as NS
    SHA = {"GIT_COMMIT_SHA": "abcdef123456"}
    flags = dict(MONEY_MODE="MOCK", KAI_SELF_IMPROVEMENT_DETECT_ENABLED=True,
                 KAI_SELF_IMPROVEMENT_ENABLED=False, KAI_A2_EXECUTION_ENABLED=False,
                 KAI_SI_SIGNAL_REPEATED_JOB_FAILURE_ENABLED=False, KAI_SI_SIGNAL_CAPABILITY_HEALTH_ENABLED=False,
                 HOLDING_AUTONOMY_ENABLED=True, KAI_CAPABILITY_EXECUTION_ENABLED=True)

    # ── The three things that must NEVER, on their own, produce a deployed claim ───────────────────
    _reset_hosted_route_verification()
    # (1) SOURCE PRESENCE. This module imported, the registry built, every feature's code is in the
    # build — and the environment is a real hosted one with a real release SHA. Still not deployed,
    # because no hosted route of this build has served anything.
    src = deployment_view(NS(APP_ENV="staging", **flags), env=SHA, source_head="abcdef123456")
    ck("source present + staging + real SHA, but no served route -> PRE_DEPLOY", src["deployment_state"] == PRE_DEPLOY)
    ck("...and no feature row claims deployed", all(f["deployed"] is False for f in src["features"]))
    ck("...and the reason names the missing evidence", "hosted route" in src["deployment_reason"])
    # (2) A CONFIGURED FLAG. Turning every authority flag ON changes enablement and nothing else.
    all_on = NS(APP_ENV="staging", **{k: True for k in flags if k != "MONEY_MODE"}, MONEY_MODE="MOCK")
    on = deployment_view(all_on, env=SHA, source_head="abcdef123456")
    ck("every flag ON does not deploy anything", on["deployment_state"] == PRE_DEPLOY)
    ck("...flags ON, deployed still False on every row", all(f["deployed"] is False for f in on["features"]))
    ck("...but enablement DID change (so the ON path is real, not inert)",
       {f["feature_id"] for f in on["features"] if f["runtime_enabled"]}
       > {f["feature_id"] for f in src["features"] if f["runtime_enabled"]})
    # (3) A PASSING UNIT TEST. This very self-test is running and passing; that mints nothing.
    ck("a passing self-test leaves hosted-route verification unset", hosted_route_verified()[0] is False)
    ck("record() with no evidence is UNAVAILABLE, never deployed",
       FEATURE_REGISTRY[0].record(NS(APP_ENV="staging"))["deployment_state"] == DEPLOYMENT_UNAVAILABLE)
    ck("...and UNAVAILABLE is not a deployed claim",
       FEATURE_REGISTRY[0].record(NS(APP_ENV="staging"))["deployed"] is False)

    # ── Deployment truth is ENVIRONMENT-SPECIFIC. Same build, same served route, three answers. ────
    mark_hosted_route_served("/admin/holding/deployment")
    stg = deployment_view(NS(APP_ENV="staging", **flags), env=SHA, source_head="abcdef123456",
                          peer_shas={"app_b": "abcdef123456", "staging": "abcdef123456"})
    prd = deployment_view(NS(APP_ENV="production", **flags), env=SHA, source_head="abcdef123456")
    dev = deployment_view(NS(APP_ENV="development", **flags), env=SHA, source_head="abcdef123456")
    ck("staging + served route -> LIVE_STAGING", stg["deployment_state"] == LIVE_STAGING)
    ck("production + served route -> LIVE_PROD", prd["deployment_state"] == LIVE_PROD)
    ck("development is never a LIVE state", dev["deployment_state"] == PRE_DEPLOY)
    ck("LIVE_STAGING is not LIVE_PROD (staging can never imply production)",
       stg["deployment_state"] != prd["deployment_state"])
    ck("no release SHA -> UNAVAILABLE even in production with a served route",
       deployment_view(NS(APP_ENV="production", **flags), env={})["deployment_state"] == DEPLOYMENT_UNAVAILABLE)
    ck("header state and every row state agree (one resolution, no self-contradiction)",
       {f["deployment_state"] for f in stg["features"]} == {LIVE_STAGING})

    # ── deployed != enabled still holds where it is genuinely deployed ────────────────────────────
    feats = {f["feature_id"]: f for f in stg["features"]}
    ck("this_app_sha unchanged", stg["this_app_sha"] == "abcdef123456")
    ck("A2 deployed but runtime OFF", feats["a2_execution"]["deployed"] is True
       and feats["a2_execution"]["runtime_enabled"] is False)
    ck("DETECT_ONLY on", feats["detect_only"]["runtime_enabled"] is True)
    ck("P0 presentation deployed + always on", feats["improvement_watch_ui"]["deployed"] is True
       and feats["improvement_watch_ui"]["flag_state"] == FLAG_ALWAYS_ON)
    ck("P2 self-improvement stays dark", feats["self_improvement_prepare"]["runtime_enabled"] is False)

    # ── A flag that binds to nothing can never report as active ───────────────────────────────────
    ck("flag absent from settings -> NOT_DECLARED", flag_state(NS(), "KAI_TYPOED_FLAG") == (FLAG_NOT_DECLARED, False))
    ck("NOT_DECLARED is distinguishable from a real OFF",
       flag_state(NS(KAI_A2_EXECUTION_ENABLED=False), "KAI_A2_EXECUTION_ENABLED")[0] == FLAG_DISABLED)
    ck("a removed flag is reported, never silently active",
       all(f["runtime_enabled"] is False and f["flag_state"] == FLAG_NOT_DECLARED
           for f in feature_registry(NS(APP_ENV="staging"), env=SHA) if f["runtime_flag"]))
    ck("a truthy-looking near miss on a DIFFERENT name does not enable the real flag",
       flag_state(NS(KAI_A2_EXECUTION_ENABLE=True), "KAI_A2_EXECUTION_ENABLED") == (FLAG_NOT_DECLARED, False))

    # ── NO FABRICATED PEER, and no self-comparing drift ───────────────────────────────────────────
    # Found by adversarial review of the hosted staging run, not by this suite: every existing check
    # supplied BOTH peers, so the router's real one-peer shape was never exercised and four HIGH
    # findings chained off it. These pin the shape the router actually uses.
    v_np = deployment_view(NS(APP_ENV="staging", **flags), env=SHA, source_head="")
    ck("an unsupplied peer is UNKNOWN, never this app's own sha",
       v_np["shas"]["app_b"] == "UNKNOWN" and v_np["shas"]["app_a"] == "UNKNOWN")
    ck("with no source head, drift is UNKNOWN rather than a self-comparison",
       v_np["drift"]["state"] == "UNKNOWN")
    ck("...and it says WHY", "source head" in v_np["drift"].get("reason", ""))
    # the exact tautology that was live: own sha as BOTH the source head and the production peer
    taut = deployment_view(NS(APP_ENV="staging", **flags), env=SHA, source_head="abcdef123456",
                           peer_shas={"app_b": "abcdef123456"})
    ck("REGRESSION GUARD: feeding this app's sha as source_head AND the prod peer yields IN_SYNC — "
       "which is why the router must do neither", taut["drift"]["state"] == "IN_SYNC")
    ck("a staging box must not report a production peer",
       deployment_view(NS(APP_ENV="staging", **flags), env=SHA,
                       peer_shas={"staging": "abcdef123456"})["shas"]["app_b"] == "UNKNOWN")
    _src = __import__("pathlib").Path(__file__).resolve().parent
    _rt = (_src.parents[1] / "routers" / "admin_holding.py").read_text()
    ck("the router labels its own sha by environment via _self_peer_shas, at EVERY call site",
       "def _self_peer_shas" in _rt and _rt.count("peer_shas=_self_peer_shas(") == 3
       # no CALL SITE may hand deployment_view a hardcoded peer dict; the helper's own
       # `return {"app_b": sha}` is the correct production branch and must survive this check
       and 'peer_shas={"app_b"' not in _rt)
    ck("...and no call site claims a source head the container cannot know",
       _rt.count('source_head=""') == 3 and "source_head=sha" not in _rt and "source_head=_sha" not in _rt)

    # ── drift (unchanged) ─────────────────────────────────────────────────────────────────────────
    ck("IN_SYNC", compute_drift(source="a" * 12, staging="a" * 12, prod_a="a" * 12, prod_b="a" * 12)["state"] == "IN_SYNC")
    ck("STAGING_BEHIND", compute_drift(source="a" * 12, staging="b" * 12)["state"] == "STAGING_BEHIND")
    ck("no source head -> UNKNOWN", compute_drift(source="", staging="b" * 12)["state"] == "UNKNOWN")

    _reset_hosted_route_verification()
    bad = [n for n, ok in _res if not ok]
    for n in bad:
        print("  FAIL:", n)
    print(f"DEPLOYMENT TRUTH (§7-10) TESTS: {len(_res) - len(bad)}/{len(_res)} — {'PASS' if not bad else 'FAIL'}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    demo()
