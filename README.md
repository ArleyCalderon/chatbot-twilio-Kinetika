##  Autor

Developed by **Arley Calderón — Software Engineer**
Backend / Automation / Chatbot Development

# WhatsApp Chatbot (Twilio + FastAPI + Postgres)

Chatbot para WhatsApp usando **Twilio** y **FastAPI** que permite dos flujos:

-  **Agendar cita**: formulario conversacional que captura datos paso a paso.
-  **Cancelar cita**: solicita **cédula** + **fecha (DD/MM/AAAA)** para procesar la cancelación.

El estado de la conversación se guarda en **PostgreSQL** (tabla `sessions`) y al finalizar se persiste el registro completo en **`submissions`** como `JSONB`.

---

##  Características

- Menú inicial: **Agendar / Cancelar**
- Validación y normalización de datos (documento, email, teléfono, fecha de nacimiento, etc.)
- Preguntas condicionales (ej: discapacidad → pregunta adicional)
- Persistencia de estado por usuario (`from_number`) en Postgres
- Guardado final en `submissions` (histórico) como `JSONB`
- Protección contra duplicados con `MessageSid` (idempotencia)
- Expiración automática de sesiones (ej: 24 horas)
- Pool de conexiones a Postgres con `psycopg_pool`

---

##  Flujo de conversación (resumen)

### 1) Menú principal
1. Agendar cita  
2. Cancelar cita  

### 2) Agendar cita
Avanza por la lista de preguntas `QUESTIONS` y al finalizar:
- Inserta el JSON completo en `submissions`
- Elimina la sesión en `sessions`

### 3) Cancelar cita
- Pide cédula (solo números)
- Pide fecha de cita a cancelar (DD/MM/AAAA)
- Inserta el JSON en `submissions`
- Elimina la sesión en `sessions`

---

##  Base de datos

Se crean automáticamente en `startup`:

### Tabla `sessions` (estado temporal)
- `from_number` (PK)
- `step` (índice de progreso)
- `data` (JSONB)
- `updated_at`

### Tabla `submissions` (histórico final)
- `id` (PK)
- `from_number`
- `flow` (`agendar` | `cancelar`)
- `message_sid` (UNIQUE)
- `data` (JSONB)
- `created_at`

---

##  Requisitos

- Python 3.10+ (recomendado)
- Cuenta de Twilio con WhatsApp habilitado
- Base de datos PostgreSQL (Render / Neon / Supabase / etc.)

---

##  Variables de entorno

Crea un archivo `.env` (o configura en Render):

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME

##  Ejecución local (opcional)

> Solo necesario para desarrollo o pruebas locales.
> En producción (Render), las variables de entorno se configuran automáticamente.

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
uvicorn main:app --reload

##  Licencia

Uso interno / privado. Todos los derechos reservados.
