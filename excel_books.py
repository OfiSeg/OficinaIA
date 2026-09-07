"""Configuración única de los dos libros lógicos de OficinaIA."""
from __future__ import annotations
import os


def obtener_libros_excel() -> dict[str, dict[str, str]]:
    """Lee IDs en tiempo de ejecución para respetar .env/Render sin estado duplicado."""
    return {
        "1": {
            "archivo": "excel_interno.xlsx",  # referencia/migración; no fuente activa
            "r2_key": "respaldo/asegurados",
            "sheet_id": (os.getenv("SHEET_ID_ASEGURADOS") or "").strip(),
            "nombre": "Asegurados",
        },
        "2": {
            "archivo": "excel_flotas.xlsx",  # referencia/migración; no fuente activa
            "r2_key": "respaldo/flotas",
            "sheet_id": (os.getenv("SHEET_ID_FLOTAS") or "").strip(),
            "nombre": "Flotas",
        },
    }
