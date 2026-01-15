from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

QUESTIONS = [
    ("nombre", "¿Cuál es tu nombre completo?"),
    ("tipo_id", "Tipo de documento:\n1️⃣ CC\n2️⃣ CE\n3️⃣ PAS"),
    ("cedula", "Escribe tu número de documento:"),
    ("direccion", "¿Cuál es tu dirección?"),
    ("eps", "¿Cuál es tu EPS?")
]

SESSIONS = {}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = (form.get("Body") or "").strip()
    from_number = form.get("From")

    resp = MessagingResponse()

    # Usuario nuevo
    if from_number not in SESSIONS:
        SESSIONS[from_number] = {"step": 0, "data": {}}
        resp.message(QUESTIONS[0][1])
        return Response(content=str(resp), media_type="application/xml")

    session = SESSIONS[from_number]
    step = session["step"]

    # Guardar respuesta anterior
    if step < len(QUESTIONS):
        key, _ = QUESTIONS[step]
        session["data"][key] = incoming_msg
        session["step"] += 1

    # ¿Hay más preguntas?
    if session["step"] < len(QUESTIONS):
        next_question = QUESTIONS[session["step"]][1]
        resp.message(next_question)
    else:
        # Final
        resp.message("Perfecto ✅\nEn un momento se le agendará la cita.")
        print(f"[CAPTURA] from={from_number} data={session['data']}")
        del SESSIONS[from_number]  # cerrar sesión

    return Response(content=str(resp), media_type="application/xml")
