"""Utilidades multimodales para adjuntos efímeros del chat.

No persiste archivos. Acepta el contrato ``Adjunto`` de ``chat_request`` y
convierte imágenes/PDFs a blobs visuales reutilizables por clasificadores y
extractores especializados.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

import fitz
from PIL import Image, ImageOps


@dataclass(frozen=True)
class MediaBlob:
    mime_type: str
    data: bytes
    pagina: int = 1


@dataclass(frozen=True)
class RenderizacionMultiple:
    blobs: list[MediaBlob]
    adjuntos_recibidos: int = 0
    paginas_renderizadas: int = 0
    paginas_omitidas_estimadas: int = 0
    truncado: bool = False
    advertencias: list[str] = field(default_factory=list)


def _normalizar_imagen_bytes(datos: bytes, mime_type: str, *, max_lado: int = 3600) -> MediaBlob:
    """Corrige orientación EXIF y limita imágenes enormes sin degradar las chicas."""
    try:
        with Image.open(BytesIO(datos)) as img:
            try:
                orientacion = int(img.getexif().get(274, 1) or 1)
            except Exception:
                orientacion = 1
            w, h = img.size
            # Sólo devolvemos los bytes originales cuando realmente no hay nada
            # que corregir. Antes se aplicaba exif_transpose en memoria pero se
            # retornaba el JPEG original, perdiendo la rotación de fotos de celular.
            if orientacion == 1 and img.mode in {"RGB", "L"} and max(w, h) <= max_lado:
                return MediaBlob(mime_type or "image/jpeg", bytes(datos), 1)
            img = ImageOps.exif_transpose(img).convert("RGB")
            mayor = max(img.size)
            if mayor > max_lado:
                escala = max_lado / float(mayor)
                img = img.resize(
                    (max(1, round(img.width * escala)), max(1, round(img.height * escala))),
                    Image.Resampling.LANCZOS,
                )
            out = BytesIO()
            img.save(out, format="JPEG", quality=96, subsampling=0, optimize=True)
            return MediaBlob("image/jpeg", out.getvalue(), 1)
    except Exception:
        return MediaBlob(mime_type or "image/jpeg", bytes(datos), 1)


def renderizar_para_vision(adjunto, *, max_paginas: int = 4, escala_pdf: float = 2.2) -> list[MediaBlob]:
    """Devuelve imágenes aptas para visión.

    - imagen -> bytes normalizados (sin persistir)
    - PDF -> PNG por página, incluso cuando el PDF no tiene texto seleccionable
    """
    if adjunto is None:
        return []
    tipo = str(getattr(adjunto, "tipo", "") or "")
    datos = bytes(getattr(adjunto, "datos_binarios", b"") or b"")
    if not datos:
        return []

    if tipo == "imagen":
        blob = _normalizar_imagen_bytes(datos, str(getattr(adjunto, "mime_type", "") or "image/jpeg"))
        return [blob]

    if tipo != "pdf":
        return []

    try:
        doc = fitz.open(stream=datos, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"No pude renderizar el PDF adjunto: {exc}") from exc

    salida: list[MediaBlob] = []
    try:
        limite = min(doc.page_count, max(1, int(max_paginas)))
        escala = max(1.0, min(3.5, float(escala_pdf or 2.2)))
        matrix = fitz.Matrix(escala, escala)
        for numero in range(limite):
            page = doc.load_page(numero)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            salida.append(MediaBlob("image/png", pix.tobytes("png"), numero + 1))
    finally:
        doc.close()
    return salida

def renderizar_varios_para_vision_con_reporte(adjuntos, *, max_paginas_total: int = 4, escala_pdf: float = 2.2) -> RenderizacionMultiple:
    """Renderiza varios adjuntos con reporte de truncamiento.

    La función histórica devolvía sólo blobs y cortaba cuando alcanzaba el
    límite. Eso sirve para presupuesto, pero en colecciones N-documentos podía
    provocar que el modelo dijera que revisó todo cuando no recibió todas las
    páginas/imágenes. Este coordinador conserva el comportamiento existente y
    además expone advertencias seguras para que el caller informe la limitación.
    """
    items = [a for a in list(adjuntos or []) if a is not None]
    salida: list[MediaBlob] = []
    advertencias: list[str] = []
    limite = max(1, int(max_paginas_total or 4))
    pagina_global = 1
    omitidas = 0
    for idx, adjunto in enumerate(items, start=1):
        if len(salida) >= limite:
            omitidas += 1
            continue
        restantes = limite - len(salida)
        try:
            blobs = renderizar_para_vision(adjunto, max_paginas=restantes, escala_pdf=escala_pdf)
        except Exception as exc:
            advertencias.append(f"No pude renderizar el adjunto {idx}: {str(exc)[:120]}")
            continue
        if str(getattr(adjunto, 'tipo', '') or '') == 'pdf':
            # No abrimos de nuevo el PDF sólo para contar páginas. Si hay capa de
            # texto extraída, el texto ya viaja por contexto; la advertencia de
            # truncamiento visual se limita al límite que realmente aplicamos.
            try:
                import fitz
                doc = fitz.open(stream=bytes(getattr(adjunto, 'datos_binarios', b'') or b''), filetype='pdf')
                page_count = int(doc.page_count)
                doc.close()
                if page_count > len(blobs):
                    omitidas += page_count - len(blobs)
            except Exception:
                pass
        for blob in blobs:
            salida.append(MediaBlob(blob.mime_type, blob.data, pagina_global))
            pagina_global += 1
            if len(salida) >= limite:
                break
    truncado = bool(omitidas or len(salida) >= limite and len(items) > 1)
    if truncado:
        advertencias.append(
            f"Se incluyeron {len(salida)} página(s)/imagen(es) visual(es) como máximo para este turno; puede haber contenido visual no enviado a la IA."
        )
    return RenderizacionMultiple(
        blobs=salida,
        adjuntos_recibidos=len(items),
        paginas_renderizadas=len(salida),
        paginas_omitidas_estimadas=max(0, omitidas),
        truncado=truncado,
        advertencias=list(dict.fromkeys(advertencias)),
    )


def renderizar_varios_para_vision(adjuntos, *, max_paginas_total: int = 4, escala_pdf: float = 2.2) -> list[MediaBlob]:
    """Renderiza varios adjuntos sin persistirlos y con numeración continua.

    Compatibilidad histórica: callers existentes siguen recibiendo sólo la lista
    de blobs. Para colecciones N-documentos, usar
    ``renderizar_varios_para_vision_con_reporte`` para evitar truncamiento
    silencioso.
    """
    return renderizar_varios_para_vision_con_reporte(
        adjuntos, max_paginas_total=max_paginas_total, escala_pdf=escala_pdf
    ).blobs

