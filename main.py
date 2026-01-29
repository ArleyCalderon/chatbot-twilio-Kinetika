import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from Core.db import init_pool, init_db
from Routers.webhook import router as webhook_router

# 👇 IMPORT DEL PANEL
from Routers.panel import router as panel_router

app = FastAPI()

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
    print("✅ Including routers...")

app.include_router(webhook_router)
app.include_router(panel_router)

# 👇 debug: imprime rutas registradas
print("=== ROUTES REGISTERED ===")
for r in app.routes:
    try:
        print(r.path, getattr(r, "methods", None))
    except Exception:
        pass


@app.get("/__routes")
def list_routes():
    out = []
    for r in app.routes:
        methods = list(getattr(r, "methods", []) or [])
        out.append({"path": r.path, "methods": methods})
    return out
