import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import json

import Core.db as db

router = APIRouter(prefix="/panel", tags=["panel"])
templates = Jinja2Templates(directory="Templates")


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user"))


def _require_login(request: Request):
    if not _is_logged_in(request):
        return RedirectResponse(url="/panel/login", status_code=302)
    return None


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if _is_logged_in(request):
        return RedirectResponse(url="/panel", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "user": None})


@router.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    env_user = os.environ.get("PANEL_USER", "asesor")
    env_pass = os.environ.get("PANEL_PASS", "1234")  # cambia en prod

    if username == env_user and password == env_pass:
        request.session["user"] = username
        return RedirectResponse(url="/panel", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Credenciales inválidas", "user": None},
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/panel/login", status_code=302)


import json


@router.get("", response_class=HTMLResponse)  # /panel
def panel_home(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    rows = []
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT from_number, data, updated_at
                FROM sessions
                WHERE step = -9
                ORDER BY updated_at DESC;
            """)
            rows = cur.fetchall()

    pending = []
    for from_number, data, updated_at in rows:
        # Asegurar que data sea dict
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {}
        elif data is None:
            data = {}

        pending.append({
            "from_number": from_number,
            "reason": data.get("flow", "Atención humana"),
            "updated_at": updated_at.strftime("%Y-%m-%d %H:%M"),
        })

    return templates.TemplateResponse(
        "panel_list.html",
        {"request": request, "pending": pending, "user": request.session.get("user")},
    )
