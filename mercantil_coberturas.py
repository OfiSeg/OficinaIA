# -*- coding: utf-8 -*-
"""Catálogo determinístico de coberturas de La Mercantil Andina.

Los códigos visuales son los que el usuario quiere ver en OficinaIA. Los
códigos reales se conservan para no perder fidelidad respecto del PDF.
"""
from __future__ import annotations

MERCANTIL_COBERTURAS = {
    "A": {
        "codigo_visual": "A",
        "nombre_cliente": "Responsabilidad Civil",
        "descripcion_cliente": "Responsabilidad civil.",
        "max_descuento": 35,
        "tipo": "rc",
    },
    "B": {
        "codigo_visual": "B",
        "nombre_cliente": "Cobertura B",
        "descripcion_cliente": "Responsabilidad civil, incendio total, robo/hurto total y destrucción total por accidente.",
        "max_descuento": 35,
        "tipo": "basica",
    },
    "B0": {
        "codigo_visual": "B0",
        "nombre_cliente": "Cobertura B0",
        "descripcion_cliente": "Responsabilidad civil y robo/hurto total.",
        "max_descuento": 35,
        "tipo": "basica",
    },
    "B1": {
        "codigo_visual": "B1",
        "nombre_cliente": "Cobertura B1",
        "descripcion_cliente": "Responsabilidad civil, incendio total y robo/hurto total.",
        "max_descuento": 35,
        "tipo": "basica",
    },
    "B3": {
        "codigo_visual": "B3",
        "nombre_cliente": "Cobertura B3",
        "descripcion_cliente": "Responsabilidad civil e incendio total y parcial.",
        "max_descuento": 35,
        "tipo": "basica",
    },
    "M BASICA": {
        "codigo_visual": "MB",
        "nombre_cliente": "Terceros Completo M Básica",
        "descripcion_cliente": "Responsabilidad civil, incendio total y parcial, robo total y parcial y destrucción total por accidente.",
        "max_descuento": 35,
        "tipo": "terceros_completo",
    },
    "M PLUS": {
        "codigo_visual": "MP",
        "nombre_cliente": "Terceros Completo M Plus",
        "descripcion_cliente": "Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total por accidente. Cubre ruedas, vidrios, granizo y cerraduras.",
        "max_descuento": 35,
        "tipo": "terceros_completo_plus",
    },
    "D2 0020": {
        "codigo_visual": "D2",
        "nombre_cliente": "Todo Riesgo",
        "descripcion_cliente": "Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total y daños parciales por accidente.",
        "max_descuento": 30,
        "tipo": "todo_riesgo",
        "franquicia_pct": 2,
    },
    "D2 0030": {
        "codigo_visual": "D3",
        "nombre_cliente": "Todo Riesgo",
        "descripcion_cliente": "Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total y daños parciales por accidente.",
        "max_descuento": 30,
        "tipo": "todo_riesgo",
        "franquicia_pct": 3,
    },
    "D2 0040": {
        "codigo_visual": "D4",
        "nombre_cliente": "Todo Riesgo",
        "descripcion_cliente": "Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total y daños parciales por accidente.",
        "max_descuento": 30,
        "tipo": "todo_riesgo",
        "franquicia_pct": 4,
    },
    "D2 0050": {
        "codigo_visual": "D5",
        "nombre_cliente": "Todo Riesgo",
        "descripcion_cliente": "Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total y daños parciales por accidente.",
        "max_descuento": 30,
        "tipo": "todo_riesgo",
        "franquicia_pct": 5,
    },
}

ORDEN_VISUAL = ["A", "B", "B0", "B1", "B3", "M BASICA", "M PLUS", "D2 0020", "D2 0030", "D2 0040", "D2 0050"]


def entrada(codigo_real: str):
    return MERCANTIL_COBERTURAS.get(str(codigo_real or "").strip().upper())


def catalogo_publico():
    salida = []
    for codigo in ORDEN_VISUAL:
        item = dict(MERCANTIL_COBERTURAS[codigo])
        item["codigo_real"] = codigo
        salida.append(item)
    return salida


__all__ = ["MERCANTIL_COBERTURAS", "ORDEN_VISUAL", "entrada", "catalogo_publico"]
