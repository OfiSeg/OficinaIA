"""Normalización del request del chat y de sus adjuntos efímeros."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from werkzeug.utils import secure_filename

from chat_pdf import extraer_contexto_pdf, ChatPdfError


class ChatRequestError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = int(status_code)


@dataclass
class IncomingChat:
    mensaje: str
    chat_id: object
    historial: list
    archivo: object = None
    archivos: list = field(default_factory=list)
    tiene_data: bool = False


@dataclass
class Adjunto:
    nombre: str
    tipo: str  # imagen | pdf | texto
    mime_type: str
    datos_binarios: bytes | None = None
    texto_plano: str | None = None
    contexto: str = ""
    paginas: int = 0
    chars: int = 0


EXTENSIONES = {
    ".pdf": ("pdf", "application/pdf"),
    ".txt": ("texto", "text/plain"),
    ".png": ("imagen", "image/png"),
    ".jpg": ("imagen", "image/jpeg"),
    ".jpeg": ("imagen", "image/jpeg"),
    ".webp": ("imagen", "image/webp"),
    ".csv": ("tabla", "text/csv"),
    ".xlsx": ("tabla", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".xlsm": ("tabla", "application/vnd.ms-excel.sheet.macroEnabled.12"),
}
MAX_ADJUNTO_BYTES = {
    "pdf": 20 * 1024 * 1024,
    "imagen": 15 * 1024 * 1024,
    "texto": 2 * 1024 * 1024,
    "tabla": 20 * 1024 * 1024,
}
# Colección del compositor del chat. El límite es por mensaje, no por selector:
# seleccionar A y luego B debe conservar A+B. El total evita cargas accidentales
# que agoten memoria antes de llegar al procesamiento multimodal.
MAX_CHAT_ATTACHMENTS = 5
MAX_CHAT_ATTACHMENTS_TOTAL_BYTES = 40 * 1024 * 1024


def _firma_valida(tipo: str, ext: str, datos: bytes) -> bool:
    if tipo == "pdf":
        return datos.startswith(b"%PDF")
    if tipo == "imagen":
        if ext in {".jpg", ".jpeg"}:
            return len(datos) >= 3 and datos[:3] == b"\xff\xd8\xff"
        if ext == ".png":
            return datos.startswith(b"\x89PNG\r\n\x1a\n")
        if ext == ".webp":
            return len(datos) >= 12 and datos[:4] == b"RIFF" and datos[8:12] == b"WEBP"
    return True


def parse_incoming(flask_request):
    if flask_request.is_json:
        data = flask_request.get_json(silent=True) or {}
        return IncomingChat(
            mensaje=str(data.get("mensaje", "")).strip(),
            chat_id=data.get("chat_id"),
            historial=data.get("historial") or [],
            archivo=None,
            archivos=[],
            tiene_data=bool(data),
        )

    data = flask_request.form
    historial_raw = data.get("historial", "[]")
    try:
        historial = json.loads(historial_raw)
    except Exception:
        historial = []
    archivos = [a for a in flask_request.files.getlist("archivo") if a and getattr(a, "filename", "")]
    if not archivos:
        archivos = [a for a in flask_request.files.getlist("pdf") if a and getattr(a, "filename", "")]
    archivo = archivos[0] if archivos else None
    return IncomingChat(
        mensaje=str(data.get("mensaje", "")).strip(),
        chat_id=data.get("chat_id"),
        historial=historial,
        archivo=archivo,
        archivos=archivos,
        tiene_data=bool(data),
    )


def _leer_bytes(archivo, limite: int) -> bytes:
    try:
        archivo.stream.seek(0, os.SEEK_END)
        size = archivo.stream.tell()
        archivo.stream.seek(0)
        if size > limite:
            raise ChatRequestError("El archivo adjunto supera el tamaño permitido.", 413)
        datos = archivo.stream.read()
        archivo.stream.seek(0)
        if len(datos) > limite:
            raise ChatRequestError("El archivo adjunto supera el tamaño permitido.", 413)
        return datos
    except ChatRequestError:
        raise
    except Exception as exc:
        raise ChatRequestError("No pude leer el archivo adjunto. Verificá que no esté dañado.", 422) from exc


def extract_attachment(archivo, *, max_pdf_bytes, max_pages, max_chars) -> Adjunto | None:
    if not archivo or not archivo.filename:
        return None

    nombre = secure_filename(archivo.filename) or "adjunto"
    ext = Path(nombre).suffix.lower()
    detectado = EXTENSIONES.get(ext)
    if not detectado:
        raise ChatRequestError("Podés adjuntar Excel (XLSX/XLSM), PDF, TXT, CSV, PNG, JPG, JPEG o WEBP.", 400)
    tipo, mime_default = detectado
    # La extensión permitida define el MIME; no confiamos en un Content-Type arbitrario del cliente.
    mime = mime_default
    if tipo == "pdf":
        limite = min(int(max_pdf_bytes), MAX_ADJUNTO_BYTES["pdf"])
    else:
        limite = MAX_ADJUNTO_BYTES[tipo]
    datos = _leer_bytes(archivo, limite)
    if not _firma_valida(tipo, ext, datos):
        raise ChatRequestError("El contenido del archivo no coincide con su formato o está dañado.", 400)

    if tipo == "pdf":
        try:
            contexto, paginas, total_chars = extraer_contexto_pdf(
                datos,
                nombre,
                max_paginas=max_pages,
                max_chars=max_chars,
                max_bytes=limite,
            )
        except ChatPdfError as exc:
            raise ChatRequestError(str(exc), exc.status_code) from exc
        return Adjunto(
            nombre=nombre, tipo=tipo, mime_type="application/pdf",
            datos_binarios=datos, contexto=contexto, paginas=paginas, chars=total_chars,
        )

    if tipo == "tabla":
        return Adjunto(
            nombre=nombre, tipo="tabla", mime_type=mime_default,
            datos_binarios=datos, contexto="", chars=0,
        )

    if tipo == "texto":
        texto = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                texto = datos.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        texto = (texto or "").replace("\x00", "").strip()
        if not texto:
            raise ChatRequestError("El TXT está vacío o no pude interpretar su contenido.", 422)
        texto = texto[:max_chars]
        contexto = (
            "\n\n===== TXT ADJUNTADO EN EL CHAT =====\n"
            f"ARCHIVO: {nombre}\n\n{texto}\n"
            "===== FIN TXT ADJUNTADO =====\n"
        )
        return Adjunto(
            nombre=nombre, tipo=tipo, mime_type="text/plain",
            datos_binarios=datos, texto_plano=texto, contexto=contexto, chars=len(texto),
        )

    return Adjunto(
        nombre=nombre,
        tipo="imagen",
        mime_type=mime if mime.startswith("image/") else mime_default,
        datos_binarios=datos,
    )


def extract_attachments(
    archivos, *, max_pdf_bytes, max_pages, max_chars,
    max_files: int = MAX_CHAT_ATTACHMENTS,
    max_total_bytes: int = MAX_CHAT_ATTACHMENTS_TOTAL_BYTES,
) -> list[Adjunto]:
    """Extrae una colección ordenada de adjuntos del mismo turno.

    ``extract_attachment`` sigue siendo la única validación por archivo. El
    coordinador conserva el orden de llegada, limita cantidad/tamaño total y no
    descarta silenciosamente archivos posteriores.
    """
    entrada = [a for a in list(archivos or []) if a and getattr(a, "filename", "")]
    if len(entrada) > max_files:
        raise ChatRequestError(f"Podés adjuntar hasta {max_files} archivos por mensaje.", 400)

    salida: list[Adjunto] = []
    total = 0
    for archivo in entrada:
        adjunto = extract_attachment(
            archivo, max_pdf_bytes=max_pdf_bytes, max_pages=max_pages, max_chars=max_chars
        )
        if adjunto is None:
            continue
        total += len(getattr(adjunto, "datos_binarios", b"") or b"")
        if total > int(max_total_bytes):
            raise ChatRequestError(
                f"El conjunto de adjuntos supera el límite de {int(max_total_bytes) // (1024 * 1024)} MB por mensaje.",
                413,
            )
        salida.append(adjunto)
    return salida
