"""Fuente activa de los libros internos de OficinaIA: Google Sheets.

Mantiene el contrato histórico de OfficeDocumentsService:
    {"hoja": str, "filas": list[list[str]], "columnas": int}
La fila 0 de ``filas`` contiene los encabezados.

La configuración se lee siempre desde ``runtime_config``. Los errores se
clasifican con códigos estables y sólo los fallos transitorios se reintentan.
"""
from __future__ import annotations

import json
import socket
import time
from functools import lru_cache
from typing import Iterable

from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from excel_books import obtener_catalogo_libros
import runtime_config
from resilience import call_read_with_resilience

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
MAX_COLUMNS = 30
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}


class SheetsServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.code = str(code)
        self.cause = cause


def _book_id(libro_id: str = "1") -> str:
    libro_id = str(libro_id or "1")
    if libro_id not in obtener_catalogo_libros():
        raise ValueError("Libro de Excel no válido.")
    return libro_id


def _sheet_env_name(libro_id: str) -> str:
    libro_id = _book_id(libro_id)
    return str(obtener_catalogo_libros()[libro_id]["sheet_env"])


def _spreadsheet_id(libro_id: str) -> str:
    env_name = _sheet_env_name(libro_id)
    try:
        return runtime_config.require_text(
            env_name,
            missing_code="MISSING_SHEET_ID",
            empty_code="EMPTY_SHEET_ID",
            label=env_name,
        )
    except runtime_config.EnvironmentConfigError as exc:
        raise SheetsServiceError(exc.code, str(exc), cause=exc) from exc


def _credentials_info() -> dict:
    try:
        raw = runtime_config.require_text(
            "GOOGLE_SHEETS_CREDENTIALS_JSON",
            missing_code="MISSING_GOOGLE_CREDENTIALS",
            empty_code="EMPTY_GOOGLE_CREDENTIALS",
            label="GOOGLE_SHEETS_CREDENTIALS_JSON",
        )
    except runtime_config.EnvironmentConfigError as exc:
        raise SheetsServiceError(exc.code, str(exc), cause=exc) from exc
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SheetsServiceError(
            "INVALID_GOOGLE_CREDENTIALS",
            "GOOGLE_SHEETS_CREDENTIALS_JSON no contiene JSON válido.",
            cause=exc,
        ) from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise SheetsServiceError(
            "INVALID_GOOGLE_CREDENTIALS",
            "GOOGLE_SHEETS_CREDENTIALS_JSON debe corresponder a una cuenta de servicio.",
        )
    return info


def validate_credentials_configuration() -> None:
    """Valida sólo forma/configuración local; no llama a Google."""
    info = _credentials_info()
    try:
        Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception as exc:
        raise SheetsServiceError(
            "INVALID_GOOGLE_CREDENTIALS",
            "Las credenciales de Google Sheets no son válidas.",
            cause=exc,
        ) from exc


@lru_cache(maxsize=1)
def _service():
    try:
        creds = Credentials.from_service_account_info(_credentials_info(), scopes=SCOPES)
        return build("sheets", "v4", credentials=creds, cache_discovery=False)
    except SheetsServiceError:
        raise
    except (GoogleAuthError, ValueError, TypeError) as exc:
        raise SheetsServiceError(
            "INVALID_GOOGLE_CREDENTIALS",
            "No se pudieron inicializar las credenciales de Google Sheets.",
            cause=exc,
        ) from exc


def reset_service_cache() -> None:
    """Útil para tests o cambios de credenciales durante desarrollo."""
    _service.cache_clear()


def _http_status(exc: Exception) -> int | None:
    if isinstance(exc, HttpError):
        try:
            return int(exc.resp.status)
        except Exception:
            return None
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _map_error(exc: Exception, *, operation: str = "read") -> SheetsServiceError:
    if isinstance(exc, SheetsServiceError):
        return exc
    status = _http_status(exc)
    text = str(exc or "").upper()
    if status == 403:
        return SheetsServiceError("SHEET_PERMISSION_DENIED", "Google rechazó el acceso a la planilla.", cause=exc)
    if status == 404:
        return SheetsServiceError("SHEET_NOT_FOUND", "La planilla configurada no existe o no es accesible.", cause=exc)
    if status == 401:
        return SheetsServiceError("INVALID_GOOGLE_CREDENTIALS", "Google rechazó las credenciales configuradas.", cause=exc)
    if status == 429:
        return SheetsServiceError("GOOGLE_API_RATE_LIMIT", "Google Sheets está temporalmente limitado por cuota.", cause=exc)
    if status in {500, 502, 503, 504}:
        return SheetsServiceError("GOOGLE_API_TEMPORARY", "Google Sheets está temporalmente no disponible.", cause=exc)
    if isinstance(exc, (TimeoutError, socket.timeout)) or "TIMEOUT" in text or "TIMED OUT" in text:
        return SheetsServiceError("SHEET_TIMEOUT", "Google Sheets no respondió a tiempo.", cause=exc)
    if "UNABLE TO PARSE RANGE" in text or "RANGE" in text and "NOT FOUND" in text:
        return SheetsServiceError("WORKSHEET_NOT_FOUND", "No se encontró la hoja esperada dentro de la planilla.", cause=exc)
    return SheetsServiceError(
        "SHEET_READ_ERROR" if operation == "read" else "GOOGLE_API_ERROR",
        "No se pudo leer Google Sheets." if operation == "read" else "No se pudo completar la operación en Google Sheets.",
        cause=exc,
    )


def _execute(request, *, operation: str = "read", attempts: int | None = None):
    """Ejecuta una request de Google con resiliencia sólo para lecturas.

    Las escrituras permanecen en un único intento para evitar duplicados. La
    clasificación de errores conserva los códigos propios de Sheets.
    """
    if operation != "read":
        try:
            return request.execute()
        except Exception as exc:
            raise _map_error(exc, operation=operation) from exc

    max_attempts = 3 if attempts is None else max(1, min(int(attempts), 3))

    def invoke():
        try:
            return request.execute()
        except Exception as exc:
            raise _map_error(exc, operation="read") from exc

    def retry_if(exc: Exception) -> bool:
        return isinstance(exc, SheetsServiceError) and exc.code in {
            "GOOGLE_API_RATE_LIMIT",
            "GOOGLE_API_TEMPORARY",
            "SHEET_TIMEOUT",
        }

    return call_read_with_resilience(
        invoke,
        operation="google_sheets_read",
        provider="google_sheets",
        attempts=max_attempts,
        delays=(0.0, 0.5, 1.2),
        retry_if=retry_if,
    )

def _sheet_title(spreadsheet_id: str, preferred: str | None = None) -> str:
    meta = _execute(
        _service().spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(title,index)",
        ),
        operation="read",
    )
    sheets = sorted(meta.get("sheets") or [], key=lambda x: x.get("properties", {}).get("index", 0))
    if not sheets:
        raise SheetsServiceError("WORKSHEET_NOT_FOUND", "La planilla de Google Sheets no tiene hojas.")
    titles = [str(x.get("properties", {}).get("title") or "") for x in sheets]
    preferred = str(preferred or "").strip()
    if preferred and preferred in titles:
        return preferred
    return titles[0]


def _quote_sheet(title: str) -> str:
    return "'" + str(title).replace("'", "''") + "'"


def _normalizar_matriz(filas: Iterable[Iterable[object]]) -> list[list[str]]:
    out: list[list[str]] = []
    for fila in filas or []:
        valores = ["" if v is None else str(v) for v in list(fila)[:MAX_COLUMNS]]
        out.append(valores)
    while out and not any(str(v).strip() for v in out[-1]):
        out.pop()
    columnas = max(1, min(max((len(f) for f in out), default=1), MAX_COLUMNS))
    return [f[:columnas] + [""] * (columnas - len(f)) for f in out]


def check_connection(libro_id: str = "1") -> dict:
    """Health check mínimo: auth, planilla, hoja y lectura de una celda."""
    libro_id = _book_id(libro_id)
    spreadsheet_id = _spreadsheet_id(libro_id)
    validate_credentials_configuration()
    title = _sheet_title(spreadsheet_id)
    _execute(
        _service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet(title)}!A1:A1",
            majorDimension="ROWS",
            valueRenderOption="FORMATTED_VALUE",
        ),
        operation="read",
    )
    return {
        "checks": [
            {"label": "Autenticación", "ok": True, "detail": "Correcta"},
            {"label": "Planilla", "ok": True, "detail": "Accesible"},
            {"label": "Hoja", "ok": True, "detail": "Detectada"},
            {"label": "Lectura", "ok": True, "detail": "Correcta"},
        ]
    }


def leer_excel(libro_id: str = "1") -> dict:
    libro_id = _book_id(libro_id)
    spreadsheet_id = _spreadsheet_id(libro_id)
    title = _sheet_title(spreadsheet_id)
    result = _execute(
        _service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=_quote_sheet(title),
            majorDimension="ROWS",
            valueRenderOption="FORMATTED_VALUE",
        ),
        operation="read",
    )
    filas = _normalizar_matriz(result.get("values") or [])
    columnas = max(1, min(max((len(f) for f in filas), default=1), MAX_COLUMNS))
    filas = [f[:columnas] + [""] * (columnas - len(f)) for f in filas]
    return {"hoja": title, "filas": filas, "columnas": columnas}


def guardar_excel(filas: list[list[str]], nombre_hoja: str = "Datos", libro_id: str = "1") -> None:
    libro_id = _book_id(libro_id)
    spreadsheet_id = _spreadsheet_id(libro_id)
    title = _sheet_title(spreadsheet_id, nombre_hoja)
    matriz = _normalizar_matriz(filas)
    range_all = _quote_sheet(title)
    svc = _service().spreadsheets().values()
    _execute(svc.clear(spreadsheetId=spreadsheet_id, range=range_all, body={}), operation="write")
    if matriz:
        _execute(
            svc.batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": [{
                        "range": f"{_quote_sheet(title)}!A1",
                        "majorDimension": "ROWS",
                        "values": matriz,
                    }],
                },
            ),
            operation="write",
        )


def agregar_filas(filas: list[list[str]], libro_id: str = "1", nombre_hoja: str | None = None) -> int:
    libro_id = _book_id(libro_id)
    matriz = _normalizar_matriz(filas)
    if not matriz:
        return 0
    spreadsheet_id = _spreadsheet_id(libro_id)
    title = _sheet_title(spreadsheet_id, nombre_hoja)
    _execute(
        _service().spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_sheet(title)}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"majorDimension": "ROWS", "values": matriz},
        ),
        operation="write",
    )
    return len(matriz)
