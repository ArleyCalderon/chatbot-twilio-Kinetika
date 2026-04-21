import time
import Core.db as db

# Caché en memoria
_settings_cache = None
_settings_cache_expires_at = 0

# TTL en segundos
SETTINGS_CACHE_TTL = 10


def _default_settings():
    return {
        "bot_active": True,
        "allow_only_existing_users": False,
        "bypass_schedule": False,
        "bot_inactive_message": (
            "Hola 👋\n"
            "Hoy no estamos atendiendo 😅\n"
            "Disculpa las molestias y gracias por tu paciencia 🙏\n"
            "Por favor escríbenos luego y con gusto te ayudamos."
        ),
        "existing_users_only_message": (
            "Hola 👋\n"
            "En este momento tenemos un alto flujo de mensajes y estamos priorizando solicitudes en curso.\n"
            "Por favor escríbenos más tarde. Gracias por tu comprensión 🙏"
        ),
        "outside_schedule_message": (
            "Hola 👋\n"
            "Nuestro horario de atención es *lunes a viernes de 8:00 a 18:00* (hora Colombia).\n"
            "Escríbenos dentro de ese horario y con gusto te atendemos 🙂"
        ),
    }


def _load_settings_from_db():
    try:
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        bot_active,
                        allow_only_existing_users,
                        bypass_schedule,
                        bot_inactive_message,
                        existing_users_only_message,
                        outside_schedule_message
                    FROM app_settings
                    ORDER BY id ASC
                    LIMIT 1;
                """)
                row = cur.fetchone()

        if not row:
            return _default_settings()

        defaults = _default_settings()

        return {
            "bot_active": row[0],
            "allow_only_existing_users": row[1],
            "bypass_schedule": row[2],
            "bot_inactive_message": row[3] or defaults["bot_inactive_message"],
            "existing_users_only_message": row[4] or defaults["existing_users_only_message"],
            "outside_schedule_message": row[5] or defaults["outside_schedule_message"],
        }
    except Exception:
        return _default_settings()


def get_runtime_settings(force_refresh: bool = False):
    global _settings_cache, _settings_cache_expires_at

    now = time.time()

    if (
        not force_refresh
        and _settings_cache is not None
        and now < _settings_cache_expires_at
    ):
        return _settings_cache

    settings = _load_settings_from_db()
    _settings_cache = settings
    _settings_cache_expires_at = now + SETTINGS_CACHE_TTL
    return settings


def clear_runtime_settings_cache():
    global _settings_cache, _settings_cache_expires_at
    _settings_cache = None
    _settings_cache_expires_at = 0