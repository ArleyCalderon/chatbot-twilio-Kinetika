from Core.db import get_conn
from datetime import datetime, timezone, timedelta
import json
# Services/chat_store.py
import Core.db as db

def load_session(from_number: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT step, data, updated_at
                FROM sessions
                WHERE from_number = %s;
            """, (from_number,))
            row = cur.fetchone()
            if not row:
                return None

            step, data, updated_at = row

            # ⏰ Expiración:
            # - Flujo normal: 24h
            # - Handoff (asesor): 72h (3 días)
            expiry_hours = 24
            if step == -9:
                expiry_hours = 72

            if datetime.now(timezone.utc) - updated_at > timedelta(hours=expiry_hours):
                delete_session(from_number)
                return None

            return {"step": step, "data": data}



def save_submission(from_number: str, flow: str, data: dict, message_sid: str | None = None):
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO submissions (from_number, flow, message_sid, data, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (message_sid) DO NOTHING;
            """, (from_number, flow, message_sid, json.dumps(data), now))
            conn.commit()


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



def save_message(from_number: str, direction: str, body: str, twilio_sid: str | None = None, to_number: str | None = None):
    """
    Guarda mensajes entrantes y salientes para ver historial en el panel.
    direction: 'in' o 'out'
    """

    if not from_number or not body:
        return
    

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    from_number TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('in','out')),
                    body TEXT NOT NULL,
                    twilio_sid TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    to_number TEXT
                
                );
            """)
            cur.execute("""
                INSERT INTO messages (from_number, direction, body, twilio_sid, to_number)
                VALUES (%s, %s, %s, %s);
            """, (from_number, direction, body, twilio_sid, to_number))
            conn.commit()
    
def delete_messages(from_number: str):
    if db.pool is None:
        return
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE from_number = %s;", (from_number,))
            conn.commit()

def delete_LastMessagesChat(from_number: str):
    if db.pool is None:
        return
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversation_reads WHERE conversation_key = %s;", (from_number,))
            conn.commit()


def get_client_by_identification(identification: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    id BIGSERIAL PRIMARY KEY,
                    identification TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                SELECT id, identification, name
                FROM clients
                WHERE identification = %s
                LIMIT 1;
            """, (identification,))
            row = cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "identification": row[1], "name": row[2]}
        
def upsert_client(identification: str, name: str):
    if not identification or not name:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clients (identification, name)
                VALUES (%s, %s)
                ON CONFLICT (identification)
                DO UPDATE SET name = EXCLUDED.name;
            """, (identification, name))
            conn.commit()
