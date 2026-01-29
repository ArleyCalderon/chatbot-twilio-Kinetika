import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/panel", tags=["panel"])
templates = Jinja2Templates(directory="templates")


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


@router.get("", response_class=HTMLResponse)  # /panel
def panel_home(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    pending = [
        {"from_number": "whatsapp:+573001112233", "reason": "Confirmar cita", "updated_at": "2026-01-29 10:05"},
        {"from_number": "whatsapp:+573004445566", "reason": "Reprogramar cita", "updated_at": "2026-01-29 09:40"},
    ]

    return templates.TemplateResponse(
        "panel_list.html",
        {"request": request, "pending": pending, "user": request.session.get("user")},
    )
