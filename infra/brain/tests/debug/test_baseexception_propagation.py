"""PR #7 — Issue #4: KeyboardInterrupt and SystemExit must propagate
through :func:`infra.brain.debug.ci_self_healing.ci_wrap_run_task`.

The diagnostic layer's job is to capture *errors*, not shutdown
signals. Pre-PR-#7 the catch was ``except BaseException`` which
swallowed both ``KeyboardInterrupt`` and ``SystemExit``, making CI
jobs un-killable from Ctrl-C / sys.exit() and breaking the contract
advertised by ``ci_auto_fix`` lines 256-258.

Two tests, one per signal class:

  1. ``KeyboardInterrupt`` raised inside ``client.run_task`` propagates
     OUT of ``ci_wrap_run_task`` (verified via ``pytest.raises``).
  2. ``SystemExit`` raised inside ``client.run_task`` propagates OUT
     of ``ci_wrap_run_task`` (same shape).

Plus a regression check: ordinary ``Exception`` subclasses (e.g.
``RuntimeError``) are STILL captured into the ``(result, exc)``
return tuple — narrowing the catch must not regress the original
"diagnostic layer captures all errors" semantics for the
appropriate scope.
"""
from __future__ import annotations

import asyncio

import pytest

from infra.brain.debug.ci_self_healing import ci_wrap_run_task


class _FakeClient:
    """Minimal stand-in for BrainClient. The wrapper only calls
    ``client.run_task(input)``; no other surface is touched."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def run_task(self, _input):
        raise self._exc


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if asyncio.get_event_loop().is_running() is False \
        else asyncio.run(coro)


# ── KeyboardInterrupt propagates ────────────────────────────────────────


def test_keyboard_interrupt_propagates_out_of_ci_wrap_run_task():
    """Ctrl-C must remain interruptive. If this test fails, CI jobs
    that fire ci_wrap_run_task become un-killable."""
    client = _FakeClient(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(ci_wrap_run_task(client, "x"))


# ── SystemExit propagates ──────────────────────────────────────────────


def test_system_exit_propagates_out_of_ci_wrap_run_task():
    """sys.exit() inside the brain runtime must continue to terminate
    the process, not be silently demoted into a (None, exc) tuple."""
    client = _FakeClient(SystemExit(2))
    with pytest.raises(SystemExit):
        asyncio.run(ci_wrap_run_task(client, "x"))


# ── Ordinary Exception subclasses STILL captured ───────────────────────


def test_runtime_error_still_captured_into_tuple():
    """Narrowing the catch from BaseException to Exception must NOT
    regress the "diagnostic captures all errors" contract for
    ordinary error types."""
    err = RuntimeError("kaboom")
    client = _FakeClient(err)
    result, exc = asyncio.run(ci_wrap_run_task(client, "x"))
    assert result is None
    assert exc is err


def test_value_error_still_captured_into_tuple():
    err = ValueError("bad input")
    client = _FakeClient(err)
    result, exc = asyncio.run(ci_wrap_run_task(client, "x"))
    assert result is None
    assert exc is err
