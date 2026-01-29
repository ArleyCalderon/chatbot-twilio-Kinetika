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
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            conn.commit()
