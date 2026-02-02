import json
from twilio.twiml.messaging_response import MessagingResponse
from Services.chat_store import load_session, save_session, delete_session, save_submission, save_message,upsert_client
from Services.chat_flow import QUESTIONS, MENU_TEXT, HANDOFF_TEXT, CANCEL_PROMPT, CANCEL_DATE_PROMPT, validate_and_normalize, next_valid_step, normalize_digits
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import Response
from Services.chat_store import get_client_by_identification


router = APIRouter()
@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From")
    message_sid = form.get("MessageSid")
    incoming_msg = (form.get("Body") or "").strip()
        
    #save_message(from_number, "in", incoming_msg, message_sid)

    resp = MessagingResponse()

    # Normalización única (NO la sobreescribas después)
    cmd = (incoming_msg or "").lower().strip()
    cmd = " ".join(cmd.split())  # quita espacios dobles

    # Cargar sesión UNA sola vez
    session = load_session(from_number)
    step = session["step"] if session else None
    data = (session["data"] or {}) if session else {}

    # -------------------------
    # Usuario nuevo -> mostrar menú (step = -1)
    # -------------------------
    if session is None:
        save_session(from_number, step=-1, data={})
        resp.message(MENU_TEXT)
        return Response(content=str(resp), media_type="application/xml")

    # -------------------------
    # STEP -9: En atención humana / handoff (silencio total)
    # -------------------------
    if step == -9:
        save_message(from_number, "in", incoming_msg, message_sid)
        m = cmd  # ya está normalizado

        if m in {"menu", "menú", "inicio", "empezar", "volver"}:
            save_session(from_number, step=-1, data={})
            resp.message(MENU_TEXT)
            return Response(content=str(resp), media_type="application/xml")

        if ("cancel" in m) or ("cancela" in m) or ("reprogram" in m) or ("cambiar" in m):
            save_session(from_number, step=-1, data={})
            resp.message("Listo 🙂\n" + MENU_TEXT)
            return Response(content=str(resp), media_type="application/xml")

        return Response(content="", status_code=204)

    # -------------------------
    # STEP -1: Menú principal
    # -------------------------
    if step == -1:
        m = cmd
        if m in {"1", "agendar", "agendar cita", "agenda", "registrar", "registrar cita"}:
            data["flow"] = "agendar"
            step = 0
            save_session(from_number, step=step, data=data)
            resp.message(QUESTIONS[0]["text"])
            return Response(content=str(resp), media_type="application/xml")

        if m in {"2", "cancelar", "cancelar cita", "cancela"}:
            data["flow"] = "cancelar"
            step = -2
            save_session(from_number, step=step, data=data)
            resp.message(CANCEL_PROMPT)
            return Response(content=str(resp), media_type="application/xml")

        resp.message("No te entendí 😅\n" + MENU_TEXT)
        return Response(content=str(resp), media_type="application/xml")

    # ---------------------------------
    # STEP -2: Captura cédula (cancelar)
    # ---------------------------------
    if step == -2:
        digits = normalize_digits(incoming_msg)
        if len(digits) < 6 or len(digits) > 15:
            resp.message("El documento debe tener entre 6 y 15 dígitos. Intenta de nuevo.")
            return Response(content=str(resp), media_type="application/xml")

        data["cedula_cancelacion"] = digits
        save_session(from_number, step=-3, data=data)
        resp.message(CANCEL_DATE_PROMPT)
        return Response(content=str(resp), media_type="application/xml")

    # ---------------------------------
    # STEP -3: Fecha de cita a cancelar
    # ---------------------------------
    if step == -3:
        try:
            fecha = datetime.strptime(incoming_msg, "%d/%m/%Y").date()
        except ValueError:
            resp.message(
                "Formato inválido 😅\n"
                "Usa DD/MM/AAAA\n"
                "Ejemplo: 25/09/2026"
            )
            return Response(content=str(resp), media_type="application/xml")

        if fecha < date.today():
            resp.message("La fecha no puede ser anterior a hoy 🤔. Intenta de nuevo.")
            return Response(content=str(resp), media_type="application/xml")

        data["fecha_cancelacion"] = fecha.strftime("%d/%m/%Y")
        save_submission(from_number, data.get("flow", "cancelar"), data, message_sid)

        resp.message(
            f"Listo ✅\n"
            f"Estoy procesando la cancelación de la cita del *{data['fecha_cancelacion']}*."
        )

        print(f"[CANCELACION] from={from_number} data={data}")

        delete_session(from_number)
        return Response(content=str(resp), media_type="application/xml")

    # -------------------------
    # Flujo normal (agendar)
    # -------------------------
    step = next_valid_step(step, data)

    if step < len(QUESTIONS):
        q = QUESTIONS[step]
        ok, normalized, error = validate_and_normalize(q, incoming_msg, data)
        if not ok:
            resp.message(error)
            return Response(content=str(resp), media_type="application/xml")

        data[q["key"]] = normalized
        if q["type"] == "doc_number":
            client = get_client_by_identification(normalized)
            if client:
                data["cliente_existente"] = True
                data["nombres_raw"] = client["name"] 
        step += 1
        step = next_valid_step(step, data)
        save_session(from_number, step=step, data=data)

    

    if step < len(QUESTIONS):
        resp.message(QUESTIONS[step]["text"])
    else:
        save_submission(from_number, data.get("flow", "agendar"), data, message_sid)
        identification = data.get("cedula")
        full_name = (data.get("nombre_completo") or data.get("nombres_raw") or "").strip()

        if identification and full_name:
            upsert_client(identification, full_name)
        resp.message(HANDOFF_TEXT)
        save_session(from_number, step=-9, data=data)

    return Response(content=str(resp), media_type="application/xml")

# endregion
