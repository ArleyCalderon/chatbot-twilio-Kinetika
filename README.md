# Chatbot Twilio WhatsApp (FastAPI)

Bot de WhatsApp usando Twilio + FastAPI para capturar datos por pasos (sesión en memoria).

## Ejecutar local
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
