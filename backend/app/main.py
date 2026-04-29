from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin_data, auth, billing, predictions


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    debug=settings.DEBUG,
)

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


@app.get("/")
def root():
    return {"name": settings.APP_NAME, "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.APP_ENV}
