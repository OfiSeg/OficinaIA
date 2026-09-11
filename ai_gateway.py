"""Infraestructura única de llamadas a Gemini para OficinaIA.

V20 etapa 1: centraliza fallback, cuota, deadline y logging sin cambiar los
prompts ni la lógica de dominio de cada módulo.

Principio: el modelo puede fallar; el request no debe quedar atrapado en
reintentos inútiles ni acercarse al timeout de Gunicorn por acumulación de
llamadas.
"""
from __future__ import annotations

import contextvars
import time

import runtime_config
from resilience import (
    describir_error_seguro,
    is_transient_error,
    registrar_evento_ia_seguro,
)
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
SDK_TIMEOUT_MS = runtime_config.get_int("GEMINI_HTTP_TIMEOUT_MS", 30000)
DEFAULT_REQUEST_BUDGET_SECONDS = runtime_config.get_float("GEMINI_REQUEST_BUDGET_SECONDS", 75.0)
MIN_TIME_FOR_NEW_CALL_SECONDS = runtime_config.get_float("GEMINI_MIN_REMAINING_SECONDS", 3.0)
AI_READ_ATTEMPTS = 3
AI_RETRY_DELAYS = (0.0, 0.8, 2.0)


class AIDeadlineExceeded(RuntimeError):
    pass


@dataclass
class AIRequestState:
    started_at: float = field(default_factory=time.monotonic)
    budget_seconds: float = DEFAULT_REQUEST_BUDGET_SECONDS
    request_id: str | None = None
    disabled_models: set[str] = field(default_factory=set)
    calls: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    sequence_counter: int = 0

    def next_sequence_id(self, operation: str) -> str:
        self.sequence_counter += 1
        prefix = self.request_id or "sin-request"
        op = str(operation or "gemini").lower().replace(" ", "_")[:40]
        return f"{prefix}:{op}:{self.sequence_counter}"

    @property
    def deadline(self) -> float:
        return self.started_at + self.budget_seconds

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


_request_state: contextvars.ContextVar[AIRequestState | None] = contextvars.ContextVar(
    "oficinaia_ai_request_state", default=None
)


def begin_request(budget_seconds: float | None = None, request_id: str | None = None) -> AIRequestState:
    """Inicia el estado efímero de IA para un request HTTP/operación.

    Debe llamarse una vez al comienzo de los endpoints que pueden usar IA.
    El estado vive sólo durante esa ejecución y no es memoria conversacional.
    Si se reinicia el presupuesto dentro del mismo request, conserva el
    request_id/correlación cuando el caller no envía uno nuevo.
    """
    previo = _request_state.get()
    state = AIRequestState(
        budget_seconds=float(budget_seconds or DEFAULT_REQUEST_BUDGET_SECONDS),
        request_id=str(request_id or getattr(previo, "request_id", "") or "") or None,
    )
    _request_state.set(state)
    return state


def current_state() -> AIRequestState:
    state = _request_state.get()
    if state is None:
        state = begin_request()
    return state


def obtener_cliente_gemini():
    api_key = runtime_config.get_text("GEMINI_API_KEY")
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


def _es_error_auth_permanente(error: Exception) -> bool:
    texto = str(error or "").upper()
    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    return (
        status_code in {401, 403}
        or code in {401, 403}
        or "API KEY INVALID" in texto
        or "INVALID API KEY" in texto
        or "UNAUTHENTICATED" in texto
        or "PERMISSION DENIED" in texto
    )


def _es_modelo_no_disponible(error: Exception) -> bool:
    texto = str(error or "").upper()
    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    return (
        status_code == 404
        or code == 404
        or "MODEL NOT FOUND" in texto
        or "MODEL_NOT_FOUND" in texto
        or "NOT SUPPORTED FOR GENERATECONTENT" in texto
    )




def _validar_respuesta_basica(respuesta: Any) -> None:
    """Detecta respuestas realmente vacías/truncadas sin romper tool calls."""
    from resilience import RecoverablePayloadError

    try:
        texto = str(getattr(respuesta, "text", "") or "").strip()
    except Exception:
        texto = ""
    candidates = list(getattr(respuesta, "candidates", None) or [])
    tiene_partes = False
    truncada = False
    for candidato in candidates:
        content = getattr(candidato, "content", None)
        parts = list(getattr(content, "parts", None) or []) if content is not None else []
        if parts:
            tiene_partes = True
        finish = str(getattr(candidato, "finish_reason", "") or "").upper()
        if "MAX_TOKENS" in finish or "LENGTH" in finish:
            truncada = True
    if truncada:
        raise RecoverablePayloadError("Respuesta truncada por límite de salida.")
    if not texto and not tiene_partes:
        raise RecoverablePayloadError("Respuesta vacía del proveedor.")

def generate_with_fallback(
    *,
    contents: Any,
    config: Any,
    models: Iterable[str] | None = None,
    client: Any | None = None,
    log_prefix: str = "GEMINI",
    response_validator: Any | None = None,
):
    """Llamada central resiliente de SOLO LECTURA a Gemini.

    Máximo tres intentos totales por operación, alternando los modelos
    configurados. Los mismos ``contents`` se reutilizan en cada intento, por lo
    que PDFs/imágenes/mensaje no deben ser reenviados por el usuario. Errores de
    autenticación/configuración fallan rápido. 429/5xx/timeouts se reintentan
    con backoff corto mientras quede presupuesto del request.
    """
    state = current_state()
    cliente = client or obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")

    candidatos = tuple(models or DEFAULT_MODELS)
    candidatos = tuple(m for m in candidatos if m not in state.disabled_models)
    if not candidatos:
        raise RuntimeError("No quedan modelos Gemini habilitados para este request.")

    ultimo_error: Exception | None = None
    intentos_realizados = 0
    indice_modelo = 0
    sequence_id = state.next_sequence_id(log_prefix)

    while intentos_realizados < AI_READ_ATTEMPTS and candidatos:
        try:
            _assert_time_available(state)
        except AIDeadlineExceeded as error:
            registrar_evento_ia_seguro(
                nivel="error",
                mensaje="IA no inició un nuevo intento por presupuesto/deadline",
                detalle=describir_error_seguro(
                    error, attempt=intentos_realizados + 1, attempts=AI_READ_ATTEMPTS,
                    sequence_id=sequence_id,
                ),
                codigo="AI_BUDGET_EXHAUSTED",
            )
            raise
        modelo = candidatos[indice_modelo % len(candidatos)]
        indice_modelo += 1
        intentos_realizados += 1
        state.calls += 1
        inicio = time.monotonic()
        try:
            respuesta = cliente.models.generate_content(
                model=modelo,
                contents=contents,
                config=config,
            )
            _validar_respuesta_basica(respuesta)
            if response_validator is not None:
                try:
                    response_validator(respuesta)
                except Exception as validation_error:
                    from resilience import RecoverablePayloadError
                    if isinstance(validation_error, RecoverablePayloadError):
                        raise
                    raise RecoverablePayloadError(str(validation_error)) from validation_error
            if intentos_realizados > 1:
                detalle = (
                    f"operation={log_prefix} | provider=gemini | "
                    f"modelo={modelo} | intento={intentos_realizados}/{AI_READ_ATTEMPTS} | "
                    f"secuencia={sequence_id}"
                )
                print(
                    f"RESILIENCIA operation={log_prefix} provider=gemini "
                    f"recovered_on_attempt={intentos_realizados} model={modelo} sequence={sequence_id}"
                )
                registrar_evento_ia_seguro(
                    nivel="ok",
                    mensaje=f"IA recuperada correctamente en intento {intentos_realizados}/{AI_READ_ATTEMPTS}",
                    detalle=detalle,
                    codigo="AI_RECOVERED",
                )
            return respuesta, modelo
        except Exception as error:
            ultimo_error = error
            state.errors.append((modelo, str(error)))
            duracion = time.monotonic() - inicio
            detalle_error = describir_error_seguro(
                error,
                model=modelo,
                attempt=intentos_realizados,
                attempts=AI_READ_ATTEMPTS,
                duration_seconds=duracion,
                sequence_id=sequence_id,
            )
            print(
                f"ERROR {log_prefix} model={modelo} attempt={intentos_realizados}/{AI_READ_ATTEMPTS} "
                f"duration={duracion:.2f}s error={detalle_error}"
            )

            if _es_error_auth_permanente(error):
                registrar_evento_ia_seguro(
                    nivel="error",
                    mensaje="IA falló por autenticación/configuración",
                    detalle=detalle_error,
                    codigo="AI_FINAL_FAILURE",
                )
                raise

            if _es_modelo_no_disponible(error):
                registrar_evento_ia_seguro(
                    nivel="aviso",
                    mensaje="Modelo de IA no disponible; se intentará fallback si existe",
                    detalle=detalle_error,
                    codigo="AI_MODEL_UNAVAILABLE",
                )
                state.disabled_models.add(modelo)
                candidatos = tuple(m for m in candidatos if m != modelo)
                indice_modelo = 0
                if not candidatos:
                    break
                continue

            if not is_transient_error(error):
                # Error no clasificado como transitorio: permitir fallback a un
                # modelo distinto una sola vez, pero no repetir ciegamente el
                # mismo proveedor hasta agotar presupuesto.
                if len(candidatos) > 1 and intentos_realizados < AI_READ_ATTEMPTS:
                    continue
                registrar_evento_ia_seguro(
                    nivel="error",
                    mensaje="IA falló por una causa no recuperable",
                    detalle=detalle_error,
                    codigo="AI_FINAL_FAILURE",
                )
                raise

            if intentos_realizados >= AI_READ_ATTEMPTS:
                registrar_evento_ia_seguro(
                    nivel="error",
                    mensaje=f"IA agotó {AI_READ_ATTEMPTS}/{AI_READ_ATTEMPTS} intentos; operación no completada",
                    detalle=detalle_error,
                    codigo="AI_RETRIES_EXHAUSTED",
                )
                break

            delay = AI_RETRY_DELAYS[min(intentos_realizados, len(AI_RETRY_DELAYS) - 1)]
            if state.remaining() <= delay + MIN_TIME_FOR_NEW_CALL_SECONDS:
                registrar_evento_ia_seguro(
                    nivel="error",
                    mensaje="IA no pudo reintentar por presupuesto/deadline",
                    detalle=detalle_error,
                    codigo="AI_BUDGET_EXHAUSTED",
                )
                break
            registrar_evento_ia_seguro(
                nivel="aviso",
                mensaje=f"Fallo temporal de IA absorbido; reintento {intentos_realizados + 1}/{AI_READ_ATTEMPTS}",
                detalle=detalle_error,
                codigo="AI_TRANSIENT_RETRY",
            )
            time.sleep(delay)

    if ultimo_error is not None:
        raise ultimo_error
    final = RuntimeError("No hay modelos Gemini disponibles para ejecutar la solicitud.")
    registrar_evento_ia_seguro(
        nivel="error",
        mensaje="No hay modelos Gemini disponibles para ejecutar la solicitud",
        detalle=f"operation={log_prefix} | sequence={sequence_id}",
        codigo="AI_MODEL_UNAVAILABLE",
    )
    raise final
