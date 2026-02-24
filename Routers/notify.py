# Routers/notify.py
import os, json
from typing import Optional, Dict, Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from twilio.rest import Client
from Services.chat_store import save_message

router = APIRouter(prefix="/notify", tags=["notify"])

class NotifyIn(BaseModel):
    to: str                         # "whatsapp:+57..."
    wa_from: str | None = None       # opcional
    body: str | None = None          # texto libre (modo viejo)

    # ✅ Nuevo: soporte para templates
    content_sid: str | None = None   # "HXxxxxxxxx..."
    content_variables: Dict[str, Any] | None = None  # {"1":"Nombre","2":"Fecha","3":"Hora"}

@router.post("/whatsapp")
def notify_whatsapp(payload: NotifyIn, x_api_key: str = Header(default="")):
    expected = os.environ.get("NOTIFY_API_KEY", "")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    default_from = os.environ.get("TWILIO_WHATSAPP_FROM")  # "whatsapp:+1..."

    if not account_sid or not auth_token or not default_from:
        raise HTTPException(status_code=500, detail="Twilio env vars missing")

    wa_from = payload.wa_from or default_from
    client = Client(account_sid, auth_token)

    # ✅ Validación: o mandas body o mandas template
    if payload.content_sid:
        if not payload.content_variables:
            raise HTTPException(status_code=400, detail="content_variables is required when content_sid is provided")

        sent = client.messages.create(
            from_=wa_from,
            to=payload.to,
            content_sid=payload.content_sid,
            content_variables=json.dumps(payload.content_variables)
        )
        rendered = f"TEMPLATE {payload.content_sid} vars={payload.content_variables}"

    else:
        if not payload.body:
            raise HTTPException(status_code=400, detail="body is required when content_sid is not provided")

        sent = client.messages.create(
            from_=wa_from,
            to=payload.to,
            body=payload.body
        )
        rendered = payload.body

    # Si luego quieres que se vea en panel, lo activas:
    # save_message(payload.to, "out", rendered, sent.sid, to_number=wa_from)

    return {"ok": True, "sid": sent.sid}