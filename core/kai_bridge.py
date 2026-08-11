"""Same-origin reverse-proxy bridge (merge Phase P3).

Forwards App A ``/admin/kai/*`` to App B (the governed KAI brain, a separate
deployment) so the admin shell can reach the governed chat/KG/twin/persona
endpoints same-origin — the unified ``wv_session`` cookie flows through and App B
re-resolves the same principal. This is the ONLY link between the two apps and it
is deliberately narrow:

  * Flag-gated by ``KAI_BRIDGE_ENABLED`` (default OFF) — fails closed (404) when off.
  * Fixed upstream only. The target host comes from config, NEVER from the
    request — no host/url parameter, no SSRF, no open-proxy behavior.
  * Path prefix allowlist + method allowlist.
  * Requires an authenticated principal with ``kai.chat``; the ultra path
    additionally requires the owner-only ``kai.ultra`` scope (closes §12).
  * Raw browser secrets (X-API-Key) are NOT forwarded; the session cookie is.
  * Preserves status code, content-type, SSE streaming, and a correlation id.

Import-light (httpx + fastapi + the pure session core) and the upstream client is
injectable, so the whole thing is testable against a mock App B with no network.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.operator_session import Principal, SCOPE_KAI_CHAT, SCOPE_KAI_ULTRA
from core.operator_session_web import SessionConfig, principal_for_request

# Hop-by-hop headers (RFC 7230 §6.1) plus ones we must not tunnel verbatim.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
})
# Request headers we deliberately DON'T forward (raw operator secrets — the
# cookie is enough for App B to re-resolve the principal).
_STRIP_REQUEST = frozenset({"x-api-key"})
_CORR_HEADER = "x-correlation-id"


@dataclass(frozen=True)
class BridgeConfig:
    enabled: bool
    upstream: str                                  # fixed base URL, e.g. https://kai.wheellsverse.com
    session: SessionConfig
    allow_prefixes: tuple = ("kai-chat", "kg", "twin", "persona", "briefing",
                             "research", "memory")
    allow_methods: frozenset = frozenset({"GET", "POST"})
    ultra_prefixes: tuple = ("kai-chat/ultra",)    # sub-paths needing kai.ultra
    timeout: float = 30.0
    # Test seam: returns an httpx.AsyncClient (default targets the real upstream).
    client_factory: Optional[Callable[[], httpx.AsyncClient]] = field(default=None)

    def make_client(self) -> httpx.AsyncClient:
        if self.client_factory is not None:
            return self.client_factory()
        return httpx.AsyncClient(base_url=self.upstream, timeout=self.timeout)


def _first_segment(path: str) -> str:
    return path.split("/", 1)[0] if path else ""


def _required_scope(path: str, request: Request, cfg: BridgeConfig) -> str:
    """kai.chat for governed routes; kai.ultra (owner-only) for the ultra path or
    an explicit ?ultra=1 — so the tier-bypass can't be reached by an operator."""
    if request.query_params.get("ultra") in ("1", "true", "yes"):
        return SCOPE_KAI_ULTRA
    for up in cfg.ultra_prefixes:
        if path == up or path.startswith(up + "/"):
            return SCOPE_KAI_ULTRA
    return SCOPE_KAI_CHAT


def _forward_request_headers(request: Request, corr_id: str) -> dict:
    out = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in _HOP_BY_HOP or lk in _STRIP_REQUEST:
            continue
        out[k] = v
    out[_CORR_HEADER] = corr_id
    return out


def _filter_response_headers(resp: httpx.Response) -> dict:
    return {k: v for k, v in resp.headers.items()
            if k.lower() not in _HOP_BY_HOP}


def install_kai_bridge(app: FastAPI, cfg: BridgeConfig) -> None:
    """Register the bridge routes. The proxy route is ALWAYS registered but
    returns 404 when disabled (fail-closed); the health route is always live."""
    router = APIRouter(tags=["kai-bridge"])

    @router.get("/admin/kai-bridge/health")
    async def bridge_health():
        # Diagnostics only — never leak the upstream URL or any secret.
        return {
            "bridge": "kai",
            "enabled": cfg.enabled,
            "upstream_configured": bool(cfg.upstream),
            "allow_prefixes": list(cfg.allow_prefixes),
            "allow_methods": sorted(cfg.allow_methods),
        }

    @router.api_route("/admin/kai/{path:path}",
                      methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(path: str, request: Request):
        # 1) Fail closed when disabled.
        if not cfg.enabled:
            return JSONResponse({"error": "kai_bridge_disabled"}, status_code=404)
        # 2) Method allowlist.
        if request.method not in cfg.allow_methods:
            return JSONResponse({"error": "method_not_allowed"}, status_code=405)
        # 3) Path prefix allowlist (blocks arbitrary upstream paths / traversal).
        if ".." in path or _first_segment(path) not in cfg.allow_prefixes:
            return JSONResponse({"error": "path_not_allowed"}, status_code=404)
        # 4) AuthN: a valid unified principal is required.
        principal: Optional[Principal] = principal_for_request(request, cfg.session)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        # 5) AuthZ: scope gate (ultra path is owner-only).
        need = _required_scope(path, request, cfg)
        if not principal.has(need):
            return JSONResponse({"error": "forbidden", "need": need}, status_code=403)

        corr_id = request.headers.get(_CORR_HEADER) or uuid.uuid4().hex
        body = await request.body()
        headers = _forward_request_headers(request, corr_id)

        client = cfg.make_client()
        upstream_req = client.build_request(
            request.method, "/" + path,
            params=dict(request.query_params), content=body, headers=headers,
        )
        try:
            upstream_resp = await client.send(upstream_req, stream=True)
        except httpx.TimeoutException:
            await client.aclose()
            return JSONResponse({"error": "upstream_timeout", "correlation_id": corr_id},
                                status_code=504)
        except httpx.HTTPError:
            await client.aclose()
            return JSONResponse({"error": "upstream_unreachable", "correlation_id": corr_id},
                                status_code=502)

        async def _stream():
            try:
                # Real upstream + stream=True leaves the body unread → true
                # end-to-end streaming (SSE) via aiter_raw. If a transport already
                # buffered the body (small/non-chunked, or a test mock), .content
                # is available and we relay it in one shot.
                try:
                    buffered = upstream_resp.content
                except httpx.ResponseNotRead:
                    buffered = None
                if buffered is not None:
                    yield buffered
                else:
                    async for chunk in upstream_resp.aiter_raw():
                        yield chunk
            finally:
                await upstream_resp.aclose()
                await client.aclose()

        out_headers = _filter_response_headers(upstream_resp)
        out_headers[_CORR_HEADER] = corr_id  # propagate for tracing
        return StreamingResponse(
            _stream(),
            status_code=upstream_resp.status_code,
            headers=out_headers,
            media_type=upstream_resp.headers.get("content-type"),
        )

    app.include_router(router)
