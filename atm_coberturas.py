# -*- coding: utf-8 -*-
"""Catálogo determinístico de coberturas ATM.

La visión transcribe el título y el precio. Este módulo resuelve ese título a un
código operativo fijo de OficinaIA. Gemini NO decide A/B/C/TR.

Los códigos son internos. La propuesta al asegurado usa nombres y descripciones
comerciales fijas del catálogo, nunca los códigos A/B/C.
"""
from __future__ import annotations

from collections import OrderedDict
import re
import unicodedata


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Z0-9%]+", " ", t.upper()).strip()
    return re.sub(r"\s+", " ", t)


def _entry(
    codigo: str,
    titulo_atm: str,
    *,
    aliases=(),
    nombre_cliente: str,
    descripcion_cliente: str,
    grua: bool = True,
    adicionales=(),
    franquicia: bool = False,
    orden: int,
):
    return {
        "codigo": codigo,
        "titulo_atm": titulo_atm,
        "aliases": list(aliases),
        "nombre_cliente": nombre_cliente,
        "descripcion": descripcion_cliente,
        "descripcion_cliente": descripcion_cliente,
        # Se conserva la clave histórica `remolque` para compatibilidad interna,
        # pero en la interfaz/propuesta se usa únicamente la palabra "grúa".
        "remolque": bool(grua),
        "grua": bool(grua),
        "adicionales": list(adicionales),
        "franquicia": bool(franquicia),
        "detectable": True,
        "orden": int(orden),
    }


_C_DESC = (
    "Te cubre responsabilidad civil, incendio total y parcial, robo total y parcial "
    "y destrucción total por accidente. Además incluye ruedas, vidrios, granizo y "
    "cerraduras. Incluye grúa."
)

# Orden VISUAL fijo. La familia B contiene exactamente seis coberturas: B + B1..B5.
CATALOGO_CODIGOS_ATM = OrderedDict([
    ("A", _entry(
        "A", "RESPONSABILIDAD CIVIL",
        aliases=("RESPONSABILIDAD CIVIL",),
        nombre_cliente="Responsabilidad Civil",
        descripcion_cliente=(
            "Seguro básico para circular. Cubre los daños que puedas ocasionar a terceros. "
            "Incluye grúa."
        ),
        grua=True,
        orden=10,
    )),
    ("A1", _entry(
        "A1", "RESPONSABILIDAD CIVIL SIN ASISTENCIA",
        aliases=("RESPONSABILIDAD CIVIL SIN ASISTENCIA",),
        nombre_cliente="Responsabilidad Civil",
        descripcion_cliente=(
            "Seguro básico para circular. Cubre los daños que puedas ocasionar a terceros. "
            "Sin grúa."
        ),
        grua=False,
        orden=20,
    )),
    ("B", _entry(
        "B", "ROBO E INCENDIO TOTAL Y/O PARCIAL + ACCIDENTE TOTAL",
        aliases=(
            "ROBO E INCENDIO TOTAL Y/O PARCIAL + ACCIDENTE TOTAL",
            "ROBO E INCENDIO TOTAL Y/O PARCIAL ACCIDENTE TOTAL",
            "ROBO E INCENDIO TOTAL O PARCIAL + ACCIDENTE TOTAL",
        ),
        nombre_cliente="Robo e Incendio Total y/o Parcial + Accidente Total",
        descripcion_cliente=(
            "Cubre robo e incendio total y parcial, más destrucción total por accidente. "
            "Incluye grúa."
        ),
        grua=True,
        orden=30,
    )),
    ("B1", _entry(
        "B1", "ROBO E INCENDIO TOTAL Y/O PARCIAL",
        aliases=(
            "ROBO E INCENDIO TOTAL Y/O PARCIAL",
            "ROBO E INCENDIO TOTAL O PARCIAL",
        ),
        nombre_cliente="Robo e Incendio Total y/o Parcial",
        descripcion_cliente="Cubre robo e incendio total y parcial. Incluye grúa.",
        grua=True,
        orden=40,
    )),
    ("B2", _entry(
        "B2", "ROBO, INCENDIO Y ACCIDENTE TOTAL",
        aliases=("ROBO INCENDIO Y ACCIDENTE TOTAL",),
        nombre_cliente="Robo, Incendio y Accidente Total",
        descripcion_cliente="Cubre robo, incendio y destrucción total por accidente. Incluye grúa.",
        grua=True,
        orden=50,
    )),
    ("B3", _entry(
        "B3", "ROBO E INCENDIO TOTAL",
        aliases=("ROBO E INCENDIO TOTAL",),
        nombre_cliente="Robo e Incendio Total",
        descripcion_cliente="Cubre robo total e incendio total. Incluye grúa.",
        grua=True,
        orden=60,
    )),
    ("B4", _entry(
        "B4", "ROBO, INCENDIO Y ACCIDENTE TOTAL SIN ASISTENCIA",
        aliases=("ROBO INCENDIO Y ACCIDENTE TOTAL SIN ASISTENCIA",),
        nombre_cliente="Robo, Incendio y Accidente Total",
        descripcion_cliente="Cubre robo, incendio y destrucción total por accidente. Sin grúa.",
        grua=False,
        orden=70,
    )),
    ("B5", _entry(
        "B5", "ROBO E INCENDIO TOTAL SIN ASISTENCIA",
        aliases=("ROBO E INCENDIO TOTAL SIN ASISTENCIA",),
        nombre_cliente="Robo e Incendio Total",
        descripcion_cliente="Cubre robo total e incendio total. Sin grúa.",
        grua=False,
        orden=80,
    )),
    ("C", _entry(
        "C", "TERCEROS COMPLETOS PLUS",
        aliases=("TERCEROS COMPLETOS PLUS", "TERCERO COMPLETO PLUS"),
        nombre_cliente="Terceros Completos Plus",
        descripcion_cliente=_C_DESC,
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        orden=90,
    )),
    ("CPr", _entry(
        "CPr", "TERCEROS COMPLETOS PREMIUM",
        aliases=("TERCEROS COMPLETOS PREMIUM", "TERCERO COMPLETO PREMIUM"),
        nombre_cliente="Terceros Completos Premium",
        descripcion_cliente=_C_DESC,
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        orden=100,
    )),
    ("CB", _entry(
        "CB", "TERCEROS COMPLETOS BLACK",
        aliases=("TERCEROS COMPLETOS BLACK", "TERCERO COMPLETO BLACK"),
        nombre_cliente="Terceros Completos Black",
        descripcion_cliente=_C_DESC,
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        orden=110,
    )),
    ("TR", _entry(
        "TR", "TODO RIESGO C/FCIA.VARIABLE % SUMA ASEGURADA",
        aliases=(
            "TODO RIESGO C/FCIA.VARIABLE 3% SUMA ASEGURADA",
            "TODO RIESGO C/FCIA.VARIABLE 6% SUMA ASEGURADA",
            "TODO RIESGO C FCIA VARIABLE 3% SUMA ASEGURADA",
            "TODO RIESGO C FCIA VARIABLE 6% SUMA ASEGURADA",
        ),
        nombre_cliente="Todo Riesgo",
        descripcion_cliente=(
            "Incluye responsabilidad civil, incendio total y parcial, robo total y parcial, "
            "destrucción total y daños parciales por accidente. Además incluye ruedas, vidrios, "
            "granizo, cerraduras y grúa."
        ),
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        franquicia=True,
        orden=120,
    )),
])

# Alias histórico para módulos que importaban COBERTURAS_ATM.
COBERTURAS_ATM = CATALOGO_CODIGOS_ATM


def _candidatos(entry: dict) -> set[str]:
    valores = [entry.get("titulo_atm"), *(entry.get("aliases") or [])]
    return {_norm(v) for v in valores if str(v or "").strip()}


def resolver_codigo_atm(nombre: str) -> str | None:
    """Resuelve sólo mapeos preconfigurados; no hace fuzzy matching agresivo."""
    n = _norm(nombre)
    if not n:
        return None

    # Todo Riesgo varía únicamente en el porcentaje de franquicia.
    if n.startswith("TODO RIESGO") and "SUMA ASEGURADA" in n:
        return "TR"

    for codigo, entry in CATALOGO_CODIGOS_ATM.items():
        if n in _candidatos(entry):
            return codigo

    # Variaciones controladas observadas: signos +, Y/O y puntuación pueden caer.
    compacta = n.replace(" Y O ", " ").replace(" O ", " ")
    for codigo, entry in CATALOGO_CODIGOS_ATM.items():
        for candidato in _candidatos(entry):
            c = candidato.replace(" Y O ", " ").replace(" O ", " ")
            if compacta == c:
                return codigo
    return None


def enriquecer_cobertura(nombre: str, *, sin_asistencia: bool = False) -> dict:
    codigo = resolver_codigo_atm(nombre)
    if not codigo:
        titulo = re.sub(r"\s+", " ", str(nombre or "")).strip()
        return {
            "id": None,
            "codigo": None,
            "nombre": titulo,
            "nombre_corto": titulo,
            "titulo_atm": titulo,
            "tooltip": titulo,
            "nombre_cliente": titulo,
            "descripcion": "Cobertura detectada en ATM todavía sin código confirmado.",
            "descripcion_cliente": "Cobertura detectada en ATM todavía sin código confirmado.",
            "franquicia": False,
            "sin_asistencia": bool(sin_asistencia),
            "remolque": None,
            "grua": None,
            "adicionales": [],
            "orden": 999,
            "catalogada": False,
        }

    entry = CATALOGO_CODIGOS_ATM[codigo]
    titulo_leido = re.sub(r"\s+", " ", str(nombre or "")).strip()
    salida = {
        "id": codigo,
        **entry,
        "nombre": entry["titulo_atm"] or titulo_leido,
        "nombre_corto": codigo,
        "tooltip": titulo_leido or entry["titulo_atm"],
        "sin_asistencia": bool(sin_asistencia or entry.get("grua") is False),
        "catalogada": True,
    }
    return salida


def catalogo_publico() -> list[dict]:
    """Catálogo apto para matriz, tooltips y propuesta del frontend."""
    salida = []
    for codigo, entry in CATALOGO_CODIGOS_ATM.items():
        salida.append({
            "codigo": codigo,
            "titulo_atm": entry.get("titulo_atm") or "",
            "tooltip": entry.get("titulo_atm") or codigo,
            "nombre_cliente": entry.get("nombre_cliente") or entry.get("titulo_atm") or codigo,
            "descripcion": entry.get("descripcion") or "",
            "descripcion_cliente": entry.get("descripcion_cliente") or entry.get("descripcion") or "",
            "remolque": entry.get("remolque"),
            "grua": entry.get("grua"),
            "adicionales": list(entry.get("adicionales") or []),
            "franquicia": bool(entry.get("franquicia")),
            "detectable": True,
            "orden": int(entry.get("orden") or 999),
        })
    return salida


__all__ = [
    "COBERTURAS_ATM", "CATALOGO_CODIGOS_ATM", "resolver_codigo_atm",
    "enriquecer_cobertura", "catalogo_publico",
]
