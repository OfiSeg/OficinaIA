"""Configuración de entorno de OficinaIA.

Esta capa NO persiste secretos ni reemplaza Render. Su objetivo es que todos los
servicios interpreten de la misma forma el entorno del proceso y que el .env
local se cargue una sola vez, sin poder pisar valores ya inyectados por Render.

Importante: las variables de Render forman parte del entorno DEL PROCESO. Si se
cambian desde el panel, un proceso que ya estaba corriendo no puede ver ese
cambio hasta reiniciarse/redeployarse. OficinaIA sí garantiza que, en el primer
arranque posterior, todos los consumidores lean la misma configuración.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
LOCAL_ENV_FILE = BASE_DIR / ".env"

# Render/entorno del proceso SIEMPRE tiene prioridad. En Render no se carga
# ningún .env del paquete. En desarrollo local, python-dotenv sólo completa
# variables ausentes y nunca sobreescribe el entorno del proceso.
if not str(os.environ.get("RENDER", "")).strip():
    load_dotenv(LOCAL_ENV_FILE, override=False)


@dataclass(frozen=True)
class EnvironmentValue:
    name: str
    state: str  # missing | empty | configured
    configured: bool


class EnvironmentConfigError(RuntimeError):
    def __init__(self, code: str, message: str, *, variable: str | None = None):
        super().__init__(message)
        self.code = str(code)
        self.variable = variable


def inspect_env(name: str) -> EnvironmentValue:
    """Inspecciona presencia sin devolver ni exponer el valor."""
    if name not in os.environ:
        return EnvironmentValue(name=name, state="missing", configured=False)
    if not str(os.environ.get(name, "")).strip():
        return EnvironmentValue(name=name, state="empty", configured=False)
    return EnvironmentValue(name=name, state="configured", configured=True)


def get_text(name: str, default: str | None = None, *, strip: bool = True) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip() if strip else value


def get_int(name: str, default: int) -> int:
    value = get_text(name)
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EnvironmentConfigError(
            "INVALID_ENV_VALUE",
            f"{name} no contiene un número entero válido.",
            variable=name,
        ) from exc


def get_float(name: str, default: float) -> float:
    value = get_text(name)
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise EnvironmentConfigError(
            "INVALID_ENV_VALUE",
            f"{name} no contiene un número válido.",
            variable=name,
        ) from exc


def require_text(
    name: str,
    *,
    missing_code: str = "MISSING_ENV",
    empty_code: str = "EMPTY_ENV",
    label: str | None = None,
) -> str:
    info = inspect_env(name)
    shown = label or name
    if info.state == "missing":
        raise EnvironmentConfigError(missing_code, f"Falta {shown}.", variable=name)
    if info.state == "empty":
        raise EnvironmentConfigError(empty_code, f"{shown} está configurada pero vacía.", variable=name)
    return str(os.environ[name]).strip()


def configured(names: Iterable[str]) -> bool:
    return all(inspect_env(name).configured for name in names)


def safe_environment_summary(names: Iterable[str]) -> dict[str, str]:
    """Devuelve sólo estado; jamás valores o secretos."""
    return {name: inspect_env(name).state for name in names}

# Variables reales encontradas en el proyecto. ``critical`` significa que una
# instalación de producción no debería arrancar sin ella; las demás degradan
# únicamente el servicio que las utiliza.
ENVIRONMENT_GROUPS = {
    "flask": ("FLASK_SECRET_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "google_sheets": ("SHEET_ID_ASEGURADOS", "GOOGLE_SHEETS_CREDENTIALS_JSON"),
    "google_sheets_flotas": ("SHEET_ID_FLOTAS", "GOOGLE_SHEETS_CREDENTIALS_JSON"),
    "database": ("DATABASE_URL",),
    "mail": ("GMAIL_SENDER_EMAIL", "GMAIL_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_SECRET", "GMAIL_OAUTH_REFRESH_TOKEN"),
    "storage": ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"),
}


def validate_environment(*, production: bool = False) -> dict:
    """Diagnóstico local de arranque, sin red y sin exponer valores."""
    services = {}
    for service, names in ENVIRONMENT_GROUPS.items():
        states = safe_environment_summary(names)
        missing = [n for n, state in states.items() if state == "missing"]
        empty = [n for n, state in states.items() if state == "empty"]
        services[service] = {
            "configured": not missing and not empty,
            "missing": missing,
            "empty": empty,
        }
    critical_errors = []
    if production and not services["flask"]["configured"]:
        critical_errors.append("FLASK_SECRET_KEY")
    return {"ok": not critical_errors, "critical_errors": critical_errors, "services": services}
