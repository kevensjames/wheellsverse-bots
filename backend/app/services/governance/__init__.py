"""KAI governance — the safety layer between 'KAI can do everything' and
production not catching fire.

Three concerns, one module:

1. AUDIT  — every privileged action records to an append-only log so the
            operator can answer 'what did KAI do at 3am'.
2. SCOPE  — each action declares a scope name; the operator opts in by
            setting KAI_SCOPE_<NAME>=1 in .env. Off-by-default means new
            capabilities can't silently activate.
3. APPROVE — actions marked destructive=True require explicit approval
            (in v1: a per-request `approved=true` flag from the dashboard;
            in v2: a Telegram callback). Read-only actions skip this.

Build modules through @audited(scope, destructive=...) and the framework
handles the rest. Without this layer, 'give KAI total control' means
'give the next prompt-injection root access to the whole stack'.
"""
from app.services.governance.actions import (
    PendingApproval,
    ScopeDenied,
    audited,
    is_scope_enabled,
)
from app.services.governance.audit_log import (
    AUDIT_LOG_PATH,
    list_actions,
    record_action,
)

__all__ = [
    "AUDIT_LOG_PATH",
    "PendingApproval",
    "ScopeDenied",
    "audited",
    "is_scope_enabled",
    "list_actions",
    "record_action",
]
