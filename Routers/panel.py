import os
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from Services.chat_store import delete_session, save_session  # según lo que uses
from urllib.parse import quote
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import os
from twilio.rest import Client
from Core.db import pool
from Services.chat_store import save_message, delete_messages, delete_session
import json
from fastapi.responses import JSONResponse
import Core.db as db
from urllib.parse import unquote
from zoneinfo import ZoneInfo
local_tz = ZoneInfo("America/Bogota")




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

        nombre = _display_name(data)
        cedula = _display_cedula(data)

        pending.append({
            "from_number": from_number,
            "nombre": nombre,
            "cedula": cedula,
            "reason": data.get("flow", "Atención humana"),
            "updated_at": updated_at.strftime("%Y-%m-%d %H:%M"),
            "chat_url": f"/panel/chat?from={quote(from_number, safe='')}",
        })

        

    return templates.TemplateResponse(
        "panel_list.html",
        {"request": request, "pending": pending, "user": request.session.get("user")},
    )


def _display_name(data: dict) -> str:
    parts = [
        data.get("primer_nombre"),
        data.get("segundo_nombre"),
        data.get("primer_apellido"),
        data.get("segundo_apellido"),
    ]
    parts = [p for p in parts if p]
    return " ".join(parts) if parts else "(sin nombre)"

def _display_cedula(data: dict) -> str:
    return data.get("cedula") or data.get("cedula_cancelacion") or "(sin cédula)"
def _display_tipo_servicio(data: dict) -> str:
    return data.get("tipo_servicio")
def _display_tipo_cita(data: dict) -> str:
    return data.get("tipo_cita") 


@router.post("/chat/{from_number}/close")
def close_chat(request: Request, from_number: str):
    redirect = _require_login(request)
    if redirect:
        return redirect

    # 1) borrar historial
    delete_messages(from_number)

    # 2) sacar del handoff: puedes borrar sesión o devolverla a menú
    # Opción A: volver a menú
    #save_session(from_number, step=-1, data={})
    # Opción B: borrar sesión
    delete_session(from_number)

    return RedirectResponse(url="/panel", status_code=302)

@router.get("/chat", response_class=HTMLResponse)
def panel_chat(request: Request, from_number: str = Query(..., alias="from")):
    redirect = _require_login(request)
    if redirect:
        return redirect

    # traer sesión
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT data
                FROM sessions
                WHERE from_number = %s
            """, (from_number,))
            row = cur.fetchone()

    data = row[0] if row else {}
    if isinstance(data, str):
        data = json.loads(data)

    nombre = _display_name(data)
    cedula = _display_cedula(data)
    tipo_servicio = _display_tipo_servicio(data)
    tipo_cita = _display_tipo_cita(data)

    # traer mensajes si los usas
    messages = []
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT direction, body, created_at
                FROM messages
                WHERE from_number = %s
                ORDER BY created_at ASC;
            """, (from_number,))
            for d, b, c in cur.fetchall():
                messages.append({
                    "direction": d,
                    "body": b,
                    "created_at": c.strftime("%Y-%m-%d %H:%M"),
                })

    return templates.TemplateResponse(
        "panel_chat.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "from_number": from_number,
            "nombre": nombre,
            "cedula": cedula,
            "tipo_servicio": tipo_servicio,
            "tipo_cita": tipo_cita,
            "messages": messages,
        },
    )


@router.post("/chat/send")
def chat_send(
    request: Request,
    from_number: str = Form(...),
    message: str = Form(...),
):
    redirect = _require_login(request)
    if redirect:
        return redirect

    message = (message or "").strip()
    if not message: 
        encoded = quote(from_number, safe="")
        return RedirectResponse(url=f"/panel/chat?from={encoded}", status_code=302)
        #return RedirectResponse(url=f"/panel/chat?from={from_number}", status_code=302)

    # Twilio config
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    wa_from = os.environ.get("TWILIO_WHATSAPP_FROM")  # ej: "whatsapp:+14155238886" o tu número WA

    if not account_sid or not auth_token or not wa_from:
        # Si no están las env vars, no tumbes el panel: muestra error simple
        return templates.TemplateResponse(
            "panel_chat.html",
            {
                "request": request,
                "user": request.session.get("user"),
                "from_number": from_number,
                "messages": [],
                "error": "Faltan TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM en Render.",
            },
            status_code=500,
        )

    client = Client(account_sid, auth_token)

    tw_sid = None
    try:
        sent = client.messages.create(
            from_=wa_from,
            to=from_number,
            body=message,
        )
        tw_sid = sent.sid
    except Exception as e:
        return templates.TemplateResponse(
            "panel_chat.html",
            {
                "request": request,
                "user": request.session.get("user"),
                "from_number": from_number,
                "messages": [],
                "error": f"Error enviando por Twilio: {e}",
            },
            status_code=500,
        )

    # Guardar como salida en DB
    try:
        save_message(from_number, "out", message, tw_sid)
    except Exception as e:
        print(f"[WARN] save_message(out) failed: {e}")
    encoded = quote(from_number, safe="")
    return RedirectResponse(url=f"/panel/chat?from={encoded}", status_code=302)
    #return RedirectResponse(url=f"/panel/chat?from={from_number}", status_code=302)

@router.post("/chat/close")
def chat_close(request: Request, from_number: str = Form(...)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    # borra historial
    try:
        delete_messages(from_number)
    except Exception as e:
        print(f"[WARN] delete_messages failed: {e}")

    # resetea conversación (para que el bot vuelva a menú)
    try:
        delete_session(from_number)
    except Exception as e:
        print(f"[WARN] delete_session failed: {e}")

    return RedirectResponse(url="/panel", status_code=302)


from fastapi import HTTPException
from fastapi.responses import JSONResponse
from urllib.parse import unquote
import Core.db as db

@router.get("/chat/messages")
def chat_messages(request: Request, from_number: str = Query(..., alias="from")):
    # En APIs: NO redirect, 401
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not logged in")

    from_number = unquote(from_number)

    messages = []
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT direction, body, created_at
                FROM messages
                WHERE from_number = %s
                ORDER BY created_at ASC
                LIMIT 500;
            """, (from_number,))
            rows = cur.fetchall()

    for direction, body, created_at in rows:
        messages.append({
            "direction": direction,
            "body": body,
            "created_at": created_at.astimezone(local_tz).strftime("%Y-%m-%d %H:%M"),
        })

    return JSONResponse(messages)
