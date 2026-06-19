import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.core.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import admin_audit, admin_briefing, admin_browser, admin_ceo, admin_chat, admin_checkin, admin_data, admin_digest, admin_eq, admin_failures, admin_journal, admin_kg, admin_learning, admin_persona, admin_planning, admin_presets, admin_relationship, admin_research, admin_self_correction, admin_self_heal, admin_security, admin_superrouter, admin_supreme, admin_twin, api_keys_admin, auth, billing, documents, nai, predictions, sol, transcribe, tts, v1


# Uvicorn configures its own loggers but doesn't attach a handler to the root
# logger, so WARNINGS from app.* loggers silently disappear into the void.
# Add a single StreamHandler to root so things like
# `logger.warning("Supabase create_user failed: ...")` actually surface in
# nai.stderr.log under launchd.
_root = logging.getLogger()
if not any(isinstance(h, logging.StreamHandler) for h in _root.handlers):
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    _root.addHandler(_h)
_root.setLevel(logging.INFO)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    debug=settings.DEBUG,
)


# KAI Supreme scheduler — opt-in via KAI_SUPREME_ENABLED=1. Background
# thread runs scan cycles every N seconds while the daemon is alive,
# replacing the standalone WheellsverseNarAISupreme.app Login Item.
@app.on_event("startup")
def _start_supreme():
    from app.services.supreme.scheduler import start as _start
    _start()


@app.on_event("shutdown")
def _stop_supreme():
    from app.services.supreme.scheduler import stop as _stop
    _stop()


# KAI bounded self-healing scheduler — opt-in via
# KAI_SELF_HEAL_SCHEDULER_ENABLED=1. Auto-runs the SAFE auto-fix allowlist
# every N seconds (also gated by scope self_heal + KAI_SELF_HEAL_ENABLED).
@app.on_event("startup")
def _start_self_heal():
    from app.services.self_heal_scheduler import start as _start
    _start()


@app.on_event("shutdown")
def _stop_self_heal():
    from app.services.self_heal_scheduler import stop as _stop
    _stop()


# Continuous Research scheduler — opt-in via KAI_RESEARCH_ENABLED=1.
# Background thread runs one cycle per day at the configured UTC hour
# (KAI_RESEARCH_HOUR_UTC, default 8). Fetches HN+arXiv+GH-trending,
# scores against KAI_RESEARCH_INTERESTS, persists a digest, Telegram
# alert on HIGH items.
@app.on_event("startup")
def _start_research():
    from app.services.research.scheduler import start as _start
    _start()


@app.on_event("shutdown")
def _stop_research():
    from app.services.research.scheduler import stop as _stop
    _stop()


# Operator Digest scheduler — opt-in via KAI_DIGEST_SCHEDULER_ENABLED=1.
# Background thread sends the cross-subsystem digest to Telegram once per day
# at KAI_DIGEST_HOUR_UTC (default 13). No startup send (Telegram is noisy);
# each cycle also re-checks KAI_SCOPE_DIGEST.
@app.on_event("startup")
def _start_digest_scheduler():
    from app.services.digest.scheduler import start as _start
    _start()


@app.on_event("shutdown")
def _stop_digest_scheduler():
    from app.services.digest.scheduler import stop as _stop
    _stop()


# CEO heartbeat scheduler — opt-in via KAI_CEO_HEARTBEAT_ENABLED=1. Stays idle
# until a router_factory is wired (see ceo/SETUP.md); the manual
# POST /admin/ceo/run works now. Each tick re-checks KAI_SCOPE_CEO + kill switch.
@app.on_event("startup")
def _start_ceo_scheduler():
    from app.services.ceo.heartbeat import start as _start
    _start()


# Sol monthly scheduler — opt-in via KAI_SOL_SCHEDULER_ENABLED=1. Daily tick at
# KAI_SOL_SCHEDULER_HOUR_UTC (default 14) that scans active circles for due
# actions and Telegram-reminds the operator. NON-DESTRUCTIVE: money actions
# (collect/payout) stay operator-approved; only cycle-advance auto-runs under
# KAI_SOL_AUTOPILOT. Each cycle re-checks KAI_SCOPE_SOL.
@app.on_event("startup")
def _start_sol_scheduler():
    from app.services.sol.scheduler import start as _start
    _start()


@app.on_event("shutdown")
def _stop_sol_scheduler():
    from app.services.sol.scheduler import stop as _stop
    _stop()


# KAI persona — seed the default warm-companion character on first boot so KAI
# is friendly out of the box. Idempotent (no-op once any trait exists), fail-soft.
@app.on_event("startup")
def _seed_persona():
    try:
        from app.services.persona import storage as _persona
        _persona.seed_defaults()
    except Exception as e:  # pragma: no cover - defensive
        logging.getLogger(__name__).warning("persona seed skipped: %s", e)


# Daily check-in scheduler — opt-in via KAI_CHECKIN_SCHEDULER_ENABLED=1. Sends
# one warm proactive Telegram check-in per day at KAI_CHECKIN_HOUR_UTC; each
# cycle re-checks KAI_SCOPE_CHECKIN. No startup send.
@app.on_event("startup")
def _start_checkin():
    try:
        from app.services.checkin.scheduler import start as _start
        _start()
    except Exception as e:  # pragma: no cover - a companion import must never block boot
        logging.getLogger(__name__).warning("checkin scheduler start skipped: %s", e)


@app.on_event("shutdown")
def _stop_checkin():
    from app.services.checkin.scheduler import stop as _stop
    _stop()

# Wire the shared limiter so route decorators (@limiter.limit("...")) take effect.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers — added last so it's the outermost wrapper, which means it
# runs *last on response* and stamps headers on every response including
# rate-limit 429s, CORS preflights, and SSE streams. HSTS is only set when
# APP_ENV indicates production (production=HTTPS=safe to set HSTS).
app.add_middleware(SecurityHeadersMiddleware, app_env=settings.APP_ENV)

app.include_router(auth.router)
app.include_router(predictions.router)
app.include_router(billing.router)
app.include_router(admin_data.router)
app.include_router(admin_chat.router)
app.include_router(admin_supreme.router)
app.include_router(admin_briefing.router)
app.include_router(admin_presets.router)
app.include_router(admin_kg.router)
app.include_router(admin_failures.router)
app.include_router(admin_research.router)
app.include_router(admin_self_correction.router)
app.include_router(admin_self_heal.router)
app.include_router(admin_planning.router)
app.include_router(admin_browser.router)
app.include_router(admin_learning.router)
app.include_router(admin_twin.router)
# KAI companion soul: own persona (warm character, edit to reshape KAI's voice)
# + emotional intelligence (mood read → tone adaptation, auto on every message).
app.include_router(admin_persona.router)
app.include_router(admin_eq.router)
# Companion relationship + proactive check-in + journal.
app.include_router(admin_relationship.router)
app.include_router(admin_checkin.router)
app.include_router(admin_journal.router)
# Super-router: decompose a complex ask into a proposed plan (P3 "smarter" layer).
app.include_router(admin_superrouter.router)
app.include_router(admin_audit.router)
app.include_router(admin_security.router)
app.include_router(admin_digest.router)
app.include_router(admin_ceo.router)
app.include_router(api_keys_admin.router)
app.include_router(documents.router)
# Sol ROSCA — operator admin surface (/admin/sol, token-gated) + the Dwolla
# webhook (/sol/webhook, HMAC-verified, no auth). Money endpoints are gated by
# KAI_SCOPE_SOL_TRANSFER + approved=True + the DwollaClient sandbox-lock.
app.include_router(sol.router)
app.include_router(sol.webhook_router)
app.include_router(transcribe.router)
app.include_router(tts.router)
app.include_router(v1.router)
# Chat router is dual-mounted during the NAI→KAI brand transition. /kai is
# canonical; /nai stays alive so any in-flight client (cached JS, open SSE
# stream, third-party bookmark) keeps working until the legacy window closes.
app.include_router(nai.router, prefix="/kai")
app.include_router(nai.router, prefix="/nai")

_STATIC_DIR = Path(__file__).parent / "static" / "nai"
if _STATIC_DIR.exists():
    # Same files served under both paths during the rename transition.
    app.mount(
        "/kai-ui",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="kai-ui",
    )
    app.mount(
        "/nai-ui",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="nai-ui",
    )


@app.get("/")
def root():
    # Bare domain lands on the chat app. Visitors sharing the URL get a real
    # landing page, not a version JSON blob.
    return RedirectResponse(url="/kai-ui/", status_code=307)


# Convenience routes — common URLs visitors type without the /kai-ui/ prefix.
# 307 (Temporary Redirect) so client doesn't cache (we may move these around).
@app.get("/login", include_in_schema=False)
def _redirect_login():
    return RedirectResponse(url="/kai-ui/login.html", status_code=307)


@app.get("/signup", include_in_schema=False)
def _redirect_signup():
    return RedirectResponse(url="/kai-ui/signup.html", status_code=307)


@app.get("/pricing", include_in_schema=False)
def _redirect_pricing():
    return RedirectResponse(url="/kai-ui/pricing.html", status_code=307)


@app.get("/admin", include_in_schema=False)
def _redirect_admin():
    # Operator dashboard at a clean URL — kai.wheellsverse.com/admin
    # serves the same page as /kai-ui/admin.html. Auth happens client-side
    # via X-Admin-Token; this redirect itself is intentionally open so a
    # 404 doesn't leak "no admin here" to fingerprinters.
    return RedirectResponse(url="/kai-ui/admin.html", status_code=307)


def _dashboard_build() -> int:
    """Newest mtime among the dashboard's own assets (admin.js + admin.css) —
    the canonical 'dashboard build' stamp.

    scripts/stamp_static_assets.py bakes these same mtimes into the page's
    ?v=ts-<mtime> cache-busters. The client takes the max of the stamps IT
    loaded and polls this endpoint; if the server's is newer, it offers a
    one-click reload (see initVersionWatcher in admin.js). Taking the max over
    JS *and* CSS means a CSS-only deploy also triggers the banner. Fail-soft
    to 0 so /version never breaks if an asset is missing.
    """
    try:
        from pathlib import Path
        base = Path(__file__).resolve().parent / "static" / "nai"
        mtimes = [int((base / name).stat().st_mtime)
                  for name in ("admin.js", "admin.css") if (base / name).exists()]
        return max(mtimes) if mtimes else 0
    except Exception:
        return 0


@app.get("/version", include_in_schema=False)
def version():
    # Old behaviour of GET / preserved here in case anything (monitors,
    # uptime checks) was scraping the JSON.
    return {"name": settings.APP_NAME, "version": "0.1.0", "build": _dashboard_build()}


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.APP_ENV}


# Catch-all for unmatched GETs: if the client looks like a browser (Accept
# header asks for HTML), send them to the chat app instead of a JSON 404.
# Curl/Stripe/internal services still see 404 because they don't ask for
# text/html. Mounted LAST so it doesn't shadow any defined route.
from fastapi import Request  # noqa: E402  (intentional late import)


_API_PREFIXES = ("/kai/", "/nai/", "/auth/", "/billing/", "/predictions/",
                 "/admin/", "/account/", "/v1/")
_ASSET_EXTS = (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
               ".ico", ".webp", ".woff", ".woff2", ".ttf", ".map", ".html")


@app.middleware("http")
async def kai_ui_cache_control(request: Request, call_next):
    """Static assets under /kai-ui/ default to short cache + must-revalidate so
    a fresh deploy reaches browsers within minutes instead of hours. Without
    this, Cloudflare's default 4h browser TTL meant a UI ship took half a day
    to propagate to phones that had already loaded the old version."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/kai-ui/", "/nai-ui/")):
        if path.endswith(".html") or path.rstrip("/").endswith(("/kai-ui", "/nai-ui")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif path.endswith((".js", ".css")):
            # 60s + revalidate-via-etag. Browsers will fast-revalidate (304) most of the time.
            response.headers["Cache-Control"] = "public, max-age=60, must-revalidate"
    return response


@app.middleware("http")
async def html_404_to_kai_ui(request: Request, call_next):
    """If a browser hits a 404 on what looks like a navigation route,
    bounce them to /kai-ui/. Asset 404s (.css, .js, etc.) and API 404s stay
    as 404 so real missing-file bugs aren't silently masked."""
    response = await call_next(request)
    if response.status_code != 404 or request.method != "GET":
        return response
    if "text/html" not in (request.headers.get("accept") or ""):
        return response
    path = request.url.path
    if path.startswith(_API_PREFIXES) or path.endswith(_ASSET_EXTS):
        return response
    return RedirectResponse(url="/kai-ui/", status_code=307)
