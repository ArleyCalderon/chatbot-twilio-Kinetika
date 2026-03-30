import Core.db as db
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/assistants", tags=["assistants"])
templates = Jinja2Templates(directory="Templates")


def _require_admin(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/panel/login", status_code=302)

    if request.session.get("user") != "Admin":
        return RedirectResponse(url="/panel", status_code=302)

    return None


def _is_sensitive_parameter(name: str) -> bool:
    if not name:
        return False

    name = name.strip().lower()
    sensitive_words = [
        "password",
        "contraseña",
        "contrasena",
        "clave",
        "secret",
        "token",
        "apikey",
        "api_key",
    ]
    return any(word in name for word in sensitive_words)


@router.get("", response_class=HTMLResponse)
def assistants_home(request: Request):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    assistants = []

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_assistant, name, usuario
                FROM assistants
                ORDER BY id_assistant ASC;
            """)
            rows = cur.fetchall()

            for row in rows:
                assistants.append({
                    "id_assistant": row[0],
                    "name": row[1],
                    "usuario": row[2],
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
    redirect = _require_admin(request)
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
                AND is_visible = TRUE
                ORDER BY id_parameter ASC;
            """, (id_assistant,))
            rows = cur.fetchall()

            for param in rows:
                parameter_name = param[1]
                parameter_value = param[2]

                masked_value = "***" if _is_sensitive_parameter(parameter_name) else parameter_value

                parameters.append({
                    "id_parameter": param[0],
                    "parameter_name": parameter_name,
                    "parameter_value": parameter_value,
                    "masked_value": masked_value,
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


@router.get("/{id_assistant}/parameters/{id_parameter}/edit", response_class=HTMLResponse)
def edit_parameter_form(request: Request, id_assistant: int, id_parameter: int):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    assistant = None
    parameter = None

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
                SELECT id_parameter, id_assistant, parameter_name, parameter_value, is_visible
                FROM rpa_parameters
                WHERE id_parameter = %s
                  AND id_assistant = %s;
            """, (id_parameter, id_assistant))
            row = cur.fetchone()

            if not row:
                return RedirectResponse(
                    url=f"/assistants/{id_assistant}/parameters",
                    status_code=302
                )

            parameter = {
                "id_parameter": row[0],
                "id_assistant": row[1],
                "parameter_name": row[2],
                "parameter_value": row[3],
                "is_visible": row[4],
            }

    return templates.TemplateResponse(
        request,
        "assistant_parameter_edit.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "assistant": assistant,
            "parameter": parameter,
        },
    )


@router.post("/{id_assistant}/parameters/{id_parameter}/edit")
def edit_parameter_save(
    request: Request,
    id_assistant: int,
    id_parameter: int,
    parameter_value: str = Form(...),
):
    redirect = _require_admin(request)
    if redirect:
        return redirect

    parameter_value = (parameter_value or "").strip()

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE rpa_parameters
                SET parameter_value = %s
                WHERE id_parameter = %s
                  AND id_assistant = %s;
            """, (parameter_value, id_parameter, id_assistant))
            conn.commit()

    return RedirectResponse(
        url=f"/assistants/{id_assistant}/parameters",
        status_code=302,
    )