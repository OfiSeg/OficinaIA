"""Catálogo de los dos libros lógicos de OficinaIA.

Los metadatos son estáticos. Los IDs de Google Sheets se leen en tiempo de
ejecución desde runtime_config para evitar dos vistas distintas de la misma
configuración dentro de un proceso.
"""
from __future__ import annotations

import runtime_config

_BOOKS = {
    "1": {
        "archivo": "excel_interno.xlsx",  # referencia/migración; no fuente activa
        "r2_key": "respaldo/asegurados",
        "sheet_env": "SHEET_ID_ASEGURADOS",
        "nombre": "Asegurados",
    },
    "2": {
        "archivo": "excel_flotas.xlsx",  # referencia/migración; no fuente activa
        "r2_key": "respaldo/flotas",
        "sheet_env": "SHEET_ID_FLOTAS",
        "nombre": "Flotas",
    },
}


def obtener_catalogo_libros() -> dict[str, dict[str, str]]:
    return {k: dict(v) for k, v in _BOOKS.items()}


def obtener_libros_excel() -> dict[str, dict[str, str]]:
    """Compatibilidad: expone sheet_id, pero lo obtiene en cada llamada."""
    libros = obtener_catalogo_libros()
    for libro in libros.values():
        libro["sheet_id"] = runtime_config.get_text(libro["sheet_env"], "") or ""
    return libros
