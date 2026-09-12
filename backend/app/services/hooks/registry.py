"""Inert hook registry (Phase-1 unit #2).

Holds ``HookDefinition``s, matches an incoming ``EventEnvelope`` to the hooks
that declared its ``event_type``, and reports lifecycle — but it CANNOT fire a
hook. A hook is "armed" (eligible to fire) only when ALL of these hold:

  * a handler is bound for it (Stage 1 binds NONE), and
  * its ``status`` is ``ACTIVE``, and
  * its per-hook ``kill_switch`` env flag is truthy (off by default).

So in Stage 1 nothing is armed and ``dispatch`` fires nothing — inert by
construction, the same posture as ``capability_exchange``. Binding a handler is
a later, separately-gated stage (and is itself gated by L3: credential/network
isolation for the worker must be closed first — see the requirements ledger).

Mirrors the ``capability_exchange`` registry pattern and reuses governance's
truthy check; it adds no second policy engine or mission authority.
"""
from __future__ import annotations

from typing import Callable

from app.services.governance.actions import _is_env_truthy
from app.services.hooks.schemas import EventEnvelope, HookDefinition, HookStatus

# A handler performs a hook's action. Stage 1 binds none.
Handler = Callable[[EventEnvelope], object]


class HookError(Exception):
    pass


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, HookDefinition] = {}
        self._handlers: dict[str, Handler] = {}

    def register(self, hook: HookDefinition) -> None:
        if hook.id in self._hooks:
            raise HookError(f"hook {hook.id!r} already registered")
        self._hooks[hook.id] = hook

    def get(self, hook_id: str) -> HookDefinition:
        if hook_id not in self._hooks:
            raise KeyError(f"unknown hook {hook_id!r}")
        return self._hooks[hook_id]

    def ids(self) -> list[str]:
        return sorted(self._hooks)

    def for_event(self, event_type: str) -> list[HookDefinition]:
        """Hooks that declared this exact event_type (registration order)."""
        return [h for h in self._hooks.values() if h.event_type == event_type]

    def bind_handler(self, hook_id: str, handler: Handler) -> None:
        """Bind a hook's executor. NOT called in Stage 1 — kept so a later,
        separately-gated stage can wire a real handler. Refuses unknown hooks."""
        if hook_id not in self._hooks:
            raise KeyError(f"cannot bind handler to unknown hook {hook_id!r}")
        self._handlers[hook_id] = handler

    def is_armed(self, hook_id: str) -> bool:
        """A hook can fire only if a handler is bound AND it is ACTIVE AND its
        kill-switch env flag is on. False for every Stage-1 hook (no handlers)."""
        hook = self.get(hook_id)
        if hook_id not in self._handlers:
            return False
        if hook.status is not HookStatus.ACTIVE:
            return False
        if not hook.kill_switch:
            return False
        return _is_env_truthy(hook.kill_switch)

    def matching_armed(self, event: EventEnvelope) -> list[HookDefinition]:
        return [h for h in self.for_event(event.event_type) if self.is_armed(h.id)]

    def dispatch(self, event: EventEnvelope) -> list:
        """Fire the armed hooks matching the event and return their results. In
        Stage 1 nothing is armed, so this is always ``[]`` — a matched-but-not-
        armed hook never fires. (This is the in-process fan-out only; durable
        delivery/outbox + the isolated worker are later, separately-gated units.)
        """
        results = []
        for hook in self.for_event(event.event_type):
            if self.is_armed(hook.id):
                results.append(self._handlers[hook.id](event))
        return results

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        by_mode: dict[str, int] = {}
        for hook in self._hooks.values():
            by_status[hook.status.value] = by_status.get(hook.status.value, 0) + 1
            by_mode[hook.mode.value] = by_mode.get(hook.mode.value, 0) + 1
        return {
            "total": len(self._hooks),
            "handlers_bound": len(self._handlers),
            "armed": sum(1 for hid in self._hooks if self.is_armed(hid)),
            "by_status": by_status,
            "by_mode": by_mode,
        }
