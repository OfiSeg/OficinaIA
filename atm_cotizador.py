# -*- coding: utf-8 -*-
"""Cotizador determinístico ATM.

Fuente única de verdad para la relación de adhesión y los presets comerciales.
No depende de Gemini ni del frontend.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP, getcontext
import re
import unicodedata

getcontext().prec = 28

ATM_FACTOR_ADHESION = Decimal(5) / Decimal(6)
ATM_DESCUENTO_AUTO = Decimal("50")
ATM_DESCUENTO_MOTO = Decimal("30")
ATM_DESCUENTO_MIN = Decimal("1")
ATM_DESCUENTO_MAX = Decimal("50")


def _normalizar_texto(valor: str) -> str:
    t = unicodedata.normalize("NFKD", str(valor or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().casefold()


def _decimal_precio(valor) -> Decimal:
    if isinstance(valor, Decimal):
        numero = valor
    else:
        texto = str("" if valor is None else valor).strip().replace("$", "").replace(" ", "")
        if not texto:
            raise ValueError("Ingresá un precio base ATM.")
        # Para este cotizador el precio base se carga en pesos. Aceptamos miles
        # argentinos (158.561) o número plano (158561).
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto):
            texto = texto.replace(".", "")
        elif re.fullmatch(r"\d+(?:,\d+)?", texto):
            texto = texto.replace(",", ".")
        elif not re.fullmatch(r"\d+(?:\.\d+)?", texto):
            raise ValueError("El precio base no es válido.")
        try:
            numero = Decimal(texto)
        except InvalidOperation as exc:
            raise ValueError("El precio base no es válido.") from exc
    if numero <= 0:
        raise ValueError("El precio base debe ser mayor que 0.")
    return numero


def _decimal_descuento(valor) -> Decimal:
    texto = str(valor if valor is not None else "").strip().replace("%", "").replace(",", ".")
    try:
        porcentaje = Decimal(texto)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("El descuento debe ser un número entre 1 y 50.") from exc
    if porcentaje < ATM_DESCUENTO_MIN or porcentaje > ATM_DESCUENTO_MAX:
        raise ValueError("El descuento debe estar entre 1% y 50%.")
    return porcentaje


def resolver_descuento(*, tipo: str | None = None, descuento=None) -> tuple[Decimal, str]:
    """Devuelve (porcentaje, origen). El manual siempre tiene prioridad."""
    if descuento is not None and str(descuento).strip() != "":
        return _decimal_descuento(descuento), "manual"
    t = _normalizar_texto(tipo)
    if t == "auto":
        return ATM_DESCUENTO_AUTO, "preset_auto"
    if t == "moto":
        return ATM_DESCUENTO_MOTO, "preset_moto"
    raise ValueError("Ingresá un descuento manual entre 1% y 50%.")


def calcular_atm(precio_base, porcentaje_descuento) -> dict:
    base = _decimal_precio(precio_base)
    descuento = _decimal_descuento(porcentaje_descuento)
    adherido = base * ATM_FACTOR_ADHESION
    factor_descuento = Decimal(1) - (descuento / Decimal(100))
    base_descuento = base * factor_descuento
    adherido_descuento = adherido * factor_descuento
    return {
        "precio_base": base,
        "precio_adherido": adherido,
        "descuento": descuento,
        "precio_base_descuento": base_descuento,
        "precio_adherido_descuento": adherido_descuento,
    }


def _redondear_pesos(valor: Decimal) -> int:
    # ROUND_HALF_EVEN preserva el ejemplo validado 158561 * 50% => 79.280.
    return int(valor.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def formatear_pesos(valor: Decimal) -> str:
    return f"${_redondear_pesos(valor):,}".replace(",", ".")


def redondear_comercial_miles(valor: Decimal) -> int:
    """Redondeo comercial sólo de presentación: $xx.500 sube al millar siguiente."""
    miles = (Decimal(valor) / Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(miles * Decimal("1000"))


def formatear_comercial_miles(valor: Decimal) -> str:
    return f"${redondear_comercial_miles(valor):,}".replace(",", ".")


def _porcentaje_visible(valor: Decimal) -> str:
    if valor == valor.to_integral_value():
        return str(int(valor))
    return format(valor.normalize(), "f")


def serializar_resultado(resultado: dict, *, tipo: str | None = None, origen_descuento: str | None = None) -> dict:
    return {
        "precio_base": str(resultado["precio_base"]),
        "precio_adherido": str(resultado["precio_adherido"]),
        "descuento": str(resultado["descuento"]),
        "precio_base_descuento": str(resultado["precio_base_descuento"]),
        "precio_adherido_descuento": str(resultado["precio_adherido_descuento"]),
        "precio_base_formateado": formatear_pesos(resultado["precio_base"]),
        "precio_adherido_formateado": formatear_pesos(resultado["precio_adherido"]),
        "precio_base_descuento_formateado": formatear_pesos(resultado["precio_base_descuento"]),
        "precio_adherido_descuento_formateado": formatear_pesos(resultado["precio_adherido_descuento"]),
        # Presentación comercial para propuestas al cliente. Los exactos de arriba
        # siguen siendo la fuente matemática y jamás se recalculan desde estos.
        "precio_base_descuento_comercial_formateado": formatear_comercial_miles(resultado["precio_base_descuento"]),
        "precio_adherido_descuento_comercial_formateado": formatear_comercial_miles(resultado["precio_adherido_descuento"]),
        "descuento_formateado": _porcentaje_visible(resultado["descuento"]) + "%",
        "tipo": (_normalizar_texto(tipo) or None),
        "origen_descuento": origen_descuento,
        "factor_adhesion": str(ATM_FACTOR_ADHESION),
    }


def cotizar_atm(precio_base, *, tipo: str | None = None, descuento=None) -> dict:
    porcentaje, origen = resolver_descuento(tipo=tipo, descuento=descuento)
    return serializar_resultado(
        calcular_atm(precio_base, porcentaje), tipo=tipo, origen_descuento=origen
    )


def parsear_consulta_atm(texto: str):
    """Reconoce consultas rápidas ATM sin depender de Gemini.

    Devuelve None si el mensaje no parece una cotización ATM. En caso contrario,
    devuelve un dict con precio/tipo/descuento o con ``error``.
    """
    raw = str(texto or "").strip()
    n = _normalizar_texto(raw)
    if not re.search(r"(?:^|\b)atm(?:\b|$)", n):
        return None
    if raw.startswith("/") and not re.match(r"^/atm\b", raw, re.I):
        return None

    tipo = None
    if re.search(r"\bauto\b", n):
        tipo = "auto"
    elif re.search(r"\bmoto\b", n):
        tipo = "moto"

    descuento = None
    m_pct = re.search(r"(?<!\d)(\d{1,2}(?:[.,]\d+)?)\s*%", raw)
    if m_pct:
        descuento = m_pct.group(1)
    else:
        m_desc = re.search(
            r"(?:con\s+)?(\d{1,2}(?:[.,]\d+)?)\s*(?:de\s+)?(?:descuento|dto)\b|(?:descuento|dto)\s*(?:de\s+)?(\d{1,2}(?:[.,]\d+)?)",
            n,
            re.I,
        )
        if m_desc:
            descuento = next((g for g in m_desc.groups() if g), None)

    # El precio es el importe principal: número de al menos 3 dígitos o miles con puntos.
    candidatos = re.findall(r"(?<!\d)(?:\$\s*)?(\d{1,3}(?:\.\d{3})+|\d{3,})(?!\d)", raw)
    precio = candidatos[0] if candidatos else None
    if not precio:
        return {"error": "Indicá el precio base ATM. Ejemplo: ATM 158561 auto."}

    if descuento is None and tipo is None:
        return {
            "error": "Indicá Auto, Moto o un descuento manual entre 1% y 50%. Ejemplo: ATM 158561 auto."
        }
    return {"precio": precio, "tipo": tipo, "descuento": descuento}


def respuesta_chat_atm(texto: str):
    datos = parsear_consulta_atm(texto)
    if datos is None:
        return None
    if datos.get("error"):
        return datos["error"]
    try:
        r = cotizar_atm(datos["precio"], tipo=datos.get("tipo"), descuento=datos.get("descuento"))
    except ValueError as exc:
        return str(exc)
    etiqueta_tipo = r.get("tipo")
    tipo_linea = f"\nTipo: {etiqueta_tipo.capitalize()}" if etiqueta_tipo in {"auto", "moto"} else ""
    return (
        "ATM — Cotización\n\n"
        f"PRECIO NORMAL\nOriginal: {r['precio_base_formateado']}\n"
        f"Con descuento ({r['descuento_formateado']}): {r['precio_base_descuento_formateado']}\n\n"
        "PRECIO ADHERIDO\n"
        f"Tarjeta/débito: {r['precio_adherido_formateado']}\n"
        f"Adherido + descuento: {r['precio_adherido_descuento_formateado']}"
        f"{tipo_linea}"
    )


__all__ = [
    "ATM_FACTOR_ADHESION", "ATM_DESCUENTO_AUTO", "ATM_DESCUENTO_MOTO",
    "ATM_DESCUENTO_MIN", "ATM_DESCUENTO_MAX", "calcular_atm", "cotizar_atm",
    "parsear_consulta_atm", "respuesta_chat_atm", "formatear_pesos",
    "redondear_comercial_miles", "formatear_comercial_miles",
]
