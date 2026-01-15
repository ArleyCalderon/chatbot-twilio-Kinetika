import os
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse

import psycopg

app = FastAPI()

QUESTIONS = [
    ("nombre", "¿Cuál es tu nombre completo?"),
    ("tipo_id", "Tipo de documento:\n1️⃣ CC\n2️⃣ CE\n3️⃣ PAS"),
    ("cedula", "Escribe tu número de documento:"),
    ("direccion", "¿Cuál es tu dirección?"),
    ("eps", "¿Cuál es tu EPS?")
]

DATABASE_URL = os.environ.get("DATABASE_URL")

@app.get("/health")
def health():
    return {"status": "ok"}

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL en environment variables")
    return psycopg.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    from_number TEXT PRIMARY KEY,
                    step INTEGER NOT NULL,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
            """)
            conn.commit()

@app.on_event("startup")
def on_startup():
    init_db()

def load_session(from_number: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT step, data FROM sessions WHERE from_number = %s;", (from_number,))
            row = cur.fetchone()
            if not row:
                return None
            step, data = row
            return {"step": step, "data": data}

def save_session(from_number: str, step: int, data: dict):
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sessions (from_number, step, data, updated_at)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (from_number)
                DO UPDATE SET step = EXCLUDED.step, data = EXCLUDED.data, updated_at = EXCLUDED.updated_at;
            """, (from_number, step, json.dumps(data), now))
            conn.commit()

def delete_session(from_number: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE from_number = %s;", (from_number,))
            conn.commit()

@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = (form.get("Body") or "").strip()
    from_number = form.get("From")

    resp = MessagingResponse()

    session = load_session(from_number)

    # Usuario nuevo
    if session is None:
        save_session(from_number, step=0, data={})
        resp.message(QUESTIONS[0][1])
        return Response(content=str(resp), media_type="application/xml")

    step = session["step"]
    data = session["data"] or {}

    # Guardar respuesta anterior
    if step < len(QUESTIONS):
        key, _ = QUESTIONS[step]
        data[key] = incoming_msg
        step += 1
        save_session(from_number, step=step, data=data)

    # ¿Hay más preguntas?
    if step < len(QUESTIONS):
        resp.message(QUESTIONS[step][1])
    else:
        resp.message("Perfecto ✅\nEn un momento se le agendará la cita.")
        print(f"[CAPTURA] from={from_number} data={data}")
        delete_session(from_number)

    return Response(content=str(resp), media_type="application/xml")
