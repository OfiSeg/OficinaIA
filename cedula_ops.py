"""Lectura reforzada de cédulas vehiculares para el chat de OficinaIA.

Objetivo operativo: evitar tipeo manual de MOTOR/CHASIS sin ocultar dudas.
"verificado" exige al menos tres evidencias independientes completas, sin
conflictos y con calidad visual suficiente (visión general, lectura focalizada,
verificación independiente y, en PDFs digitales, la capa de texto como señal
adicional). 3/3 es evidencia fuerte, no certeza si la imagen es deficiente. Un
fallo de una etapa no descarta toda la cédula: se conserva la mejor lectura
disponible y se marca ``revisar``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from base64 import b64encode
from io import BytesIO
import json
import re
from typing import Any

from google.genai import types
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ai_gateway import DEFAULT_MODELS, current_state, generate_with_fallback, obtener_cliente_gemini
from resilience import parse_json_object
from attachment_vision import MediaBlob, renderizar_para_vision, renderizar_varios_para_vision


CEDULA_SYSTEM_INSTRUCTION = r"""
Vas a recibir una o más imágenes de un documento vehicular argentino.
Primero determiná si realmente es una CÉDULA DE IDENTIFICACIÓN de automotor o
motovehículo (cédula verde/azul, formato nuevo/digital o registral equivalente).
Luego transcribí los datos visibles. NO infieras caracteres.

Devolvé SOLO JSON válido:
{
  "es_cedula": true,
  "mismo_documento": true,
  "caras": [{"cara": "frente|dorso|desconocida", "patente": "", "titular": ""}],
  "orientaciones": [{"pagina": 1, "rotacion_para_leer": 0}],
  "titular": "",
  "dni": "",
  "patente": "",
  "patente_legible": true,
  "patente_dudas": [],
  "patente_calidad": "buena|media|mala",
  "marca": "",
  "modelo": "",
  "tipo": "",
  "uso": "",
  "anio": "",
  "vencimiento": "",
  "control": "",
  "numero_cedula": "",
  "motor": "",
  "chasis": "",
  "motor_legible": true,
  "chasis_legible": true,
  "motor_dudas": [],
  "chasis_dudas": [],
  "motor_calidad": "buena|media|mala",
  "chasis_calidad": "buena|media|mala",
  "calidad_documento": "buena|media|mala",
  "problemas_imagen": [],
  "motor_region": {"pagina": 1, "bbox": [ymin, xmin, ymax, xmax]},
  "chasis_region": {"pagina": 1, "bbox": [ymin, xmin, ymax, xmax]},
  "advertencias": []
}

REGLAS CRÍTICAS:
- Si NO es una cédula, ``es_cedula=false`` y no inventes datos de cédula.
- Si recibís dos imágenes y no parecen frente/dorso del mismo documento/vehículo, ``mismo_documento=false``.
- Copiá PATENTE, MOTOR y CHASIS carácter por carácter exactamente como se ven.
- No completes por formato esperado, marca, conocimiento del vehículo ni VIN.
- Si un carácter es dudoso, usá ? en esa posición y describí la duda.
- Si un campo no puede leerse, valor="" y *_legible=false.
- Atención a 0/O/D, 1/I/L, 2/Z, 5/S, 6/G, 8/B, V/Y, C/G, U/V y cualquier otra ambigüedad visible.
- Informá `*_calidad` según la región concreta del dato crítico, no sólo por la apariencia general del documento.
- En `problemas_imagen` describí sólo problemas realmente visibles: desenfoque, baja nitidez, reflejo, poco contraste, oclusión, pixelado, recorte, etc.
- `orientaciones` debe contener una entrada por cada imagen/página recibida. `rotacion_para_leer` es el ángulo horario 0/90/180/270 que habría que aplicar para dejar el texto derecho. No inventes rotación si ya está legible en orientación normal.
- No confundas DNI, número de trámite, dominio, control/número de cédula, motor y chasis.
- ``bbox`` usa coordenadas normalizadas 0..1000 [ymin,xmin,ymax,xmax].
- La región debe incluir la cadena completa y un pequeño margen/etiqueta.
- Si no podés localizar una región con seguridad, devolvé null.
"""

CEDULA_FOCUSED_SYSTEM_INSTRUCTION = r"""
Actuás como transcriptor documental especializado. Recibís recortes de MOTOR y/o
CHASIS (original y mejorado) o, si no pudo recortarse, la imagen completa.
No conocés la lectura anterior.

Devolvé SOLO JSON válido:
{
  "patente": {"valor": "", "legible": true, "dudas": [], "calidad": "buena|media|mala"},
  "motor": {"valor": "", "legible": true, "dudas": [], "calidad": "buena|media|mala"},
  "chasis": {"valor": "", "legible": true, "dudas": [], "calidad": "buena|media|mala"}
}

Transcribí literalmente PATENTE, MOTOR y CHASIS. No corrijas por contexto. Si un carácter es dudoso,
usá ? y explicá posición/opciones. Si no se lee, valor="" y legible=false.
"""

CEDULA_VERIFY_SYSTEM_INSTRUCTION = r"""
Actuás como verificador INDEPENDIENTE. Mirá nuevamente el documento ORIGINAL y
transcribí SOLAMENTE PATENTE, MOTOR y CHASIS. No recibís las lecturas anteriores.

Devolvé SOLO JSON válido:
{
  "patente": {"valor": "", "legible": true, "dudas": [], "calidad": "buena|media|mala"},
  "motor": {"valor": "", "legible": true, "dudas": [], "calidad": "buena|media|mala"},
  "chasis": {"valor": "", "legible": true, "dudas": [], "calidad": "buena|media|mala"}
}

No adivines. No autocorrijas. Si un carácter es dudoso, usá ?. Si el campo no
es legible, dejalo vacío y legible=false.
"""


class NotCedulaError(ValueError):
    pass


class CedulasIncompatiblesError(ValueError):
    pass


@dataclass
class CedulaResult:
    datos: dict[str, Any]
    advertencias: list[str] = field(default_factory=list)


@dataclass
class FieldCrop:
    original: MediaBlob
    mejorado: MediaBlob
    preview_data_url: str = ""


def _limpio(valor: Any) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def _ident(valor: Any) -> str:
    # Normalización segura: mayúsculas + remover espacios/saltos. No sustituir
    # caracteres ni borrar signos internos que podrían representar una duda.
    return re.sub(r"\s+", "", str(valor or "")).strip().upper()


def _patente_visual(valor: Any) -> str:
    """Normaliza separadores de patente SIN borrar una duda visual ``?``.

    ``envios_ya_utils.normalizar_patente`` sirve para una patente ya confirmada,
    pero elimina cualquier carácter no alfanumérico. En extracción documental eso
    sería peligroso porque transformaría, por ejemplo, ``AB?23CD`` en ``AB23CD``
    y ocultaría que el modelo no pudo leer un carácter.
    """
    bruto = str(valor or "").upper().strip()
    bruto = re.sub(r"[\s-]+", "", bruto)
    return re.sub(r"[^A-Z0-9?]", "", bruto)


def _bool_legible(valor: Any, default: bool = False) -> bool:
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return bool(default)
    t = str(valor).strip().lower()
    if t in {"true", "1", "si", "sí", "yes"}:
        return True
    if t in {"false", "0", "no"}:
        return False
    return bool(default)


def _lista(valor: Any, *, max_items=12) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [_limpio(x)[:220] for x in valor if _limpio(x)][:max_items]


def _candidato_identificador(texto: str, *, campo: str) -> str:
    """Extrae un candidato literal cercano a una etiqueta de PDF digital.

    No corrige caracteres. Sólo descarta tokens obviamente estructurales para
    que la capa de texto de PyMuPDF pueda actuar como evidencia adicional.
    """
    texto = str(texto or '').upper().strip(' :;=\t')
    if not texto:
        return ''
    tokens = re.findall(r"[A-Z0-9][A-Z0-9./-]{3,39}", texto)
    blacklist = {
        'MOTOR', 'CHASIS', 'CHASSIS', 'NUMERO', 'NRO.', 'MARCA', 'MODELO',
        'DOMINIO', 'TITULAR', 'AUTOMOTOR', 'MOTOVEHICULO', 'IDENTIFICACION',
    }
    min_len = 8 if campo == 'chasis' else 5
    max_len = 30
    for token in tokens:
        limpio = token.strip(' .,:;-')
        if len(limpio) < min_len or len(limpio) > max_len:
            continue
        if limpio in blacklist:
            continue
        # Fechas y páginas no son identificadores de motor/chasis.
        if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", limpio):
            continue
        return _ident(limpio)
    return ''


def _extraer_identificadores_texto(adjunto) -> dict[str, str]:
    """Lee MOTOR/CHASIS desde la capa textual si el PDF realmente la posee.

    Es una señal de apoyo muy valiosa para un PDF digital, pero jamás modifica
    O/0, I/1, B/8 ni otra pareja ambigua. En fotos/scans retorna vacío.
    """
    if isinstance(adjunto, (list, tuple)):
        salida = {"motor": "", "chasis": ""}
        for item in adjunto:
            parcial = _extraer_identificadores_texto(item)
            for campo in salida:
                if not salida[campo] and parcial.get(campo):
                    salida[campo] = parcial[campo]
        return salida
    if str(getattr(adjunto, 'tipo', '') or '') != 'pdf':
        return {'motor': '', 'chasis': ''}
    contexto = str(getattr(adjunto, 'contexto', '') or '')
    if not contexto.strip():
        return {'motor': '', 'chasis': ''}

    lineas = []
    for linea in contexto.replace('\r', '').split('\n'):
        limpia = re.sub(r"\s+", ' ', linea).strip()
        if not limpia or limpia.startswith('=====') or re.fullmatch(r"PÁGINA\s+\d+", limpia, re.I):
            continue
        lineas.append(limpia)

    patrones = {
        'motor': re.compile(r"(?:N(?:RO|[°º])?\.?\s*(?:DE\s+)?)?\bMOTOR\b(?:\s+N(?:RO|[°º])?\.?)?", re.I),
        'chasis': re.compile(r"(?:N(?:RO|[°º])?\.?\s*(?:DE\s+)?)?\b(?:CHASIS|CHASSIS)\b(?:\s+N(?:RO|[°º])?\.?)?", re.I),
    }
    salida = {'motor': '', 'chasis': ''}
    for campo, patron in patrones.items():
        for i, linea in enumerate(lineas):
            m = patron.search(linea)
            if not m:
                continue
            # Primero el resto de la misma línea; luego hasta dos líneas
            # siguientes por si el extractor separó etiqueta y valor.
            segmentos = [linea[m.end():]] + lineas[i + 1:i + 3]
            for segmento in segmentos:
                candidato = _candidato_identificador(segmento, campo=campo)
                if candidato:
                    salida[campo] = candidato
                    break
            if salida[campo]:
                break
    return salida


def _evidencia_textual(valor: Any, campo: str) -> dict[str, Any]:
    valor = _ident(valor)
    return {
        'valor': valor,
        'legible': bool(valor and '?' not in valor),
        'dudas': [],
        'calidad': 'buena',
        'fuente': f'texto_pdf_{campo}',
    }


def _parse_json_robusto(texto: str) -> dict:
    return parse_json_object(texto)

def _cliente_o_error():
    cliente = obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")
    return cliente


def _es_error_transitorio(exc: Exception) -> bool:
    t = str(exc or "").upper()
    return any(x in t for x in ("503", "502", "504", "TIMEOUT", "TIMED OUT", "UNAVAILABLE", "TEMPORAR"))


def _generar_json(*, media_parts: list[Any], prompt: str, system: str, max_tokens: int, log_prefix: str) -> dict:
    """Lectura estructurada; retries transitorios/JSON viven en ai_gateway."""
    cliente = _cliente_o_error()
    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
        system_instruction=system.strip(),
    )
    respuesta, _modelo = generate_with_fallback(
        client=cliente,
        models=DEFAULT_MODELS,
        contents=[prompt, *media_parts],
        config=config,
        log_prefix=log_prefix,
        response_validator=lambda r: _parse_json_robusto(getattr(r, "text", "")),
    )
    return _parse_json_robusto(getattr(respuesta, "text", ""))

def _normalizar_blob_imagen(blob: MediaBlob, *, max_lado=3600) -> MediaBlob:
    try:
        with Image.open(BytesIO(blob.data)) as img:
            try:
                orientacion = int(img.getexif().get(274, 1) or 1)
            except Exception:
                orientacion = 1
            if orientacion == 1 and img.mode in {"RGB", "L"} and max(img.size) <= max_lado:
                return blob
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
            return MediaBlob("image/jpeg", out.getvalue(), blob.pagina)
    except Exception:
        return blob




def _rotar_blob(blob: MediaBlob, grados_horarios: int) -> MediaBlob:
    """Rota una representación temporal para visión sin tocar el adjunto original."""
    try:
        grados = int(grados_horarios or 0) % 360
    except Exception:
        grados = 0
    if grados not in {90, 180, 270}:
        return blob
    try:
        with Image.open(BytesIO(blob.data)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            # PIL usa ángulos antihorarios; negativo = giro horario.
            img = img.rotate(-grados, expand=True, resample=Image.Resampling.BICUBIC)
            out = BytesIO()
            img.save(out, format="JPEG", quality=96, subsampling=0, optimize=True)
            return MediaBlob("image/jpeg", out.getvalue(), blob.pagina)
    except Exception:
        return blob


def _rotaciones_detectadas(primera: dict, cantidad: int) -> dict[int, int]:
    """Devuelve {indice_base_0: grados_horarios}; ignora valores dudosos."""
    resultado: dict[int, int] = {}
    items = primera.get("orientaciones") if isinstance(primera, dict) else None
    if not isinstance(items, list):
        return resultado
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            pagina = int(item.get("pagina") or 0)
            grados = int(item.get("rotacion_para_leer") or 0) % 360
        except Exception:
            continue
        if 1 <= pagina <= cantidad and grados in {90, 180, 270}:
            resultado[pagina - 1] = grados
    return resultado


def _aplicar_rotaciones_detectadas(media: list[MediaBlob], primera: dict) -> tuple[list[MediaBlob], bool]:
    rotaciones = _rotaciones_detectadas(primera, len(media))
    if not rotaciones:
        return media, False
    salida: list[MediaBlob] = []
    cambio = False
    for idx, blob in enumerate(media):
        grados = rotaciones.get(idx, 0)
        nuevo = _rotar_blob(blob, grados) if grados else blob
        salida.append(nuevo)
        cambio = cambio or (nuevo is not blob)
    return salida, cambio


def _calidad_normalizada(valor: Any) -> str:
    t = _limpio(valor).lower()
    if t in {"buena", "alta", "good", "high"}:
        return "buena"
    if t in {"media", "regular", "medium"}:
        return "media"
    if t in {"mala", "baja", "deficiente", "poor", "low"}:
        return "mala"
    return ""


def _problema_visual_material(problemas: list[str] | None) -> bool:
    texto = " ".join(str(x or "").lower() for x in (problemas or []))
    señales = (
        "borros", "desenfo", "nitidez", "reflej", "contraste", "oscuro",
        "sobreex", "subex", "pixel", "oclu", "tapad", "recort",
        "movimiento", "resoluci", "ilegible", "distorsi",
    )
    return any(x in texto for x in señales)


def _calidad_impide_verificar(
    *,
    calidad_documento: Any = "",
    problemas_imagen: list[str] | None = None,
    evidencias: list[dict] | None = None,
) -> bool:
    """3/3 es evidencia fuerte, no certeza si la imagen/región es deficiente."""
    calidad_global = _calidad_normalizada(calidad_documento)
    if calidad_global == "mala":
        return True
    # Si el propio análisis marcó el documento como bueno, un problema leve
    # fuera de la región crítica no debería degradar por sí solo todo el campo.
    if calidad_global != "buena" and _problema_visual_material(problemas_imagen):
        return True
    calidades = [_calidad_normalizada(e.get("calidad")) for e in (evidencias or []) if isinstance(e, dict)]
    if any(c == "mala" for c in calidades):
        return True
    # Con calidad global media, exigir que las evidencias que sí informaron calidad
    # no sean también medias/malas. Si el modelo no informó calidad, no degradar
    # compatibilidad con lecturas históricas.
    if calidad_global == "media" and calidades and not any(c == "buena" for c in calidades):
        return True
    return False

def _media_cedula(adjunto) -> list[MediaBlob]:
    # 2.6x ayuda con texto pequeño de PDFs escaneados/digitales sin llegar a
    # imágenes gigantes que empeoren latencia. Frente+dorso puede llegar como
    # dos adjuntos y se renderiza con numeración continua.
    if isinstance(adjunto, (list, tuple)):
        media = renderizar_varios_para_vision(adjunto, max_paginas_total=4, escala_pdf=2.6)
    else:
        media = renderizar_para_vision(adjunto, max_paginas=4, escala_pdf=2.6)
    return [_normalizar_blob_imagen(m) for m in media]


def _leer_general(media: list[MediaBlob]) -> dict:
    if not media:
        raise ValueError("No hay contenido visual para leer la cédula.")
    parts: list[Any] = []
    for idx, m in enumerate(media, start=1):
        parts.extend([
            f"PÁGINA/IMAGEN {idx}",
            types.Part.from_bytes(data=m.data, mime_type=m.mime_type),
        ])
    return _generar_json(
        media_parts=parts,
        prompt=(
            "Determiná si el documento es una cédula vehicular argentina y, si lo es, extraé sus datos. "
            "Priorizá MOTOR y CHASIS y localizá sus regiones completas para la segunda lectura."
        ),
        system=CEDULA_SYSTEM_INSTRUCTION,
        max_tokens=1600,
        log_prefix="GEMINI CEDULA GENERAL",
    )


def _parse_region(valor: Any, cantidad_paginas: int):
    if not isinstance(valor, dict):
        return None
    try:
        pagina = int(valor.get("pagina") or 1)
    except Exception:
        pagina = 1
    if pagina < 1 or pagina > max(1, cantidad_paginas):
        return None
    bbox = valor.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        vals = [float(x) for x in bbox]
    except Exception:
        return None
    if max(abs(x) for x in vals) <= 1.5:
        vals = [x * 1000.0 for x in vals]
    ymin, xmin, ymax, xmax = [max(0.0, min(1000.0, x)) for x in vals]
    if ymax <= ymin or xmax <= xmin or (ymax-ymin) < 6 or (xmax-xmin) < 10:
        return None
    return pagina - 1, (ymin, xmin, ymax, xmax)


def _encode_png(img: Image.Image) -> bytes:
    out = BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()


def _preview_data_url(img: Image.Image) -> str:
    copia = img.copy().convert("RGB")
    copia.thumbnail((1400, 520), Image.Resampling.LANCZOS)
    out = BytesIO()
    copia.save(out, format="JPEG", quality=91, optimize=True)
    return "data:image/jpeg;base64," + b64encode(out.getvalue()).decode("ascii")


def _crear_crop(media: list[MediaBlob], region: Any) -> FieldCrop | None:
    parsed = _parse_region(region, len(media))
    if parsed is None:
        return None
    idx, (ymin, xmin, ymax, xmax) = parsed
    try:
        with Image.open(BytesIO(media[idx].data)) as src:
            src = ImageOps.exif_transpose(src).convert("RGB")
            w, h = src.size
            bw = (xmax - xmin) / 1000.0 * w
            bh = (ymax - ymin) / 1000.0 * h
            # Margen generoso: los bbox de visión no siempre abrazan el primer/
            # último carácter exactamente.
            mx = max(16, bw * 0.12)
            my = max(12, bh * 0.32)
            left = max(0, int(xmin / 1000.0 * w - mx))
            top = max(0, int(ymin / 1000.0 * h - my))
            right = min(w, int(xmax / 1000.0 * w + mx))
            bottom = min(h, int(ymax / 1000.0 * h + my))
            if right-left < 30 or bottom-top < 16:
                return None
            crop = src.crop((left, top, right, bottom))
            cw, ch = crop.size
            factor = max(1.0, min(4.0, max(1100.0/max(cw,1), 260.0/max(ch,1))))
            mejorado = crop.resize(
                (max(1, round(cw*factor)), max(1, round(ch*factor))),
                Image.Resampling.LANCZOS,
            )
            # Mejora moderada/no destructiva. El original se envía siempre al lado.
            mejorado = ImageOps.autocontrast(mejorado, cutoff=0.2)
            mejorado = ImageEnhance.Contrast(mejorado).enhance(1.16)
            mejorado = ImageEnhance.Sharpness(mejorado).enhance(1.28)
            mejorado = mejorado.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=2))
            return FieldCrop(
                original=MediaBlob("image/png", _encode_png(crop), media[idx].pagina),
                mejorado=MediaBlob("image/png", _encode_png(mejorado), media[idx].pagina),
                preview_data_url=_preview_data_url(mejorado),
            )
    except Exception:
        return None


def _leer_focalizado(media: list[MediaBlob], crop_motor: FieldCrop | None, crop_chasis: FieldCrop | None) -> dict:
    parts: list[Any] = []
    faltantes: list[str] = []
    paginas_contexto: set[int] = set()
    if crop_motor:
        parts.extend([
            "MOTOR — RECORTE ORIGINAL",
            types.Part.from_bytes(data=crop_motor.original.data, mime_type=crop_motor.original.mime_type),
            "MOTOR — MISMO RECORTE MEJORADO",
            types.Part.from_bytes(data=crop_motor.mejorado.data, mime_type=crop_motor.mejorado.mime_type),
        ])
        paginas_contexto.add(int(crop_motor.original.pagina or 1))
    else:
        faltantes.append("MOTOR")
    if crop_chasis:
        parts.extend([
            "CHASIS — RECORTE ORIGINAL",
            types.Part.from_bytes(data=crop_chasis.original.data, mime_type=crop_chasis.original.mime_type),
            "CHASIS — MISMO RECORTE MEJORADO",
            types.Part.from_bytes(data=crop_chasis.mejorado.data, mime_type=crop_chasis.mejorado.mime_type),
        ])
        paginas_contexto.add(int(crop_chasis.original.pagina or 1))
    else:
        faltantes.append("CHASIS")

    prompt = "Transcribí PATENTE, MOTOR y CHASIS de forma independiente, carácter por carácter."
    if faltantes:
        prompt += " No pude recortar con seguridad " + " y ".join(faltantes) + "; buscá sólo esos campos en las imágenes completas adjuntas."
        paginas_contexto.update(m.pagina for m in media)
    else:
        # Aun con un bbox válido, una coordenada visual puede quedar corrida.
        # Enviamos UNA sola vez las páginas que contienen los crops como
        # contexto, evitando una llamada extra y haciendo el fallback adaptativo.
        prompt += " Usá los recortes como fuente principal; las páginas completas son sólo contexto para confirmar que el recorte corresponde al campo correcto."

    for m in media:
        if int(m.pagina or 1) in paginas_contexto:
            parts.extend([
                f"PÁGINA COMPLETA DE CONTEXTO {m.pagina}",
                types.Part.from_bytes(data=m.data, mime_type=m.mime_type),
            ])

    return _generar_json(
        media_parts=parts,
        prompt=prompt,
        system=CEDULA_FOCUSED_SYSTEM_INSTRUCTION,
        max_tokens=750,
        log_prefix="GEMINI CEDULA FOCALIZADA",
    )


def _leer_verificacion_independiente(media: list[MediaBlob]) -> dict:
    parts: list[Any] = []
    for idx, m in enumerate(media, start=1):
        parts.extend([
            f"PÁGINA/IMAGEN ORIGINAL {idx}",
            types.Part.from_bytes(data=m.data, mime_type=m.mime_type),
        ])
    return _generar_json(
        media_parts=parts,
        prompt="Hacé una verificación nueva únicamente de PATENTE, MOTOR y CHASIS. No presupongas ninguna lectura previa.",
        system=CEDULA_VERIFY_SYSTEM_INSTRUCTION,
        max_tokens=700,
        log_prefix="GEMINI CEDULA VERIFICACION",
    )


def _evidencia_general(dato: dict, campo: str) -> dict[str, Any]:
    valor = _patente_visual(dato.get(campo)) if campo == "patente" else _ident(dato.get(campo))
    return {
        "valor": valor,
        "legible": _bool_legible(dato.get(f"{campo}_legible"), bool(valor and "?" not in valor)),
        "dudas": _lista(dato.get(f"{campo}_dudas")),
        "calidad": _calidad_normalizada(dato.get(f"{campo}_calidad") or dato.get("calidad_documento")),
        "fuente": "general",
    }


def _evidencia_anidada(dato: dict, campo: str, fuente: str) -> dict[str, Any]:
    item = dato.get(campo) if isinstance(dato, dict) else None
    if not isinstance(item, dict):
        valor = _patente_visual(item) if campo == "patente" else _ident(item)
        return {"valor": valor, "legible": bool(valor and "?" not in valor), "dudas": [], "calidad": "", "fuente": fuente}
    valor = _patente_visual(item.get("valor")) if campo == "patente" else _ident(item.get("valor"))
    return {
        "valor": valor,
        "legible": _bool_legible(item.get("legible"), bool(valor and "?" not in valor)),
        "dudas": _lista(item.get("dudas")),
        "calidad": _calidad_normalizada(item.get("calidad")),
        "fuente": fuente,
    }


def _posiciones_discrepantes(valores: list[str]) -> tuple[str | None, list[str]]:
    valores = [v for v in valores if v]
    if not valores:
        return "", []
    if len(valores) == 1:
        return valores[0], []
    if len({len(v) for v in valores}) != 1:
        return None, ["Las lecturas devolvieron longitudes diferentes."]
    mascara: list[str] = []
    dudas: list[str] = []
    for idx, chars in enumerate(zip(*valores), start=1):
        opciones = list(dict.fromkeys(c for c in chars if c != "?"))
        habia_ilegible = any(c == "?" for c in chars)
        if not opciones:
            mascara.append("?")
            dudas.append(f"Posición {idx}: no legible")
        elif len(opciones) == 1:
            mascara.append(opciones[0])
            if habia_ilegible:
                dudas.append(f"Posición {idx}: {opciones[0]} / no legible")
        else:
            mascara.append("?")
            dudas.append(f"Posición {idx}: {' / '.join(opciones)}")
    return "".join(mascara), dudas


def _resolver_campo(
    general: dict,
    focal: dict,
    verificacion: dict,
    errores_etapa: list[str] | None = None,
    textual: dict | None = None,
    *,
    calidad_documento: Any = "",
    problemas_imagen: list[str] | None = None,
):
    evidencias = [general, focal, verificacion]
    if textual and textual.get('valor'):
        evidencias.append(textual)

    valores = [str(e.get("valor", "") or "") for e in evidencias if e.get("valor")]
    dudas: list[str] = []
    for e in evidencias:
        dudas.extend(_lista(e.get("dudas")))
    dudas.extend(errores_etapa or [])

    # Las opciones seleccionables deben ser lecturas completas REALMENTE
    # observadas. No fabricamos el producto cartesiano de caracteres dudosos.
    alternativas = list(dict.fromkeys(
        str(e.get("valor", "") or "") for e in evidencias
        if e.get("valor") and "?" not in str(e.get("valor", ""))
    ))

    if not valores:
        return "", "no_legible", list(dict.fromkeys(dudas)), alternativas

    completos = [
        e["valor"] for e in evidencias
        if e.get("valor") and e.get("legible") and "?" not in e.get("valor", "") and not e.get("dudas")
    ]
    conteos = {v: completos.count(v) for v in set(completos)}
    mejor_valor = max(conteos, key=conteos.get) if conteos else ""
    mejor_conteo = conteos.get(mejor_valor, 0) if mejor_valor else 0

    # 3/3 = evidencia fuerte, NO certeza absoluta. Además del consenso, la
    # región/documento debe tener calidad suficiente y no presentar problemas
    # visuales materiales.
    conflictos_completos = [v for v in completos if mejor_valor and v != mejor_valor]
    calidad_bloquea = _calidad_impide_verificar(
        calidad_documento=calidad_documento,
        problemas_imagen=problemas_imagen,
        evidencias=evidencias,
    )
    if mejor_conteo >= 3 and not conflictos_completos and not calidad_bloquea:
        valores_parciales_conflictivos = [
            e.get('valor', '') for e in evidencias
            if e.get('valor') and '?' not in e.get('valor', '') and e.get('valor') != mejor_valor
        ]
        if not valores_parciales_conflictivos:
            return mejor_valor, "verificado", [], alternativas

    mascara, diferencias = _posiciones_discrepantes(valores)
    dudas.extend(diferencias)

    valor_mostrar = ""
    if mejor_conteo >= 2:
        valor_mostrar = mejor_valor
    elif mascara is not None:
        valor_mostrar = mascara
    else:
        valor_mostrar = focal.get("valor") or verificacion.get("valor") or general.get("valor") or (textual or {}).get('valor', '')

    if calidad_bloquea:
        dudas.append("Las lecturas coinciden, pero la calidad visual no permite considerarlo verificado automáticamente.")
    elif valor_mostrar and mejor_conteo < 3 and not diferencias:
        dudas.append("La lectura es utilizable, pero no obtuvo tres verificaciones independientes idénticas.")
    return valor_mostrar, "revisar", list(dict.fromkeys(d for d in dudas if d)), alternativas


def _conteo_consenso(evidencias: list[dict], valor: str) -> int:
    if not valor:
        return 0
    return sum(
        1 for e in evidencias
        if e.get("valor") == valor and e.get("legible") and "?" not in str(e.get("valor", "")) and not e.get("dudas")
    )


def _contexto_confirma_cedula(adjunto) -> bool:
    if isinstance(adjunto, (list, tuple)):
        contexto = "\n".join(str(getattr(a, "contexto", "") or "") for a in adjunto).upper()
    else:
        contexto = str(getattr(adjunto, 'contexto', '') or '').upper()
    if not contexto:
        return False
    fuertes = (
        'CEDULA DE IDENTIFICACION', 'CÉDULA DE IDENTIFICACIÓN', 'DNRPA',
        'REGISTRO NACIONAL DE LA PROPIEDAD',
    )
    if any(x in contexto for x in fuertes):
        return True
    señales = sum(1 for x in ('DOMINIO', 'TITULAR', 'MOTOR', 'CHASIS', 'CHASSIS') if x in contexto)
    return señales >= 4


def _caras_cedula_compatibles(primera: dict) -> bool | None:
    caras = primera.get("caras")
    if not isinstance(caras, list) or len(caras) < 2:
        valor = primera.get("mismo_documento")
        return valor if isinstance(valor, bool) else None
    items = [c for c in caras[:2] if isinstance(c, dict)]
    if len(items) < 2:
        return None
    patentes = [_patente_visual(c.get("patente")) for c in items if _patente_visual(c.get("patente"))]
    if len(patentes) >= 2 and len(set(patentes)) > 1:
        return False
    titulares = [_limpio(c.get("titular")).upper() for c in items if _limpio(c.get("titular"))]
    if len(titulares) >= 2 and len(set(titulares)) > 1:
        return False
    if (len(patentes) >= 2 and len(set(patentes)) == 1) or (len(titulares) >= 2 and len(set(titulares)) == 1):
        return True
    valor = primera.get("mismo_documento")
    return valor if isinstance(valor, bool) else None


def procesar_cedula(adjunto, *, clasificacion_confirmada: bool = False) -> CedulaResult:
    media = _media_cedula(adjunto)
    if not media:
        raise ValueError("No hay contenido visual para leer la cédula.")

    primera = _leer_general(media)
    # La primera mirada también detecta orientación. Sólo si informa un giro
    # seguro normalizamos la representación temporal y repetimos la lectura
    # general para que bbox/calidad/datos críticos se calculen ya derechos.
    media_normalizada, orientacion_corregida = _aplicar_rotaciones_detectadas(media, primera)
    if orientacion_corregida:
        media = media_normalizada
        primera = _leer_general(media)
    es_cedula = _bool_legible(primera.get("es_cedula"), False)
    # Dos archivos o un PDF multipágina pueden representar frente+dorso. Si la
    # lectura devolvió dos caras, exigir compatibilidad aunque hayan llegado
    # dentro de un único PDF; así no se fusionan dos cédulas distintas por error.
    caras_reportadas = primera.get("caras") if isinstance(primera.get("caras"), list) else []
    es_multicara = (isinstance(adjunto, (list, tuple)) and len(adjunto) > 1) or len(caras_reportadas) > 1
    if es_multicara:
        compatibles = _caras_cedula_compatibles(primera)
        if compatibles is not True:
            raise CedulasIncompatiblesError(
                "Las imágenes/páginas de cédula no pudieron confirmarse como frente/dorso del mismo documento."
            )
    texto_ids = _extraer_identificadores_texto(adjunto)
    if not clasificacion_confirmada and not es_cedula and not _contexto_confirma_cedula(adjunto):
        raise NotCedulaError("La lectura visual no confirmó que el documento sea una cédula.")

    crop_motor = _crear_crop(media, primera.get("motor_region"))
    crop_chasis = _crear_crop(media, primera.get("chasis_region"))

    errores: list[str] = []
    try:
        focal = _leer_focalizado(media, crop_motor, crop_chasis)
    except Exception as exc:
        focal = {}
        errores.append("La lectura focalizada no pudo completarse; revisá el dato antes de emitir.")
        print("ERROR CEDULA FOCALIZADA:", exc)
    try:
        verificacion = _leer_verificacion_independiente(media)
    except Exception as exc:
        verificacion = {}
        errores.append("La verificación independiente no pudo completarse; revisá el dato antes de emitir.")
        print("ERROR CEDULA VERIFICACION:", exc)

    ev_patente = [
        _evidencia_general(primera, "patente"),
        _evidencia_anidada(focal, "patente", "focal"),
        _evidencia_anidada(verificacion, "patente", "verificacion"),
    ]
    calidad_documento = _calidad_normalizada(primera.get("calidad_documento"))
    problemas_imagen = _lista(primera.get("problemas_imagen"))
    patente, estado_patente, dudas_patente, alternativas_patente = _resolver_campo(
        ev_patente[0], ev_patente[1], ev_patente[2], errores,
        calidad_documento=calidad_documento,
        problemas_imagen=problemas_imagen,
    )
    ev_motor = [
        _evidencia_general(primera, "motor"),
        _evidencia_anidada(focal, "motor", "focal"),
        _evidencia_anidada(verificacion, "motor", "verificacion"),
    ]
    ev_chasis = [
        _evidencia_general(primera, "chasis"),
        _evidencia_anidada(focal, "chasis", "focal"),
        _evidencia_anidada(verificacion, "chasis", "verificacion"),
    ]
    motor, estado_motor, dudas_motor, alternativas_motor = _resolver_campo(
        ev_motor[0], ev_motor[1], ev_motor[2], errores,
        _evidencia_textual(texto_ids.get('motor'), 'motor'),
        calidad_documento=calidad_documento,
        problemas_imagen=problemas_imagen,
    )
    chasis, estado_chasis, dudas_chasis, alternativas_chasis = _resolver_campo(
        ev_chasis[0], ev_chasis[1], ev_chasis[2], errores,
        _evidencia_textual(texto_ids.get('chasis'), 'chasis'),
        calidad_documento=calidad_documento,
        problemas_imagen=problemas_imagen,
    )

    datos = {
        "titular": _limpio(primera.get("titular")),
        "dni": re.sub(r"\D", "", _limpio(primera.get("dni"))),
        "patente": patente,
        "estado_patente": estado_patente,
        "dudas_patente": dudas_patente,
        "alternativas_patente": alternativas_patente,
        "coincidencias_patente": _conteo_consenso(ev_patente, patente),
        "marca": _limpio(primera.get("marca")),
        "modelo": _limpio(primera.get("modelo")),
        "tipo": _limpio(primera.get("tipo")),
        "uso": _limpio(primera.get("uso")),
        "anio": _limpio(primera.get("anio")),
        "vencimiento": _limpio(primera.get("vencimiento")),
        "control": _limpio(primera.get("control") or primera.get("numero_cedula")),
        "numero_cedula": _limpio(primera.get("numero_cedula") or primera.get("control")),
        "motor": motor,
        "chasis": chasis,
        "estado_motor": estado_motor,
        "estado_chasis": estado_chasis,
        "coincidencias_motor": _conteo_consenso(ev_motor, motor),
        "coincidencias_chasis": _conteo_consenso(ev_chasis, chasis),
        "dudas_motor": dudas_motor,
        "dudas_chasis": dudas_chasis,
        "alternativas_motor": alternativas_motor,
        "alternativas_chasis": alternativas_chasis,
        "evidencia_textual_motor": bool(texto_ids.get('motor')),
        "evidencia_textual_chasis": bool(texto_ids.get('chasis')),
        "recorte_motor": crop_motor.preview_data_url if crop_motor and estado_motor != "verificado" else "",
        "recorte_chasis": crop_chasis.preview_data_url if crop_chasis and estado_chasis != "verificado" else "",
        "calidad_documento": calidad_documento,
        "problemas_imagen": problemas_imagen,
        "orientacion_normalizada": bool(orientacion_corregida),
        "fuente_verificacion_patente": "automatic" if estado_patente == "verificado" else "",
        "fuente_verificacion_motor": "automatic" if estado_motor == "verificado" else "",
        "fuente_verificacion_chasis": "automatic" if estado_chasis == "verificado" else "",
    }

    advertencias = _lista(primera.get("advertencias"))
    problemas = problemas_imagen
    if estado_patente != "verificado":
        advertencias.append("Revisá PATENTE antes de usar: las lecturas no alcanzaron alta confianza.")
    if estado_motor != "verificado":
        advertencias.append("Revisá MOTOR antes de usarlo: la lectura automática no alcanza certeza suficiente.")
    if estado_chasis != "verificado":
        advertencias.append("Revisá CHASIS antes de usarlo: la lectura automática no alcanza certeza suficiente.")
    if estado_patente != "verificado" or estado_motor != "verificado" or estado_chasis != "verificado":
        advertencias.extend(problemas[:3])
        advertencias.extend(errores[:2])
    advertencias = list(dict.fromkeys(x for x in advertencias if x))
    return CedulaResult(datos, advertencias)


def resumen_cedula(resultado: CedulaResult) -> str:
    d = resultado.datos
    if all(d.get(f"estado_{campo}") == "verificado" for campo in ("patente", "motor", "chasis")):
        return "Cédula detectada. Patente, motor y chasis quedaron verificados automáticamente."
    if not d.get("motor") and not d.get("chasis"):
        return "Cédula detectada. La imagen no permite leer motor/chasis con seguridad; probá con una foto más nítida."
    return "Cédula detectada. Te dejo la mejor lectura disponible; confirmá los campos marcados antes de usarlos."
