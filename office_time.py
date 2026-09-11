"""Fecha/hora de negocio para OficinaIA.

Los timestamps técnicos pueden seguir en UTC cuando corresponda. Este módulo
centraliza el concepto de "hoy" que ve la oficina/productor, evitando que un
servidor en UTC cambie de día antes que Argentina.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_OFFICE_TIMEZONE = "America/Argentina/Buenos_Aires"


def office_timezone():
    nombre = (os.environ.get("OFFICE_TIMEZONE") or DEFAULT_OFFICE_TIMEZONE).strip() or DEFAULT_OFFICE_TIMEZONE
    try:
        return ZoneInfo(nombre)
    except ZoneInfoNotFoundError:
        if nombre != DEFAULT_OFFICE_TIMEZONE:
            try:
                return ZoneInfo(DEFAULT_OFFICE_TIMEZONE)
            except ZoneInfoNotFoundError:
                pass
        # Fallback local/Windows sin tzdata: Argentina no usa horario de verano.
        return timezone(timedelta(hours=-3), name="ART")


def office_now() -> datetime:
    return datetime.now(office_timezone())


def office_today() -> date:
    return office_now().date()


def office_date_string(fmt: str = "%d/%m/%Y") -> str:
    return office_today().strftime(fmt)


def office_year() -> int:
    return office_today().year


def date_string(d: date, fmt: str = "%d/%m/%Y") -> str:
    return d.strftime(fmt)


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=int(days))
