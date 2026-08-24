import os, json
from fastapi import APIRouter, Request, Response
from psycopg_pool import ConnectionPool
router = APIRouter()
DATABASE_URL = os.environ.get("DATABASE_URL")
pool: ConnectionPool | None = None

def get_conn():
    if pool is None:
        raise RuntimeError("Pool no inicializado aún")
    return pool.connection()

def init_pool():
    global pool
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL")
    pool = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=5)

def init_db():
    from .db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            # tus tablas existentes
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    from_number TEXT PRIMARY KEY,
                    step INTEGER NOT NULL,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS submissions (
                    id BIGSERIAL PRIMARY KEY,
                    from_number TEXT NOT NULL,
                    flow TEXT NOT NULL,
                    message_sid TEXT UNIQUE,
                    data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            # NUEVO: historial de mensajes (in/out) para el panel
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
                CREATE TABLE IF NOT EXISTS clients (
                id BIGSERIAL PRIMARY KEY,
                identification TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversation_reads (
                conversation_key TEXT NOT NULL,
                advisor_id TEXT NOT NULL,
                last_read_message_id BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (conversation_key, advisor_id)
                );
            
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS comedero_state (
                    device_id TEXT PRIMARY KEY,

                    pending_command TEXT,
                    command_id TEXT,
                    command_status TEXT,
                    command_sent_at TIMESTAMPTZ,

                    last_command TEXT,
                    last_result TEXT,

                    last_seen TIMESTAMPTZ,
                    last_ip TEXT,
                    last_wifi_rssi INTEGER,
                    last_wifi_quality INTEGER,
                    last_wifi_label TEXT,
                    last_uptime_ms BIGINT,

                    closed_angle INTEGER,
                    open_angle INTEGER,
                    open_time_ms INTEGER,

                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                    CHECK (
                        pending_command IS NULL
                        OR pending_command IN ('dar_comida', 'abrir', 'cerrar')
                    ),

                    CHECK (
                        last_command IS NULL
                        OR last_command IN ('dar_comida', 'abrir', 'cerrar')
                    ),

                    CHECK (
                        command_status IS NULL
                        OR command_status IN ('pending', 'sent', 'done', 'failed')
                    )
                );
            """)
            # Migración compatible con instalaciones donde la tabla ya existía.
            cur.execute("""
                ALTER TABLE comedero_state
                ADD COLUMN IF NOT EXISTS command_sent_at TIMESTAMPTZ;
            """)


            conn.commit()
