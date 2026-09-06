"""Lectura efímera de PDFs adjuntos al chat.

No usa Flask ni sesión. Recibe bytes y devuelve texto de contexto; la ruta web
sólo se ocupa de validar request/response.
"""
from __future__ import annotations

import re
import fitz


class ChatPdfError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def extraer_contexto_pdf(datos_pdf: bytes, nombre_archivo: str, *, max_paginas: int,
                          max_chars: int, max_bytes: int) -> tuple[str, int, int]:
    datos_pdf = bytes(datos_pdf or b"")
    if not datos_pdf:
        raise ChatPdfError("El PDF está vacío o no se pudo leer.", 422)
    if len(datos_pdf) > max_bytes:
        raise ChatPdfError("El PDF es demasiado grande para procesarlo en el chat.", 413)

    paginas = []
    total_chars = 0
    procesadas = 0
    try:
        documento = fitz.open(stream=datos_pdf, filetype="pdf")
    except Exception as exc:
        raise ChatPdfError(f"No se pudo leer el PDF adjunto: {exc}", 400) from exc

    try:
        limite_paginas = min(documento.page_count, max_paginas)
        for numero in range(limite_paginas):
            if total_chars >= max_chars:
                break
            try:
                pagina = documento.load_page(numero)
                texto = pagina.get_text("text", sort=True) or ""
                del pagina
            except Exception:
                continue
            texto = re.sub(r"[ \t]+", " ", texto).strip()
            if not texto:
                continue
            restante = max_chars - total_chars
            texto = texto[:restante]
            paginas.append(f"PÁGINA {numero + 1}\n{texto}")
            total_chars += len(texto)
            procesadas += 1
    finally:
        documento.close()

    if not paginas:
        raise ChatPdfError(
            "El PDF parece ser escaneado o no contiene texto seleccionable. En esta versión puedo leer PDFs con texto.",
            422,
        )

    contexto = (
        "\n\n===== PDF ADJUNTADO EN EL CHAT =====\n"
        f"ARCHIVO: {nombre_archivo}\n"
        f"PÁGINAS PROCESADAS: {procesadas}\n\n"
        + "\n\n".join(paginas)
        + "\n===== FIN PDF ADJUNTADO =====\n"
    )
    return contexto, procesadas, total_chars
