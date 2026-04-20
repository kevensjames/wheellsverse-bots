"""NarAI FastAPI application.
Runs standalone on NARAI_PORT (default 5051) or mounts into the monorepo's core/api.py.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from narai.api.auth import create_token, verify_password
from narai.api.routes.chat import rt as chat_rt
from narai.api.routes.memory import rag_rt, rt as memory_rt
from narai.api.routes.skills_route import rt as skills_rt
from narai.api.routes.trading import rt as trading_rt
from narai.core.db import init_db
from narai.core.resilience import breaker_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


@app.post("/api/v2/narai/auth/login")
def login(req: LoginRequest) -> dict:
    if not verify_password(req.password):
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": create_token()}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/v2/narai/health")
def health() -> dict:
    return {"status": "ok", "breakers": breaker_status()}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NARAI_PORT", "5051"))
    uvicorn.run("narai.api.main:app", host="0.0.0.0", port=port, reload=True)
