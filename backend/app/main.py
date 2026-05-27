from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.core.rate_limit import limiter
from app.routers import admin_data, auth, billing, nai, predictions


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

app.include_router(auth.router)
app.include_router(predictions.router)
app.include_router(billing.router)
app.include_router(admin_data.router)
app.include_router(nai.router)

_NAI_STATIC = Path(__file__).parent / "static" / "nai"
if _NAI_STATIC.exists():
    app.mount(
        "/nai-ui",
        StaticFiles(directory=str(_NAI_STATIC), html=True),
        name="nai-ui",
    )


@app.get("/")
def root():
    return {"name": settings.APP_NAME, "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.APP_ENV}
