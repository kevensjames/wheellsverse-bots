import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.core.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import admin_data, auth, billing, nai, predictions


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
    return {"name": settings.APP_NAME, "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.APP_ENV}
