"""Estado conversacional efímero y acotado por chat.

Centraliza los contextos determinísticos que antes vivían como claves de sesión
independientes sin una política común de expiración. No guarda historial ni
contenido documental pesado; sólo estado operativo corto y explícito.
"""
from __future__ import annotations

import time
from typing import Any


DEFAULT_TTLS = {
    "arca_context": 5 * 60,
    "registro_contexto_activo": 5 * 60,
    "alta_activa": 15 * 60,
    "source_choice_pending": 5 * 60,
}

_META_SAVED = "_ctx_saved_at"
_META_EXPIRES = "_ctx_expires_at"


def _ahora() -> int:
    return int(time.time())


def guardar(session_obj, clave: str, payload: dict | None, *, chat_id=None, ttl_seconds: int | None = None) -> dict:
    """Guarda un contexto con chat_id + TTL serializable en Flask session."""
    dato = dict(payload or {})
    if chat_id is not None:
        dato["chat_id"] = str(chat_id or "")
    ttl = int(ttl_seconds or DEFAULT_TTLS.get(clave, 5 * 60))
    ahora = _ahora()
    dato[_META_SAVED] = ahora
    dato[_META_EXPIRES] = ahora + max(30, ttl)
    session_obj[clave] = dato
    return dato


def obtener(session_obj, clave: str, *, chat_id=None, tocar: bool = False, ttl_seconds: int | None = None) -> dict | None:
    """Devuelve sólo contexto vigente y del chat actual; limpia lo vencido."""
    dato = session_obj.get(clave)
    if not isinstance(dato, dict):
        if dato is not None:
            session_obj.pop(clave, None)
        return None

    if chat_id is not None and str(dato.get("chat_id") or "") != str(chat_id or ""):
        session_obj.pop(clave, None)
        return None

    expira = int(dato.get(_META_EXPIRES) or 0)
    if expira and _ahora() >= expira:
        session_obj.pop(clave, None)
        return None

    if tocar:
        limpio = {k: v for k, v in dato.items() if k not in {_META_SAVED, _META_EXPIRES}}
        return guardar(session_obj, clave, limpio, chat_id=chat_id, ttl_seconds=ttl_seconds)
    return dato


def limpiar(session_obj, clave: str) -> None:
    session_obj.pop(clave, None)


def podar(session_obj, *, chat_id=None) -> None:
    """Limpia contextos vencidos o pertenecientes a otro chat."""
    for clave in DEFAULT_TTLS:
        obtener(session_obj, clave, chat_id=chat_id)


def cambiar_fuente(session_obj, fuente: str) -> None:
    """Invalida estados incompatibles al confirmar una fuente determinística."""
    fuente = str(fuente or "").strip().upper()
    if fuente == "ARCA":
        limpiar(session_obj, "registro_contexto_activo")
    elif fuente == "CARTERA":
        limpiar(session_obj, "arca_context")


def sin_metadata(dato: dict | None) -> dict | None:
    if not isinstance(dato, dict):
        return dato
    return {k: v for k, v in dato.items() if k not in {_META_SAVED, _META_EXPIRES}}
