"""Caché efímero del último adjunto por chat.

Conserva el último adjunto como documento activo efímero del chat (15 minutos).
Puede reutilizarse en follow-ups documentales claros o en un envío cuando el
usuario lo pide explícitamente. Nunca se adjunta automáticamente a mensajes no
relacionados. No es persistencia documental y se pierde al reiniciar el proceso.
"""
from __future__ import annotations
import time

_CACHE: dict[int, tuple[float, object]] = {}
TTL_SECONDS = 15 * 60
MAX_ENTRIES = 32


def _podar() -> None:
    ahora = time.monotonic()
    vencidos = [chat_id for chat_id, (creado, _) in _CACHE.items() if ahora - creado > TTL_SECONDS]
    for chat_id in vencidos:
        _CACHE.pop(chat_id, None)
    if len(_CACHE) > MAX_ENTRIES:
        antiguos = sorted(_CACHE.items(), key=lambda item: item[1][0])
        for chat_id, _ in antiguos[: len(_CACHE) - MAX_ENTRIES]:
            _CACHE.pop(chat_id, None)


def guardar(chat_id: int, adjunto) -> None:
    _podar()
    if chat_id and adjunto:
        _CACHE[int(chat_id)] = (time.monotonic(), adjunto)
        _podar()


def obtener(chat_id: int):
    _podar()
    if not chat_id:
        return None
    item = _CACHE.get(int(chat_id))
    return item[1] if item else None


def limpiar(chat_id: int) -> None:
    if chat_id:
        _CACHE.pop(int(chat_id), None)
