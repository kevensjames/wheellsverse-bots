"""Minimal ACP (Agent Client Protocol) client for the KAI local connector.

Transport: newline-delimited JSON-RPC 2.0 over the harness process's stdio.
This matters for containment: the harness opens NO network listener, so there is
no port to expose, no router hole to punch, and no browser-to-localhost path. The
only way to reach the agent is to own its stdin/stdout -- which the connector does,
as its parent process.

Why the client is the policy point
----------------------------------
Upstream documents ACP clients as "trusted controllers" and the ACP server itself
requires no authentication (`authenticate` returns immediate success). Security
therefore comes entirely from process ownership plus the fact that KAI answers
`session/request_permission`. Every consequential tool call the harness wants to make
becomes an inbound JSON-RPC request to THIS process, which KAI resolves from its own
policy -- outside the harness, outside the model's prompt, and unreachable by
anything the model writes.

Upstream's approval semantics make the failure mode safe: policy `ask` with no
available answerer FAILS CLOSED. If this connector dies mid-mission, pending
approvals resolve to rejection rather than allow.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from jail import JailSpec, preflight, wrap

#: ACP wire version, from @agentclientprotocol/sdk 1.4.0 (`protocolVersion: 1`).
ACP_PROTOCOL_VERSION = 1

#: Outcomes the connector may return for an inbound permission request.
ALLOW = "allow"
REJECT = "reject"


@dataclass
class PermissionRequest:
    """An inbound `session/request_permission` the harness is blocked on."""

    session_id: str
    raw: dict[str, Any]

    @property
    def tool_name(self) -> str:
        call = self.raw.get("toolCall") or {}
        return call.get("title") or call.get("kind") or "<unknown>"


class AcpError(RuntimeError):
    pass


class AcpClient:
    """Owns one harness process and speaks ACP to it over stdio.

    `permission_handler` receives every permission request and returns ALLOW or
    REJECT. It is the ONLY place an action can be authorised; there is deliberately
    no default-allow path. A handler that raises is treated as REJECT, so a policy
    bug denies rather than permits.
    """

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str] | None = None,
        permission_handler: Callable[[PermissionRequest], str] | None = None,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
        jail: "JailSpec | None" = None,
        require_jail: bool = True,
    ) -> None:
        """`jail` confines the worker process in the kernel (see jail.py).

        `require_jail` defaults True so the ONLY way to run a worker unconfined is to
        say so explicitly at the call site. Plugin removal is configuration; the jail is
        the boundary, and a boundary that can be forgotten is not one. Containment
        probes pass require_jail=False deliberately, to measure what the harness does
        WITHOUT the jail and so prove the jail is what stops it.
        """
        if jail is None and require_jail:
            raise AcpError(
                "refusing to spawn an unconfined harness worker: pass jail=JailSpec(...), "
                "or require_jail=False for a containment probe that measures the "
                "unjailed baseline")
        if jail is not None:
            preflight(jail)          # fail closed if the boundary is not enforcing
            argv = wrap(argv, jail)
        self._jail = jail
        self._argv = argv
        self._cwd = cwd
        self._env = {**os.environ, **(env or {})}
        self._permission_handler = permission_handler or (lambda _req: REJECT)
        self._on_update = on_update or (lambda _u: None)
        self._on_stderr = on_stderr or (lambda _l: None)

        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._pending: dict[int, dict[str, Any]] = {}
        self._events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self._closed = threading.Event()

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._proc = subprocess.Popen(
            self._argv,
            cwd=self._cwd,
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def close(self) -> None:
        """Terminate the harness. Used by STOP and by normal teardown."""
        self._closed.set()
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    # --- framing -----------------------------------------------------------
    def _send(self, msg: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise AcpError("harness process is not running")
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def _read_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Stdout is reserved for protocol traffic; anything else is a
                # provider bug worth surfacing, not silently dropping.
                self._on_stderr(f"[non-JSON on stdout] {line}")
                continue
            self._dispatch(msg)
        self._closed.set()
        # Unblock anyone waiting on a reply that can no longer arrive.
        with self._lock:
            for ev in self._events.values():
                ev.set()

    def _read_stderr(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        for line in proc.stderr:
            self._on_stderr(line.rstrip())

    def _dispatch(self, msg: dict[str, Any]) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            with self._lock:
                self._pending[msg["id"]] = msg
                ev = self._events.get(msg["id"])
            if ev:
                ev.set()
            return

        method = msg.get("method")
        if method == "session/update":
            self._on_update(msg.get("params") or {})
            return

        if method == "session/request_permission":
            self._answer_permission(msg)
            return

        # Unknown inbound request: refuse rather than ignore, so the harness is
        # never left believing an unsupported capability succeeded.
        if "id" in msg:
            self._send({
                "jsonrpc": "2.0", "id": msg["id"],
                "error": {"code": -32601, "message": f"unsupported method {method!r}"},
            })

    def _answer_permission(self, msg: dict[str, Any]) -> None:
        params = msg.get("params") or {}
        req = PermissionRequest(session_id=params.get("sessionId", ""), raw=params)
        try:
            decision = self._permission_handler(req)
        except Exception as exc:  # policy bug must deny, never permit
            self._on_stderr(f"[permission handler raised, denying] {exc!r}")
            decision = REJECT

        options = params.get("options") or []
        chosen = _select_option(options, decision)
        if chosen is None:
            outcome: dict[str, Any] = {"outcome": "cancelled"}
        else:
            outcome = {"outcome": "selected", "optionId": chosen}
        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": outcome}})

    # --- requests ----------------------------------------------------------
    def request(self, method: str, params: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            ev = threading.Event()
            self._events[rid] = ev
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not ev.wait(timeout):
            raise AcpError(f"timeout waiting for {method}")
        with self._lock:
            msg = self._pending.pop(rid, None)
            self._events.pop(rid, None)
        if msg is None:
            raise AcpError(f"connection closed before {method} replied")
        if "error" in msg:
            raise AcpError(f"{method} failed: {msg['error']}")
        return msg.get("result") or {}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # --- protocol helpers --------------------------------------------------
    def initialize(self) -> dict[str, Any]:
        return self.request("initialize", {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "clientCapabilities": {},
        })

    def session_new(self, workspace: str, *, ready_deadline: float = 30.0) -> str:
        """Create a session, tolerating the harness's route-registration race.

        At the pinned commit `initialize` returns before the plugin tree has finished
        registering LLM adapter routes, so an immediate `session/new` intermittently
        fails with `no adapter registered for provider "<route>"`. Reproduced here:
        4 back-to-back launches, the first failed and the rest succeeded, and a 2s
        delay made it disappear.

        This retries the SAME route under a bounded deadline. It deliberately does NOT
        fall back to another provider: substituting whatever route happens to be ready
        would turn a timing bug into a silent LOCAL_ONLY violation, sending mission
        content to a cloud endpoint KAI attested it would never reach. If the route
        never appears the caller gets MODEL_UNAVAILABLE and the mission fails honestly.
        """
        deadline = time.monotonic() + ready_deadline
        attempt = 0
        while True:
            attempt += 1
            try:
                result = self.request("session/new", {"cwd": workspace, "mcpServers": []})
                break
            except AcpError as exc:
                if "no adapter registered" not in str(exc):
                    raise
                if time.monotonic() >= deadline:
                    raise AcpError(
                        f"MODEL_UNAVAILABLE: configured provider route never registered "
                        f"within {ready_deadline:.0f}s ({attempt} attempts). Original: {exc}"
                    ) from exc
                if self._closed.is_set():
                    raise AcpError("MODEL_UNAVAILABLE: harness exited before the route registered") from exc
                time.sleep(0.25)

        sid = result.get("sessionId")
        if not sid:
            raise AcpError(f"session/new returned no sessionId: {result}")
        return sid

    def prompt(self, session_id: str, text: str, *, timeout: float = 300.0) -> dict[str, Any]:
        return self.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            timeout=timeout,
        )

    def cancel(self, session_id: str) -> None:
        """STOP path. A notification, so it is not blocked behind an in-flight prompt."""
        self.notify("session/cancel", {"sessionId": session_id})


def _select_option(options: list[dict[str, Any]], decision: str) -> str | None:
    """Map an ALLOW/REJECT decision onto one of the offered ACP option ids.

    Options are provider-supplied, so we match on their declared `kind` rather than
    guessing ids. If the requested kind is not offered we return None (cancelled)
    instead of falling back to some other option -- picking "whatever was available"
    is exactly how an allow gets granted that policy never authorised.
    """
    wanted = ("allow_once", "allow_always") if decision == ALLOW else ("reject_once", "reject_always")
    for kind in wanted:
        for opt in options:
            if opt.get("kind") == kind:
                return opt.get("optionId")
    return None
