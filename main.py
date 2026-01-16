import os
import json
import re
from datetime import datetime, timezone, date

from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse

import psycopg

app = FastAPI()

# =========================
# Preguntas (estructura pro)
# =========================
QUESTIONS = [
    # Identificación
    {"key": "nombres_raw", "text": "Escribe tus *NOMBRES* (uno o dos).\nEj: Juan David", "type": "names"},
    {"key": "apellidos_raw", "text": "Escribe tus *APELLIDOS* (uno o dos).\nEj: Pérez Gómez", "type": "surnames"},
    {"key": "tipo_id", "text": "Tipo de documento:\n1) CC\n2) CE\n3) PAS\n\nResponde con el número o con CC/CE/PAS.", "type": "doc_type"},
    {"key": "cedula", "text": "Escribe tu número de documento (solo números):", "type": "doc_number"},
    {"key": "genero", "text": "Género:\n1) Masculino\n2) Femenino", "type": "gender"},
    {"key": "fecha_nacimiento", "text": "Fecha de nacimiento (DD/MM/AAAA).\nEj: 05/09/1996", "type": "dob"},

    # Contacto
    {"key": "celular", "text": "Número de celular (solo números).\nEj: 3001234567", "type": "phone"},
    {"key": "email", "text": "Correo electrónico:\nEj: nombre@correo.com", "type": "email"},

    # Ubicación
    {"key": "pais_origen", "text": "País de origen:", "type": "text_min3"},
    {"key": "direccion", "text": "Dirección completa:\nEj: Cra 80 # 45-20, Medellín", "type": "text_min6"},
    {"key": "departamento", "text": "Departamento:", "type": "text_min3"},
    {"key": "municipio", "text": "Municipio:", "type": "text_min3"},
    {"key": "zona", "text": "Zona:\n1) Urbana\n2) Rural", "type": "zone"},

    # Salud
    {"key": "regimen", "text": "Régimen:\n1) Contributivo\n2) Subsidiado\n3) Especial\n4) No sabe", "type": "regimen"},
    {"key": "eps", "text": "¿Cuál es tu EPS?", "type": "text_min3"},

    # Condicional
    {"key": "discapacidad", "text": "¿Tienes alguna discapacidad?\n1) Sí\n2) No", "type": "yesno"},
    {"key": "cual_discapacidad", "text": "¿Cuál discapacidad tienes?", "type": "text_min3",
     "condition": lambda data: data.get("discapacidad") == "SI"},

    # Emergencia
    {"key": "nombre_acompanante", "text": "Nombre de acompañante (si aplica). Si no, escribe NO.", "type": "optional_name"},
    {"key": "telefono_emergencia", "text": "Teléfono de emergencia (solo números):", "type": "phone"},
]

# =========================
# DB
# =========================
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


# =========================
# Normalización / Validación
# =========================
DOC_MAP = {
    "1": "CC", "cc": "CC", "c.c": "CC", "cedula": "CC", "cédula": "CC",
    "2": "CE", "ce": "CE", "c.e": "CE",
    "3": "PAS", "pas": "PAS", "pasaporte": "PAS",
}


def normalize_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def next_valid_step(step: int, data: dict) -> int:
    """Avanza hasta la próxima pregunta cuya condición se cumpla."""
    while step < len(QUESTIONS):
        cond = QUESTIONS[step].get("condition")
        if cond is None or cond(data):
            return step
        step += 1
    return step


def calc_age(d: date) -> int:
    today = date.today()
    years = today.year - d.year
    if (today.month, today.day) < (d.month, d.day):
        years -= 1
    return years


def validate_and_normalize(q: dict, msg: str, data: dict):
    """
    Retorna: (ok: bool, normalized_value, error_message|None)
    Puede además escribir campos derivados en data (ej: primer_nombre, edad, etc.)
    """
    t = q["type"]
    msg = (msg or "").strip()

    if t == "names":
        clean = re.sub(r"\s+", " ", msg)
        parts = clean.split(" ")
        if len(clean) < 2 or len(parts) < 1:
            return False, None, "Escribe al menos 1 nombre 🙂"
        if len(parts) > 3:
            return False, None, "Escribe máximo 2 nombres (si tienes 3, pon solo los 2 principales)."
        primer = parts[0].title()
        segundo = " ".join(parts[1:]).title() if len(parts) > 1 else ""
        data["primer_nombre"] = primer
        data["segundo_nombre"] = segundo
        return True, clean.title(), None

    if t == "surnames":
        clean = re.sub(r"\s+", " ", msg)
        parts = clean.split(" ")
        if len(clean) < 2 or len(parts) < 1:
            return False, None, "Escribe al menos 1 apellido 🙂"
        if len(parts) > 3:
            return False, None, "Escribe máximo 2 apellidos (si tienes 3, pon solo los 2 principales)."
        primer = parts[0].title()
        segundo = " ".join(parts[1:]).title() if len(parts) > 1 else ""
        data["primer_apellido"] = primer
        data["segundo_apellido"] = segundo
        return True, clean.title(), None

    if t == "doc_type":
        key = msg.lower().replace("️⃣", "").strip()
        doc = DOC_MAP.get(key)
        if not doc:
            return False, None, "No te entendí 😅 Responde con 1, 2, 3 o CC / CE / PAS."
        return True, doc, None

    if t == "doc_number":
        digits = normalize_digits(msg)
        if len(digits) < 6 or len(digits) > 15:
            return False, None, "El documento debe tener entre 6 y 15 dígitos. Intenta de nuevo."
        return True, digits, None

    if t == "gender":
        m = msg.lower()
        if m in {"1", "masculino", "m"}:
            return True, "MASCULINO", None
        if m in {"2", "femenino", "f"}:
            return True, "FEMENINO", None
        return False, None, "Responde con 1 (Masculino) o 2 (Femenino)."

    if t == "dob":
        try:
            d = datetime.strptime(msg, "%d/%m/%Y").date()
        except ValueError:
            return False, None, "Formato inválido. Usa DD/MM/AAAA.\nEj: 05/09/1996"
        age = calc_age(d)
        if age < 0 or age > 120:
            return False, None, "Esa fecha se ve rara 😅 Revisa y envíala en DD/MM/AAAA."
        data["edad"] = age
        return True, msg, None

    if t == "phone":
        digits = normalize_digits(msg)
        if len(digits) < 7 or len(digits) > 15:
            return False, None, "Número inválido. Escribe entre 7 y 15 dígitos."
        return True, digits, None

    if t == "email":
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", msg):
            return False, None, "Ese correo no parece válido 😅\nEj: nombre@correo.com"
        return True, msg.lower(), None

    if t == "zone":
        m = msg.lower()
        if m in {"1", "urbana"}:
            return True, "URBANA", None
        if m in {"2", "rural"}:
            return True, "RURAL", None
        return False, None, "Responde con 1 (Urbana) o 2 (Rural)."

    if t == "regimen":
        m = msg.lower()
        mapping = {"1": "CONTRIBUTIVO", "2": "SUBSIDIADO", "3": "ESPECIAL", "4": "NO_SABE"}
        if m in mapping:
            return True, mapping[m], None
        if "contri" in m:
            return True, "CONTRIBUTIVO", None
        if "subsi" in m:
            return True, "SUBSIDIADO", None
        if "espe" in m:
            return True, "ESPECIAL", None
        if "no" in m and "sab" in m:
            return True, "NO_SABE", None
        return False, None, "Responde con 1, 2, 3 o 4."

    if t == "yesno":
        m = msg.lower()
        if m in {"1", "si", "sí"}:
            return True, "SI", None
        if m in {"2", "no"}:
            return True, "NO", None
        return False, None, "Responde con 1 (Sí) o 2 (No)."

    if t == "optional_name":
        m = msg.strip()
        if m.lower() in {"no", "n/a", "na"}:
            return True, "", None
        if len(m) < 3:
            return False, None, "Escribe un nombre válido o responde NO."
        return True, re.sub(r"\s+", " ", m).title(), None

    if t == "text_min3":
        if len(msg) < 3:
            return False, None, "Porfa escribe al menos 3 caracteres."
        return True, msg.title(), None

    if t == "text_min6":
        if len(msg) < 6:
            return False, None, "Porfa escribe un poco más (mínimo 6 caracteres)."
        return True, msg, None

    return True, msg, None


# =========================
# Webhook Twilio WhatsApp
# =========================
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
        resp.message(QUESTIONS[0]["text"])
        return Response(content=str(resp), media_type="application/xml")

    step = session["step"]
    data = session["data"] or {}

    # Asegura step válido (salta condicionales)
    step = next_valid_step(step, data)

    # Guardar respuesta actual con validación
    if step < len(QUESTIONS):
        q = QUESTIONS[step]
        ok, normalized, error = validate_and_normalize(q, incoming_msg, data)
        if not ok:
            resp.message(error)
            return Response(content=str(resp), media_type="application/xml")

        # guarda campo principal
        data[q["key"]] = normalized

        # avanza
        step += 1
        step = next_valid_step(step, data)
        save_session(from_number, step=step, data=data)

    # Preguntar siguiente o terminar
    if step < len(QUESTIONS):
        resp.message(QUESTIONS[step]["text"])
    else:
        resp.message("Perfecto ✅\nEn un momento se le agendará la cita.")
        print(f"[CAPTURA] from={from_number} data={data}")
        delete_session(from_number)

    return Response(content=str(resp), media_type="application/xml")
