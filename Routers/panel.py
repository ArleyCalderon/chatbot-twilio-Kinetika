import os
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from urllib.parse import quote
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import os
from twilio.rest import Client
from Core.db import pool
from Services.chat_store import save_message, delete_messages, delete_session,delete_LastMessagesChat
import json
from fastapi.responses import JSONResponse
import Core.db as db
from urllib.parse import unquote
from pydantic import BaseModel
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from urllib.parse import unquote
import Core.db as db
from fastapi import Request
from zoneinfo import ZoneInfo
local_tz = ZoneInfo("America/Bogota")




router = APIRouter(prefix="/panel", tags=["panel"])
templates = Jinja2Templates(directory="Templates")


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user"))


def _require_login(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/panel/login", status_code=302)
    return None



@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if _is_logged_in(request):
        return RedirectResponse(url="/panel", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "user": None})


def parse_users(raw: str) -> dict[str, str]:
    """
    Convierte un string tipo:
      'user1:pass1,user2:pass2'
    en un dict:
      {'user1': 'pass1', 'user2': 'pass2'}
    """
    users: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            continue  # item inválido, lo ignoramos
        u, p = item.split(":", 1)  # solo parte por el primer ':'
        u, p = u.strip(), p.strip()
        if u:
            users[u] = p
    return users


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if _is_logged_in(request):
        return RedirectResponse(url="/panel", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "user": None})


@router.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    raw_users = os.environ.get("PANEL_USERS")

    if not raw_users:
        # sin usuarios configurados = nadie entra
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Login no configurado", "user": None},
            status_code=500,
        )

    users = parse_users(raw_users)
    ok = (users.get(username) == password)

    if ok:
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

    advisor_id = request.session.get("user") or "default"

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

                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        data = {}
                elif data is None:
                    data = {}

                nombre = _display_name(data)
                cedula = _display_cedula(data)
                local_dt = updated_at.astimezone(local_tz)

                cur.execute("""
                    SELECT COALESCE(MAX(id), 0)
                    FROM messages
                    WHERE from_number = %s AND direction = 'in';
                """, (from_number,))
                latest_in_id = cur.fetchone()[0]

                cur.execute("""
                    SELECT last_read_message_id
                    FROM conversation_reads
                    WHERE conversation_key = %s AND advisor_id = %s;
                """, (from_number, advisor_id))
                r = cur.fetchone()
                last_read = r[0] if r else 0

                has_new = latest_in_id > last_read

                pending.append({
                    "from_number": from_number,
                    "nombre": nombre,
                    "cedula": cedula,
                    "reason": data.get("flow", "Atención humana"),
                    "updated_at": local_dt.strftime("%d/%m/%Y %I:%M %p"),
                    "chat_url": f"/panel/chat?from={quote(from_number, safe='')}",
                    "has_new": has_new,
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
def _display_toNumber(data: dict) -> str:
    return data.get("to_number") or data.get("to_number")

def _display_Cirugia(data):
    return data.get("cual_cirugia")  # devuelve None si no existe

def _display_tipo_servicio(data: dict) -> str:
    return data.get("tipo_servicio")
def _display_tipo_cita(data: dict) -> str:
    return data.get("tipo_cita") 

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
        try:
            data = json.loads(data)
        except Exception:
            data = {}

    nombre = _display_name(data)
    cedula = _display_cedula(data)
    tipo_servicio = _display_tipo_servicio(data)
    tipo_cita = _display_tipo_cita(data)
    to_number = _display_toNumber(data)
    cirugia= _display_Cirugia(data)
    # traer mensajes
    messages = []
    last_message_id = 0
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, direction, body, created_at, to_number
                FROM messages
                WHERE from_number = %s
                ORDER BY created_at ASC, id ASC;
            """, (from_number,))
            for mid, d, b, c,to_number in cur.fetchall():
                last_message_id = max(last_message_id, mid)
                local_dt = c.astimezone(local_tz) if getattr(c, "tzinfo", None) else c
                messages.append({
                    "id": mid,
                    "direction": d,
                    "body": b,
                    "created_at": local_dt.strftime("%d/%m/%Y %I:%M %p"),
                    "to_number": to_number,
                   
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
            "last_message_id": last_message_id,
            "to_number": to_number,
            "cual_cirugia": cirugia,

            
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
    wa_from_default  = os.environ.get("TWILIO_WHATSAPP_FROM")  # ej: "whatsapp:+14155238886" o tu número WA
    wa_from = wa_from_default
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT to_number
                FROM messages
                WHERE from_number = %s
                AND direction = 'in'
                AND to_number IS NOT NULL
                ORDER BY id DESC
                LIMIT 1;
            """, (from_number,))
            r = cur.fetchone()
            if r and r[0]:
                wa_from = r[0]

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
        sent = client.messages.create(from_=wa_from, to=from_number, body=message)
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
        save_message(from_number, "out", message, tw_sid,to_number=wa_from)
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
    
    # resetea conversación (para que el bot vuelva a menú)
    try:
        delete_LastMessagesChat(from_number)
    except Exception as e:
        print(f"[WARN] delete_LastMessagesChat failed: {e}")

    
    return RedirectResponse(url="/panel", status_code=302)




@router.get("/chat/messages")
def chat_messages(request: Request, from_number: str = Query(..., alias="from")):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not logged in")

    from_number = unquote(from_number)

    messages = []
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, direction, body, created_at
                FROM messages
                WHERE from_number = %s
                ORDER BY created_at ASC, id ASC
                LIMIT 500;
            """, (from_number,))
            rows = cur.fetchall()

    for mid, direction, body, created_at in rows:
        local_dt = created_at.astimezone(local_tz) if getattr(created_at, "tzinfo", None) else created_at
        messages.append({
            "id": mid,
            "direction": direction,
            "body": body,
            "created_at": local_dt.strftime("%Y-%m-%d %H:%M"),
        })

    return JSONResponse(messages)



class MarkReadIn(BaseModel):
    conversation_key: str
    last_read_message_id: int

@router.post("/chat/mark_read")
def panel_mark_read(request: Request, payload: MarkReadIn):
    redirect = _require_login(request)
    if redirect:
        return {"ok": False}

    advisor_id = request.session.get("user") or "default"

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversation_reads (conversation_key, advisor_id, last_read_message_id, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (conversation_key, advisor_id)
                DO UPDATE SET
                    last_read_message_id = GREATEST(conversation_reads.last_read_message_id, EXCLUDED.last_read_message_id),
                    updated_at = NOW();
            """, (payload.conversation_key, advisor_id, payload.last_read_message_id))
            conn.commit()

    return {"ok": True}


from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import Core.db as db

@router.get("/pending/poll")
def panel_pending_poll(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not logged in")

    advisor_id = request.session.get("user") or "default"

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT from_number
                FROM sessions
                WHERE step = -9;
            """)
            convs = [r[0] for r in cur.fetchall()]

            new_map = {}

            for from_number in convs:
                cur.execute("""
                    SELECT COALESCE(MAX(id), 0)
                    FROM messages
                    WHERE from_number = %s AND direction = 'in';
                """, (from_number,))
                latest_in_id = cur.fetchone()[0]

                cur.execute("""
                    SELECT last_read_message_id
                    FROM conversation_reads
                    WHERE conversation_key = %s AND advisor_id = %s;
                """, (from_number, advisor_id))
                r = cur.fetchone()
                last_read = r[0] if r else 0

                new_map[from_number] = (latest_in_id > last_read)

    total_new = sum(1 for v in new_map.values() if v)
    total_pending = len(convs)

    return JSONResponse({
        "new": new_map,
        "total_new": total_new,
        "total_pending": total_pending
    })

