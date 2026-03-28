import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import PlainTextResponse
from Core.db import init_pool, init_db
from Routers.webhook import router as webhook_router
from fastapi.staticfiles import StaticFiles
from Routers.panel import router as panel_router
from Routers.notify import router as notify_router
from Routers.assistants import router as assistants_router


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

secret = os.environ.get("PANEL_SECRET_KEY")
if not secret:
    raise RuntimeError("PANEL_SECRET_KEY no configurada")

app.add_middleware(
    SessionMiddleware,
    secret_key=secret,
    same_site="lax",
    https_only=True,
    max_age=60 * 60 * 8,
)

@app.on_event("startup")
def on_startup():
    init_pool()
    init_db()
    print("✅ Startup OK")

app.include_router(webhook_router)
app.include_router(panel_router)
app.include_router(notify_router)
app.include_router(assistants_router)

@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"