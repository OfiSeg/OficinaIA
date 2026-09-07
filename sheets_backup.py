"""Respaldo de sólo escritura: Google Sheets -> XLSX -> Cloudflare R2."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from openpyxl import Workbook

import google_sheets_service
import storage_r2
import system_health

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BOOKS = {"1": "asegurados", "2": "flotas"}


def _xlsx_bytes(datos: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = str(datos.get("hoja") or "Datos")[:31]
    for fila in datos.get("filas") or []:
        ws.append(["" if v is None else str(v) for v in fila])
    out = BytesIO(); wb.save(out)
    return out.getvalue()


def _podar(prefijo: str, conservar: int = 30) -> int:
    def orden(obj):
        valor = obj.get("LastModified")
        if isinstance(valor, datetime):
            if valor.tzinfo is None:
                valor = valor.replace(tzinfo=timezone.utc)
            return valor.timestamp()
        return 0.0

    objetos = sorted(
        storage_r2.listar_objetos(prefijo),
        key=orden,
        reverse=True,
    )
    eliminados = 0
    for obj in objetos[max(1, int(conservar)):]:
        key = obj.get("Key")
        if key:
            storage_r2.eliminar_objeto(key); eliminados += 1
    return eliminados


def ejecutar_respaldo_diario(fecha: datetime | None = None, conservar: int = 30) -> dict:
    fecha = fecha or datetime.now()
    stamp = fecha.strftime("%Y-%m-%d")
    resultado = {"ok": True, "libros": {}}
    for libro_id, nombre in BOOKS.items():
        prefijo = f"respaldo/{nombre}_"
        key = f"{prefijo}{stamp}.xlsx"
        try:
            datos = google_sheets_service.leer_excel(libro_id)
            storage_r2.subir_bytes(_xlsx_bytes(datos), key, MIME_XLSX)
            eliminados = _podar(prefijo, conservar)
            resultado["libros"][libro_id] = {"ok": True, "key": key, "eliminados": eliminados}
        except Exception as error:
            resultado["ok"] = False
            resultado["libros"][libro_id] = {"ok": False, "error": str(error)}
            system_health.registrar_evento("excel", "error", f"Falló respaldo diario de {nombre}", str(error))
    return resultado
