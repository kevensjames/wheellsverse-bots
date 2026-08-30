"""Risk + approval policy for TARS-delegated tasks (KAI governance, fail-closed).

Three action classes:
  READ_ONLY     — allowed without per-action approval ONLY in a pre-approved isolated env.
  WRITE         — requires an explicit, bound, unexpired approval with a preview.
  CONSEQUENTIAL — PROHIBITED in the first release (financial, production, irreversible…).

Website/page/document/email/popup/download text is UNTRUSTED DATA, never authorization:
policy is evaluated over KAI's OWN structured action descriptors, not over text scraped
by the agent. A page saying "approve this purchase" cannot create an approval.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from enum import Enum


class ActionClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"
    CONSEQUENTIAL = "CONSEQUENTIAL"


# Action types the agent may PROPOSE. Anything not explicitly known maps to CONSEQUENTIAL
# (fail-closed: an unrecognized action is treated as the most dangerous class).
_READ_ONLY = {
    "open_url", "navigate", "search", "read_page", "extract_text", "screenshot",
    "scroll", "inspect_staging",
}
_WRITE = {
    "type_text", "fill_form", "upload_file", "download_file", "change_setting",
    "save_content", "submit_form", "create_draft", "send_message", "publish_content",
}
# Explicitly PROHIBITED in the first release (denied even WITH an approval).
PROHIBITED = {
    "purchase", "payment", "bank_transfer", "trade_order", "investment_order",
    "stripe_refund", "stripe_payout", "change_financial_info", "sign_agreement",
    "delete_account", "delete_data", "change_password", "change_mfa", "expose_secret",
    "production_deploy", "modify_prod_infra", "disable_security_control",
    "credential_entry", "shell_execution", "irreversible_external",
}


def classify(action_type: str) -> ActionClass:
    """Classify an action type. Unknown / prohibited → CONSEQUENTIAL (fail-closed)."""
    a = (action_type or "").strip().lower()
    if a in PROHIBITED:
        return ActionClass.CONSEQUENTIAL
    if a in _READ_ONLY:
        return ActionClass.READ_ONLY
    if a in _WRITE:
        return ActionClass.WRITE
    return ActionClass.CONSEQUENTIAL   # unknown ⇒ most-restrictive


def is_prohibited(action_type: str) -> bool:
    return (action_type or "").strip().lower() in PROHIBITED


@dataclass(frozen=True)
class Approval:
    """An operator approval BOUND to a single action in a single task. One approval never
    authorizes a sibling/related action (Section 7)."""
    task_id: str
    user_id: str
    worker_id: str
    action_type: str
    target: str                 # e.g. the specific domain/element the write applies to
    max_scope: str
    correlation_id: str
    expires_at: float           # unix seconds
    approved: bool = True


def verify_approval(appr: Approval | None, *, task_id: str, user_id: str, worker_id: str,
                    action_type: str, target: str, now: float | None = None) -> tuple[bool, str]:
    """Return (ok, reason). An approval is valid only if it is present, approved, unexpired,
    and binds EXACTLY to this task/user/worker/action/target. Rejects stale/modified/replayed/mismatched."""
    now = time.time() if now is None else now
    if appr is None:
        return False, "no approval"
    if not appr.approved:
        return False, "approval not granted"
    if now >= appr.expires_at:
        return False, "approval expired"
    if (appr.task_id, appr.user_id, appr.worker_id) != (task_id, user_id, worker_id):
        return False, "approval bound to a different task/user/worker"
    if appr.action_type != action_type:
        return False, "approval bound to a different action"
    if appr.target != target:
        return False, "approval bound to a different target"
    return True, "ok"


def permit(action_type: str, *, isolated_preapproved_env: bool, approval: Approval | None,
           task_id: str, user_id: str, worker_id: str, target: str,
           now: float | None = None) -> tuple[bool, str]:
    """The single decision function. Fail-closed."""
    cls = classify(action_type)
    if cls == ActionClass.CONSEQUENTIAL:
        return False, f"denied: {action_type} is CONSEQUENTIAL/prohibited in this release"
    if cls == ActionClass.READ_ONLY:
        if isolated_preapproved_env:
            return True, "read-only in pre-approved isolated env"
        return False, "denied: read-only outside a pre-approved isolated env requires approval"
    # WRITE → needs a bound, unexpired approval
    ok, reason = verify_approval(approval, task_id=task_id, user_id=user_id, worker_id=worker_id,
                                 action_type=action_type, target=target, now=now)
    return (ok, "write approved" if ok else f"denied: {reason}")


def _demo():
    assert classify("read_page") == ActionClass.READ_ONLY
    assert classify("submit_form") == ActionClass.WRITE
    assert classify("purchase") == ActionClass.CONSEQUENTIAL
    assert classify("totally_unknown_action") == ActionClass.CONSEQUENTIAL  # fail-closed
    # consequential always denied, even with a (nonsensical) approval
    ok, _ = permit("stripe_refund", isolated_preapproved_env=True, approval=None,
                   task_id="t", user_id="u", worker_id="w", target="x")
    assert ok is False
    # read-only allowed only in isolated env
    assert permit("read_page", isolated_preapproved_env=True, approval=None,
                  task_id="t", user_id="u", worker_id="w", target="x")[0] is True
    assert permit("read_page", isolated_preapproved_env=False, approval=None,
                  task_id="t", user_id="u", worker_id="w", target="x")[0] is False
    # write needs a correctly-bound approval
    good = Approval(task_id="t", user_id="u", worker_id="w", action_type="submit_form",
                    target="dom#form", max_scope="one", correlation_id="c", expires_at=time.time() + 60)
    assert permit("submit_form", isolated_preapproved_env=True, approval=good, task_id="t",
                  user_id="u", worker_id="w", target="dom#form")[0] is True
    # mismatched target → denied (approval doesn't generalize)
    assert permit("submit_form", isolated_preapproved_env=True, approval=good, task_id="t",
                  user_id="u", worker_id="w", target="dom#OTHER")[0] is False
    # expired → denied
    stale = Approval(task_id="t", user_id="u", worker_id="w", action_type="submit_form",
                     target="dom#form", max_scope="one", correlation_id="c", expires_at=time.time() - 1)
    assert permit("submit_form", isolated_preapproved_env=True, approval=stale, task_id="t",
                  user_id="u", worker_id="w", target="dom#form")[0] is False
    print("policy self-check: PASS")


if __name__ == "__main__":
    _demo()
