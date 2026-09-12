"""Resiliencia central para operaciones idempotentes de lectura de OficinaIA.

Esta capa NO debe usarse para escrituras, envíos ni acciones con efectos reales.
Centraliza clasificación de fallos transitorios, backoff corto, logging seguro y
recuperación local de JSON sin inventar datos.
"""
from __future__ import annotations

import ast
import json
import re
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_DELAYS = (0.0, 0.8, 2.0)
TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
PERMANENT_STATUS = {400, 401, 403, 404, 405, 413, 415, 422}


class RecoverablePayloadError(ValueError):
    """Respuesta recibida pero estructuralmente recuperable/reintentable."""


@dataclass(frozen=True)
class RetryInfo:
    operation: str
    provider: str
    attempt: int
    attempts: int


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        try:
            if value is not None and str(value).isdigit():
                return int(value)
        except Exception:
            pass
    resp = getattr(exc, "resp", None)
    try:
        if resp is not None and getattr(resp, "status", None) is not None:
            return int(resp.status)
    except Exception:
        pass
    return None


def is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, RecoverablePayloadError):
        return True
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionError, ConnectionResetError, BrokenPipeError)):
        return True
    status = _status_code(exc)
    if status in TRANSIENT_STATUS:
        return True
    if status in PERMANENT_STATUS:
        return False
    text = str(exc or "").upper()
    transient_tokens = (
        "TIMEOUT", "TIMED OUT", "TEMPORAR", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
        "TOO MANY REQUESTS", "RATE LIMIT", "CONNECTION RESET", "CONNECTION CLOSED",
        "CONNECTION ABORTED", "SERVER ERROR", "INTERNAL ERROR", "BAD GATEWAY",
        "SERVICE UNAVAILABLE", "GATEWAY TIMEOUT", "EMPTY RESPONSE", "TRUNCATED RESPONSE",
    )
    permanent_tokens = (
        "API KEY INVALID", "INVALID API KEY", "PERMISSION DENIED", "UNAUTHENTICATED",
        "MISSING_", "FALTA GEMINI_API_KEY", "FALTA LA VARIABLE", "CREDENTIAL", "FILE TOO LARGE",
        "ARCHIVO DEMASIADO GRANDE", "UNSUPPORTED", "NO EXISTE", "NOT FOUND",
    )
    if any(token in text for token in permanent_tokens):
        return False
    return any(token in text for token in transient_tokens)


def _motivo_error(exc: Exception) -> str | None:
    """Extrae un motivo técnico breve sin inventarlo ni volcar el mensaje completo."""
    for attr in ("reason", "error_code", "error", "grpc_status"):
        try:
            value = getattr(exc, attr, None)
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
        if value is not None and not isinstance(value, (dict, list, tuple)):
            text = str(value).strip()
            if text:
                return text[:80]
    text = str(exc or "").upper()
    for token in (
        "UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "TIMEOUT",
        "TIMED OUT", "INTERNAL", "BAD GATEWAY", "SERVICE UNAVAILABLE",
        "GATEWAY TIMEOUT", "UNAUTHENTICATED", "PERMISSION_DENIED",
        "PERMISSION DENIED", "MODEL_NOT_FOUND", "MODEL NOT FOUND",
    ):
        if token in text:
            return token
    return None




def clasificar_error_ia(exc: Exception) -> str:
    """Clasificación técnica estable para diagnóstico de IA, sin exponer payloads."""
    if isinstance(exc, RecoverablePayloadError):
        return "INVALID_RESPONSE"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "TIMEOUT"
    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError)):
        return "NETWORK_ERROR"
    status = _status_code(exc)
    texto = str(exc or "").upper()
    if status == 429 or "RESOURCE_EXHAUSTED" in texto or "RATE LIMIT" in texto or "TOO MANY REQUESTS" in texto:
        return "RATE_LIMIT"
    if status in {500, 502, 503, 504, 520, 521, 522, 523, 524} or "UNAVAILABLE" in texto or "SERVICE UNAVAILABLE" in texto:
        return "SERVICE_UNAVAILABLE"
    if status in {401, 403} or "UNAUTHENTICATED" in texto or "PERMISSION DENIED" in texto or "INVALID API KEY" in texto:
        return "AUTH_ERROR"
    if status == 404 or "MODEL_NOT_FOUND" in texto or "MODEL NOT FOUND" in texto:
        return "MODEL_UNAVAILABLE"
    if "JSON" in texto and ("INVALID" in texto or "PARSE" in texto or "TRUNC" in texto):
        return "JSON_ERROR"
    if "TIMEOUT" in texto or "TIMED OUT" in texto or "DEADLINE_EXCEEDED" in texto:
        return "TIMEOUT"
    if status is not None and 400 <= status < 500:
        return "REQUEST_ERROR"
    return "INTERNAL_APP_ERROR"

def describir_error_seguro(
    exc: Exception,
    *,
    model: str | None = None,
    attempt: int | None = None,
    attempts: int | None = None,
    duration_seconds: float | None = None,
    sequence_id: str | None = None,
) -> str:
    """Detalle técnico mínimo para logs, sin prompts, documentos ni secretos."""
    partes = [type(exc).__name__, f"categoria={clasificar_error_ia(exc)}"]
    code = _status_code(exc)
    motivo = _motivo_error(exc)
    if code is not None:
        partes.append(f"status={code}")
    if motivo:
        partes.append(f"motivo={motivo}")
    if model:
        partes.append(f"modelo={model}")
    if attempt is not None and attempts is not None:
        partes.append(f"intento={attempt}/{attempts}")
    elif attempt is not None:
        partes.append(f"intento={attempt}")
    if duration_seconds is not None:
        try:
            partes.append(f"duracion={float(duration_seconds):.2f}s")
        except Exception:
            pass
    if sequence_id:
        partes.append(f"secuencia={sequence_id}")
    return " | ".join(partes)


def registrar_evento_ia_seguro(
    *,
    nivel: str,
    mensaje: str,
    codigo: str,
    detalle: str | None = None,
) -> None:
    """Registra eventos de IA sin permitir que Salud rompa el flujo principal."""
    try:
        import system_health
        system_health.registrar_evento("ia", nivel, mensaje, detalle, codigo=codigo)
    except Exception:
        pass


def _log_retry(operation: str, provider: str, attempt: int, attempts: int, exc: Exception) -> None:
    safe_error = describir_error_seguro(exc, attempt=attempt, attempts=attempts)
    print(f"RESILIENCIA operation={operation} provider={provider} attempt={attempt}/{attempts} error={safe_error}")
    registrar_evento_ia_seguro(
        nivel="aviso",
        mensaje=f"Fallo temporal de IA absorbido; reintento {attempt + 1}/{attempts}",
        detalle=f"operation={operation} | provider={provider} | {safe_error}",
        codigo="AI_TRANSIENT_RETRY",
    )


def _log_recovered(operation: str, provider: str, attempt: int) -> None:
    if attempt > 1:
        msg = f"RESILIENCIA operation={operation} provider={provider} recovered_on_attempt={attempt}"
        print(msg)
        registrar_evento_ia_seguro(
            nivel="ok",
            mensaje=f"IA recuperada correctamente en intento {attempt}",
            detalle=f"operation={operation} | provider={provider} | intento={attempt}",
            codigo="AI_RECOVERED",
        )


def call_read_with_resilience(
    func: Callable[[], T],
    *,
    operation: str,
    provider: str,
    attempts: int = DEFAULT_ATTEMPTS,
    delays: Iterable[float] = DEFAULT_DELAYS,
    retry_if: Callable[[Exception], bool] | None = None,
    remaining_seconds: Callable[[], float] | None = None,
    min_remaining_seconds: float = 3.0,
) -> T:
    """Ejecuta una operación de SOLO LECTURA con hasta 3 intentos.

    El callable debe ser idempotente y no producir efectos secundarios. Errores
    permanentes fallan inmediatamente. Los reintentos reutilizan el mismo cierre,
    por lo que mensaje, bytes, imágenes y parámetros permanecen disponibles.
    """
    attempts = max(1, min(int(attempts or 1), 3))
    delays = tuple(float(x) for x in delays) or DEFAULT_DELAYS
    should_retry = retry_if or is_transient_error
    last: Exception | None = None

    for idx in range(attempts):
        attempt = idx + 1
        if idx:
            delay = delays[min(idx, len(delays) - 1)]
            if remaining_seconds is not None:
                try:
                    if remaining_seconds() <= delay + min_remaining_seconds:
                        break
                except Exception:
                    pass
            if delay > 0:
                time.sleep(delay)
        try:
            result = func()
            _log_recovered(operation, provider, attempt)
            return result
        except Exception as exc:
            last = exc
            retryable = bool(should_retry(exc))
            if not retryable:
                registrar_evento_ia_seguro(
                    nivel="error",
                    mensaje="IA falló por una causa no recuperable",
                    detalle=f"operation={operation} | provider={provider} | " + describir_error_seguro(exc, attempt=attempt, attempts=attempts),
                    codigo="AI_FINAL_FAILURE",
                )
                raise
            if attempt >= attempts:
                registrar_evento_ia_seguro(
                    nivel="error",
                    mensaje=f"IA agotó {attempts}/{attempts} intentos; operación no completada",
                    detalle=f"operation={operation} | provider={provider} | " + describir_error_seguro(exc, attempt=attempt, attempts=attempts),
                    codigo="AI_RETRIES_EXHAUSTED",
                )
                raise
            _log_retry(operation, provider, attempt, attempts, exc)

    if last is not None:
        registrar_evento_ia_seguro(
            nivel="error",
            mensaje="IA no pudo completar la operación por presupuesto/deadline",
            detalle=f"operation={operation} | provider={provider} | " + describir_error_seguro(last, attempt=attempt if 'attempt' in locals() else None, attempts=attempts),
            codigo="AI_BUDGET_EXHAUSTED",
        )
        raise last
    raise RuntimeError(f"{operation} no pudo ejecutarse.")


def _extract_json_object(text: str) -> str:
    s = str(text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I)
    if not s:
        raise RecoverablePayloadError("Respuesta JSON vacía.")
    start = s.find("{")
    if start < 0:
        raise RecoverablePayloadError("No se encontró un objeto JSON.")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    raise RecoverablePayloadError("Objeto JSON truncado.")


def parse_json_object(text: Any) -> dict:
    """Recupera JSON de respuestas del modelo sin completar ni inventar campos."""
    raw = str(text or "").strip()
    candidates: list[str] = []
    if raw:
        candidates.append(raw)
    try:
        extracted = _extract_json_object(raw)
        if extracted not in candidates:
            candidates.append(extracted)
    except RecoverablePayloadError:
        extracted = ""

    for candidate in candidates:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate.strip(), flags=re.I)
        variants = [cleaned]
        # Reparaciones puramente sintácticas: trailing commas y comillas simples
        # mediante literal_eval. No se agregan claves ni valores.
        no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
        if no_trailing != cleaned:
            variants.append(no_trailing)
        for variant in variants:
            try:
                value = json.loads(variant)
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
            try:
                value = ast.literal_eval(variant)
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
    raise RecoverablePayloadError("La respuesta no contiene JSON utilizable.")
