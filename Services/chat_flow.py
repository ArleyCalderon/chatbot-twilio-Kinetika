from datetime import datetime, timezone, date, timedelta
import re
#region Preguntas
QUESTIONS = [
    # Identificación
    {"key": "tipo_id", "text": "Tipo de documento:\n1) Cédula de ciudadanía\n2) Cédula de extranjería\n3) Pasaporte\n4) Registro civil\n5) Tarjeta de identidad\n6) Adulto sin identificación\n7) Menor sin identificación\n8) Número único de identificación\n9) Carnet Diplomático\n10) Permiso especial de permanencia\n11) Certificado nacido vivo\n12) Permiso por protección temporal\n13) Salva conducto\n14) Documento extranjero\n\nResponde con el número", "type": "doc_type"},
    {"key": "cedula", "text": "Escribe tu número de documento (solo números):", "type": "doc_number"},
    {"key": "nombres_raw", "text": "Escribe tus *NOMBRES* (uno o dos).\nEj: Juan David", "type": "names","condition": lambda data: not data.get("cliente_existente")},
    {"key": "apellidos_raw", "text": "Escribe tus *APELLIDOS* (uno o dos).\nEj: Pérez Gómez", "type": "surnames","condition": lambda data: not data.get("cliente_existente")},
    {"key": "genero", "text": "Género:\n1) Masculino\n2) Femenino", "type": "gender","condition": lambda data: not data.get("cliente_existente")},
    {"key": "fecha_nacimiento", "text": "Fecha de nacimiento (DD/MM/AAAA).\nEj: 11/05/1997", "type": "dob","condition": lambda data: not data.get("cliente_existente")},

    # Contacto
    {"key": "celular", "text": "Número de celular (solo números).\nEj: 3001234567", "type": "phone","condition": lambda data: not data.get("cliente_existente")},
    {"key": "email", "text": "Correo electrónico:\nEj: nombre@correo.com", "type": "email","condition": lambda data: not data.get("cliente_existente")},

    # Ubicación
    {"key": "pais_origen", "text": "País de origen:", "type": "text_min3","condition": lambda data: not data.get("cliente_existente")},
    {"key": "direccion", "text": "Dirección completa:\nEj: Cra 80 # 45-20, Medellín", "type": "text_min6","condition": lambda data: not data.get("cliente_existente")},
    {"key": "departamento", "text": "Departamento:", "type": "text_min3","condition": lambda data: not data.get("cliente_existente")},
    {"key": "municipio", "text": "Municipio:", "type": "text_min3","condition": lambda data: not data.get("cliente_existente")},
    {"key": "zona", "text": "Zona:\n1) Urbana\n2) Rural", "type": "zone","condition": lambda data: not data.get("cliente_existente")},

    # Salud
    {"key": "regimen", "text": "Régimen:\n1) Contributivo cotizante\n2) Subsidiado\n3) Contributivo beneficiario\n4) particular\n5) No afiliado\n6) Tomador/Amparado ARL\n7) Tomador/Amparado SOAT\n8) Tomador/Amparado Planes voluntarios de salud\n9) Especial o Excepción cotizante\n10) Especial o Excepción beneficiario\n11) Personas privadas de la libertad a cargo del fondo\n12) No sabe", "type": "regimen","condition": lambda data: not data.get("cliente_existente")},
    {"key": "eps", "text": "¿Cuál es tu EPS?\n1) Arl\n2) Eps\n3) Particular\n4) Poliza\n5) Soat", "type": "tiposeguro","condition": lambda data: not data.get("cliente_existente")},
    {"key": "afiliacion", "text": "¿Cuál es tu Afiliación?\n1) Cotizante\n2) Beneficiario", "type": "tipoafiliacion","condition": lambda data: not data.get("cliente_existente")},

    # Condicional
    {"key": "discapacidad", "text": "¿Tienes alguna discapacidad?\n1) Sí\n2) No", "type": "yesno"},
    {"key": "cual_discapacidad", "text": "¿Cuál discapacidad tienes?", "type": "text_min3",
     "condition": lambda data: data.get("discapacidad") == "SI"},

    # Emergencia
    {"key": "nombre_acompanante", "text": "Nombre de contacto de emergencia", "type": "optional_name","condition": lambda data: not data.get("cliente_existente")},
    {"key": "telefono_emergencia", "text": "Teléfono de emergencia (solo números):", "type": "phone","condition": lambda data: not data.get("cliente_existente")},

    # Cita Component
    {"key": "tipo_cita", "text": "¿Tipo de cita?\n1) Valoración primera vez\n2) Control", "type": "tipocita"},
    {"key": "tipo_servicio", "text": "¿Qué servicio desea agendar?\n1) Hidroterapia\n2) Terapia Física\n3) Terapia domiciliaria", "type": "tiposervicio"},

    {"key": "cirugia", "text": "¿Tienes alguna cirugía reciente?\n1) Sí\n2) No", "type": "yesno"},
]
#endregion

#region Normalización / Validación
DOC_MAP = {
    "1": "Cédula de ciudadanía", "cc": "Cédula de ciudadanía", "c.c": "Cédula de ciudadanía", "cedula": "Cédula de ciudadanía", "cédula": "Cédula de ciudadanía",
    "2": "Cédula de extranjería", "ce": "Cédula de extranjería", "c.e": "Cédula de extranjería",
    "3": "Pasaporte", "pas": "Pasaporte", "pasaporte": "Pasaporte",
    "4": "registro civil", "registro": "registro civil", "rc": "registro civil",
    "5": "tarjeta de identidad", "ti": "tarjeta de identidad", "tarjeta de identidad": "tarjeta de identidad",
    "6": "Adulto sin identificación", "asi": "Adulto sin identificación", "adulto sin identificación": "Adulto sin identificación",
    "7": "Menor sin identificación", "Menor sin identificación": "Menor sin identificación",
    "8": "Número único de identificación", "nui": "Número único de identificación", "número único de identificación": "Número único de identificación",
    "9": "Carnet Diplomático", "cd": "Carnet Diplomático", "carnet diplomático": "Carnet Diplomático",
    "10": "Permiso especial de permanencia", "pep": "Permiso especial de permanencia", "permiso especial de permanencia": "Permiso especial de permanencia",
    "11": "Certificado nacido vivo", "cnv": "Certificado nacido vivo", "certificado nacido vivo": "Certificado nacido vivo",
    "12": "Permiso por protección temporal", "ppt": "Permiso por protección temporal", "permiso por protección temporal": "Permiso por protección temporal",
    "13": "Salva conducto", "sc": "Salva conducto", "salva conducto": "Salva conducto",
    "14": "Documento extranjero", "de": "Documento extranjero", "documento extranjero": "Documento extranjero",
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
            return False, None, "No te entendí 😅 Responde con 1, 2, 3 o 4 ...."
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

    if t == "tiposeguro":
        m = msg.lower()
        if m in {"1", "arl"}:
            return True, "ARL", None
        if m in {"2", "eps"}:
            return True, "EPS", None
        if m in {"3", "particular"}:
            return True, "Particular", None
        if m in {"4", "poliza"}:
            return True, "Póliza", None
        if m in {"5", "soat"}:
            return True, "SOAT", None
        return False, None, "Responde con 1, 2, 3, 4 o 5."

    if t == "tipoafiliacion":
        m = msg.lower()
        if m in {"1", "cotizante"}:
            return True, "Cotizante", None
        if m in {"2", "beneficiario"}:
            return True, "Beneficiario", None
        return False, None, "Responde con 1 (Cotizante) o 2 (Beneficiario)."

    if t == "dob":
        try:
            d = datetime.strptime(msg, "%d/%m/%Y").date()
        except ValueError:
            return False, None, "Formato inválido. Usa DD/MM/AAAA.\nEj: 11/05/1997"
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
        mapping = {
            "1": "Contributivo cotizante", "2": "Subsidiado", "3": "Contributivo beneficiario",
            "4": "particular", "5": "No afiliado", "6": "Tomador/Amparado ARL", "7": "Tomador/Amparado SOAT",
            "8": "Tomador/Amparado Planes voluntarios de salud", "9": "Especial o Excepción cotizante",
            "10": "Especial o Excepción beneficiario", "11": "Personas privadas de la libertad a cargo del fondo",
            "12": "NO_SABE"
        }
        if m in mapping:
            return True, mapping[m], None
        if "contributivo cotizante" in m:
            return True, "Contributivo cotizante", None
        if "subsi" in m:
            return True, "Subsidiado", None
        if "contributivo beneficiario" in m:
            return True, "Contributivo beneficiario", None
        if "particular" in m:
            return True, "particular", None
        if "no afiliado" in m:
            return True, "No afiliado", None
        if "arl" in m:
            return True, "Tomador/Amparado ARL", None
        if "soat" in m:
            return True, "Tomador/Amparado SOAT", None
        if "planes voluntarios de salud" in m:
            return True, "Tomador/Amparado Planes voluntarios de salud", None
        if "especial o excepción cotizante" in m:
            return True, "Especial o Excepción cotizante", None
        if "especial o excepción beneficiario" in m:
            return True, "Especial o Excepción beneficiario", None
        if "personas privadas de la libertad a cargo del fondo" in m:
            return True, "Personas privadas de la libertad a cargo del fondo", None
        if "no" in m and "no sabe" in m:
            return True, "NO_SABE", None
        return False, None, "Responde con 1, 2, 3 o 4..."

    if t == "tipocita":
        m = msg.lower()
        if m in {"1", "valoración primera vez", "valoracion primera vez"}:
            return True, "Valoración primera vez", None
        if m in {"2", "control"}:
            return True, "Control", None
        return False, None, "Responde con 1 o 2 ."

    if t == "tiposervicio":
        m = msg.lower()
        if m in {"1", "hidroterapia"}:
            return True, "Hidroterapia", None
        if m in {"2", "terapia física", "terapia fisica"}:
            return True, "Terapia Física", None
        if m in {"3", "terapia domiciliaria"}:
            return True, "Terapia domiciliaria", None
        return False, None, "Responde con 1, 2  o 3"

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
#endregion

# region Flow menu
MENU_TEXT = (
    
    "Hola👋 te damos la bienvenida. Gracias por ponerte en contacto con nosotros. Antes de iniciar, es necesario que aceptes los términos y condiciones de WhatsApp.   ¿Qué deseas hacer?\n"
    "1) Agendar cita\n"
    "2) Cancelar cita\n\n"
    "Responde con 1 o 2"
)

CANCEL_PROMPT = "Para cancelar, escribe tu número de documento (solo números):"
CANCEL_DATE_PROMPT = (
    "Indica la *fecha de la cita* que deseas cancelar.\n"
    "Formato: DD/MM/AAAA\n"
    "Ejemplo: 25/09/2026"
)

#  Modo handoff (asesor humano)
HANDOFF_TEXT = (
    "Perfecto ✅\n"
    "Te remitiremos a un asesor para ayudarte con tu requerimiento.\n\n"
    "📌 Importante:\n"
    "• La respuesta puede tardar debido a altos volúmenes de solicitudes.\n"
    "• Te contactaremos por este mismo medio.\n\n"
    "👉 Si en cualquier momento deseas volver al bot, escribe *menu*."
)



THANKS_WORDS = {
    "gracias", "muchas gracias", "mil gracias", "ok", "oka", "listo", "vale",
    "perfecto", "dale", "bien", "genial", "👍", "🙏"
}
# endregion
