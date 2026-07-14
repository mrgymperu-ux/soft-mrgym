"""Fecha y hora operativa de Soft-Gym.

La base existente usa DateTime sin zona horaria. Para mantener compatibilidad
entre Windows local y Render (UTC), todos los valores nuevos se guardan como
hora local de Lima sin tzinfo. La conversión explícita evita el desfase de
cinco horas en producción y el cambio de fecha después de las 19:00.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo


ZONA_LIMA = ZoneInfo("America/Lima")


def ahora_lima() -> datetime:
    """Devuelve la hora actual de Lima compatible con DateTime naive existente."""
    return datetime.now(ZONA_LIMA).replace(tzinfo=None)


def hoy_lima() -> date:
    """Devuelve la fecha calendario actual en Lima."""
    return datetime.now(ZONA_LIMA).date()
