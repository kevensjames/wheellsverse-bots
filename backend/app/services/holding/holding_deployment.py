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

    def record(self, settings) -> dict:
        d = asdict(self)
        # runtime_enabled: for a flag-gated capability, read the live flag; for pure presentation ("") it is
        # enabled wherever deployed. This is the deployed!=enabled truth the operator must always see.
        d["runtime_enabled"] = (True if not self.runtime_flag
                                else bool(getattr(settings, self.runtime_flag, False)))
        d["deployed"] = True    # if this code is running, the feature's code is deployed here
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
]


def feature_registry(settings) -> list:
    return [f.record(settings) for f in FEATURE_REGISTRY]


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


def deployment_view(settings, *, env: dict | None = None, peer_shas: dict | None = None,
                    source_head: str = "") -> dict:
    """Assemble the deployment-truth section. this_sha = the SHA this app is running; peer_shas carries any
    cross-app SHAs the caller resolved (e.g. App A knows App B's SHA via the bridge). Read-only."""
    this = deployed_sha(env)
    peers = dict(peer_shas or {})
    money = getattr(settings, "MONEY_MODE", "MOCK")
    return {
        "this_app_sha": this,
        "environment": str(getattr(settings, "APP_ENV", "")),
        "money_mode": money,
        "shas": {"source_head": source_head or "UNKNOWN", "app_b": peers.get("app_b", this),
                 "app_a": peers.get("app_a", "UNKNOWN"), "staging": peers.get("staging", "UNKNOWN")},
        "drift": compute_drift(source=source_head, staging=peers.get("staging", ""),
                               prod_a=peers.get("app_a", ""), prod_b=peers.get("app_b", "")),
        "features": feature_registry(settings),
    }


def demo() -> None:
    from types import SimpleNamespace
    s = SimpleNamespace(APP_ENV="staging", MONEY_MODE="MOCK", KAI_SELF_IMPROVEMENT_DETECT_ENABLED=True,
                        KAI_SELF_IMPROVEMENT_ENABLED=False, KAI_A2_EXECUTION_ENABLED=False,
                        KAI_SI_SIGNAL_REPEATED_JOB_FAILURE_ENABLED=False, KAI_SI_SIGNAL_CAPABILITY_HEALTH_ENABLED=False,
                        HOLDING_AUTONOMY_ENABLED=True, KAI_CAPABILITY_EXECUTION_ENABLED=True)
    v = deployment_view(s, env={"GIT_COMMIT_SHA": "abcdef123456"}, source_head="abcdef123456",
                        peer_shas={"app_b": "abcdef123456", "staging": "abcdef123456"})
    assert v["this_app_sha"] == "abcdef123456"
    feats = {f["feature_id"]: f for f in v["features"]}
    # deployed != enabled: A2 code deployed but runtime OFF; DETECT_ONLY on
    assert feats["a2_execution"]["deployed"] is True and feats["a2_execution"]["runtime_enabled"] is False
    assert feats["detect_only"]["runtime_enabled"] is True
    assert feats["improvement_watch_ui"]["deployed"] is True and feats["improvement_watch_ui"]["runtime_enabled"] is True  # P0 presentation
    assert feats["self_improvement_prepare"]["runtime_enabled"] is False  # P2 dark
    # drift: source == app_b, staging known and equal -> IN_SYNC; prod unknown is not counted as behind here
    assert compute_drift(source="a" * 12, staging="a" * 12, prod_a="a" * 12, prod_b="a" * 12)["state"] == "IN_SYNC"
    assert compute_drift(source="a" * 12, staging="b" * 12)["state"] == "STAGING_BEHIND"
    assert compute_drift(source="", staging="b" * 12)["state"] == "UNKNOWN"
    print("holding_deployment.demo OK — feature registry (deployed!=enabled) + drift states")


if __name__ == "__main__":
    demo()
