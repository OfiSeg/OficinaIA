"""Fuente única de los libros internos de OficinaIA: Google Sheets.

Mantiene el contrato histórico de OfficeDocumentsService:
    {"hoja": str, "filas": list[list[str]], "columnas": int}
La fila 0 de ``filas`` contiene los encabezados.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Iterable

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from excel_books import obtener_libros_excel

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
MAX_COLUMNS = 30


def _book_id(libro_id: str = "1") -> str:
    libro_id = str(libro_id or "1")
    if libro_id not in obtener_libros_excel():
        raise ValueError("Libro de Excel no válido.")
    return libro_id


def _spreadsheet_id(libro_id: str) -> str:
    libro_id = _book_id(libro_id)
    libro = obtener_libros_excel()[libro_id]
    value = str(libro.get("sheet_id") or "").strip()
    if not value:
        env_name = "SHEET_ID_ASEGURADOS" if libro_id == "1" else "SHEET_ID_FLOTAS"
        raise RuntimeError(f"Falta la variable de entorno {env_name}.")
    return value


def _credentials_info() -> dict:
    raw = (os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON") or "").strip()
    if not raw:
        raise RuntimeError("Falta GOOGLE_SHEETS_CREDENTIALS_JSON.")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS_JSON no contiene JSON válido.") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS_JSON debe corresponder a una cuenta de servicio.")
    return info


@lru_cache(maxsize=1)
def _service():
    creds = Credentials.from_service_account_info(_credentials_info(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def reset_service_cache() -> None:
    """Útil para tests o cambios de credenciales durante desarrollo."""
    _service.cache_clear()


def _sheet_title(spreadsheet_id: str, preferred: str | None = None) -> str:
    meta = _service().spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties(title,index)",
    ).execute()
    sheets = sorted(meta.get("sheets") or [], key=lambda x: x.get("properties", {}).get("index", 0))
    if not sheets:
        raise RuntimeError("La planilla de Google Sheets no tiene hojas.")
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
    # Mantiene filas vacías intermedias pero elimina sólo el vacío sobrante al final.
    while out and not any(str(v).strip() for v in out[-1]):
        out.pop()
    columnas = max(1, min(max((len(f) for f in out), default=1), MAX_COLUMNS))
    return [f[:columnas] + [""] * (columnas - len(f)) for f in out]


def leer_excel(libro_id: str = "1") -> dict:
    libro_id = _book_id(libro_id)
    spreadsheet_id = _spreadsheet_id(libro_id)
    title = _sheet_title(spreadsheet_id)
    result = _service().spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=_quote_sheet(title),
        majorDimension="ROWS",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
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
    # Limpia antes de escribir para que una matriz más chica no deje residuos viejos.
    svc.clear(spreadsheetId=spreadsheet_id, range=range_all, body={}).execute()
    if matriz:
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
        ).execute()


def agregar_filas(filas: list[list[str]], libro_id: str = "1", nombre_hoja: str | None = None) -> int:
    """Agrega filas sin reescribir el libro completo. Devuelve cuántas agregó."""
    libro_id = _book_id(libro_id)
    matriz = _normalizar_matriz(filas)
    if not matriz:
        return 0
    spreadsheet_id = _spreadsheet_id(libro_id)
    title = _sheet_title(spreadsheet_id, nombre_hoja)
    _service().spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{_quote_sheet(title)}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"majorDimension": "ROWS", "values": matriz},
    ).execute()
    return len(matriz)
