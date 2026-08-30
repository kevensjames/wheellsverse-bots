"""Register TARS computer-use in KAI's authoritative Capability Fabric (no parallel catalog).

The displayed availability is DERIVED from runtime truth via the adapter's health():
AVAILABLE (selectable) only when a certified READY worker is online; otherwise DISCOVERED +
DISABLED so the fabric's own selectable()/auto_selectable() gates refuse it. RESTRICTED tier,
never auto-selected (automatic_activation_allowed=False) — always explicit + approval-gated.
"""
from __future__ import annotations
from app.services.tars.adapter import TarsAdapter, WorkerStatus
from app.services.tars.provenance import PINNED

CAP_ID = "computer_use"


def capability_dict(status: WorkerStatus) -> dict:
    """A capabilities.json-shaped record for the fabric. availability/activation are
    runtime-derived — never a static READY."""
    ready = (status == WorkerStatus.READY)
    return {
        "id": CAP_ID,
        "name": "Computer Use",
        "type": "EXECUTION",
        "provider": "ui_tars",
        "runtime": "LOCAL_WORKER",
        # runtime truth: AVAILABLE only with a certified READY worker; else not selectable
        "availability": "AVAILABLE" if ready else "DISCOVERED",
        "activation": "MANUAL_ONLY" if ready else "DISABLED",
        "certification": "EXPERIMENTAL",
        "security_tier": 3,                      # active control — RESTRICTED handling
        "risk_class": "RESTRICTED",
        "automatic_activation_allowed": False,   # the Brain may NEVER auto-select computer-use
        "capabilities": {
            "browser_navigation": True,
            "browser_read": True,
            "form_entry": "approval_required",
            "file_upload": "approval_required",
            "file_download": "approval_required",
            "desktop_control": "approval_required",
            "shell_execution": "prohibited_by_default",
            "credential_entry": "prohibited_by_default",
            "purchase": "prohibited",
            "financial_transaction": "prohibited",
            "production_deployment": "prohibited",
        },
        "worker_status": status.value,
        "evidence": {
            "health_check": "required",
            "worker_attestation": "required",
            "last_verified_at": "required",
            "implementation_version": "required",
            "upstream_version": PINNED.package_version,
        },
        "provenance": PINNED.as_dict(),
        "notes": ("Isolated TARS execution worker. Not local-only if screenshots/tasks reach a "
                  "remote model provider — the privacy boundary is displayed from real config."),
    }


def current_record(adapter: TarsAdapter | None = None) -> dict:
    """The record to surface in the fabric right now — status derived from the live adapter."""
    adapter = adapter or TarsAdapter()
    return capability_dict(adapter.health())


def _demo():
    # no worker → not READY → not selectable-shaped
    rec = current_record()
    assert rec["worker_status"] == "UNAVAILABLE"
    assert rec["availability"] == "DISCOVERED" and rec["activation"] == "DISABLED"
    assert rec["automatic_activation_allowed"] is False
    assert rec["security_tier"] == 3 and rec["risk_class"] == "RESTRICTED"
    assert rec["capabilities"]["purchase"] == "prohibited"
    print("capability self-check: PASS")


if __name__ == "__main__":
    _demo()
