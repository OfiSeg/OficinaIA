"""Adaptador HTTP del chat.

V20 Etapa 5: concentra el parseo JSON/multipart y la lectura efímera del PDF.
El orquestador de /api/chat recibe datos ya normalizados y no necesita conocer
los detalles de FileStorage, seek/read ni JSON embebido en formularios.
"""

from dataclasses import dataclass
import json
import os

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
    archivo_pdf: object = None
    tiene_data: bool = False


@dataclass
class PdfAttachment:
    nombre: str = ""
    contexto: str = ""
    paginas: int = 0
    chars: int = 0


def parse_incoming(flask_request):
    if flask_request.is_json:
        data = flask_request.get_json(silent=True) or {}
        return IncomingChat(
            mensaje=str(data.get("mensaje", "")).strip(),
            chat_id=data.get("chat_id"),
            historial=data.get("historial") or [],
            archivo_pdf=None,
            tiene_data=bool(data),
        )

    data = flask_request.form
    historial_raw = data.get("historial", "[]")
    try:
        historial = json.loads(historial_raw)
    except Exception:
        historial = []
    archivo_pdf = flask_request.files.get("pdf")
    return IncomingChat(
        mensaje=str(data.get("mensaje", "")).strip(),
        chat_id=data.get("chat_id"),
        historial=historial,
        archivo_pdf=archivo_pdf,
        tiene_data=bool(data),
    )


def extract_pdf_attachment(
    archivo_pdf,
    *,
    max_bytes,
    max_pages,
    max_chars,
    transport_max_bytes=20 * 1024 * 1024,
):
    if not archivo_pdf or not archivo_pdf.filename:
        return PdfAttachment()

    nombre = secure_filename(archivo_pdf.filename) or "documento.pdf"
    if not nombre.lower().endswith(".pdf"):
        raise ChatRequestError("El archivo adjunto debe ser un PDF.", 400)

    try:
        archivo_pdf.stream.seek(0, os.SEEK_END)
        size = archivo_pdf.stream.tell()
        archivo_pdf.stream.seek(0)
        if size > transport_max_bytes:
            raise ChatRequestError("El PDF es demasiado grande. El máximo permitido es 20 MB.", 413)

        datos = archivo_pdf.stream.read()
        archivo_pdf.stream.seek(0)
        if len(datos) > max_bytes:
            raise ChatRequestError("El PDF es demasiado grande para procesarlo en el chat.", 413)

        try:
            contexto, paginas, total_chars = extraer_contexto_pdf(
                datos,
                nombre,
                max_paginas=max_pages,
                max_chars=max_chars,
                max_bytes=max_bytes,
            )
        except ChatPdfError as exc:
            raise ChatRequestError(str(exc), exc.status_code) from exc
        finally:
            del datos

        return PdfAttachment(nombre=nombre, contexto=contexto, paginas=paginas, chars=total_chars)
    except ChatRequestError:
        raise
    except Exception as exc:
        raise ChatRequestError(
            "No pude leer ese PDF. Verificá que el archivo no esté dañado.", 422
        ) from exc
