# Routers/notify.py
import os
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from twilio.rest import Client
from Services.chat_store import save_message

router = APIRouter(prefix="/notify", tags=["notify"])

class NotifyIn(BaseModel):
    to: str                 # e.g. "whatsapp:+573001234567"
    body: str               # e.g. "✅ Tu cita fue cancelada..."
    wa_from: str | None = None  # opcional: "whatsapp:+1415xxxxxxx" o tu WA approved

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
    sent = client.messages.create(
        from_=wa_from,
        to=payload.to,
        body=payload.body
    )

    # Guardar en DB como mensaje saliente (para que aparezca en tu panel)
    #save_message(payload.to, "out", payload.body, sent.sid, to_number=wa_from)

    return {"ok": True, "sid": sent.sid}
