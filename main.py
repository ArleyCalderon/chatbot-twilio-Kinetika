import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from Core.db import init_pool, init_db
from Routers.webhook import router as webhook_router
from Routers.panel import router as panel_router

app = FastAPI()

# Necesario para login con sesión por cookie
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("PANEL_SECRET_KEY", "dev-secret-change-me"),
    same_site="lax",
    https_only=False,  # ✅ en Render/producción pon True (porque vas por https)
)

@app.on_event("startup")
def on_startup():
    init_pool()
    init_db()

app.include_router(webhook_router)
app.include_router(panel_router)
