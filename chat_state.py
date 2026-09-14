"""Estado conversacional efímero y acotado por chat.

Centraliza contextos determinísticos con TTL. Cada conversación conserva su
propio estado operativo; cambiar de chat nunca borra el estado de otro chat.
"""
from __future__ import annotations

import time


DEFAULT_TTLS = {
    "arca_context": 5 * 60,
    "registro_contexto_activo": 5 * 60,
    "alta_activa": 15 * 60,
}

_META_SAVED = "_ctx_saved_at"
_META_EXPIRES = "_ctx_expires_at"
_STORE_KEY = "_chat_contexts_v2"
_GLOBAL_CHAT = "__global__"


def _ahora() -> int:
    return int(time.time())


def _chat_key(chat_id) -> str:
    return str(chat_id) if chat_id is not None else _GLOBAL_CHAT


def _store(session_obj) -> dict:
    value = session_obj.get(_STORE_KEY)
    if not isinstance(value, dict):
        value = {}
        session_obj[_STORE_KEY] = value
    return value


def _persist(session_obj, store: dict) -> None:
    # Flask session detecta mejor la mutación cuando se reasigna el objeto.
    session_obj[_STORE_KEY] = store


def guardar(session_obj, clave: str, payload: dict | None, *, chat_id=None, ttl_seconds: int | None = None) -> dict:
    """Guarda contexto con TTL dentro del espacio del chat indicado."""
    dato = dict(payload or {})
    if chat_id is not None:
        dato["chat_id"] = str(chat_id or "")
    ttl = int(ttl_seconds or DEFAULT_TTLS.get(clave, 5 * 60))
    ahora = _ahora()
    dato[_META_SAVED] = ahora
    dato[_META_EXPIRES] = ahora + max(30, ttl)

    store = _store(session_obj)
    key = _chat_key(chat_id)
    bucket = dict(store.get(key) or {})
    bucket[clave] = dato
    store[key] = bucket
    _persist(session_obj, store)

    # Limpieza de la representación legacy de la misma clave. No migramos un
    # contexto de otro chat porque sería justamente contaminación entre chats.
    session_obj.pop(clave, None)
    return dato


def obtener(session_obj, clave: str, *, chat_id=None, tocar: bool = False, ttl_seconds: int | None = None) -> dict | None:
    """Devuelve contexto vigente del chat sin destruir estados de otros chats."""
    store = _store(session_obj)
    key = _chat_key(chat_id)
    bucket = dict(store.get(key) or {})
    dato = bucket.get(clave)

    # Migración conservadora de una sesión legacy únicamente si pertenece al
    # chat solicitado (o no había chat_id en una llamada global).
    if not isinstance(dato, dict):
        legacy = session_obj.get(clave)
        legacy_chat = str((legacy or {}).get("chat_id") or "") if isinstance(legacy, dict) else ""
        if isinstance(legacy, dict) and (chat_id is None or legacy_chat == str(chat_id or "")):
            dato = dict(legacy)
            bucket[clave] = dato
            store[key] = bucket
            _persist(session_obj, store)
            session_obj.pop(clave, None)

    if not isinstance(dato, dict):
        return None

    expira = int(dato.get(_META_EXPIRES) or 0)
    if expira and _ahora() >= expira:
        bucket.pop(clave, None)
        if bucket:
            store[key] = bucket
        else:
            store.pop(key, None)
        _persist(session_obj, store)
        return None

    if tocar:
        limpio = {k: v for k, v in dato.items() if k not in {_META_SAVED, _META_EXPIRES}}
        return guardar(session_obj, clave, limpio, chat_id=chat_id, ttl_seconds=ttl_seconds)
    return dato


def limpiar(session_obj, clave: str, *, chat_id=None) -> None:
    """Limpia una clave sólo del chat solicitado; sin chat_id limpia todas."""
    store = _store(session_obj)
    if chat_id is None:
        for key in list(store):
            bucket = dict(store.get(key) or {})
            bucket.pop(clave, None)
            if bucket:
                store[key] = bucket
            else:
                store.pop(key, None)
        session_obj.pop(clave, None)
    else:
        key = _chat_key(chat_id)
        bucket = dict(store.get(key) or {})
        bucket.pop(clave, None)
        if bucket:
            store[key] = bucket
        else:
            store.pop(key, None)
        legacy = session_obj.get(clave)
        if isinstance(legacy, dict) and str(legacy.get("chat_id") or "") == str(chat_id or ""):
            session_obj.pop(clave, None)
    _persist(session_obj, store)


def podar(session_obj, *, chat_id=None) -> None:
    """Limpia contextos vencidos de todos los chats sin tocar los vigentes.

    La sesión de Flask puede viajar en cookie. Si sólo podáramos el chat que se
    está visitando, los buckets vencidos de conversaciones antiguas quedarían
    acumulados indefinidamente. Por eso la expiración se barre globalmente,
    pero nunca se elimina estado vigente por cambiar de conversación.
    """
    store = _store(session_obj)
    ahora = _ahora()
    cambio = False

    for key in list(store):
        bucket = dict(store.get(key) or {})
        for clave, dato in list(bucket.items()):
            if not isinstance(dato, dict):
                continue
            expira = int(dato.get(_META_EXPIRES) or 0)
            if expira and ahora >= expira:
                bucket.pop(clave, None)
                cambio = True

        if bucket:
            store[key] = bucket
        else:
            store.pop(key, None)
            cambio = True

    if cambio:
        _persist(session_obj, store)

    # Conserva la migración legacy para el chat efectivamente solicitado, sin
    # reactivar ni inspeccionar estados ajenos que todavía estén vigentes.
    if chat_id is not None:
        for clave in DEFAULT_TTLS:
            obtener(session_obj, clave, chat_id=chat_id)


def cambiar_fuente(session_obj, fuente: str, *, chat_id=None) -> None:
    """Invalida estados incompatibles únicamente dentro del chat actual."""
    fuente = str(fuente or "").strip().upper()
    if fuente == "ARCA":
        limpiar(session_obj, "registro_contexto_activo", chat_id=chat_id)
    elif fuente == "CARTERA":
        limpiar(session_obj, "arca_context", chat_id=chat_id)


def sin_metadata(dato: dict | None) -> dict | None:
    if not isinstance(dato, dict):
        return dato
    return {k: v for k, v in dato.items() if k not in {_META_SAVED, _META_EXPIRES}}
