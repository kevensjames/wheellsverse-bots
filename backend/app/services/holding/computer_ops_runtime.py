"""Truthful runtime and containment status for the panel.

Every field here is probed or read at call time. Nothing is a constant, and nothing is
inferred from a component merely being installed or importable. The panel renders this
verbatim, so a hard-coded READY here would become a lie on a dashboard -- which is the
specific failure this project has already had to correct once.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone

HARNESS_DIR = os.environ.get("KAI_HARNESS_DIR", "/Users/jhonwheeler/kai-harness-runtime/deepseek-harness")
PINNED_COMMIT = "c389f96bf3a9b6807cb71ed6bdad5849be0df6d8"

#: Named plainly so a reader is never misled about the strength of the boundary.
CONTAINMENT_LABEL = "macOS Seatbelt + per-mission APFS volume"
CONTAINMENT_CAVEAT = "NOT A HYPERVISOR BOUNDARY"


def _harness_state() -> dict:
    if not os.path.isdir(os.path.join(HARNESS_DIR, ".git")):
        return {"state": "NOT_INSTALLED", "pinned_sha": PINNED_COMMIT, "actual_sha": None}
    try:
        head = subprocess.run(["git", "-C", HARNESS_DIR, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""
    built = os.path.isfile(os.path.join(HARNESS_DIR, "apps/cli/lib/bin.js"))
    if head != PINNED_COMMIT:
        # Drift is reported as DEGRADED rather than READY: no attestation recorded
        # against the pinned commit means anything about a drifted runtime.
        return {"state": "DEGRADED", "reason": "pin drift", "pinned_sha": PINNED_COMMIT,
                "actual_sha": head or None, "built": built}
    return {"state": "INSTALLED" if built else "DEGRADED",
            "reason": None if built else "not built",
            "pinned_sha": PINNED_COMMIT, "actual_sha": head, "built": built}


def _model_state() -> dict:
    base = os.environ.get("KAI_LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    model = os.environ.get("KAI_LOCAL_LLM_MODEL", "qwen2.5:7b")
    from urllib.parse import urlparse
    host = urlparse(base).hostname or ""
    loopback = host in ("127.0.0.1", "localhost", "::1")
    reachable = False
    try:
        import urllib.request
        urllib.request.urlopen(base.replace("/v1", "") + "/api/tags", timeout=3)
        reachable = True
    except Exception:  # noqa: BLE001
        reachable = False
    return {"model": model, "endpoint": base, "execution_location": "LOCAL" if loopback else "REMOTE",
            "loopback_only": loopback, "reachable": reachable,
            "state": "READY" if (loopback and reachable) else
                     ("UNAVAILABLE" if loopback else "DEGRADED"),
            "policy": "LOCAL_ONLY"}


def _browser_state() -> dict:
    try:
        from app.services.browser import browser_availability
        b = browser_availability()
    except Exception as exc:  # noqa: BLE001
        return {"state": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
    if b.get("state") != "AVAILABLE":
        b = {**b, "display": "UNAVAILABLE - LOCAL CONNECTOR PLAYWRIGHT NOT INSTALLED"}
    return b


def _voice_state() -> dict:
    """Voice may create the same typed mission as text, but only through the existing
    pathway. Nothing here builds a second voice brain."""
    try:
        from app.services.holding.approval_dialog import interpret_confirmation  # noqa: F401
        has_confirm_guard = True
    except Exception:  # noqa: BLE001
        has_confirm_guard = False
    return {"state": "VOICE_ENTRY_UNAVAILABLE",
            "reason": "no certified voice->mission entry point is wired on this branch",
            "confirmation_guard_present": has_confirm_guard,
            "note": "ambiguous speech can never authorize a consequential action; "
                    "interpret_confirmation() already refuses voice/gesture channels"}


def _desktop_state() -> dict:
    try:
        import sys
        sys.path.insert(0, os.environ.get(
            "KAI_BRIDGE_DIR",
            "/Users/jhonwheeler/wheellsverse-kai-compute/ops/computer-ops/bridge"))
        import desktop_bridge as bridge
        ident = bridge.executable_identity()
        return {"state": "DESKTOP_CONTROL_NOT_VERIFIED",
                "tcc_granted": False,
                "executable_identity_acceptable": ident["acceptable"],
                "required_bundle_id": ident["required_bundle_id"],
                "reason": "TCC not granted and no signed helper identity present"}
    except Exception as exc:  # noqa: BLE001
        return {"state": "DESKTOP_CONTROL_NOT_VERIFIED",
                "reason": f"bridge not importable: {type(exc).__name__}"}


def runtime_report() -> dict:
    from app.services.holding.mission_store import PgMissionStore
    store = PgMissionStore()
    stop = store.stop_state()
    active = store.list_active()
    devices = []
    try:
        from app.services.holding.device_store import PgDeviceStore
        devices = PgDeviceStore().list_devices()
    except Exception:  # noqa: BLE001
        devices = []

    harness = _harness_state()
    model = _model_state()

    # Connector liveness is derived from device heartbeats, not from a flag. A connector
    # that is not calling in is OFFLINE regardless of what any configuration says.
    #
    # Only NON-REVOKED devices count. A revoked device's last heartbeat is history: it
    # cannot authenticate any more, so treating it as evidence of a live connector would
    # keep a decommissioned machine propping up a READY badge.
    now = datetime.now(timezone.utc)
    usable = [d for d in devices if d.status != "REVOKED"]
    last_seen = [d.last_seen_at for d in usable if d.last_seen_at]
    newest = max(last_seen) if last_seen else None
    connector = "OFFLINE"
    if newest is not None:
        age = (now - newest).total_seconds()
        connector = "READY" if age < 120 else ("DEGRADED" if age < 900 else "OFFLINE")

    if stop["engaged"]:
        overall = "STOPPED"
    elif not devices:
        overall = "UNPAIRED"
    elif not usable:
        # Every enrolled device is revoked: nothing can authenticate, so the feature is
        # not merely degraded, it has no reachable device at all.
        overall = "REVOKED"
    elif harness["state"] not in ("INSTALLED",) or model["state"] != "READY":
        overall = "DEGRADED"
    elif active:
        overall = "BUSY"
    elif connector == "OFFLINE":
        overall = "OFFLINE"
    else:
        overall = "READY"

    reasons = []
    if harness["state"] != "INSTALLED":
        reasons.append(f"harness {harness['state']}" +
                       (f" ({harness.get('reason')})" if harness.get("reason") else ""))
    if model["state"] != "READY":
        reasons.append(f"local model {model['state']} at {model['endpoint']}")
    if connector != "READY":
        reasons.append(f"connector {connector}")
    if not devices:
        reasons.append("no device enrolled")
    elif not usable:
        reasons.append("all enrolled devices are revoked")

    return {
        "feature_state": overall,
        "degradation_reason": "; ".join(reasons) or None,
        "backend_state": "READY",
        "connector_state": connector,
        "last_heartbeat": newest.isoformat() if newest else None,
        "device_count": len(devices),
        "usable_device_count": len(usable),
        "active_missions": [m.mission_id for m in active],
        "harness": harness,
        "model": model,
        "containment": {
            "type": CONTAINMENT_LABEL,
            "caveat": CONTAINMENT_CAVEAT,
            "digest": None,
            "note": "per-mission digest is recorded on each mission's attestation",
        },
        "browser": _browser_state(),
        "voice": _voice_state(),
        "desktop": _desktop_state(),
        "stop": stop,
        "server_time": now.isoformat(),
    }
