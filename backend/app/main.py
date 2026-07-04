import logging
from contextlib import asynccontextmanager
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
from app.routers import admin_audit, admin_briefing, admin_browser, admin_ceo, admin_chat, admin_checkin, admin_data, admin_digest, admin_eq, admin_failures, admin_goals, admin_journal, admin_kg, admin_learning, admin_persona, admin_planning, admin_presets, admin_relationship, admin_research, admin_security, admin_self_correction, admin_self_heal, admin_superrouter, admin_supreme, admin_twin, api_keys_admin, auth, billing, documents, nai, predictions, sol, sol_v1, sol_v1_admin, sol_v1_charges, sol_v1_ledger, sol_v1_legal, sol_v1_notifications, sol_v1_reminders, sol_v1_reputation, sol_v1_stripe, sol_v1_subscription, sol_v1_templates, sol_v1_webhook, transcribe, tts, v1, ws_collab


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


# ── Lifespan — single context manager replacing 12 deprecated @app.on_event
# handlers (6 startup/shutdown pairs + 1 startup-only fail-soft persona seed).
# Each handler call is wrapped in its own try/except so one failure cannot
# block boot — matches the existing fail-soft pattern around _seed_persona.
# Shutdown runs scheduler stops in reverse-registration order.
@asynccontextmanager
async def lifespan(app: FastAPI):
    _log = logging.getLogger(__name__)

    # ── Startup ──────────────────────────────────────────────────────────────
    # KAI Supreme scheduler — opt-in via KAI_SUPREME_ENABLED=1. Background
    # thread runs scan cycles every N seconds while the daemon is alive,
    # replacing the standalone WheellsverseNarAISupreme.app Login Item.
    try:
        from app.services.supreme.scheduler import start as _start_supreme
        _start_supreme()
    except Exception as e:
        _log.warning("supreme scheduler start failed: %s", e)

    # KAI bounded self-healing scheduler — opt-in via
    # KAI_SELF_HEAL_SCHEDULER_ENABLED=1. Auto-runs the SAFE auto-fix allowlist
    # every N seconds (also gated by scope self_heal + KAI_SELF_HEAL_ENABLED).
    try:
        from app.services.self_heal_scheduler import start as _start_self_heal
        _start_self_heal()
    except Exception as e:
        _log.warning("self-heal scheduler start failed: %s", e)

    # Continuous Research scheduler — opt-in via KAI_RESEARCH_ENABLED=1.
    # Background thread runs one cycle per day at the configured UTC hour
    # (KAI_RESEARCH_HOUR_UTC, default 8). Fetches HN+arXiv+GH-trending,
    # scores against KAI_RESEARCH_INTERESTS, persists a digest, Telegram
    # alert on HIGH items.
    try:
        from app.services.research.scheduler import start as _start_research
        _start_research()
    except Exception as e:
        _log.warning("research scheduler start failed: %s", e)

    # Operator Digest scheduler — opt-in via KAI_DIGEST_SCHEDULER_ENABLED=1.
    # Background thread sends the cross-subsystem digest to Telegram once per
    # day at KAI_DIGEST_HOUR_UTC (default 13). No startup send (Telegram is
    # noisy); each cycle also re-checks KAI_SCOPE_DIGEST.
    try:
        from app.services.digest.scheduler import start as _start_digest
        _start_digest()
    except Exception as e:
        _log.warning("digest scheduler start failed: %s", e)

    # Sol monthly scheduler — opt-in via KAI_SOL_SCHEDULER_ENABLED=1. Daily
    # tick at KAI_SOL_SCHEDULER_HOUR_UTC (default 14) that scans active
    # circles for due actions and Telegram-reminds the operator.
    # NON-DESTRUCTIVE: money actions (collect/payout) stay operator-approved;
    # only cycle-advance auto-runs under KAI_SOL_AUTOPILOT. Each cycle
    # re-checks KAI_SCOPE_SOL.
    try:
        from app.services.sol.scheduler import start as _start_sol
        _start_sol()
    except Exception as e:
        _log.warning("sol scheduler start failed: %s", e)

    # KAI persona — seed the default warm-companion character on first boot so
    # KAI is friendly out of the box. Idempotent (no-op once any trait exists),
    # fail-soft (do NOT block boot if seed fails).
    try:
        from app.services.persona import storage as _persona
        _persona.seed_defaults()
    except Exception as e:  # pragma: no cover - defensive
        _log.warning("persona seed skipped: %s", e)

    # Daily check-in scheduler — opt-in via KAI_CHECKIN_SCHEDULER_ENABLED=1.
    # Sends one warm proactive Telegram check-in per day at
    # KAI_CHECKIN_HOUR_UTC; each cycle re-checks KAI_SCOPE_CHECKIN.
    # No startup send.
    try:
        from app.services.checkin.scheduler import start as _start_checkin
        _start_checkin()
    except Exception as e:
        _log.warning("checkin scheduler start failed: %s", e)

    # Goal-loop heartbeat scheduler — opt-in via KAI_GOALS_HEARTBEAT_ENABLED=1.
    # Once/day at KAI_GOALS_HEARTBEAT_HOUR_UTC, runs the NON-DESTRUCTIVE goal
    # advance pass; each cycle re-checks KAI_SCOPE_GOALS. No startup run.
    try:
        from app.services.goals.scheduler import start as _start_goals
        _start_goals()
    except Exception as e:
        _log.warning("goals scheduler start failed: %s", e)

    # Sol v1 reminders — opt-in via SOL_V1_REMINDERS_ENABLED=1. Once/day at
    # SOL_V1_REMINDERS_HOUR_UTC, flips overdue member payments to 'late' and
    # pushes an operator digest. NON-CUSTODIAL: labels + notifies only.
    try:
        from app.services.sol_v1.reminder_scheduler import start as _start_sol_v1_reminders
        _start_sol_v1_reminders()
    except Exception as e:
        _log.warning("sol_v1 reminders scheduler start failed: %s", e)

    # Sol v1 supervisor — opt-in via SOL_V1_SUPERVISOR_ENABLED=1. Once/day, a
    # READ-ONLY integrity + health sweep that alerts the operator on findings.
    try:
        from app.services.sol_v1.supervisor_scheduler import start as _start_sol_v1_supervisor
        _start_sol_v1_supervisor()
    except Exception as e:
        _log.warning("sol_v1 supervisor scheduler start failed: %s", e)

    yield

    # ── Shutdown (reverse-registration order) ────────────────────────────────
    try:
        from app.services.sol_v1.reminder_scheduler import stop as _stop_sol_v1_reminders
        _stop_sol_v1_reminders()
    except Exception as e:
        _log.warning("sol_v1 reminders scheduler stop failed: %s", e)

    try:
        from app.services.sol_v1.supervisor_scheduler import stop as _stop_sol_v1_supervisor
        _stop_sol_v1_supervisor()
    except Exception as e:
        _log.warning("sol_v1 supervisor scheduler stop failed: %s", e)

    try:
        from app.services.goals.scheduler import stop as _stop_goals
        _stop_goals()
    except Exception as e:
        _log.warning("goals scheduler stop failed: %s", e)

    try:
        from app.services.checkin.scheduler import stop as _stop_checkin
        _stop_checkin()
    except Exception as e:
        _log.warning("checkin scheduler stop failed: %s", e)

    try:
        from app.services.sol.scheduler import stop as _stop_sol
        _stop_sol()
    except Exception as e:
        _log.warning("sol scheduler stop failed: %s", e)

    try:
        from app.services.digest.scheduler import stop as _stop_digest
        _stop_digest()
    except Exception as e:
        _log.warning("digest scheduler stop failed: %s", e)

    try:
        from app.services.research.scheduler import stop as _stop_research
        _stop_research()
    except Exception as e:
        _log.warning("research scheduler stop failed: %s", e)

    try:
        from app.services.self_heal_scheduler import stop as _stop_self_heal
        _stop_self_heal()
    except Exception as e:
        _log.warning("self-heal scheduler stop failed: %s", e)

    try:
        from app.services.supreme.scheduler import stop as _stop_supreme
        _stop_supreme()
    except Exception as e:
        _log.warning("supreme scheduler stop failed: %s", e)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

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


# Never let the operator dashboard go stale: the /kai-ui + /nai-ui app shell
# (HTML/JS/CSS/avatar) must always revalidate, so a new build shows on a plain
# reload instead of being served from a sticky browser cache.
@app.middleware("http")
async def _no_cache_dashboard(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/kai-ui") or path.startswith("/nai-ui"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Consumer product surface — mounted in BOTH profiles. This is the ONLY
#    surface a mobile/web app user needs: chat, auth, billing, documents, voice.
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(documents.router)
app.include_router(predictions.router)
app.include_router(transcribe.router)
app.include_router(tts.router)
app.include_router(v1.router)
# Chat router is dual-mounted during the NAI→KAI brand transition. /kai is
# canonical; /nai stays alive so any in-flight client keeps working.
app.include_router(nai.router, prefix="/kai")
app.include_router(nai.router, prefix="/nai")
# Sol v1 — non-custodial ROSCA coordinator (/sol/v1). Safe on the consumer
# surface because it never touches money: it only coordinates and records
# member-to-member payments made outside the app. (The custodial Dwolla Sol
# stays operator-only below.)
app.include_router(sol_v1.router)
app.include_router(sol_v1_ledger.router)  # Sol v1 ledger: double-confirmed member payments
app.include_router(sol_v1_reminders.router)  # Sol v1 reminders: member's due/overdue view
app.include_router(sol_v1_notifications.router)  # Sol v1 notifications: member in-app inbox
app.include_router(sol_v1_templates.router)  # Sol v1 templates: reusable blueprint + instances/rounds
app.include_router(sol_v1_reputation.router)  # Sol v1 reputation: trust scores from history
app.include_router(sol_v1_legal.router)  # Sol v1 legal: disclosure + recorded consent
app.include_router(sol_v1_stripe.router)  # Sol v1 Stripe Connect rail (sandbox-locked onboarding)
app.include_router(sol_v1_subscription.router)  # Sol v1 member subscription ($9.99/mo SaaS fee)
app.include_router(sol_v1_charges.router)  # Sol v1 Stripe-rail contributions (destination charges)
app.include_router(sol_v1_webhook.router)  # Sol v1 Stripe webhooks (settle/mirror/reverse)

# ── Operator surface — control plane, agent subsystems, money ops. NEVER
#    mounted when KAI_PROFILE=consumer (App-Store Step 0): the /admin/* control
#    plane, Sol/Dwolla transfers, browser-control, real-time collab, and
#    API-key admin must be physically unreachable from a consumer app — the
#    routes are simply never registered, so a consumer replica returns 404 for
#    all of them (the #1 App Store rejection + security boundary, per the audit).
if not settings.is_consumer:
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
    app.include_router(admin_goals.router)
    app.include_router(admin_browser.router)
    app.include_router(admin_learning.router)
    app.include_router(admin_twin.router)
    # Companion soul: persona + EQ (also drive /kai chat tone via build_system_prompt).
    app.include_router(admin_persona.router)
    app.include_router(admin_eq.router)
    app.include_router(admin_relationship.router)
    app.include_router(admin_checkin.router)
    app.include_router(admin_journal.router)
    app.include_router(admin_audit.router)
    app.include_router(admin_security.router)
    app.include_router(admin_superrouter.router)
    app.include_router(admin_digest.router)
    app.include_router(admin_ceo.router)
    app.include_router(api_keys_admin.router)
    # Sol ROSCA money surface (/admin/sol) + Dwolla webhook (/sol/webhook, HMAC).
    app.include_router(sol.router)
    app.include_router(sol.webhook_router)
    # Sol v1 NON-CUSTODIAL operator dashboard (/admin/sol-v1, read-only, token-gated).
    app.include_router(sol_v1_admin.router)
    # Real-time collab (in-memory, single-node) — operator-only for now.
    app.include_router(ws_collab.router)

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

# Sol v1 member app — mobile-first SPA over /sol/v1/*. Served SAME-ORIGIN from the
# daemon so the httpOnly nai_access cookie authenticates its fetches (no CORS, no
# token in JS). Consumer surface (a member feature), so mounted unconditionally.
_SOL_APP_DIR = Path(__file__).parent / "static" / "sol_v1_app"
if _SOL_APP_DIR.exists():
    app.mount(
        "/sol-app",
        StaticFiles(directory=str(_SOL_APP_DIR), html=True),
        name="sol-v1-app",
    )

# Sol v1 operator dashboard — read-only viewer over /admin/sol-v1/* (token-gated).
# Operator surface only (never on a consumer replica); the page itself carries no
# data — every fetch requires the admin token, enforced server-side.
_SOL_ADMIN_DIR = Path(__file__).parent / "static" / "sol_v1_admin"
if not settings.is_consumer and _SOL_ADMIN_DIR.exists():
    app.mount(
        "/sol-admin",
        StaticFiles(directory=str(_SOL_ADMIN_DIR), html=True),
        name="sol-v1-admin",
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


# Operator-dashboard entry — NOT registered in a consumer backend (Step 0), so a
# consumer replica has no /admin surface at all.
if not settings.is_consumer:
    @app.get("/admin", include_in_schema=False)
    def _redirect_admin():
        # kai.wheellsverse.com/admin → the same page as /kai-ui/admin.html.
        # Auth is client-side via X-Admin-Token.
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
