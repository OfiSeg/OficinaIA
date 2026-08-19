# -*- coding: utf-8 -*-
"""Comando determinístico /coti de OficinaIA.

La lógica de /coti es deliberadamente independiente de Gemini.
Las compañías y coberturas son datos/configuración para poder ampliarlos
sin modificar el parser.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


# Catálogo inicial. Para agregar compañías en el futuro, modificar solamente
# este diccionario. No hace falta tocar procesar_comando_coti().
COMPANIAS_COTI = {
    "allianz": "Allianz",
    "ags": "AGS",
    "federacion patronal": "Federación Patronal",
    "atm": "ATM",
    "mercantil andina": "Mercantil Andina",
    "san cristobal": "San Cristóbal",
    "prof": "Prof",
    "euroamerica": "Euroamerica",
    "triunfo": "Triunfo",
    "rivadavia": "Rivadavia",
}


# Los códigos alternativos se normalizan al código canónico antes de buscar
# la cobertura. Así C1/CF/CM/CPLUS/C PLUS comparten la misma definición.
ALIAS_COBERTURAS_COTI = {
    "a": "a",
    "a1": "a1",
    "b": "b",
    "b1": "b1",
    "b2": "b2",
    "b3": "b3",
    "c": "c",
    "c1": "cplus",
    "cf": "cplus",
    "cm": "cplus",
    "cplus": "cplus",
}


COBERTURAS_COTI = {
    "a": {
        "codigo": "A",
        "nombre": "Responsabilidad Civil con grúa",
        "incluye": ["Responsabilidad Civil", "Grúa"],
    },
    "a1": {
        "codigo": "A1",
        "nombre": "Responsabilidad Civil sin grúa",
        "incluye": ["Responsabilidad Civil", "sin grúa"],
    },
    "b": {
        "codigo": "B",
        "nombre": "Terceros Básico",
        "incluye": ["Robo total", "Incendio total", "Destrucción total"],
    },
    "b1": {
        "codigo": "B1",
        "nombre": "Terceros Básico",
        "incluye": ["Robo total", "Incendio total"],
    },
    "b2": {
        "codigo": "B2",
        "nombre": "Terceros Básico",
        "incluye": ["Robo total", "Destrucción total"],
    },
    "b3": {
        "codigo": "B3",
        "nombre": "Terceros Básico",
        "incluye": ["Incendio total"],
    },
    "c": {
        "codigo": "C",
        "nombre": "Terceros Completo",
        "incluye": [
            "Responsabilidad Civil",
            "Incendio total",
            "Incendio parcial",
            "Robo total",
            "Robo parcial",
            "Destrucción total por accidente",
            "Ruedas",
            "Vidrios",
        ],
    },
    "cplus": {
        "codigo": "C1",
        "nombre": "Terceros Completo Plus",
        "incluye": [
            "Responsabilidad Civil",
            "Incendio total",
            "Incendio parcial",
            "Robo total",
            "Robo parcial",
            "Destrucción total por accidente",
            "Ruedas",
            "Vidrios",
            "Granizo",
            "Cerraduras",
        ],
    },
}


def _normalizar_texto(valor: str) -> str:
    """Normaliza espacios, mayúsculas/minúsculas y acentos para comparar."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(
        caracter for caracter in texto
        if not unicodedata.combining(caracter)
    )
    texto = re.sub(r"\s+", " ", texto).strip().casefold()
    return texto


def _normalizar_cobertura(valor: str) -> str:
    """Convierte variantes como 'C PLUS' en la clave canónica."""
    clave = _normalizar_texto(valor).replace(" ", "")
    return ALIAS_COBERTURAS_COTI.get(clave, "")


def _normalizar_importe(valor: str) -> Optional[int]:
    """Convierte importes argentinos simples a enteros.

    Acepta, por ejemplo:
      18000000
      18.000.000
      $18.000.000
      85.000
      $85.000
    """
    texto = str(valor or "").strip()
    if not texto:
        return None

    texto = texto.replace("$", "").replace(" ", "")
    if not texto:
        return None

    # Para el formato de cotización se esperan importes enteros.
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", texto):
        return None

    # La entrada argentina habitual usa puntos/comas como separadores de miles.
    # Como suma y precio se manejan como pesos enteros, se eliminan ambos.
    digitos = re.sub(r"[.,]", "", texto)
    try:
        return int(digitos)
    except (TypeError, ValueError):
        return None


def _formatear_pesos(valor: int) -> str:
    return f"${valor:,}".replace(",", ".")


def _formatear_lista(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} y {items[1]}"
    return ", ".join(items[:-1]) + f" y {items[-1]}"


def _buscar_compania_y_resto(argumentos: str):
    """Busca una compañía registrada al comienzo del argumento.

    Se prueban primero las compañías más largas para soportar nombres de varias
    palabras sin depender de posiciones fijas.
    """
    candidatos = sorted(
        COMPANIAS_COTI.items(),
        key=lambda item: len(_normalizar_texto(item[0])),
        reverse=True,
    )
    texto_normalizado = _normalizar_texto(argumentos)

    for clave, nombre in candidatos:
        clave_normalizada = _normalizar_texto(clave)
        if texto_normalizado == clave_normalizada:
            return nombre, ""

        prefijo = clave_normalizada + " "
        if texto_normalizado.startswith(prefijo):
            resto = texto_normalizado[len(prefijo):].strip()
            return nombre, resto

    return None, texto_normalizado


def _respuesta_error_formato() -> str:
    return (
        "Formato incorrecto.\n\n"
        "Formato correcto:\n"
        "/coti COMPAÑIA COBERTURA SUMA_ASEGURADA PRECIO_MENSUAL"
    )


def procesar_comando_coti(texto: str):
    """Procesa /coti y devuelve una respuesta local o None.

    Devuelve None si el mensaje no es un comando /coti.
    Devuelve texto de respuesta si sí es /coti, incluso cuando contiene un
    error de validación.
    """
    mensaje = str(texto or "").strip()
    if not re.match(r"^/coti(?:\s|$)", mensaje, flags=re.IGNORECASE):
        return None

    argumentos = re.sub(
        r"^/coti(?:\s+|$)",
        "",
        mensaje,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    if not argumentos:
        return _respuesta_error_formato()

    compania, resto = _buscar_compania_y_resto(argumentos)

    if compania is None:
        primer_token = re.split(r"\s+", argumentos, maxsplit=1)[0]
        disponibles = ", ".join(COMPANIAS_COTI.values())
        return (
            f'La compañía "{primer_token}" no está registrada para /coti.\n\n'
            f"Compañías disponibles: {disponibles}."
        )

    if not resto:
        return _respuesta_error_formato()

    partes = resto.split()
    # "C PLUS" es una variante de la cobertura C1/CPLUS y ocupa dos tokens.
    if len(partes) >= 2 and _normalizar_texto(partes[0]) == "c" and _normalizar_texto(partes[1]) == "plus":
        partes = ["CPLUS"] + partes[2:]

    if len(partes) < 3:
        faltante = {
            0: "la cobertura, la suma asegurada y el precio mensual",
            1: "la suma asegurada y el precio mensual",
            2: "el precio mensual",
        }.get(len(partes), "los datos requeridos")
        return (
            f"Falta {faltante}.\n\n"
            + _respuesta_error_formato()
        )

    cobertura_ingresada = partes[0]
    suma_texto = partes[1]
    precio_texto = partes[2]

    cobertura_clave = _normalizar_cobertura(cobertura_ingresada)
    if not cobertura_clave:
        disponibles = "A, A1, B, B1, B2, B3, C, C1, CF, CM, CPLUS"
        return (
            f'La cobertura "{cobertura_ingresada}" no está registrada para /coti.\n\n'
            f"Coberturas disponibles: {disponibles}."
        )

    suma = _normalizar_importe(suma_texto)
    if suma is None:
        return (
            f'La suma asegurada "{suma_texto}" no es válida.\n\n'
            "Ejemplos válidos: 18000000, 18.000.000 o $18.000.000."
        )

    precio = _normalizar_importe(precio_texto)
    if precio is None:
        return (
            f'El precio mensual "{precio_texto}" no es válido.\n\n'
            "Ejemplos válidos: 85000, 85.000 o $85.000."
        )

    # Si sobran tokens, es mejor informar el formato en vez de ignorarlos.
    if len(partes) > 3:
        return (
            "Hay datos de más en el comando /coti.\n\n"
            + _respuesta_error_formato()
        )

    cobertura = COBERTURAS_COTI[cobertura_clave]
    descripcion = _formatear_lista(cobertura["incluye"])

    return (
        f"Te envío cotización en {compania}.\n\n"
        f"Cobertura: {cobertura['codigo']} — {cobertura['nombre']}.\n"
        f"Incluye {descripcion}.\n\n"
        f"Suma asegurada: {_formatear_pesos(suma)}\n"
        f"Precio mensual: {_formatear_pesos(precio)}"
    )


__all__ = [
    "COMPANIAS_COTI",
    "COBERTURAS_COTI",
    "procesar_comando_coti",
]
