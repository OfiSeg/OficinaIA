"""Infraestructura única de llamadas a Gemini para OficinaIA.

V20 etapa 1: centraliza fallback, cuota, deadline y logging sin cambiar los
prompts ni la lógica de dominio de cada módulo.

Principio: el modelo puede fallar; el request no debe quedar atrapado en
reintentos inútiles ni acercarse al timeout de Gunicorn por acumulación de
llamadas.
"""
from __future__ import annotations

import contextvars
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from google import genai
from google.genai import types


DEFAULT_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
)

# El timeout de cada llamada individual queda bastante por debajo del fusible
# de Gunicorn (180s). El presupuesto total del request se controla aparte.
SDK_TIMEOUT_MS = int(os.getenv("GEMINI_HTTP_TIMEOUT_MS", "30000"))
DEFAULT_REQUEST_BUDGET_SECONDS = float(os.getenv("GEMINI_REQUEST_BUDGET_SECONDS", "75"))
MIN_TIME_FOR_NEW_CALL_SECONDS = float(os.getenv("GEMINI_MIN_REMAINING_SECONDS", "3"))


class AIDeadlineExceeded(RuntimeError):
    pass


@dataclass
class AIRequestState:
    started_at: float = field(default_factory=time.monotonic)
    budget_seconds: float = DEFAULT_REQUEST_BUDGET_SECONDS
    disabled_models: set[str] = field(default_factory=set)
    calls: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def deadline(self) -> float:
        return self.started_at + self.budget_seconds

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


_request_state: contextvars.ContextVar[AIRequestState | None] = contextvars.ContextVar(
    "oficinaia_ai_request_state", default=None
)


def begin_request(budget_seconds: float | None = None) -> AIRequestState:
    """Inicia el estado efímero de IA para un request HTTP/operación.

    Debe llamarse una vez al comienzo de los endpoints que pueden usar IA.
    El estado vive sólo durante esa ejecución y no es memoria conversacional.
    """
    state = AIRequestState(
        budget_seconds=float(budget_seconds or DEFAULT_REQUEST_BUDGET_SECONDS)
    )
    _request_state.set(state)
    return state


def current_state() -> AIRequestState:
    state = _request_state.get()
    if state is None:
        state = begin_request()
    return state


def obtener_cliente_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=SDK_TIMEOUT_MS),
    )


def _es_429(error: Exception) -> bool:
    texto = str(error or "").upper()
    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    return (
        status_code == 429
        or code == 429
        or "429" in texto
        or "RESOURCE_EXHAUSTED" in texto
        or "TOO MANY REQUESTS" in texto
    )


def _assert_time_available(state: AIRequestState) -> None:
    restante = state.remaining()
    if restante <= MIN_TIME_FOR_NEW_CALL_SECONDS:
        raise AIDeadlineExceeded(
            f"Presupuesto interno de IA agotado; quedan {max(0.0, restante):.2f}s."
        )


def generate_with_fallback(
    *,
    contents: Any,
    config: Any,
    models: Iterable[str] | None = None,
    client: Any | None = None,
    log_prefix: str = "GEMINI",
):
    """Ejecuta Gemini con fallback y circuit breaker por request.

    Si un modelo devuelve 429, queda deshabilitado para el resto del request.
    No duerme esperando Retry-After y no hace retries ciegos del mismo modelo.
    Devuelve (respuesta, modelo_usado).
    """
    state = current_state()
    cliente = client or obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")

    candidatos = tuple(models or DEFAULT_MODELS)
    ultimo_error: Exception | None = None
    intento_real = False

    for modelo in candidatos:
        if modelo in state.disabled_models:
            print(f"{log_prefix} SKIP {modelo}: deshabilitado para este request")
            continue

        _assert_time_available(state)
        intento_real = True
        state.calls += 1
        try:
            respuesta = cliente.models.generate_content(
                model=modelo,
                contents=contents,
                config=config,
            )
            return respuesta, modelo
        except Exception as error:
            ultimo_error = error
            state.errors.append((modelo, str(error)))
            print(f"ERROR {log_prefix} {modelo} :", error)
            if _es_429(error):
                # Circuit breaker request-scoped: no volver a quemar tiempo/cuota
                # contra el mismo modelo en las siguientes vueltas del tool loop.
                state.disabled_models.add(modelo)

    if not intento_real and state.disabled_models:
        deshabilitados = ", ".join(sorted(state.disabled_models))
        raise RuntimeError(
            f"No quedan modelos habilitados para este request ({deshabilitados})."
        )
    if ultimo_error is not None:
        raise ultimo_error
    raise RuntimeError("No hay modelos Gemini disponibles para ejecutar la solicitud.")
