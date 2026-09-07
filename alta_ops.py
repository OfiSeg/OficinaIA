"""Dominio de alta individual de asegurados desde pólizas.

V20 Etapa 4: módulo puro respecto de Flask/sesión/DB. Toda llamada de IA pasa
por ai_gateway; el flujo sigue siendo de un solo turno.
"""
import json
import re
from google.genai import types

from ai_gateway import generate_with_fallback, obtener_cliente_gemini, DEFAULT_MODELS
from companias import normalizar_compania, aliases_companias
from domain_prompts import ALTA_SYSTEM_INSTRUCTION
from payment_rules import calcular_regla_pago, normalizar_medio_pago


COLUMNAS_ALTA_ASEGURADO = (
    "ASEGURADO", "NUMERO", "VEHICULO", "PATENTE", "ENVIOS YA", "COMPAÑIA",
    "MEDIO DE PAGO", "CODIGO POSTAL", "EMITIDO DÍA:", "IMPORTE APROX",
    "DE DONDE ", "MAIL", "TELEFONO",
)

MENSAJE_PDF_POR_DEFECTO = "Analizá el PDF que acabo de adjuntar y explicame de qué trata."
PATENTE_REGEX_ALTA = re.compile(r"\b[A-Z]{2}\d{3}[A-Z]{2}\b|\b[A-Z]{3}\d{3}\b")


def pdf_parece_poliza_individual(contexto_pdf_adjunto):
    texto = str(contexto_pdf_adjunto or "")
    if not texto.strip():
        return False
    patentes = {m.group(0).upper() for m in PATENTE_REGEX_ALTA.finditer(texto)}
    if len(patentes) >= 2:
        return False
    if len(re.findall(r"(?:^|\n)\s*(?:ITEM|ÍTEM|N[°º]\s*\d+)\b", texto, re.IGNORECASE)) >= 2:
        return False
    return bool(re.search(
        r"\b(P[ÓO]LIZA|ASEGURADO|PREMIO|PRIMA|COBERTURA|VIGENCIA|CERTIFICADO)\b",
        texto, re.IGNORECASE,
    ))


def _companias_conocidas():
    # Una sola fuente de verdad: la tabla canónica de companias.py.
    vistos = []
    for _alias, (_codigo, display) in aliases_companias().items():
        if display not in vistos:
            vistos.append(display)
    return vistos


def _detectar_compania_poliza(texto):
    texto_norm = str(texto or "")
    m = re.search(r"COMPA[ÑN][IÍ]A\s*:?\s*([A-ZÁÉÍÓÚÑ .]{3,40})", texto_norm, re.IGNORECASE)
    if m:
        candidato = re.sub(r"\s+", " ", m.group(1)).strip(" .")
        if candidato:
            return candidato
    for nombre in _companias_conocidas():
        if re.search(rf"\b{re.escape(nombre)}\b", texto_norm, re.IGNORECASE):
            return nombre
    return ""




def _detectar_medio_pago_poliza(texto):
    fuente = str(texto or "")
    # Primero miramos la línea/cercanía de una etiqueta explícita de pago.
    m = re.search(
        r"(?:FORMA|MEDIO|MODALIDAD)\s+DE\s+PAGO\s*[:\-]?\s*([^\n\r]{0,100})",
        fuente, re.IGNORECASE,
    )
    if m:
        medio = normalizar_medio_pago(m.group(1))
        if medio:
            return medio
    # Fallback conservador: sólo expresiones inequívocas.
    patrones = (
        (r"\bCUPONERA\b|\bCUP[ÓO]N(?:ES)?\b", "CUPONERA"),
        (r"\bTARJETA(?:\s+DE)?\s+(?:CR[ÉE]DITO|D[ÉE]BITO)\b|\bVISA\b|\bMASTERCARD\b|\bAMEX\b", "CREDITO"),
        (r"\bCBU\b|\bD[ÉE]BITO\s+AUTOM[ÁA]TICO(?:\s+EN\s+CUENTA)?\b", "CBU"),
    )
    for patron, valor in patrones:
        if re.search(patron, fuente, re.IGNORECASE):
            return valor
    return ""


def _detectar_fecha_emision_poliza(texto):
    fuente = str(texto or "")
    patrones = (
        r"FECHA\s+DE\s+EMISI[ÓO]N\s*[:\-]?\s*(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})",
        r"EMISI[ÓO]N\s*[:\-]?\s*(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})",
        r"EMITID[AO]\s+(?:EL\s+)?(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})",
    )
    for patron in patrones:
        m = re.search(patron, fuente, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _detectar_premio_poliza(texto):
    fuente = str(texto or "")
    patrones = (
        r"PREMIO\s+TOTAL\s*[:\-]?\s*\$?\s*([0-9][0-9.]*?(?:,[0-9]{1,2})?)(?=\s|$)",
        r"PREMIO\s*[:\-]?\s*\$?\s*([0-9][0-9.]*?(?:,[0-9]{1,2})?)(?=\s|$)",
        r"TOTAL\s+A\s+PAGAR\s*[:\-]?\s*\$?\s*([0-9][0-9.]*?(?:,[0-9]{1,2})?)(?=\s|$)",
    )
    for patron in patrones:
        m = re.search(patron, fuente, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""

def _normalizar_fecha_emision(valor):
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if not texto:
        return ""
    m = re.search(r"\b(\d{1,2})[\-/\.](\d{1,2})[\-/\.](\d{2,4})\b", texto)
    if not m:
        return texto
    dia, mes, anio = m.groups()
    if len(anio) == 2:
        anio = "20" + anio
    try:
        d, mo, y = int(dia), int(mes), int(anio)
        if not (1 <= d <= 31 and 1 <= mo <= 12 and 2000 <= y <= 2100):
            return texto
    except ValueError:
        return texto
    return f"{d:02d}/{mo:02d}/{y:04d}"


def _normalizar_importe(valor):
    texto = str(valor or "").strip()
    if not texto:
        return ""
    limpio = re.sub(r"[^0-9,.-]", "", texto)
    if not limpio:
        return ""
    # Formato argentino habitual: 94.207,30 -> 94207.30
    if "," in limpio:
        entero, decimal = limpio.rsplit(",", 1)
        entero = entero.replace(".", "").replace(",", "")
        decimal = re.sub(r"\D", "", decimal)
        numero = entero + ("." + decimal if decimal else "")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", limpio):
        numero = limpio.replace(".", "")
    else:
        numero = limpio
    return numero.strip(".")

def interpretar_poliza_a_json(texto):
    texto = str(texto or "").replace("\r", "")
    if not texto.strip():
        return {}
    cliente = obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")

    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=1500,
        response_mime_type="application/json",
        system_instruction=ALTA_SYSTEM_INSTRUCTION.strip(),
    )
    try:
        respuesta, _modelo = generate_with_fallback(
            client=cliente,
            models=DEFAULT_MODELS,
            contents=texto.strip(),
            config=config,
            log_prefix="GEMINI /ALTA",
        )
        bruto = str(getattr(respuesta, "text", "") or "").strip()
        if not bruto:
            raise ValueError("Gemini no devolvió JSON.")
        datos = json.loads(bruto)
        if not isinstance(datos, dict):
            raise ValueError("Gemini no devolvió un objeto JSON.")

        def limpio(clave):
            return re.sub(r"\s+", " ", str(datos.get(clave, "") or "")).strip()

        medio_pago = normalizar_medio_pago(limpio("medio_pago")) or _detectar_medio_pago_poliza(texto)
        emitido = _normalizar_fecha_emision(limpio("emitido") or _detectar_fecha_emision_poliza(texto))
        premio = _normalizar_importe(limpio("premio") or _detectar_premio_poliza(texto))
        return {
            "asegurado": limpio("asegurado"),
            "vehiculo": limpio("vehiculo"),
            "patente": limpio("patente").upper(),
            "compania": normalizar_compania(limpio("compania") or _detectar_compania_poliza(texto)),
            "medio_pago": medio_pago,
            "codigo_postal": limpio("codigo_postal"),
            "emitido": emitido,
            "premio": premio,
        }
    except Exception as error:
        print("ERROR GEMINI /ALTA:", error)
        raise RuntimeError(f"No pude interpretar la póliza: {error}") from error


def propuesta_a_columnas(propuesta):
    propuesta = propuesta or {}
    return {
        "ASEGURADO": propuesta.get("asegurado", ""),
        # NUMERO es el teléfono histórico de la planilla. Nunca se completa
        # desde una póliza: queda manual.
        "NUMERO": "",
        "VEHICULO": propuesta.get("vehiculo", ""),
        "PATENTE": propuesta.get("patente", ""),
        "ENVIOS YA": "",
        "COMPAÑIA": propuesta.get("compania", ""),
        "MEDIO DE PAGO": normalizar_medio_pago(propuesta.get("medio_pago", "")),
        "CODIGO POSTAL": propuesta.get("codigo_postal", ""),
        "EMITIDO DÍA:": propuesta.get("emitido", ""),
        "IMPORTE APROX": propuesta.get("premio", ""),
        "DE DONDE ": "",
        "MAIL": "",
        # Campo legado/alternativo: también queda manual y no se extrae del PDF.
        "TELEFONO": "",
    }


def resumen(columnas):
    columnas = columnas or {}
    asegurado = str(columnas.get("ASEGURADO") or "").strip()
    if asegurado:
        return f"Póliza detectada. Preparé el alta de {asegurado} para revisar y guardar."
    return "Póliza detectada. Preparé el alta para revisar y guardar."


def procesar(mensaje, contexto_pdf_adjunto, automatico=False):
    if not re.match(r"^/alta\b", str(mensaje or ""), re.IGNORECASE):
        return None, False, None
    texto_comando = re.sub(r"^/alta\s*", "", mensaje, count=1, flags=re.IGNORECASE).strip()
    fuente = texto_comando
    if contexto_pdf_adjunto:
        fuente = f"{texto_comando}\n\n{contexto_pdf_adjunto}".strip() if texto_comando else contexto_pdf_adjunto
    if not fuente:
        return (
            "Para dar de alta un asegurado desde una póliza, adjuntame el PDF "
            "(con el clip o arrastrándolo al chat) y escribí /alta, o pegame "
            "el texto del frente de póliza después de /alta.", True, None,
        )
    try:
        propuesta = interpretar_poliza_a_json(fuente)
    except Exception as error:
        print("ERROR PROCESANDO /ALTA:", error)
        return (
            "No pude leer bien esa póliza para armar el alta. Probá adjuntarla "
            "de nuevo o pegar el texto del frente.", True, None,
        )
    columnas = propuesta_a_columnas(propuesta)
    respuesta = resumen(columnas)
    # La UI muestra la ficha compacta inmediatamente debajo. No agregamos
    # explicación redundante aunque el alta se haya detectado automáticamente.
    return respuesta, True, columnas


def armar_tabulado(columnas):
    valores = [str((columnas or {}).get(col, "") or "") for col in COLUMNAS_ALTA_ASEGURADO]
    return "\t".join(valores)


def a_campos_guardar_asegurado(columnas):
    columnas = columnas or {}
    return {
        "LIBRO_ID": "1",
        "ASEGURADO": columnas.get("ASEGURADO", ""),
        "NUMERO": "",
        "VEHICULO": columnas.get("VEHICULO", ""),
        "PATENTE": columnas.get("PATENTE", ""),
        "ENVIOS YA": "",
        "CIA": normalizar_compania(columnas.get("COMPAÑIA", "")),
        "MEDIO DE PAGO": normalizar_medio_pago(columnas.get("MEDIO DE PAGO", "")),
        "CP": columnas.get("CODIGO POSTAL", ""),
        "EMITIDO DÍA:": columnas.get("EMITIDO DÍA:", ""),
        "IMPORTE APROX": columnas.get("IMPORTE APROX", ""),
        "MAIL": "",
        "TELEFONO": "",
    }

