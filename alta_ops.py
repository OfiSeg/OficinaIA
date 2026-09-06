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
from payment_rules import calcular_regla_pago


COLUMNAS_ALTA_ASEGURADO = (
    "ASEGURADO", "NUMERO", "VEHICULO", "PATENTE", "ENVIOS YA", "COMPAÑIA",
    "MEDIO DE PAGO", "CODIGO POSTAL", "EMITIDO DÍA:", "IMPORTE APROX", "TELEFONO",
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

        return {
            "asegurado": limpio("asegurado"),
            "telefono": limpio("telefono"),
            "numero": limpio("numero"),
            "vehiculo": limpio("vehiculo"),
            "patente": limpio("patente"),
            "compania": normalizar_compania(limpio("compania") or _detectar_compania_poliza(texto)),
            "medio_pago": limpio("medio_pago"),
            "codigo_postal": limpio("codigo_postal"),
            "emitido": limpio("emitido"),
            "premio": limpio("premio"),
        }
    except Exception as error:
        print("ERROR GEMINI /ALTA:", error)
        raise RuntimeError(f"No pude interpretar la póliza: {error}") from error


def propuesta_a_columnas(propuesta):
    propuesta = propuesta or {}
    return {
        "ASEGURADO": propuesta.get("asegurado", ""),
        "NUMERO": propuesta.get("numero", ""),
        "VEHICULO": propuesta.get("vehiculo", ""),
        "PATENTE": propuesta.get("patente", ""),
        "ENVIOS YA": "",
        "COMPAÑIA": propuesta.get("compania", ""),
        "MEDIO DE PAGO": propuesta.get("medio_pago", ""),
        "CODIGO POSTAL": propuesta.get("codigo_postal", ""),
        "EMITIDO DÍA:": propuesta.get("emitido", ""),
        "IMPORTE APROX": propuesta.get("premio", ""),
        "TELEFONO": propuesta.get("telefono", ""),
    }


def resumen(columnas):
    columnas = columnas or {}
    asegurado = columnas.get("ASEGURADO") or ""
    compania = columnas.get("COMPAÑIA") or ""
    numero = columnas.get("NUMERO") or ""
    partes = []
    if asegurado and compania:
        partes.append(f"Leí la póliza: es de {asegurado}, en {compania}.")
    elif asegurado:
        partes.append(f"Leí la póliza: es de {asegurado}.")
    else:
        partes.append("Leí la póliza, pero no pude identificar con seguridad a nombre de quién está.")
    if numero:
        partes.append(f"El número de póliza es {numero}.")
    faltan = [
        etiqueta for etiqueta, clave in (
            ("la compañía", "COMPAÑIA"), ("el vehículo", "VEHICULO"), ("la patente", "PATENTE")
        ) if not columnas.get(clave)
    ]
    if faltan:
        partes.append(f"No encontré {', '.join(faltan)}; si lo tenés, pasámelo y lo agrego.")
    if not columnas.get("MEDIO DE PAGO"):
        partes.append("El medio de pago no queda claro en la póliza, así que lo dejé vacío para que lo completes vos.")
    if not columnas.get("CODIGO POSTAL"):
        partes.append("Tampoco encontré el código postal.")
    if not columnas.get("IMPORTE APROX"):
        partes.append("No encontré un premio identificable, así que el importe quedó vacío.")
    partes.append("Envíos Ya lo dejo vacío siempre, para que lo cargues a mano.")
    regla = calcular_regla_pago(columnas.get("COMPAÑIA"), columnas.get("MEDIO DE PAGO"))
    if regla:
        partes.append(regla["descripcion"])
    return " ".join(partes)


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
    if automatico:
        respuesta = "Reconocí que me pasaste una póliza, así que te dejo directamente la propuesta de alta. " + respuesta
    return respuesta, True, columnas


def armar_tabulado(columnas):
    valores = [str((columnas or {}).get(col, "") or "") for col in COLUMNAS_ALTA_ASEGURADO]
    return "\t".join(valores)


def a_campos_guardar_asegurado(columnas):
    columnas = columnas or {}
    return {
        "LIBRO_ID": "1",
        "ASEGURADO": columnas.get("ASEGURADO", ""),
        "NUMERO": columnas.get("NUMERO", ""),
        "VEHICULO": columnas.get("VEHICULO", ""),
        "PATENTE": columnas.get("PATENTE", ""),
        "ENVIOS YA": "",
        "CIA": normalizar_compania(columnas.get("COMPAÑIA", "")),
        "MEDIO DE PAGO": columnas.get("MEDIO DE PAGO", ""),
        "CP": columnas.get("CODIGO POSTAL", ""),
        "MAIL": "",
        "TELEFONO": columnas.get("TELEFONO", ""),
    }
