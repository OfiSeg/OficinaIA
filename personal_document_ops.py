"""Lectura estructurada de DNI y licencias para el chat de OficinaIA.

Prioriza precisión. Los campos críticos (DNI, fecha de nacimiento y CUIL cuando
aparece) se leen tres veces de forma independiente. Frente/dorso puede llegar
en el mismo turno o como dos adjuntos consecutivos; sólo se combina si las
señales visibles son compatibles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from office_time import office_today
import json
import re
import unicodedata
from typing import Any

from google.genai import types

from ai_gateway import DEFAULT_MODELS, current_state, generate_with_fallback, obtener_cliente_gemini
from resilience import parse_json_object
from attachment_vision import renderizar_varios_para_vision


PERSONAL_SYSTEM_INSTRUCTION = r"""
Sos un extractor documental ESTRICTO para documentos argentinos. Vas a recibir
una o dos imágenes/páginas que pueden ser frente/dorso de un DNI o licencia de
conducir. No calcules ni inventes datos.

TIPO esperado: {tipo_hint}

Devolvé SOLO JSON válido:
{{
  "tipo_documento": "dni|licencia|otro",
  "mismo_titular": true,
  "compatibilidad": "alta|media|baja",
  "nombre": "",
  "apellido": "",
  "dni": "",
  "fecha_nacimiento": "",
  "cuil": "",
  "domicilio": "",
  "localidad": "",
  "otorgamiento": "",
  "vencimiento": "",
  "clases": [],
  "observaciones": [],
  "caras": [
    {{
      "cara": "frente|dorso|desconocida",
      "nombre": "", "apellido": "", "dni": "", "fecha_nacimiento": "",
      "cuil": "", "domicilio": "", "localidad": "",
      "otorgamiento": "", "vencimiento": "", "clases": [], "observaciones": []
    }}
  ],
  "dni_legible": true,
  "fecha_nacimiento_legible": true,
  "cuil_legible": true,
  "dni_dudas": [],
  "fecha_nacimiento_dudas": [],
  "cuil_dudas": [],
  "advertencias": []
}}

REGLAS:
- Si no es DNI/licencia, tipo_documento="otro".
- No calcules CUIL a partir de DNI/sexo. Si no está impreso, cuil="".
- No confundas localidad con partido, provincia, organismo emisor o lugar de emisión.
- Domicilio/localidad sólo si están impresos y son identificables con seguridad.
- Para LICENCIA, extraé otorgamiento, vencimiento, clases habilitadas, descripción visible y observaciones/restricciones si están impresas.
- No inventes descripción de clases por conocimiento externo: copiá solamente lo visible.
- Si hay dos caras y muestran datos incompatibles, mismo_titular=false.
- Si no hay señales suficientes para saber si pertenecen al mismo titular,
  mismo_titular=null y compatibilidad="baja".
- No completes campos faltantes por intuición.
- Para un carácter dudoso usá ? y explicalo en *_dudas.
"""

PERSONAL_VERIFY_SYSTEM_INSTRUCTION = r"""
Actuás como transcriptor INDEPENDIENTE de un DNI o licencia argentina. No
conocés ninguna lectura previa. Mirá el/los documentos originales y transcribí
SOLAMENTE los campos críticos visibles.

Devolvé SOLO JSON válido:
{
  "dni": {"valor": "", "legible": true, "dudas": []},
  "fecha_nacimiento": {"valor": "", "legible": true, "dudas": []},
  "cuil": {"valor": "", "legible": true, "dudas": []}
}

No calcules CUIL. No infieras fecha. No corrijas por contexto. Si no aparece,
valor="" y legible=false. Si un carácter es dudoso, usá ?.
"""


class NotPersonalDocumentError(ValueError):
    pass


class DocumentosIncompatiblesError(ValueError):
    pass


@dataclass
class PersonalDocumentResult:
    datos: dict[str, Any]
    advertencias: list[str] = field(default_factory=list)


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _norm_text(v: Any) -> str:
    t = unicodedata.normalize("NFKD", _clean(v)).upper()
    return "".join(c for c in t if not unicodedata.combining(c))


def _safe_digits(v: Any) -> str:
    raw = _clean(v)
    if not raw:
        return ""
    # Sólo quitamos separadores habituales. Letras u otros símbolos quedan como
    # señal de duda, no se borran silenciosamente.
    compact = re.sub(r"[.\-\s]", "", raw)
    if re.fullmatch(r"\d+", compact):
        return compact
    return compact.upper()


def normalizar_fecha(v: Any) -> str:
    raw = _clean(v)
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw


def mostrar_fecha(v: Any) -> str:
    raw = normalizar_fecha(v)
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return raw


def mostrar_dni(v: Any) -> str:
    d = _safe_digits(v)
    if re.fullmatch(r"\d{7,8}", d):
        return f"{int(d):,}".replace(",", ".")
    return d


def mostrar_cuil(v: Any) -> str:
    d = _safe_digits(v)
    if re.fullmatch(r"\d{11}", d):
        return f"{d[:2]}-{d[2:10]}-{d[10]}"
    return d


def mostrar_fecha_documental(v: Any) -> str:
    raw = _clean(v)
    if not raw:
        return ""
    return mostrar_fecha(raw)


def _cuil_checksum_valido(v: str) -> bool:
    d = _safe_digits(v)
    if not re.fullmatch(r"\d{11}", d):
        return False
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    suma = sum(int(d[i]) * pesos[i] for i in range(10))
    mod = 11 - (suma % 11)
    dig = 0 if mod == 11 else 9 if mod == 10 else mod
    return dig == int(d[-1])


def _list(v: Any, max_items=12) -> list[str]:
    if not isinstance(v, list):
        return []
    return [_clean(x)[:220] for x in v if _clean(x)][:max_items]


def _parse_json(texto: str) -> dict:
    return parse_json_object(texto)

def _transitorio(exc: Exception) -> bool:
    t = str(exc or "").upper()
    return any(x in t for x in ("429", "500", "502", "503", "504", "TIMEOUT", "TIMED OUT", "UNAVAILABLE", "TEMPORAR"))


def _call_json(parts: list[Any], prompt: str, system: str, max_tokens: int, prefix: str) -> dict:
    client = obtener_cliente_gemini()
    if client is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")
    cfg = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
        system_instruction=system.strip(),
    )
    respuesta, _modelo = generate_with_fallback(
        client=client, models=DEFAULT_MODELS, contents=[prompt, *parts], config=cfg, log_prefix=prefix,
        response_validator=lambda r: _parse_json(getattr(r, "text", "")),
    )
    return _parse_json(getattr(respuesta, "text", ""))

def _media_parts(adjuntos: list) -> list[Any]:
    media = renderizar_varios_para_vision(adjuntos, max_paginas_total=4, escala_pdf=2.4)
    parts: list[Any] = []
    for idx, blob in enumerate(media, start=1):
        parts.extend([
            f"IMAGEN/PÁGINA {idx}",
            types.Part.from_bytes(data=blob.data, mime_type=blob.mime_type),
        ])
    return parts


def _evidence_general(d: dict, campo: str) -> dict:
    value = d.get(campo)
    if campo == "dni" or campo == "cuil":
        value = _safe_digits(value)
    elif campo == "fecha_nacimiento":
        value = normalizar_fecha(value)
    else:
        value = _clean(value)
    return {
        "valor": value,
        "legible": bool(d.get(f"{campo}_legible", bool(value and "?" not in value))),
        "dudas": _list(d.get(f"{campo}_dudas")),
    }


def _evidence_nested(d: dict, campo: str) -> dict:
    item = d.get(campo) if isinstance(d, dict) else None
    if not isinstance(item, dict):
        item = {"valor": item}
    value = item.get("valor")
    if campo in {"dni", "cuil"}:
        value = _safe_digits(value)
    elif campo == "fecha_nacimiento":
        value = normalizar_fecha(value)
    else:
        value = _clean(value)
    return {
        "valor": value,
        "legible": bool(item.get("legible", bool(value and "?" not in value))),
        "dudas": _list(item.get("dudas")),
    }


def _resolver_critico(evidencias: list[dict], *, campo: str) -> tuple[str, str, int, list[str]]:
    completos = [
        e.get("valor", "") for e in evidencias
        if e.get("valor") and e.get("legible") and "?" not in str(e.get("valor")) and not e.get("dudas")
    ]
    dudas: list[str] = []
    for e in evidencias:
        dudas.extend(_list(e.get("dudas")))
    if not completos:
        parciales = [str(e.get("valor") or "") for e in evidencias if e.get("valor")]
        if parciales:
            dudas.append("El campo tiene una lectura parcial o ambigua.")
            return parciales[0], "revisar", 0, list(dict.fromkeys(dudas))
        return "", "no_disponible", 0, list(dict.fromkeys(dudas))
    conteo = {v: completos.count(v) for v in set(completos)}
    mejor = max(conteo, key=conteo.get)
    n = conteo[mejor]
    if len(set(completos)) > 1:
        dudas.append("Las lecturas independientes devolvieron valores diferentes.")
    if campo == "dni" and not re.fullmatch(r"\d{7,8}", mejor):
        dudas.append("El formato del DNI requiere revisión.")
    if campo == "fecha_nacimiento" and mejor:
        try:
            fecha = datetime.strptime(mejor, "%Y-%m-%d")
            if fecha.date() > office_today() or fecha.year < 1900:
                dudas.append("La fecha de nacimiento requiere revisión.")
        except ValueError:
            dudas.append("El formato de la fecha de nacimiento requiere revisión.")
    if campo == "cuil" and mejor:
        if not re.fullmatch(r"\d{11}", mejor):
            dudas.append("El formato del CUIL requiere revisión.")
        elif not _cuil_checksum_valido(mejor):
            dudas.append("El dígito verificador del CUIL no coincide; revisá la lectura.")
    if n >= 3 and not dudas:
        return mejor, "alta", 3, []
    if n >= 2:
        return mejor, "media", n, list(dict.fromkeys(dudas or ["Dos lecturas coinciden; revisá antes de usar."]))
    return mejor, "revisar", 1, list(dict.fromkeys(dudas or ["No hubo coincidencia suficiente entre lecturas."]))


def _valores_caras(caras: list[dict], campo: str, normalizer) -> list[str]:
    valores: list[str] = []
    for cara in caras:
        try:
            valor = normalizer(cara.get(campo))
        except Exception:
            valor = ""
        if valor:
            valores.append(valor)
    return valores


def _conflictos_campos_caras(caras: Any) -> dict[str, list[str]]:
    """Devuelve contradicciones visibles sin resolverlas por mayoría.

    Se usa después para impedir que el valor combinado de Gemini tape un
    conflicto entre frente y dorso. Los valores se sanitizan/normalizan sólo
    de forma segura para compararlos.
    """
    if not isinstance(caras, list):
        return {}
    items = [x for x in caras[:2] if isinstance(x, dict)]
    if len(items) < 2:
        return {}
    normalizadores = {
        "dni": _safe_digits,
        "fecha_nacimiento": normalizar_fecha,
        "cuil": _safe_digits,
        "domicilio": _norm_text,
        "localidad": _norm_text,
    }
    out: dict[str, list[str]] = {}
    for campo, normalizer in normalizadores.items():
        vals = _valores_caras(items, campo, normalizer)
        unicos = list(dict.fromkeys(vals))
        if len(unicos) >= 2:
            out[campo] = unicos
    return out


def _caras_compatibles(caras: Any, mismo_titular: Any) -> tuple[bool | None, list[str]]:
    if not isinstance(caras, list) or len(caras) < 2:
        return True, []
    c = [x for x in caras[:2] if isinstance(x, dict)]
    if len(c) < 2:
        return None, ["No pude confirmar que ambas imágenes sean frente y dorso del mismo documento."]

    conflictos = _conflictos_campos_caras(c)
    warnings: list[str] = []

    # Un DNI explícitamente distinto es una señal fuerte de personas distintas.
    if "dni" in conflictos:
        return False, ["Revisar: se detectaron números de DNI distintos entre las imágenes."]
    if mismo_titular is False:
        return False, ["Las imágenes podrían corresponder a documentos o titulares diferentes."]

    nombres = []
    for x in c:
        nom = _norm_text(f"{x.get('nombre','')} {x.get('apellido','')}").strip()
        if nom:
            nombres.append(nom)
    nombre_coincide = len(nombres) >= 2 and len(set(nombres)) == 1
    nombre_conflicta = len(nombres) >= 2 and len(set(nombres)) > 1

    dni_vals = _valores_caras(c, "dni", _safe_digits)
    fecha_vals = _valores_caras(c, "fecha_nacimiento", normalizar_fecha)
    dni_coincide = len(dni_vals) >= 2 and len(set(dni_vals)) == 1
    fecha_coincide = len(fecha_vals) >= 2 and len(set(fecha_vals)) == 1

    # Contradicciones de campos no identitarios no se resuelven por intuición:
    # se permite combinar sólo si otra señal fuerte confirma el mismo titular y
    # luego el campo contradictorio se marca como REVISAR.
    for campo in ("fecha_nacimiento", "cuil", "domicilio", "localidad"):
        if campo in conflictos:
            warnings.append(
                f"Revisar: se detectaron valores distintos de {campo.replace('_', ' ')} entre frente y dorso."
            )

    if nombre_conflicta:
        warnings.append("Revisar: el nombre/apellido no coincide exactamente entre ambas lecturas.")

    if dni_coincide:
        return True, warnings
    if fecha_coincide and nombre_coincide:
        return True, warnings
    if mismo_titular is True and (fecha_coincide or nombre_coincide):
        return True, warnings

    # No depender de una sola señal blanda. Si sólo el modelo cree que es el
    # mismo titular pero no hay dato compartido verificable, pedimos revisión.
    return None, warnings + ["No pude confirmar con suficiente seguridad que ambas imágenes sean del mismo titular."]


def procesar_documento_personal(adjuntos, *, tipo_hint: str) -> PersonalDocumentResult:
    items = [a for a in (adjuntos if isinstance(adjuntos, (list, tuple)) else [adjuntos]) if a is not None]
    if not items:
        raise ValueError("No hay adjuntos para leer.")
    tipo_hint = str(tipo_hint or "").lower()
    if tipo_hint not in {"dni", "licencia"}:
        raise ValueError("Tipo personal no soportado.")
    parts = _media_parts(items)
    if not parts:
        raise ValueError("No hay contenido visual para leer el documento.")

    general = _call_json(
        parts,
        "Leé el documento completo. Si hay dos imágenes, determiná si son frente/dorso del mismo titular y combiná sólo datos compatibles.",
        PERSONAL_SYSTEM_INSTRUCTION.format(tipo_hint=tipo_hint),
        1500,
        "GEMINI DOCUMENTO PERSONAL GENERAL",
    )
    tipo_detectado = str(general.get("tipo_documento") or "otro").lower()
    if tipo_detectado not in {tipo_hint, "dni", "licencia"}:
        raise NotPersonalDocumentError("La lectura visual no confirmó un DNI/licencia.")
    if tipo_detectado != tipo_hint and tipo_hint in {"dni", "licencia"}:
        # No fusionar DNI y licencia como si fueran dos caras del mismo documento.
        raise NotPersonalDocumentError("El documento detectado no coincide con el tipo esperado.")

    caras = general.get("caras") if isinstance(general.get("caras"), list) else []
    es_multicara = len(items) > 1 or len([x for x in caras if isinstance(x, dict)]) > 1
    compatible, avisos_union = _caras_compatibles(caras, general.get("mismo_titular"))
    if es_multicara and compatible is not True:
        raise DocumentosIncompatiblesError(" ".join(avisos_union) or "Las imágenes no pudieron combinarse con seguridad.")
    conflictos_caras = _conflictos_campos_caras(caras) if es_multicara else {}

    v1 = _call_json(parts, "Primera verificación independiente de DNI, fecha de nacimiento y CUIL visible.", PERSONAL_VERIFY_SYSTEM_INSTRUCTION, 650, "GEMINI DOCUMENTO PERSONAL V1")
    v2 = _call_json(parts, "Segunda verificación independiente de DNI, fecha de nacimiento y CUIL visible. No presupongas ninguna lectura previa.", PERSONAL_VERIFY_SYSTEM_INSTRUCTION, 650, "GEMINI DOCUMENTO PERSONAL V2")

    resolved = {}
    warnings = _list(general.get("advertencias")) + avisos_union
    for campo in ("dni", "fecha_nacimiento", "cuil"):
        val, estado, coinc, dudas = _resolver_critico(
            [_evidence_general(general, campo), _evidence_nested(v1, campo), _evidence_nested(v2, campo)],
            campo=campo,
        )
        # Si frente/dorso contradicen explícitamente este campo, no elegir una
        # versión arbitraria aunque las lecturas globales hayan convergido.
        if campo in conflictos_caras:
            val = ""
            estado = "revisar"
            coinc = 0
            dudas = list(dict.fromkeys([
                *dudas,
                f"Revisar: frente y dorso muestran valores distintos de {campo.replace('_', ' ')}.",
            ]))
        # CUIL ausente en las tres lecturas es correcto: nunca se calcula.
        resolved[campo] = val
        resolved[f"estado_{campo}"] = estado
        resolved[f"coincidencias_{campo}"] = coinc
        resolved[f"dudas_{campo}"] = dudas
        warnings.extend(dudas[:2])

    datos = {
        "tipo_documento": tipo_hint,
        "nombre": _clean(general.get("nombre")),
        "apellido": _clean(general.get("apellido")),
        "caras_combinadas": es_multicara,
        **resolved,
    }
    for campo in ("domicilio", "localidad"):
        if campo in conflictos_caras:
            datos[campo] = ""
            datos[f"estado_{campo}"] = "revisar"
            datos[f"dudas_{campo}"] = [
                f"Revisar: frente y dorso muestran valores distintos de {campo}."
            ]
        else:
            valor_simple = _clean(general.get(campo))
            datos[campo] = valor_simple
            datos[f"estado_{campo}"] = "disponible" if valor_simple else "no_disponible"
            datos[f"dudas_{campo}"] = []

    # Campos informativos de licencia/DNI: se copian sólo si están visibles en
    # la lectura general. No participan del bloqueo crítico, pero sí aparecen en
    # la card y en la copia para no perder información útil de frente+dorso.
    for campo in ("otorgamiento", "vencimiento"):
        valor_simple = _clean(general.get(campo))
        datos[campo] = valor_simple
        datos[f"{campo}_mostrar"] = mostrar_fecha_documental(valor_simple)
        datos[f"estado_{campo}"] = "disponible" if valor_simple else "no_disponible"
        datos[f"dudas_{campo}"] = []
    clases = general.get("clases") if isinstance(general.get("clases"), list) else []
    datos["clases"] = [_clean(x) for x in clases if _clean(x)][:12]
    observaciones = general.get("observaciones") if isinstance(general.get("observaciones"), list) else []
    datos["observaciones"] = [_clean(x) for x in observaciones if _clean(x)][:12]
    # Presentación separada del valor normalizado para evitar inconsistencias.
    datos["dni_mostrar"] = mostrar_dni(datos.get("dni"))
    datos["fecha_nacimiento_mostrar"] = mostrar_fecha(datos.get("fecha_nacimiento"))
    datos["cuil_mostrar"] = mostrar_cuil(datos.get("cuil"))
    warnings = list(dict.fromkeys(x for x in warnings if x))
    return PersonalDocumentResult(datos, warnings)


def resumen_documento_personal(resultado: PersonalDocumentResult) -> str:
    d = resultado.datos
    tipo = "DNI" if d.get("tipo_documento") == "dni" else "Licencia"
    combinado = " Frente y dorso quedaron combinados." if d.get("caras_combinadas") else ""
    criticos = [d.get("estado_dni"), d.get("estado_fecha_nacimiento")]
    if d.get("cuil"):
        criticos.append(d.get("estado_cuil"))
    if criticos and all(x == "alta" for x in criticos):
        return f"{tipo} detectado.{combinado} Te dejo los datos para copiar."
    return f"{tipo} detectado.{combinado} Te dejo lo legible y marqué lo que necesita revisión."
