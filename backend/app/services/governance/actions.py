"""Action decorator + scope/approval primitives.

Usage:
    from app.services.governance import audited

    @audited(scope="briefing.generate", destructive=False)
    def generate_brief(...): ...

    @audited(scope="stripe.refund", destructive=True)
    def issue_refund(amount, charge_id, *, approved: bool = False): ...

Calling a destructive action without `approved=True` raises
PendingApproval. The dashboard's UI is expected to show a confirm
button that re-submits with approved=True.

Calling any action whose scope isn't enabled via env raises ScopeDenied.
Scopes are opt-in (KAI_SCOPE_<NAME>=1) so a new module can't quietly
activate on the next deploy.

All paths — success, denied, pending, exception — record to the audit
log via record_action. The log is the single source of truth for
'what did KAI do'.
"""
from __future__ import annotations

import functools
import logging
import os
import time
from typing import Any, Callable

from app.services.governance.audit_log import record_action

logger = logging.getLogger(__name__)


class ScopeDenied(PermissionError):
    """Scope isn't enabled in env. Operator must set KAI_SCOPE_<NAME>=1."""


class PendingApproval(PermissionError):
    """Destructive action invoked without explicit approval. Caller should
    surface a confirm prompt to the operator and retry with approved=True."""


def is_scope_enabled(scope: str) -> bool:
    """Check KAI_SCOPE_<NORMALIZED>. Scope 'briefing.generate' →
    KAI_SCOPE_BRIEFING_GENERATE. Truthy = '1', 'true', 'yes' (case-insensitive).

    A scope is enabled if either:
      - the specific scope env (e.g. KAI_SCOPE_BRIEFING_GENERATE), or
      - the wildcard parent (KAI_SCOPE_BRIEFING) is set.
    Wildcards let the operator opt-in to a whole module without listing
    each action individually.
    """
    norm = scope.replace(".", "_").replace("-", "_").upper()
    if _is_env_truthy(f"KAI_SCOPE_{norm}"):
        return True
    # Wildcard parent — KAI_SCOPE_BRIEFING enables every BRIEFING.* scope
    parent = norm.split("_")[0]
    if parent and _is_env_truthy(f"KAI_SCOPE_{parent}"):
        return True
    return False


def _is_env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def audited(
    scope: str,
    *,
    destructive: bool = False,
    actor_default: str = "operator",
) -> Callable:
    """Decorator that wraps a function with audit + scope + approval.

    The wrapped function is called with whatever args/kwargs it normally
    takes. The decorator reserves two kwargs of its own and strips them
    before the inner call:
        approved: bool = False
        actor:    str  = actor_default

    Return value of the inner function is unchanged. The audit record is
    written as a side effect.
    """
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            approved = bool(kwargs.pop("approved", False))
            actor = str(kwargs.pop("actor", actor_default))

            # Scope check FIRST — if the scope isn't enabled, we don't even
            # consider the destructive-without-approval case.
            if not is_scope_enabled(scope):
                record_action(
                    action=fn.__name__, scope=scope, actor=actor,
                    destructive=destructive, approved=approved,
                    inputs={"_args": _safe_repr(args), "_kwargs": _safe_repr(kwargs)},
                    success=False,
                    error=f"scope '{scope}' not enabled (set KAI_SCOPE_{scope.replace('.','_').upper()}=1)",
                )
                raise ScopeDenied(
                    f"Scope '{scope}' is not enabled. Set "
                    f"KAI_SCOPE_{scope.replace('.', '_').upper()}=1 to authorize."
                )

            if destructive and not approved:
                record_action(
                    action=fn.__name__, scope=scope, actor=actor,
                    destructive=True, approved=False,
                    inputs={"_args": _safe_repr(args), "_kwargs": _safe_repr(kwargs)},
                    success=False,
                    error="destructive action invoked without approved=True",
                )
                raise PendingApproval(
                    f"Action '{fn.__name__}' is destructive and requires "
                    f"approved=True. Surface a confirm prompt and retry."
                )

            # A destructive action gets a fail-CLOSED intent record BEFORE the
            # side effect: if we cannot durably record what we are about to do,
            # we do not do it. (Pattern proven in swe_runtime/push.py.) Routine
            # outcome logging below stays fail-soft — a full disk must not brick
            # ordinary operation, but it must never silently hide money movement.
            if destructive:
                record_action(
                    action=fn.__name__, scope=scope, actor=actor,
                    destructive=True, approved=approved,
                    inputs={"_args": _safe_repr(args), "_kwargs": _safe_repr(kwargs)},
                    success=None, event="intent", fail_closed=True,
                )

            t0 = time.time()
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                record_action(
                    action=fn.__name__, scope=scope, actor=actor,
                    destructive=destructive, approved=approved,
                    inputs={"_args": _safe_repr(args), "_kwargs": _safe_repr(kwargs)},
                    success=False, error=str(e),
                    duration_ms=int((time.time() - t0) * 1000),
                )
                raise

            record_action(
                action=fn.__name__, scope=scope, actor=actor,
                destructive=destructive, approved=approved,
                inputs={"_args": _safe_repr(args), "_kwargs": _safe_repr(kwargs)},
                outputs=_outputs_for_log(result),
                success=True,
                duration_ms=int((time.time() - t0) * 1000),
            )
            return result

        # Stash metadata so admin endpoints / introspection tools can
        # discover which actions exist and what they require.
        wrapper.__kai_action__ = {  # type: ignore[attr-defined]
            "scope": scope,
            "destructive": destructive,
            "name": fn.__name__,
        }
        return wrapper
    return deco


def _safe_repr(v: Any) -> Any:
    """Convert non-serializable inputs to safe strings for the audit log."""
    if isinstance(v, dict):
        return {k: _safe_repr(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe_repr(x) for x in v]
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    return repr(v)[:200]


def _outputs_for_log(result: Any) -> dict[str, Any]:
    """Best-effort serialization of return value. We never want a huge or
    binary response to bloat the audit log."""
    if isinstance(result, dict):
        return result
    return {"result": _safe_repr(result)}
