# -*- coding: utf-8 -*-
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _decimal(valor, nombre="valor") -> Decimal:
    try:
        v = Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{nombre.capitalize()} inválido.") from exc
    if v < 0:
        raise ValueError(f"{nombre.capitalize()} inválido.")
    return v


def calcular_descuento(precio, descuento, max_descuento=35):
    p = _decimal(precio, "precio")
    d = _decimal(descuento, "descuento")
    maxd = _decimal(max_descuento, "descuento máximo")
    if d > maxd:
        raise ValueError(f"El descuento máximo permitido es {maxd.normalize()}%.")
    final = (p * (Decimal("1") - d / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"precio_original": str(p), "descuento": str(d), "precio_final": str(final)}


__all__ = ["calcular_descuento"]
