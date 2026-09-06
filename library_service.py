"""Dominio Biblioteca / Manuales / Pólizas de OficinaIA.

Este módulo no conoce Flask, request, session ni Response. Centraliza validación,
persistencia coordinada Neon/R2 y rollback. Las rutas HTTP quedan como adaptadores.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
import os
import uuid
import re
import unicodedata

import fitz


def _secure_filename(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    value = value.replace("/", " ").replace("\\", " ")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return value


@dataclass
class OpResult:
    ok: bool
    status: int = 200
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def payload(self) -> dict[str, Any]:
        body = {"ok": self.ok, **self.data}
        if self.error:
            body["error"] = self.error
        return body


def _fecha_texto(fecha: Any) -> str:
    return fecha.strftime("%d/%m/%Y %H:%M") if fecha else ""


def agrupar_manuales(filas: Iterable[dict], companias: Iterable[str], slugger: Callable[[str], str]) -> list[dict]:
    companias = list(companias)
    agrupados = {slugger(nombre): [] for nombre in companias}
    for fila in filas:
        r2_key = str(fila.get("r2_key") or "")
        partes = r2_key.split("/")
        if len(partes) < 3 or partes[0] != "manuales" or partes[1] not in agrupados:
            continue
        agrupados[partes[1]].append({
            "nombre": fila.get("nombre") or "manual.pdf",
            "archivo": r2_key,
            "fecha": _fecha_texto(fila.get("fecha_subida")),
            "tamaño": round((fila.get("tamaño") or 0) / 1024, 1),
        })
    return [{
        "nombre": nombre,
        "slug": slugger(nombre),
        "cargado": bool(agrupados[slugger(nombre)]),
        "cantidad": len(agrupados[slugger(nombre)]),
        "archivos": agrupados[slugger(nombre)],
    } for nombre in companias]


def preparar_polizas(filas: Iterable[dict]) -> list[dict]:
    return [{
        "archivo": f["r2_key"],
        "nombre": f["nombre"],
        "fecha": _fecha_texto(f.get("fecha_subida")),
        "tamaño": round((f.get("tamaño") or 0) / 1024, 1),
    } for f in filas]


def _medir_archivo(archivo) -> int:
    archivo.stream.seek(0, os.SEEK_END)
    tamaño = archivo.stream.tell()
    archivo.stream.seek(0)
    return tamaño


def _validar_pdf(archivo, max_bytes: int, *, max_label: str | None = None) -> tuple[str, int, bytes]:
    nombre = _secure_filename(Path(archivo.filename).name)
    if not nombre or Path(nombre).suffix.lower() != ".pdf":
        raise ValueError(f'El archivo "{archivo.filename}" no es un PDF válido.')
    try:
        tamaño = _medir_archivo(archivo)
    except Exception as exc:
        raise ValueError(f'No se pudo leer el archivo "{archivo.filename}".') from exc
    if tamaño <= 0:
        raise ValueError(f'El PDF "{archivo.filename}" está vacío.')
    if tamaño > max_bytes:
        limite = max_label or f"{max_bytes // (1024 * 1024)} MB"
        raise OverflowError(f'El PDF "{archivo.filename}" es demasiado grande. El máximo permitido es {limite}.')
    try:
        if archivo.stream.read(5) != b"%PDF-":
            raise ValueError(f'El archivo "{archivo.filename}" no parece ser un PDF válido.')
        archivo.stream.seek(0)
        datos = archivo.stream.read()
        archivo.stream.seek(0)
        doc = fitz.open(stream=datos, filetype="pdf")
        doc.close()
        return nombre, tamaño, datos
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'No se pudo leer el PDF "{archivo.filename}". Verificá que no esté dañado.') from exc


def subir_poliza(archivo, *, max_bytes: int, upload: Callable, register: Callable, delete_r2: Callable) -> OpResult:
    if not archivo or not getattr(archivo, "filename", ""):
        return OpResult(False, 400, error="Seleccioná un archivo PDF.")
    try:
        nombre, tamaño, _ = _validar_pdf(archivo, max_bytes)
    except OverflowError as exc:
        return OpResult(False, 413, error=str(exc))
    except ValueError as exc:
        return OpResult(False, 400, error=str(exc))
    key = f"polizas/{uuid.uuid4().hex}__{nombre}"
    try:
        archivo.stream.seek(0); upload(archivo.stream, key, tamaño)
    except Exception:
        return OpResult(False, 502, error="No se pudo guardar la póliza en Cloudflare R2.")
    try:
        register(nombre, key, tamaño)
    except Exception:
        try: delete_r2(key)
        except Exception: pass
        return OpResult(False, 502, error="La póliza se subió a R2 pero no pudo registrarse en PostgreSQL. La operación no se completó.")
    return OpResult(True, data={"archivo": key, "nombre": nombre, "tamaño": tamaño})


def eliminar_poliza(key: str, *, get_record: Callable, delete_db: Callable, delete_r2: Callable, restore_db: Callable) -> OpResult:
    key = str(key or "").strip()
    if not key.startswith("polizas/") or not key.lower().endswith(".pdf"):
        return OpResult(False, 404, error="Póliza no encontrada.")
    existente = get_record(key)
    if not existente:
        return OpResult(False, 404, error="Póliza no encontrada.")
    try:
        if not delete_db(key):
            return OpResult(False, 404, error="Póliza no encontrada.")
    except Exception:
        return OpResult(False, 502, error="No se pudo actualizar PostgreSQL. La póliza no fue eliminada.")
    try:
        delete_r2(key)
    except Exception:
        try: restore_db(existente["nombre"], existente["r2_key"], existente["tamaño"])
        except Exception: pass
        return OpResult(False, 502, error="No se pudo eliminar el PDF de Cloudflare R2. La póliza se mantuvo registrada.")
    return OpResult(True)


def subir_manuales(slug: str, archivos: list, reemplazar: str, *, companias: Iterable[str], slugger: Callable,
                    max_bytes: int, get_record: Callable, upload: Callable, delete_r2: Callable,
                    register: Callable, update: Callable, extract_text: Callable, propose: Callable) -> OpResult:
    compania = next((c for c in companias if slugger(c) == slug), None)
    if not compania:
        return OpResult(False, 404, error="Compañía no válida.")
    archivos = [a for a in archivos if a and getattr(a, "filename", "")]
    if not archivos:
        return OpResult(False, 400, error="Seleccioná al menos un archivo PDF.")
    reemplazar = str(reemplazar or "").strip()
    if reemplazar and len(archivos) != 1:
        return OpResult(False, 400, error="El reemplazo de un manual debe hacerse con un solo PDF.")

    preparados = []
    for archivo in archivos:
        try:
            nombre, tamaño, datos = _validar_pdf(archivo, min(max_bytes, 20 * 1024 * 1024), max_label="20 MB por archivo")
        except OverflowError as exc:
            return OpResult(False, 413, error=str(exc))
        except ValueError as exc:
            return OpResult(False, 400, error=str(exc))
        ficha = None
        try:
            ficha = propose(extract_text(datos), compania=compania, nombre_archivo=nombre)
        except Exception:
            ficha = None
        preparados.append((archivo, nombre, tamaño, ficha))

    anterior = None
    if reemplazar:
        prefijo = f"manuales/{slug}/"
        if not reemplazar.startswith(prefijo) or not reemplazar.lower().endswith(".pdf"):
            return OpResult(False, 400, error="El manual a reemplazar no es válido.")
        anterior = get_record(reemplazar)
        if not anterior:
            return OpResult(False, 404, error="El manual a reemplazar no existe.")

    resultados = []
    for archivo, nombre, tamaño, ficha in preparados:
        key = f"manuales/{slug}/{uuid.uuid4().hex}__{nombre}"
        try:
            archivo.stream.seek(0); upload(archivo.stream, key, tamaño)
        except Exception:
            return OpResult(False, 502, {"cargados": resultados}, f'No se pudo guardar "{archivo.filename}" en Cloudflare R2.')
        try:
            if anterior:
                update(reemplazar, nombre, key, tamaño)
            else:
                register(nombre, key, tamaño)
        except Exception:
            try: delete_r2(key)
            except Exception: pass
            return OpResult(False, 502, {"cargados": resultados}, f'"{archivo.filename}" se subió a R2, pero no pudo registrarse en PostgreSQL. La operación no se completó.')

        item = {"archivo": key, "nombre": nombre, "tamaño": tamaño}
        if ficha: item["ficha_sugerida"] = ficha
        resultados.append(item)

        if anterior:
            try:
                delete_r2(reemplazar)
            except Exception:
                try: update(key, anterior["nombre"], reemplazar, anterior["tamaño"])
                except Exception: pass
                try: delete_r2(key)
                except Exception: pass
                return OpResult(False, 502, {"cargados": []}, "No se pudo completar el reemplazo porque el PDF anterior no pudo eliminarse de R2.")
            anterior = None

    return OpResult(True, data={
        "mensaje": f"{len(resultados)} manual(es) de {compania} cargado(s) correctamente.",
        "archivos": resultados, "cantidad": len(resultados)
    })


def eliminar_manual(slug: str, key: str, *, companias: Iterable[str], slugger: Callable,
                    get_record: Callable, delete_db: Callable, delete_r2: Callable, restore_db: Callable) -> OpResult:
    if slug not in {slugger(c) for c in companias}:
        return OpResult(False, 404, error="Compañía no válida.")
    key = str(key or "").strip(); prefijo = f"manuales/{slug}/"
    if not key.startswith(prefijo) or not key.lower().endswith(".pdf"):
        return OpResult(False, 400, error="Manual no válido para esa compañía.")
    existente = get_record(key)
    if not existente:
        return OpResult(False, 404, error="Manual no encontrado.")
    try:
        if not delete_db(key): return OpResult(False, 404, error="Manual no encontrado.")
    except Exception:
        return OpResult(False, 502, error="No se pudo actualizar PostgreSQL. El PDF no fue eliminado.")
    try:
        delete_r2(key)
    except Exception:
        try: restore_db(existente["nombre"], existente["r2_key"], existente["tamaño"])
        except Exception: pass
        return OpResult(False, 502, error="No se pudo eliminar el PDF de Cloudflare R2. El manual se mantuvo registrado.")
    return OpResult(True)


def validar_key_manual(slug: str, key: str, companias: Iterable[str], slugger: Callable) -> bool:
    return slug in {slugger(c) for c in companias} and str(key or "").startswith(f"manuales/{slug}/") and str(key).lower().endswith(".pdf")


def validar_key_poliza(key: str) -> bool:
    key = str(key or "").strip()
    return key.startswith("polizas/") and key.lower().endswith(".pdf")
