"""Hook CATALOG (Phase-1 unit #2) — a read-only inventory, not an executor.

This registry holds and looks up ``HookDefinition``s. It has NO surface that can
make a hook run: no handler binding, no arming, no dispatch, and it evaluates no
execution/enable flag. ``execution_supported`` is ``False``. Being a catalog is a
property of its *construction* — there is simply no code path to execution, so
no in-process caller (not just no HTTP caller) can activate a hook through it.

Executing a hook is the job of a FUTURE, separately-built ``HookDispatcher`` that
may be created ONLY after these are certified: L3 (credential/network test
isolation), policy, approvals, the transactional outbox, worker isolation, and
independent evidence verification. When that dispatcher is built:

  * its kill switch MUST default to BLOCKING execution (a kill switch stops
    things; its truthiness must never *enable* execution), and
  * any activation control is a separately named ``enable_flag`` — never a flag
    called "kill_switch" whose truthiness turns execution on.

Mirrors the catalog half of ``capability_exchange``; adds no policy engine,
mission authority, queue, worker, handler, or flag evaluation.
"""
from __future__ import annotations

from app.services.hooks.schemas import HookDefinition


class HookError(Exception):
    pass


class HookRegistry:
    """Catalog only. Holds and looks up HookDefinitions; never executes one."""

    #: There is no execution path in this class, by construction.
    execution_supported: bool = False

    def __init__(self) -> None:
        self._hooks: dict[str, HookDefinition] = {}

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
        """Catalog lookup: which hooks *declared* this event_type. A read-only
        query for inspection/planning — it neither arms nor fires anything."""
        return [h for h in self._hooks.values() if h.event_type == event_type]

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        by_mode: dict[str, int] = {}
        for hook in self._hooks.values():
            by_status[hook.status.value] = by_status.get(hook.status.value, 0) + 1
            by_mode[hook.mode.value] = by_mode.get(hook.mode.value, 0) + 1
        return {
            "total": len(self._hooks),
            "execution_supported": self.execution_supported,
            "by_status": by_status,
            "by_mode": by_mode,
        }
