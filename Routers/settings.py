import Core.db as db
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from Services.app_settings import clear_runtime_settings_cache

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="Templates")


def _require_admin(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/panel/login", status_code=302)

    if request.session.get("user") != "Admin":
        return RedirectResponse(url="/panel", status_code=302)

    return None


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    bot_active,
                    allow_only_existing_users,
                    bypass_schedule,
                    bot_inactive_message,
                    existing_users_only_message,
                    outside_schedule_message
                FROM app_settings
                ORDER BY id ASC
                LIMIT 1;
            """)
            row = cur.fetchone()

    settings = {
        "bot_active": row[0],
        "allow_only_existing_users": row[1],
        "bypass_schedule": row[2],
        "bot_inactive_message": row[3],
        "existing_users_only_message": row[4],
        "outside_schedule_message": row[5],
    }

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "settings": settings,
        },
    )


@router.post("")
def save_settings(
    request: Request,
    bot_active: str = Form("off"),
    allow_only_existing_users: str = Form("off"),
    bypass_schedule: str = Form("off"),
    bot_inactive_message: str = Form(""),
    existing_users_only_message: str = Form(""),
    outside_schedule_message: str = Form(""),
):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    # convertir checkboxes a boolean
    bot_active = bot_active == "on"
    allow_only_existing_users = allow_only_existing_users == "on"
    bypass_schedule = bypass_schedule == "on"

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE app_settings
                SET
                    bot_active = %s,
                    allow_only_existing_users = %s,
                    bypass_schedule = %s,
                    bot_inactive_message = %s,
                    existing_users_only_message = %s,
                    outside_schedule_message = %s
                WHERE id = 1;
            """, (
                bot_active,
                allow_only_existing_users,
                bypass_schedule,
                bot_inactive_message.strip(),
                existing_users_only_message.strip(),
                outside_schedule_message.strip()
            ))
            conn.commit()

    #  clave: limpiar caché
    clear_runtime_settings_cache()

    return RedirectResponse(url="/settings", status_code=302)