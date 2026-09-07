"""Normalización del request del chat y de sus adjuntos efímeros."""
from __future__ import annotations

from dataclasses import dataclass
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
}
MAX_ADJUNTO_BYTES = {
    "pdf": 20 * 1024 * 1024,
    "imagen": 15 * 1024 * 1024,
    "texto": 2 * 1024 * 1024,
}


def parse_incoming(flask_request):
    if flask_request.is_json:
        data = flask_request.get_json(silent=True) or {}
        return IncomingChat(
            mensaje=str(data.get("mensaje", "")).strip(),
            chat_id=data.get("chat_id"),
            historial=data.get("historial") or [],
            archivo=None,
            tiene_data=bool(data),
        )

    data = flask_request.form
    historial_raw = data.get("historial", "[]")
    try:
        historial = json.loads(historial_raw)
    except Exception:
        historial = []
    archivo = flask_request.files.get("archivo") or flask_request.files.get("pdf")
    return IncomingChat(
        mensaje=str(data.get("mensaje", "")).strip(),
        chat_id=data.get("chat_id"),
        historial=historial,
        archivo=archivo,
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
        raise ChatRequestError("Podés adjuntar PDF, TXT, PNG, JPG, JPEG o WEBP.", 400)
    tipo, mime_default = detectado
    # La extensión permitida define el MIME; no confiamos en un Content-Type arbitrario del cliente.
    mime = mime_default
    if tipo == "pdf":
        limite = min(int(max_pdf_bytes), MAX_ADJUNTO_BYTES["pdf"])
    else:
        limite = MAX_ADJUNTO_BYTES[tipo]
    datos = _leer_bytes(archivo, limite)

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
