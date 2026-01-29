import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import PlainTextResponse
from Core.db import init_pool, init_db
from Routers.webhook import router as webhook_router
from fastapi.staticfiles import StaticFiles
from Routers.panel import router as panel_router

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("PANEL_SECRET_KEY", "dev-secret-change-me"),
    same_site="lax",
    https_only=True,
)

@app.on_event("startup")
def on_startup():
    init_pool()
    init_db()

    print("✅ Startup OK")

app.include_router(webhook_router)
app.include_router(panel_router)

@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"