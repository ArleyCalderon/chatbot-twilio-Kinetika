import os
from typing import Optional, Literal
from uuid import uuid4
from datetime import datetime, timezone
import Core.db as db
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel


COMEDERO_API_KEY = os.environ.get("COMEDERO_API_KEY")


def require_comedero_key(x_comedero_key: Optional[str] = Header(None)):
    if not COMEDERO_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="COMEDERO_API_KEY no configurada en el servidor",
        )

    if x_comedero_key != COMEDERO_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="No autorizado",
        )


router = APIRouter(
    prefix="/comedero",
    tags=["comedero"],
    dependencies=[Depends(require_comedero_key)],
)


class DeviceStatusRequest(BaseModel):
    device_id: str
    ip: Optional[str] = None
    wifi_rssi: Optional[int] = None
    wifi_quality: Optional[int] = None
    wifi_label: Optional[str] = None
    uptime_ms: Optional[int] = None
    closed_angle: Optional[int] = None
    open_angle: Optional[int] = None
    open_time_ms: Optional[int] = None


class CreateOrderRequest(BaseModel):
    device_id: str
    command: Literal["dar_comida", "abrir", "cerrar"]


class OrderDoneRequest(BaseModel):
    device_id: str
    command_id: str
    success: bool
    message: Optional[str] = None


@router.get("/ping")
def ping():
    return {
        "ok": True,
        "message": "Comedero API activa",
    }


@router.post("/status")
def update_status(status: DeviceStatusRequest):
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO comedero_state (
                    device_id,
                    last_ip,
                    last_wifi_rssi,
                    last_wifi_quality,
                    last_wifi_label,
                    last_uptime_ms,
                    closed_angle,
                    open_angle,
                    open_time_ms,
                    last_seen,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (device_id)
                DO UPDATE SET
                    last_ip = EXCLUDED.last_ip,
                    last_wifi_rssi = EXCLUDED.last_wifi_rssi,
                    last_wifi_quality = EXCLUDED.last_wifi_quality,
                    last_wifi_label = EXCLUDED.last_wifi_label,
                    last_uptime_ms = EXCLUDED.last_uptime_ms,
                    closed_angle = EXCLUDED.closed_angle,
                    open_angle = EXCLUDED.open_angle,
                    open_time_ms = EXCLUDED.open_time_ms,
                    last_seen = NOW(),
                    updated_at = NOW();
                """,
                (
                    status.device_id,
                    status.ip,
                    status.wifi_rssi,
                    status.wifi_quality,
                    status.wifi_label,
                    status.uptime_ms,
                    status.closed_angle,
                    status.open_angle,
                    status.open_time_ms,
                ),
            )

            conn.commit()

    return {
        "ok": True,
        "message": "Estado recibido",
    }


@router.get("/status/{device_id}")
def get_status(device_id: str):
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    device_id,
                    pending_command,
                    command_id,
                    command_status,
                    last_command,
                    last_result,
                    last_seen::text,
                    last_ip,
                    last_wifi_rssi,
                    last_wifi_quality,
                    last_wifi_label,
                    last_uptime_ms,
                    closed_angle,
                    open_angle,
                    open_time_ms,
                    updated_at::text
                FROM comedero_state
                WHERE device_id = %s;
                """,
                (device_id,),
            )

            row = cur.fetchone()

    if not row:
        return {
            "ok": False,
            "message": "Dispositivo no encontrado",
        }

    return {
        "ok": True,
        "device_id": row[0],
        "pending_command": row[1],
        "command_id": row[2],
        "command_status": row[3],
        "last_command": row[4],
        "last_result": row[5],
        "last_seen": row[6],
        "last_ip": row[7],
        "last_wifi_rssi": row[8],
        "last_wifi_quality": row[9],
        "last_wifi_label": row[10],
        "last_uptime_ms": row[11],
        "closed_angle": row[12],
        "open_angle": row[13],
        "open_time_ms": row[14],
        "updated_at": row[15],
    }


@router.post("/order")
def create_order(request: CreateOrderRequest):
    new_command_id = str(uuid4())

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            # Garantiza que exista la fila del dispositivo.
            cur.execute(
                """
                INSERT INTO comedero_state (
                    device_id,
                    created_at,
                    updated_at
                )
                VALUES (%s, NOW(), NOW())
                ON CONFLICT (device_id) DO NOTHING;
                """,
                (request.device_id,),
            )

            # Bloquea la fila mientras revisamos y modificamos la orden.
            cur.execute(
                """
                SELECT
                    pending_command,
                    command_status,
                    command_sent_at
                FROM comedero_state
                WHERE device_id = %s
                FOR UPDATE;
                """,
                (request.device_id,),
            )

            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=500,
                    detail="No fue posible registrar el comedero",
                )

            pending_command = row[0]
            command_status = row[1]
            command_sent_at = row[2]

            # Ya existe una orden activa.
            if pending_command is not None:

                if command_status == "pending":
                    conn.commit()
                    return {
                        "ok": False,
                        "message": "Ya existe una orden pendiente.",
                    }

                if command_status == "sent":
                    # Si no existe fecha de envío, la tratamos como una orden dañada.
                    if command_sent_at is None:
                        segundos = 999999
                    else:
                        if command_sent_at.tzinfo is None:
                            command_sent_at = command_sent_at.replace(
                                tzinfo=timezone.utc
                            )

                        segundos = (
                            datetime.now(timezone.utc) - command_sent_at
                        ).total_seconds()

                    # Todavía puede estar ejecutándose normalmente.
                    if segundos < 30:
                        conn.commit()
                        return {
                            "ok": False,
                            "message": "La orden anterior aún está siendo procesada.",
                        }

                    # Llevaba más de 30 segundos en sent:
                    # se limpia, pero NO se crea otra orden automáticamente.
                    cur.execute(
                        """
                        UPDATE comedero_state
                        SET
                            pending_command = NULL,
                            command_id = NULL,
                            command_status = NULL,
                            command_sent_at = NULL,
                            last_command = %s,
                            last_result = 'Orden expirada automáticamente',
                            updated_at = NOW()
                        WHERE device_id = %s;
                        """,
                        (
                            pending_command,
                            request.device_id,
                        ),
                    )

                    conn.commit()

                    return {
                        "ok": False,
                        "message": (
                            "Se detectó una orden expirada y el estado fue "
                            "restablecido. Vuelve a enviar la orden."
                        ),
                    }

            # No había ninguna orden activa: creamos una nueva.
            cur.execute(
                """
                UPDATE comedero_state
                SET
                    pending_command = %s,
                    command_id = %s,
                    command_status = 'pending',
                    command_sent_at = NULL,
                    last_command = %s,
                    last_result = NULL,
                    updated_at = NOW()
                WHERE device_id = %s;
                """,
                (
                    request.command,
                    new_command_id,
                    request.command,
                    request.device_id,
                ),
            )

            conn.commit()

    return {
        "ok": True,
        "message": "Orden creada",
        "device_id": request.device_id,
        "command_id": new_command_id,
        "command": request.command,
        "status": "pending",
    }

@router.get("/order/next")
def get_next_order(device_id: str):
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pending_command,
                    command_id,
                    command_status
                FROM comedero_state
                WHERE device_id = %s
                FOR UPDATE;
                """,
                (device_id,),
            )

            row = cur.fetchone()

            if not row:
                conn.commit()
                return {
                    "has_order": False,
                    "message": "Dispositivo no registrado",
                }

            pending_command = row[0]
            command_id = row[1]
            command_status = row[2]

            if pending_command is None or command_status != "pending":
                conn.commit()
                return {
                    "has_order": False,
                }

            cur.execute(
                """
                UPDATE comedero_state
                SET
                    command_status = 'sent',
                    command_sent_at = NOW(),
                    updated_at = NOW()
                WHERE device_id = %s;
                """,
                (device_id,),
            )

            conn.commit()

    return {
        "has_order": True,
        "device_id": device_id,
        "command_id": command_id,
        "command": pending_command,
    }


@router.post("/order/done")
def mark_order_done(result: OrderDoneRequest):
    new_status = "done" if result.success else "failed"

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    command_id,
                    pending_command
                FROM comedero_state
                WHERE device_id = %s
                FOR UPDATE;
                """,
                (result.device_id,),
            )

            row = cur.fetchone()

            if not row:
                conn.commit()
                return {
                    "ok": False,
                    "message": "Dispositivo no encontrado",
                }

            current_command_id = row[0]
            current_command = row[1]

            if current_command_id != result.command_id:
                conn.commit()
                return {
                    "ok": False,
                    "message": "El command_id no coincide con la orden activa",
                }

            cur.execute(
                """
                UPDATE comedero_state
                SET
                    pending_command = NULL,
                    command_status = %s,
                    command_sent_at = NULL,
                    last_command = %s,
                    last_result = %s,
                    updated_at = NOW()
                WHERE device_id = %s;
                """,
                (
                    new_status,
                    current_command,
                    result.message,
                    result.device_id,
                ),
            )

            conn.commit()

    return {
        "ok": True,
        "message": "Resultado de orden recibido",
        "device_id": result.device_id,
        "command_id": result.command_id,
        "status": new_status,
    }

@router.post("/order/reset")
def reset_order(device_id: str):
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE comedero_state
                SET
                pending_command = NULL,
                command_id = NULL,
                command_status = NULL,
                last_command = NULL,
                last_result = NULL,
                updated_at = NOW(),
                command_sent_at = NULL
                WHERE device_id = %s;
                """,
                (device_id,),
            )

            conn.commit()

    return {
        "ok": True,
        "message": "Estado restablecido",
    }