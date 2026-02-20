import json
from twilio.twiml.messaging_response import MessagingResponse
from Services.chat_store import load_session, save_session, delete_session, save_submission, save_message,upsert_client
from Services.chat_flow import QUESTIONS, MENU_TEXT, HANDOFF_TEXT, CANCEL_PROMPT, CANCEL_DATE_PROMPT, validate_and_normalize, next_valid_step, normalize_digits
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import Response
from Services.chat_store import get_client_by_identification
from zoneinfo import ZoneInfo
import re


router = APIRouter()
@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From")
    message_sid = form.get("MessageSid")
    incoming_msg = (form.get("Body") or "").strip()
    to_number = form.get("To")
        
    #save_message(from_number, "in", incoming_msg, message_sid)

    resp = MessagingResponse()

    # -------------------------
    # Horario de atención (Colombia)
    # -------------------------
    tz = ZoneInfo("America/Bogota")
    now_co = datetime.now(tz)

    OPEN_DAYS = {0, 1, 2, 3, 4}   # Lunes(0) a Viernes(4)
    OPEN_START_HOUR = 8          # 08:00
    OPEN_END_HOUR = 18           # 18:00 (18:00 en adelante ya está cerrado)

    is_open_day = now_co.weekday() in OPEN_DAYS
    is_open_hour = (OPEN_START_HOUR <= now_co.hour < OPEN_END_HOUR)

    if not (is_open_day and is_open_hour):
        resp.message(
            "Hola 👋\n"
            "Nuestro horario de atención es *lunes a viernes de 8:00 a 18:00* (hora Colombia).\n"
            "Escríbenos dentro de ese horario y con gusto te atendemos 🙂"
        )
        return Response(content=str(resp), media_type="application/xml")


# Nota: como ya cargamos session/step/data arriba, NO los vuelvas a cargar más abajo.

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
        save_message(from_number, "in", incoming_msg, message_sid,to_number=to_number)
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

    # STEP -10: En cola para registro CRM (modo mudo)
    if step == -10:
        save_message(from_number, "in", incoming_msg, message_sid, to_number=to_number)

        m = cmd
        if m in {"menu", "menú", "inicio", "empezar", "volver"}:
            save_session(from_number, step=-1, data={})
            resp.message(MENU_TEXT)
            return Response(content=str(resp), media_type="application/xml")

        # si quieres silencio total:
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
        
        if m in {"3", "informe", "informe final", "solicitud informe final"}:
            data["flow"] = "informe_final"
            save_session(from_number, step=-20, data=data)
            resp.message(
                "¿Para qué servicio necesitas el informe?\n"
                "1) Fisioterapia\n"
                "2) Hidroterapia\n"
                "Responde con 1 o 2"
            )
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
        data["wa_from"] = to_number  # Guardamos el número de destino (tu WA) para usarlo en la notificación de cancelación
        save_session(from_number, step=-4, data=data)
        

        resp.message(
            f"Listo ✅\n"
            f"Estoy procesando la cancelación de la cita del *{data['fecha_cancelacion']}*.\n"
            f"¿Desea reagendar su cita?\n"
            f"1) Sí\n"
            f"2) No\n"
        )

        print(f"[CANCELACION] from={from_number} data={data}")

        #delete_session(from_number)
        return Response(content=str(resp), media_type="application/xml")

    # ---------------------------------
    # STEP -4: Pregunta si desea reagendar (cancelar)
    # ---------------------------------
    if step == -4:
        m = cmd

        if m in {"1", "si", "sí", "s"}:
            data["reason"] = "reagendar"
            save_submission(from_number, data.get("flow", "cancelar"), data, message_sid)
            save_session(from_number, step=-9, data=data)
            save_message(from_number, "in", "Inicio de conversación", message_sid, to_number=to_number)
            resp.message("Un asesor lo apoyará a reagendar su cita lo antes posible 🙂")
            return Response(content=str(resp), media_type="application/xml")

        if m in {"2", "no", "n"}:
            data["reagendar"] = False
            save_submission(from_number, data.get("flow", "cancelar"), data, message_sid)
            delete_session(from_number)
            return Response(content=str(resp), media_type="application/xml")  # silencio

        resp.message("Porfa elige una opción:\n1) Sí\n2) No")
        return Response(content=str(resp), media_type="application/xml")
    
    # ---------------------------------
    # STEP -20: Tipo de informe (informe final)
    if step == -20:
        m = cmd

        if m in {"1", "terapia fisica", "terapia física"}:
            data["tipo_informe"] = "FISIOTERAPIA INFORME FINAL"
        elif m in {"2", "hidroterapia"}:
            data["tipo_informe"] = "HIDROTERAPIA INFORME FINAL"
        else:
            resp.message("Responde con 1 (Terapia Física) o 2 (Hidroterapia).")
            return Response(content=str(resp), media_type="application/xml")

        save_session(from_number, step=-21, data=data)
        resp.message("Escribe tu número de documento (solo números):")
        return Response(content=str(resp), media_type="application/xml")
    
    if step == -21:
        digits = normalize_digits(incoming_msg)

        if len(digits) < 6 or len(digits) > 15:
            resp.message("El documento debe tener entre 6 y 15 dígitos. Intenta de nuevo.")
            return Response(content=str(resp), media_type="application/xml")

        data["cedula_informe"] = digits
        save_session(from_number, step=-22, data=data)
        resp.message("Escribe tu correo electrónico:")
        return Response(content=str(resp), media_type="application/xml")
    

    if step == -22:
        email = incoming_msg.strip().lower()

        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
            resp.message("Ese correo no parece válido 😅\nEj: nombre@correo.com")
            return Response(content=str(resp), media_type="application/xml")

        data["email_informe"] = email

        # Guardar submission
        save_submission(from_number, data.get("flow", "informe_final"), data, message_sid)

        # Pasarlo a asesor
        #delete_session(from_number)
        data["wa_from"] = to_number 
        save_session(from_number, step=-23, data=data) #no es necesario pasar a asesor porque el informe se procesa automáticamente sin intervención humana, así que lo dejamos en step -22 para evitar confusiones.
        #save_message(from_number, "in", "Inicio de conversación", message_sid, to_number=to_number)

        resp.message(
            "Perfecto ✅\n"
            "Tu solicitud de informe fue registrada.\n"
            "En unos minutos puede revisar su correo electrónico con el informe solicitado."
        )

        return Response(content=str(resp), media_type="application/xml")
    # -------------------------
    # STEP -23: Informe registrado (modo mudo total)
    # -------------------------
    if step == -23:
        return Response(content="", status_code=204)


    #fin bloque informe final
    # ---------------------------------



    
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
                data["primer_nombre"] = client["name"] 
        step += 1
        step = next_valid_step(step, data)
        save_session(from_number, step=step, data=data)

    

    if step < len(QUESTIONS):
        resp.message(QUESTIONS[step]["text"])
    else:
        #save_submission(from_number, data.get("flow", "agendar"), data, message_sid)
        #Comento la linea de arriba para guardar la sumisión solo después de intentar el upsert del cliente, así evitamos guardar datos de clientes nuevos que no se pudieron registrar en el CRM.
        identification = data.get("cedula")
        full_name = (data.get("nombre_completo") or data.get("nombres_raw") or "").strip()

        if identification and full_name:
            upsert_client(identification, full_name)
        resp.message(HANDOFF_TEXT)

        if data.get("cliente_existente") is True:
            save_session(from_number, step=-9, data=data)
        else:
            save_session(from_number, step=-10, data=data)
            save_submission(from_number, data.get("flow", "agendar"), data, message_sid)
        save_message(from_number, "in", "Inicio de conversación", message_sid, to_number=to_number)
        
        # si el cliente es nuevo, se le asigna step -10 para que el asistente lo registre en el CRM antes de pasarlo a un agente humano.
        # Si el cliente ya existe, se le asigna step -9 para pasar directo a atención humana sin registro previo.
    return Response(content=str(resp), media_type="application/xml")

# endregion
