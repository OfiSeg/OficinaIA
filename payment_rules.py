"""Reglas determinísticas de negocio para medios de pago.

V20 Etapa 4: este módulo no conoce Flask, sesión, DB ni Gemini. Mantiene una
única responsabilidad: normalizar compañía/medio de pago y devolver una regla
sólo cuando está explícitamente definida.
"""
import re
import unicodedata
from companias import normalizar_compania


def _normalizar_texto_pago(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.upper()).strip()


def _normalizar_medio_pago(medio_pago):
    texto = _normalizar_texto_pago(medio_pago)
    if not texto:
        return ""
    if "CUPON" in texto:
        return "CUPONERA"
    if "CBU" in texto or "DEBITO" in texto or "TRANSFERENCIA" in texto:
        return "CBU"
    if "CREDITO" in texto or "TARJETA" in texto:
        return "CREDITO"
    return ""


_REGLAS_PAGO = {
    ("ATM", "CUPONERA"): {
        "precio_fijo": True,
        "meses_precio_fijo": 3,
        "cantidad_cupones": 3,
        "cupones_fisicos": True,
        "descripcion": (
            "Con ATM y cuponera el precio se mantiene fijo 3 meses. "
            "Hay 3 cupones, uno para cada mes, y se pueden pagar físicamente."
        ),
    },
    ("ATM", "CBU"): {
        "precio_fijo": False,
        "meses_precio_fijo": None,
        "cantidad_cupones": 0,
        "cupones_fisicos": False,
        "descripcion": "Con ATM y CBU el precio puede cambiar todos los meses. No hay cupones.",
    },
    ("ATM", "CREDITO"): {
        "precio_fijo": False,
        "meses_precio_fijo": None,
        "cantidad_cupones": 0,
        "cupones_fisicos": False,
        "descripcion": "Con ATM y crédito el precio puede cambiar todos los meses. No hay cupones.",
    },
    ("AGS", "CUPONERA"): {
        "precio_fijo": True,
        "meses_precio_fijo": 4,
        "cantidad_cupones": 4,
        "cupones_fisicos": True,
        "descripcion": (
            "Con AGS y cuponera el precio se mantiene fijo 4 meses. "
            "Hay 4 cupones, uno para cada mes."
        ),
    },
}


def calcular_regla_pago(compania, medio_pago):
    compania_norm = normalizar_compania(compania)
    medio_norm = _normalizar_medio_pago(medio_pago)
    if not compania_norm or not medio_norm:
        return None
    regla = _REGLAS_PAGO.get((compania_norm, medio_norm))
    return dict(regla) if regla else None
