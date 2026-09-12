# -*- coding: utf-8 -*-
"""Lectura especializada de capturas del cotizador web de ATM.

No analiza pólizas ni documentación general. Recibe una captura, extrae sólo
nombres/precios/franquicias y delega las descripciones al catálogo local.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re

from google.genai import types

from ai_gateway import DEFAULT_MODELS, generate_with_fallback, obtener_cliente_gemini
from attachment_vision import renderizar_para_vision
from atm_coberturas import enriquecer_cobertura
from resilience import RecoverablePayloadError


SYSTEM_INSTRUCTION = r"""
Sos un lector ESTRICTO de capturas del cotizador web de ATM Seguros.
Tu única tarea es transcribir las opciones de cobertura y sus precios visibles.
NO expliques coberturas. NO inventes importes. NO completes texto cortado.

Devolvé SOLO JSON válido con este formato:
{
  "es_cotizacion_atm": true,
  "coberturas": [
    {
      "titulo": "texto visible de la cobertura",
      "precio": "198375.98",
      "franquicia_pct": "3",
      "sin_asistencia": false,
      "confianza": "alta|media|baja"
    }
  ],
  "advertencias": []
}

Reglas:
- Si la imagen no es una pantalla/listado de cotización ATM, es_cotizacion_atm=false.
- Un precio argentino como $ 198.375,98 debe devolverse como "198375.98".
- Cada precio debe asociarse únicamente a su título visible.
- Si dice "SIN ASISTENCIA", sin_asistencia=true.
- En Todo Riesgo, extraé el porcentaje de franquicia si está visible; si no, "".
- No confundas porcentajes de franquicia con descuentos.
- Si un precio o título no se lee con seguridad, confianza="baja" y agregá una advertencia breve.
- Omití filas que no tengan un precio identificable. Nunca adivines.
"""


def _json_robusto(texto: str) -> dict:
    raw = str(texto or "").strip()
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
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
            continue
    raise RecoverablePayloadError("La lectura ATM no devolvió JSON válido.")


def _precio_decimal(valor) -> str | None:
    texto = str(valor or "").strip().replace("$", "").replace(" ", "")
    if not texto:
        return None
    # Soporta tanto salida normalizada del modelo como formato AR visible.
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", texto):
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    texto = re.sub(r"[^0-9.]", "", texto)
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError):
        return None
    if numero <= 0:
        return None
    return format(numero, "f")


def _franquicia(valor, titulo: str = "") -> str:
    texto = str(valor or "").strip().replace(",", ".")
    if not texto:
        m = re.search(r"(?:FRANQUICIA|FRANQ\.?)[^0-9]{0,10}(\d{1,2}(?:[.,]\d+)?)\s*%", str(titulo or ""), re.I)
        texto = m.group(1).replace(",", ".") if m else ""
    try:
        n = Decimal(texto)
    except Exception:
        return ""
    if n <= 0 or n > 100:
        return ""
    return str(int(n)) if n == n.to_integral_value() else format(n.normalize(), "f")


def _normalizar_salida(dato: dict) -> dict:
    es_atm = bool(dato.get("es_cotizacion_atm"))
    coberturas = []
    for idx, item in enumerate(dato.get("coberturas") or []):
        if not isinstance(item, dict):
            continue
        titulo = re.sub(r"\s+", " ", str(item.get("titulo") or "")).strip()
        precio = _precio_decimal(item.get("precio"))
        if not titulo or not precio:
            continue
        sin_asistencia = bool(item.get("sin_asistencia")) or bool(re.search(r"SIN\s+ASISTENCIA", titulo, re.I))
        catalogo = enriquecer_cobertura(titulo, sin_asistencia=sin_asistencia)
        confianza = str(item.get("confianza") or "media").strip().lower()
        if confianza not in {"alta", "media", "baja"}:
            confianza = "media"
        franquicia = _franquicia(item.get("franquicia_pct"), titulo)
        coberturas.append({
            "uid": f"atm-{idx+1}",
            "titulo_leido": titulo,
            "precio_base": precio,
            "franquicia_pct": franquicia,
            "confianza": confianza,
            "requiere_revision": confianza == "baja" or not catalogo.get("catalogada"),
            **catalogo,
        })
    advertencias = [str(x).strip()[:220] for x in (dato.get("advertencias") or []) if str(x).strip()]
    if es_atm and not coberturas:
        advertencias.append("Detecté la pantalla de ATM, pero no pude confirmar ningún precio.")
    return {
        "es_cotizacion_atm": es_atm,
        "coberturas": coberturas,
        "advertencias": list(dict.fromkeys(advertencias)),
    }


def extraer_cotizacion_atm(adjunto) -> dict:
    media = renderizar_para_vision(adjunto, max_paginas=1, escala_pdf=1.7)
    if not media:
        raise ValueError("No recibí una imagen válida para leer la cotización ATM.")
    cliente = obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")
    partes = [
        "Leé esta captura. Extraé todas las filas de coberturas con su precio visible.",
        types.Part.from_bytes(data=media[0].data, mime_type=media[0].mime_type),
    ]
    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=1800,
        response_mime_type="application/json",
        system_instruction=SYSTEM_INSTRUCTION.strip(),
    )
    respuesta, _modelo = generate_with_fallback(
        client=cliente,
        models=DEFAULT_MODELS,
        contents=partes,
        config=config,
        log_prefix="GEMINI COTIZACION ATM",
        response_validator=lambda r: _json_robusto(getattr(r, "text", "")),
    )
    dato = _json_robusto(getattr(respuesta, "text", ""))
    return _normalizar_salida(dato)


__all__ = ["extraer_cotizacion_atm"]
