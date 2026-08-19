import os
import json
import Core.db as db
from Core.db import pool
from zoneinfo import ZoneInfo
from pydantic import BaseModel
from twilio.rest import Client
from fastapi import HTTPException
from urllib.parse import quote, unquote
from datetime import datetime, timedelta
from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from Services.chat_store import save_message, delete_messages, delete_session, delete_LastMessagesChat

local_tz = ZoneInfo("America/Bogota")

WHATSAPP_WINDOW_HOURS = 24

def _get_chat_status(from_number: str) -> dict:
    last_inbound_at = None
    wa_from = os.environ.get("TWILIO_WHATSAPP_FROM")

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT created_at, to_number
                FROM messages
                WHERE from_number = %s
                  AND direction = 'in'
                ORDER BY created_at DESC, id DESC
                LIMIT 1;
            """, (from_number,))
            row = cur.fetchone()

    if row:
        last_inbound_at, inbound_to_number = row
        if inbound_to_number:
            wa_from = inbound_to_number

    now_local = datetime.now(local_tz)

    if last_inbound_at:
        if getattr(last_inbound_at, "tzinfo", None):
            last_inbound_local = last_inbound_at.astimezone(local_tz)
        else:
            # asumir UTC si viene naive desde la BD
            last_inbound_local = last_inbound_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(local_tz)
    else:
        last_inbound_local = None

    is_window_open = False
    if last_inbound_local:
        is_window_open = (now_local - last_inbound_local) <= timedelta(hours=WHATSAPP_WINDOW_HOURS)

    return {
        "last_inbound_at": last_inbound_local,
        "last_inbound_at_str": last_inbound_local.strftime("%d/%m/%Y %I:%M %p") if last_inbound_local else None,
        "is_window_open": is_window_open,
        "is_window_expired": not is_window_open,
        "wa_from": wa_from,
    }


router = APIRouter(prefix="/panel", tags=["panel"])
templates = Jinja2Templates(directory="Templates")


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user"))


def _require_login(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/panel/login", status_code=302)
    return None






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
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None, "user": None})



@router.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    raw_users = os.environ.get("PANEL_USERS")

    if not raw_users:
        # sin usuarios configurados = nadie entra
        return templates.TemplateResponse(request,
            "login.html",
            {"request": request, "error": "Login no configurado", "user": None},
            status_code=500,
        )

    users = parse_users(raw_users)
    ok = (users.get(username) == password)

    if ok:
        request.session["user"] = username
        return RedirectResponse(url="/panel", status_code=302)

    return templates.TemplateResponse(request, "login.html", {"request": request, "error": "Credenciales inválidas", "user": None})


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/panel/login", status_code=302)


import json


@router.get("", response_class=HTMLResponse)
def panel_home(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    advisor_id = get_read_scope()

    with db.pool.connection() as conn:
        with conn.cursor() as cur:

            # 1) Lista principal desde sessions
            cur.execute("""
                SELECT from_number, data, updated_at
                FROM sessions
                WHERE step = -9
                ORDER BY updated_at ASC;
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
                entidad = _display_entidad(data)
                local_dt = updated_at.astimezone(local_tz)

                cur.execute("""
                    SELECT COALESCE(MAX(id), 0)
                    FROM messages
                    WHERE from_number = %s
                      AND direction = 'in'
                      AND body <> 'Inicio de conversación';
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
                clean_number = ''.join(filter(str.isdigit, from_number))[-10:]

                pending.append({
                    "from_number": clean_number,
                    "nombre": nombre,
                    "cedula": cedula,
                    "reason": data.get("reason", "Agendar"),
                    "entidad": entidad,
                    "cirugia": data.get("cirugia") == "SI",
                    "cual_cirugia": data.get("cual_cirugia"),
                    "updated_at": local_dt.strftime("%d/%m/%Y %I:%M %p"),
                    "chat_url": f"/panel/chat?from={quote(from_number, safe='')}",
                    "has_new": has_new,
                })

            # 2) Contadores desde submissions
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE LOWER(flow) = 'agendar') AS total_agendar,
                    COUNT(*) FILTER (WHERE LOWER(flow) = 'cancelar') AS total_cancelar,
                    COUNT(*) FILTER (WHERE LOWER(flow) = 'informe_final') AS total_informe
                FROM submissions;
            """)
            rpa_counts = cur.fetchone()

            total_agendar = rpa_counts[0] or 0
            total_cancelar = rpa_counts[1] or 0
            total_informe = rpa_counts[2] or 0

    return templates.TemplateResponse(
        request,
        "panel_list.html",
        {
            "request": request,
            "pending": pending,
            "user": request.session.get("user"),
            "total_agendar": total_agendar,
            "total_cancelar": total_cancelar,
            "total_informe": total_informe,
        },
    )

def _display_name(data: dict) -> str:
    parts = [
        data.get("primer_nombre"),
        data.get("segundo_nombre"),
        data.get("primer_apellido"),
        data.get("segundo_apellido"),
    ]
    parts = [p for p in parts if p]
    return " ".join(parts) if parts else "Paciente"

def _display_cedula(data: dict) -> str:
    return data.get("cedula") or data.get("cedula_cancelacion") or "(sin cédula)"

def _display_toNumber(data: dict) -> str:
    return data.get("to_number") or data.get("to_number")

def _display_entidad(data: dict) -> str:
    return data.get("eps")

def _display_Cirugia(data):
    return data.get("cual_cirugia")  # devuelve None si no existe

def _display_Terapia(data):
    return data.get("razon_terapia")  # devuelve None si no existe

def _display_fecha_cancelacion(data):
    return data.get("fecha_cancelacion")  # devuelve None si no existe


def _display_LugarCita(data):
    return data.get("lugar_cita")  # devuelve None si no existe


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
    razonterapia= _display_Terapia(data)
    lugarcita = _display_LugarCita(data)
    chat_status = _get_chat_status(from_number)
    fecha_cancelacion=_display_fecha_cancelacion(data)
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

    return templates.TemplateResponse(request,
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
            "razon_terapia": razonterapia,
            "lugar_cita": lugarcita,
            "fecha_cancelacion": fecha_cancelacion,
            "is_window_open": chat_status["is_window_open"],
            "is_window_expired": chat_status["is_window_expired"],
            "last_inbound_at": chat_status["last_inbound_at_str"],

            
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
    # evitar mensaje vacío
    if not message:
        encoded = quote(from_number, safe="")
        return RedirectResponse(url=f"/panel/chat?from={encoded}", status_code=302)

    # validar ventana de WhatsApp
    chat_status = _get_chat_status(from_number)

    if chat_status["is_window_expired"]:
        encoded = quote(from_number, safe="")
        return RedirectResponse(url=f"/panel/chat?from={encoded}", status_code=302)

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
        return templates.TemplateResponse(request,
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
        return templates.TemplateResponse(request,
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

    advisor_id = get_read_scope()
    # Guardar como salida en DB
    try:
        save_message(from_number, "out", message, tw_sid,to_number=wa_from)
    except Exception as e:
        print(f"[WARN] save_message(out) failed: {e}")
        

    try:
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(MAX(id), 0)
                    FROM messages
                    WHERE from_number = %s
                      AND direction = 'in';
                """, (from_number,))
                latest_in_id = cur.fetchone()[0]

                cur.execute("""
                    INSERT INTO conversation_reads (conversation_key, advisor_id, last_read_message_id, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (conversation_key, advisor_id)
                    DO UPDATE SET
                        last_read_message_id = GREATEST(conversation_reads.last_read_message_id, EXCLUDED.last_read_message_id),
                        updated_at = NOW();
                """, (from_number, advisor_id, latest_in_id))
                conn.commit()
    except Exception as e:
        print(f"[WARN] mark read after send failed: {e}")
    encoded = quote(from_number, safe="")
    return RedirectResponse(url=f"/panel/chat?from={encoded}", status_code=302)
    #return RedirectResponse(url=f"/panel/chat?from={from_number}", status_code=302)

@router.post("/chat/reactivate")
def chat_reactivate(request: Request, from_number: str = Form(...)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    content_sid = os.environ.get("TWILIO_REACTIVATE_TEMPLATE_SID")

    chat_status = _get_chat_status(from_number)
    wa_from = chat_status["wa_from"]

    if not account_sid or not auth_token or not wa_from or not content_sid:
        return templates.TemplateResponse(request,
            "panel_chat.html",
            {
                "request": request,
                "user": request.session.get("user"),
                "from_number": from_number,
                "messages": [],
                "error": "Faltan variables de Twilio para reactivar el chat.",
                "is_window_open": chat_status["is_window_open"],
                "is_window_expired": chat_status["is_window_expired"],
                "last_inbound_at": chat_status["last_inbound_at_str"],
            },
            status_code=500,
        )

    client = Client(account_sid, auth_token)

    try:
        sent = client.messages.create(
            from_=wa_from,
            to=from_number,
            content_sid=content_sid,
        )
        save_message(from_number, "out", "Reactivación de chat", sent.sid, to_number=wa_from)

        advisor_id = get_read_scope()

        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(MAX(id), 0)
                    FROM messages
                    WHERE from_number = %s
                    AND direction = 'in'
                    AND body <> 'Inicio de conversación';
                """, (from_number,))
                latest_in_id = cur.fetchone()[0]

                cur.execute("""
                    INSERT INTO conversation_reads (conversation_key, advisor_id, last_read_message_id, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (conversation_key, advisor_id)
                    DO UPDATE SET
                        last_read_message_id = GREATEST(conversation_reads.last_read_message_id, EXCLUDED.last_read_message_id),
                        updated_at = NOW();
                """, (from_number, advisor_id, latest_in_id))
                conn.commit()
    except Exception as e:
        return templates.TemplateResponse( request,
            "panel_chat.html",
            {
                "request": request,
                "user": request.session.get("user"),
                "from_number": from_number,
                "messages": [],
                "error": f"Error reactivando chat: {e}",
                "is_window_open": chat_status["is_window_open"],
                "is_window_expired": chat_status["is_window_expired"],
                "last_inbound_at": chat_status["last_inbound_at_str"],
            },
            status_code=500,
        )

    encoded = quote(from_number, safe="")
    return RedirectResponse(url=f"/panel/chat?from={encoded}", status_code=302)

@router.post("/chat/close")
def chat_close(request: Request, from_number: str = Form(...)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    close_template_sid = os.environ.get("TWILIO_CLOSE_CHAT_TEMPLATE_SID")

    chat_status = _get_chat_status(from_number)
    wa_from = chat_status["wa_from"]

    close_message = "El chat ha finalizado. Si necesitas algo más, puedes escribirnos nuevamente."

    # Intentar avisarle al usuario antes de cerrar
    if account_sid and auth_token and wa_from:
        client = Client(account_sid, auth_token)

        try:
            if chat_status["is_window_open"]:
                sent = client.messages.create(
                    from_=wa_from,
                    to=from_number,
                    body=close_message,
                )
                # Si igual vas a borrar mensajes abajo, esto realmente no queda guardado mucho tiempo,
                # pero no estorba.
                save_message(from_number, "out", close_message, sent.sid, to_number=wa_from)

            else:
                if close_template_sid:
                    sent = client.messages.create(
                        from_=wa_from,
                        to=from_number,
                        content_sid=close_template_sid,
                    )
                    save_message(from_number, "out", "Cierre de chat por plantilla", sent.sid, to_number=wa_from)
                else:
                    print("[WARN] La ventana está cerrada y falta TWILIO_CLOSE_CHAT_TEMPLATE_SID")

        except Exception as e:
            print(f"[WARN] no se pudo enviar mensaje de cierre: {e}")
    else:
        print("[WARN] faltan variables de Twilio para enviar cierre de chat")

    # Cerrar en BD
    try:
        delete_messages(from_number)
    except Exception as e:
        print(f"[WARN] delete_messages failed: {e}")

    try:
        delete_session(from_number)
    except Exception as e:
        print(f"[WARN] delete_session failed: {e}")

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

    advisor_id = get_read_scope()

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

    advisor_id = get_read_scope()

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
                    WHERE from_number = %s AND direction = 'in' AND body <> 'Inicio de conversación'; 
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

def get_read_scope() -> str:
    return "global"