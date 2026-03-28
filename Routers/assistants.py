import Core.db as db
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/assistants", tags=["assistants"])
templates = Jinja2Templates(directory="Templates")


def _require_login(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/panel/login", status_code=302)
    return None


@router.get("", response_class=HTMLResponse)
def assistants_home(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    assistants = []

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_assistant, name
                FROM assistants
                ORDER BY id_assistant ASC;
            """)
            rows = cur.fetchall()

            for row in rows:
                assistants.append({
                    "id_assistant": row[0],
                    "name": row[1],
                })

    return templates.TemplateResponse(
        request,
        "assistants_list.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "assistants": assistants,
        },
    )


@router.get("/{id_assistant}/parameters", response_class=HTMLResponse)
def assistant_parameters(request: Request, id_assistant: int):
    redirect = _require_login(request)
    if redirect:
        return redirect

    assistant = None
    parameters = []

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_assistant, name
                FROM assistants
                WHERE id_assistant = %s;
            """, (id_assistant,))
            row = cur.fetchone()

            if not row:
                return RedirectResponse(url="/assistants", status_code=302)

            assistant = {
                "id_assistant": row[0],
                "name": row[1],
            }

            cur.execute("""
                SELECT id_parameter, parameter_name, parameter_value, is_visible
                FROM rpa_parameters
                WHERE id_assistant = %s
                ORDER BY id_parameter ASC;
            """, (id_assistant,))
            rows = cur.fetchall()

            for param in rows:
                parameters.append({
                    "id_parameter": param[0],
                    "parameter_name": param[1],
                    "parameter_value": param[2],
                    "is_visible": param[3],
                })

    return templates.TemplateResponse(
        request,
        "assistant_parameters.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "assistant": assistant,
            "parameters": parameters,
        },
    )