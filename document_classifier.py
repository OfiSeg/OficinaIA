"""Clasificación automática y tolerante a fallos de adjuntos del chat.

La clasificación es explícita (cedula/dni/licencia/poliza/otro). Para PDFs digitales se
prefieren heurísticas de estructura. Para imágenes y scans se usa Gemini visión.
Un fallo de clasificación visual NO bloquea el adjunto: el caller puede intentar
una lectura especializada o dejar continuar a Sofia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import unicodedata

from google.genai import types

from ai_gateway import DEFAULT_MODELS, generate_with_fallback, obtener_cliente_gemini
from attachment_vision import renderizar_para_vision, renderizar_varios_para_vision


CLASSIFIER_SYSTEM_INSTRUCTION = r"""
Sos un clasificador ESTRICTO de documentos de una oficina de seguros argentina.
Mirá el adjunto y decidí únicamente el tipo documental.

Devolvé SOLO JSON válido:
{
  "tipo_documento": "cedula|dni|licencia|poliza|cotizacion_atm|otro",
  "confianza": "alta|media|baja",
  "evidencia": ["frase breve"]
}

CEDULA:
- cédula de identificación del automotor o motovehículo argentina;
- cédula verde/azul o formato registral moderno/digital equivalente;
- suele contener DOMINIO, TITULAR, MARCA, MODELO, MOTOR y/o CHASIS;
- puede decir DNRPA, Registro Nacional, Cédula de Identificación, automotor,
  motovehículo, dominio, nro. motor, nro. chasis.

DNI:
- Documento Nacional de Identidad argentino, frente o dorso;
- puede decir DOCUMENTO NACIONAL DE IDENTIDAD, DNI, REPÚBLICA ARGENTINA, RENAPER;
- el dorso puede mostrar CUIL, domicilio, código/lectura mecánica y otros datos.

LICENCIA:
- licencia/registro de conducir argentina, nacional/provincial/municipal;
- puede decir LICENCIA NACIONAL DE CONDUCIR, LICENCIA DE CONDUCIR, CLASE, CATEGORÍA, VENCIMIENTO.

POLIZA:
- frente/certificado/póliza emitida por una aseguradora;
- suele contener asegurado, póliza/certificado, vigencia, cobertura, prima,
  premio, suma asegurada, compañía.

COTIZACION_ATM:
- captura de pantalla del cotizador web de ATM Seguros con un listado de alternativas;
- suele mostrar títulos como Terceros Completos Plus/Black/Premium, Todo Riesgo,
  Robo e Incendio, Responsabilidad Civil y precios en pesos;
- puede mostrar varias filas/tarjetas de coberturas y porcentajes de franquicia.

OTRO: cualquier otro documento.

IMPORTANTE:
- una póliza también puede mostrar motor/chasis: eso NO la convierte en cédula;
- no confundas DNI con licencia sólo porque ambas muestran nombre, DNI y fecha;
- una cédula puede tener poco texto y diseño gráfico: reconocé el tipo por su
  estructura visual, no sólo por una palabra;
- si es una foto nítida de una cédula, clasificala como cedula aunque el archivo
  se llame "WhatsApp Image...";
- no extraigas datos todavía.
"""


@dataclass
class ClasificacionAdjunto:
    tipo_documento: str = "otro"
    confianza: str = "baja"
    evidencia: list[str] = field(default_factory=list)
    fuente: str = "heuristica"
    error: str = ""


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto.upper()).strip()
    return texto


def _score_texto(texto: str):
    n = _norm(texto)
    if not n:
        return {"cedula": (0, []), "dni": (0, []), "licencia": (0, []), "poliza": (0, [])}

    reglas = {
        "cedula": (
            ("CEDULA DE IDENTIFICACION", 6), ("CEDULA IDENTIFICACION", 5),
            ("DNRPA", 5), ("REGISTRO NACIONAL DE LA PROPIEDAD", 5),
            ("REGISTRO SECCIONAL", 3), ("DOMINIO", 2), ("TITULAR", 2),
            ("NRO MOTOR", 3), ("NUMERO MOTOR", 3), ("MOTOR", 2),
            ("NRO CHASIS", 3), ("NUMERO CHASIS", 3), ("CHASIS", 2),
            ("MARCA", 1), ("MODELO", 1), ("MOTOVEHICULO", 2), ("AUTOMOTOR", 2),
        ),
        "dni": (
            ("DOCUMENTO NACIONAL DE IDENTIDAD", 8), ("DOCUMENTO NACIONAL IDENTIDAD", 7),
            ("RENAPER", 6), ("REGISTRO NACIONAL DE LAS PERSONAS", 6),
            ("DNI", 4), ("TRAMITE", 2), ("CUIL", 2), ("DOMICILIO", 1),
            ("FECHA DE NACIMIENTO", 2), ("DATE OF BIRTH", 2),
        ),
        "licencia": (
            ("LICENCIA NACIONAL DE CONDUCIR", 9), ("LICENCIA DE CONDUCIR", 8),
            ("LICENCIA CONDUCIR", 7), ("NATIONAL DRIVING LICENCE", 7),
            ("CLASES", 2), ("CLASE", 1), ("CATEGORIA", 2),
            ("VENCIMIENTO", 1), ("OTORGAMIENTO", 2),
        ),
        "poliza": (
            ("POLIZA", 6), ("CERTIFICADO DE COBERTURA", 5), ("ASEGURADO", 2),
            ("VIGENCIA", 2), ("COBERTURA", 2), ("PREMIO", 2), ("PRIMA", 2),
            ("SUMA ASEGURADA", 2), ("ENDOSO", 2), ("FORMA DE PAGO", 1),
        ),
        "cotizacion_atm": (
            ("TERCEROS COMPLETOS PLUS", 6), ("TERCEROS COMPLETOS BLACK", 6),
            ("TERCEROS COMPLETOS PREMIUM", 6), ("TODO RIESGO", 4),
            ("ROBO E INCENDIO", 3), ("SIN ASISTENCIA", 2),
        ),
    }
    salida = {}
    for tipo, reglas_tipo in reglas.items():
        score, ev = 0, []
        for token, puntos in reglas_tipo:
            if token in n:
                score += puntos
                if len(ev) < 4:
                    ev.append(token)
        salida[tipo] = [score, ev]

    # Combinación registral fuerte para cédula.
    tiene_dom = "DOMINIO" in n
    tiene_motor = "MOTOR" in n
    tiene_chasis = "CHASIS" in n
    tiene_titular = "TITULAR" in n
    if tiene_dom and tiene_motor and tiene_chasis and tiene_titular:
        salida["cedula"][0] += 6
        salida["cedula"][1].append("DOMINIO+MOTOR+CHASIS+TITULAR")
    elif tiene_dom and tiene_motor and tiene_chasis:
        salida["cedula"][0] += 4
        salida["cedula"][1].append("DOMINIO+MOTOR+CHASIS")
    return {k: (int(v[0]), list(v[1])[:4]) for k, v in salida.items()}


def clasificar_por_texto(texto: str) -> ClasificacionAdjunto | None:
    n = _norm(texto)
    if not n:
        return None
    scores = _score_texto(n)
    orden = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
    tipo, (score, evidencia) = orden[0]
    segundo = orden[1][1][0] if len(orden) > 1 else 0

    umbrales = {"cedula": 9, "dni": 7, "licencia": 7, "poliza": 7, "cotizacion_atm": 8}
    # Requerimos una ventaja razonable. DNI/licencia comparten muchos campos y,
    # si quedan cerca, la visión debe decidir en vez de forzar una etiqueta.
    if score >= umbrales[tipo] and score >= segundo + 2:
        return ClasificacionAdjunto(tipo, "alta", evidencia, "heuristica_texto")
    if score >= 5:
        return None
    if len(n) >= 220:
        return ClasificacionAdjunto("otro", "alta", ["texto sin estructura documental operativa conocida"], "heuristica_texto")
    return None


def _parse_json_robusto(texto: str) -> dict:
    bruto = str(texto or "").strip()
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", bruto, flags=re.I)
    candidatos = [limpio]
    m = re.search(r"\{.*\}", limpio, re.S)
    if m:
        candidatos.append(m.group(0))
    for candidato in candidatos:
        try:
            dato = json.loads(candidato)
            if isinstance(dato, dict):
                return dato
        except Exception:
            pass

    # Último fallback: si el modelo contestó texto corto con el tipo, no tirar
    # abajo todo el flujo por una falla cosmética de JSON.
    low = _norm(bruto)
    if "CEDULA" in low:
        return {"tipo_documento": "cedula", "confianza": "media", "evidencia": ["respuesta visual menciona cédula"]}
    if "LICENCIA" in low and ("CONDUC" in low or "DRIVING" in low):
        return {"tipo_documento": "licencia", "confianza": "media", "evidencia": ["respuesta visual menciona licencia"]}
    if "DNI" in low or "DOCUMENTO NACIONAL" in low:
        return {"tipo_documento": "dni", "confianza": "media", "evidencia": ["respuesta visual menciona DNI"]}
    if "COTIZACION_ATM" in low or ("ATM" in low and "COTIZACION" in low):
        return {"tipo_documento": "cotizacion_atm", "confianza": "media", "evidencia": ["respuesta visual identifica cotización ATM"]}
    if "POLIZA" in low:
        return {"tipo_documento": "poliza", "confianza": "media", "evidencia": ["respuesta visual menciona póliza"]}
    if "OTRO" in low:
        return {"tipo_documento": "otro", "confianza": "media", "evidencia": ["respuesta visual indica otro"]}
    raise ValueError("El clasificador visual no devolvió una salida interpretable.")



def _resultado_clasificacion_visual(dato: dict, *, fuente: str = "gemini_visual") -> ClasificacionAdjunto:
    tipo = str(dato.get("tipo_documento") or "otro").strip().lower()
    if tipo not in {"cedula", "dni", "licencia", "poliza", "cotizacion_atm", "otro"}:
        tipo = "otro"
    confianza = str(dato.get("confianza") or "baja").strip().lower()
    if confianza not in {"alta", "media", "baja"}:
        confianza = "baja"
    evidencia = dato.get("evidencia") if isinstance(dato.get("evidencia"), list) else []
    evidencia = [str(x).strip()[:160] for x in evidencia if str(x).strip()][:3]
    return ClasificacionAdjunto(tipo, confianza, evidencia, fuente)


def _clasificar_media(media, *, prompt: str, fuente: str = "gemini_visual") -> ClasificacionAdjunto:
    cliente = obtener_cliente_gemini()
    if cliente is None:
        return ClasificacionAdjunto("otro", "baja", [], "sin_gemini", "Falta GEMINI_API_KEY")
    if not media:
        return ClasificacionAdjunto("otro", "baja", [], "sin_media")
    try:
        partes = [prompt]
        for idx, blob in enumerate(media, start=1):
            partes.extend([
                f"PÁGINA/IMAGEN {idx}",
                types.Part.from_bytes(data=blob.data, mime_type=blob.mime_type),
            ])
        config = types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=280,
            response_mime_type="application/json",
            system_instruction=CLASSIFIER_SYSTEM_INSTRUCTION.strip(),
        )
        respuesta, _modelo = generate_with_fallback(
            client=cliente,
            models=DEFAULT_MODELS,
            contents=partes,
            config=config,
            log_prefix="GEMINI CLASIFICADOR ADJUNTO",
            response_validator=lambda r: _parse_json_robusto(getattr(r, "text", "")),
        )
        dato = _parse_json_robusto(getattr(respuesta, "text", ""))
        return _resultado_clasificacion_visual(dato, fuente=fuente)
    except Exception as exc:
        return ClasificacionAdjunto("otro", "baja", [], "gemini_error", str(exc)[:300])


def clasificar_adjuntos(adjuntos) -> ClasificacionAdjunto:
    """Clasifica un pequeño conjunto (máximo frente+dorso) con el MISMO clasificador.

    Se usa sólo como rescate cuando las caras por separado quedaron como ``otro``.
    No crea un segundo sistema de clasificación: reutiliza exactamente el mismo
    contrato, prompt base, parser y gateway. El extractor especializado sigue
    siendo quien confirma que ambas caras pertenecen al mismo documento/titular.
    """
    items = [a for a in list(adjuntos or []) if a is not None][:2]
    if not items:
        return ClasificacionAdjunto()
    if len(items) == 1:
        return clasificar_adjunto(items[0])

    contexto = "\n".join(str(getattr(a, "contexto", "") or "") for a in items)
    textual = clasificar_por_texto(contexto)
    if textual is not None:
        textual.fuente = "heuristica_texto_grupo"
        return textual

    if all(str(getattr(a, "tipo", "") or "") == "texto" for a in items):
        return ClasificacionAdjunto("otro", "alta", ["archivos de texto"], "heuristica_texto_grupo")

    try:
        media = renderizar_varios_para_vision(items, max_paginas_total=4, escala_pdf=1.9)
    except Exception as exc:
        return ClasificacionAdjunto("otro", "baja", [], "gemini_error", str(exc)[:300])
    return _clasificar_media(
        media,
        prompt=(
            "Clasificá estas imágenes/páginas como un conjunto. Pueden ser frente y dorso del mismo "
            "documento. Si claramente son caras del mismo DNI, licencia o cédula, devolvé ese tipo. "
            "Si son documentos de tipos incompatibles, no los fuerces a unirse: devolvé otro. "
            "No extraigas datos todavía."
        ),
        fuente="gemini_visual_grupo",
    )

def clasificar_adjunto(adjunto) -> ClasificacionAdjunto:
    if adjunto is None:
        return ClasificacionAdjunto()

    contexto = str(getattr(adjunto, "contexto", "") or "")
    textual = clasificar_por_texto(contexto)
    if textual is not None:
        return textual

    # Si es TXT y no se clasificó por texto, no hay visión que ejecutar.
    if str(getattr(adjunto, "tipo", "") or "") == "texto":
        return ClasificacionAdjunto("otro", "alta", ["archivo de texto"], "heuristica_texto")

    try:
        media = renderizar_para_vision(adjunto, max_paginas=2, escala_pdf=1.9)
    except Exception as exc:
        return ClasificacionAdjunto("otro", "baja", [], "gemini_error", str(exc)[:300])
    return _clasificar_media(
        media,
        prompt="Clasificá este adjunto. Mirá el diseño completo del documento y no te guíes por el nombre del archivo.",
        fuente="gemini_visual",
    )
