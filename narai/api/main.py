"""NarAI FastAPI application.
Runs standalone on NARAI_PORT (default 5051) or mounts into the monorepo's core/api.py.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from narai.api.auth import create_token
from narai.api.routes.chat import rt as chat_rt
from narai.api.routes.memory import rag_rt, rt as memory_rt
from narai.api.routes.skills_route import rt as skills_rt
from narai.api.routes.trading import rt as trading_rt
from narai.api.routes.content import rt as content_rt
from narai.api.routes.sales import rt as sales_rt
from narai.api.routes.research import rt as research_rt
from narai.api.routes.ops import rt as ops_rt
from narai.api.routes.creative import rt as creative_rt
from narai.api.routes.kdp import rt as kdp_rt
from narai.api.routes.voice import rt as voice_rt
from narai.api.routes.shopify_oauth import router as shopify_oauth_rt
from narai.api.routes.shopify_webhooks import router as shopify_webhooks_rt
from narai.api.routes.shopify_billing import api_router as shopify_billing_api_rt, webhook_router as shopify_billing_webhook_rt
from narai.api.routes.shopify_admin import router as shopify_admin_rt
from narai.api.routes.telegram import rt as telegram_rt
from narai.core.db import init_db
from infra.brain.resilience import breaker_status
from narai.integrations.telegram import setup_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    base_url = os.getenv("APP_BASE_URL", "")
    if base_url:
        try:
            await setup_webhook(base_url)
        except Exception as e:
            import logging
            logging.getLogger("narai.main").warning(f"Telegram webhook setup failed (non-fatal): {e}")
    yield


app = FastAPI(
    title="NarAI",
    version="0.1.0",
    description="NarAI — J.K. Blaze's production AI assistant",
    lifespan=lifespan,
    docs_url="/docs" if os.getenv("NARAI_ENV", "dev") == "dev" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("NARAI_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(chat_rt, prefix="/api/v2/narai")
app.include_router(memory_rt, prefix="/api/v2/narai")
app.include_router(rag_rt, prefix="/api/v2/narai")
app.include_router(skills_rt, prefix="/api/v2/narai")
app.include_router(trading_rt, prefix="/api/v2/narai")
app.include_router(content_rt, prefix="/api/v2/narai")
app.include_router(sales_rt, prefix="/api/v2/narai")
app.include_router(research_rt, prefix="/api/v2/narai")
app.include_router(ops_rt, prefix="/api/v2/narai")
app.include_router(creative_rt, prefix="/api/v2/narai")
app.include_router(kdp_rt, prefix="/api/v2/narai")
app.include_router(voice_rt, prefix="/api/v2/narai")
app.include_router(telegram_rt, prefix="/api/v2/narai")

# Multi-tenant Shopify (no prefix — Shopify hits /shopify/install and /shopify/callback directly)
app.include_router(shopify_oauth_rt)
app.include_router(shopify_webhooks_rt)
app.include_router(shopify_billing_webhook_rt)
app.include_router(shopify_billing_api_rt, prefix="/api/narai")
app.include_router(shopify_admin_rt)


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/v2/narai/auth/login")
def login(req: LoginRequest) -> dict:
    """Email/password login. Delegates verification to Supabase auth, then
    mints a NarAI-signed JWT carrying the user's UUID as ``sub``."""
    from narai.api.auth import sign_in_with_supabase
    user_id = sign_in_with_supabase(req.email, req.password)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"token": create_token(user_id)}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/v2/narai/health")
def health() -> dict:
    return {"status": "ok", "breakers": breaker_status()}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NARAI_PORT", "5051"))
    uvicorn.run("narai.api.main:app", host="0.0.0.0", port=port, reload=True)
