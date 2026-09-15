# -*- coding: utf-8 -*-
"""Catálogos determinísticos de coberturas ATM para autos y motos.

La visión transcribe el título y el precio. Este módulo resuelve ese título a un
código operativo fijo de OficinaIA. Gemini NO decide A/B/C/TR ni RP/RC/RC1.

Los códigos son internos. La propuesta al asegurado usa nombres y descripciones
comerciales fijas del catálogo.
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
    tipo_vehiculo: str = "auto",
    tooltip: str | None = None,
    franquicia_visible: str = "",
    riesgos_detectados=(),
    beneficios_adicionales=(),
    detalle_tecnico=(),
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
        "franquicia_visible": str(franquicia_visible or ""),
        "detectable": True,
        "orden": int(orden),
        "tipo_vehiculo": tipo_vehiculo,
        "tooltip": tooltip or titulo_atm,
        "riesgos_detectados": list(riesgos_detectados),
        "beneficios_adicionales": list(beneficios_adicionales),
        "detalle_tecnico": list(detalle_tecnico),
    }


# Riesgos canónicos compartidos con el normalizador universal. Se conservan como
# strings para que este catálogo siga siendo determinístico y desacoplado.
RC = "RESPONSABILIDAD_CIVIL"
DT_ACC = "DESTRUCCION_TOTAL_ACCIDENTE"
DP_ACC = "DANOS_PARCIALES_ACCIDENTE"
INC_T = "INCENDIO_TOTAL"
INC_P = "INCENDIO_PARCIAL"
ROB_T = "ROBO_HURTO_TOTAL"
ROB_P = "ROBO_HURTO_PARCIAL"
RUEDAS = "RUEDAS"
VIDRIOS = "VIDRIOS"
GRANIZO = "GRANIZO"
CERRADURAS = "CERRADURAS"
GRUA = "GRUA"

# Orden VISUAL fijo AUTOS. La familia B contiene exactamente seis coberturas: B + B1..B5.
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
        riesgos_detectados=(RC, GRUA),
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
        riesgos_detectados=(RC,),
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
            "Responsabilidad Civil\nIncendio Total y Parcial\nRobo/Hurto Total y Parcial\n"
            "Destrucción Total por Accidente\nReposición de 1 rueda por año con depreciación\nIncluye grúa"
        ),
        grua=True,
        riesgos_detectados=(RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC, RUEDAS, GRUA),
        beneficios_adicionales=("Reposición de 1 rueda por año con depreciación",),
        orden=30,
    )),
    ("B1", _entry(
        "B1", "ROBO E INCENDIO TOTAL Y/O PARCIAL",
        aliases=(
            "ROBO E INCENDIO TOTAL Y/O PARCIAL",
            "ROBO E INCENDIO TOTAL O PARCIAL",
        ),
        nombre_cliente="Robo e Incendio Total y/o Parcial",
        descripcion_cliente=(
            "Responsabilidad Civil\nIncendio Total y Parcial\nRobo/Hurto Total y Parcial\n"
            "Reposición de 1 rueda por año con depreciación\nIncluye grúa"
        ),
        grua=True,
        riesgos_detectados=(RC, INC_T, INC_P, ROB_T, ROB_P, RUEDAS, GRUA),
        beneficios_adicionales=("Reposición de 1 rueda por año con depreciación",),
        orden=40,
    )),
    ("B2", _entry(
        "B2", "ROBO, INCENDIO Y ACCIDENTE TOTAL",
        aliases=("ROBO INCENDIO Y ACCIDENTE TOTAL",),
        nombre_cliente="Robo, Incendio y Accidente Total",
        descripcion_cliente="Cubre robo, incendio y destrucción total por accidente. Incluye grúa.",
        grua=True,
        riesgos_detectados=(RC, INC_T, ROB_T, DT_ACC, GRUA),
        orden=50,
    )),
    ("B3", _entry(
        "B3", "ROBO E INCENDIO TOTAL",
        aliases=("ROBO E INCENDIO TOTAL",),
        nombre_cliente="Robo e Incendio Total",
        descripcion_cliente="Cubre robo total e incendio total. Incluye grúa.",
        grua=True,
        riesgos_detectados=(RC, INC_T, ROB_T, GRUA),
        orden=60,
    )),
    ("B4", _entry(
        "B4", "ROBO, INCENDIO Y ACCIDENTE TOTAL SIN ASISTENCIA",
        aliases=("ROBO INCENDIO Y ACCIDENTE TOTAL SIN ASISTENCIA",),
        nombre_cliente="Robo, Incendio y Accidente Total",
        descripcion_cliente="Cubre robo, incendio y destrucción total por accidente. Sin grúa.",
        grua=False,
        riesgos_detectados=(RC, INC_T, ROB_T, DT_ACC),
        orden=70,
    )),
    ("B5", _entry(
        "B5", "ROBO E INCENDIO TOTAL SIN ASISTENCIA",
        aliases=("ROBO E INCENDIO TOTAL SIN ASISTENCIA",),
        nombre_cliente="Robo e Incendio Total",
        descripcion_cliente="Cubre robo total e incendio total. Sin grúa.",
        grua=False,
        riesgos_detectados=(RC, INC_T, ROB_T),
        orden=80,
    )),
    ("C", _entry(
        "C", "TERCEROS COMPLETOS PLUS",
        aliases=("TERCEROS COMPLETOS PLUS", "TERCERO COMPLETO PLUS"),
        nombre_cliente="Terceros Completo Plus",
        descripcion_cliente=(
            "Responsabilidad Civil\nIncendio Total y Parcial\nRobo/Hurto Total y Parcial\n"
            "Destrucción Total por Accidente"
        ),
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        riesgos_detectados=(RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC, RUEDAS, VIDRIOS, GRANIZO, CERRADURAS, GRUA),
        detalle_tecnico=(
            "Cristales y cerraduras hasta 5% de la suma asegurada · 1 evento por año",
            "Parabrisas y lunetas hasta 5% de la suma asegurada · 1 evento por año",
            "Granizo hasta 10% de la suma asegurada · 1 evento por año",
            "Terremoto hasta la suma asegurada, excepto Mendoza, San Juan y San Luis",
            "Daños parciales por robo/hurto aparecido hasta 10% de la suma asegurada",
            "Reposición 0 km durante el primer año, según condiciones de cobertura",
            "Reposición de 1 rueda por año con depreciación",
            "Reposición de llave física o electrónica por Robo Total aparecido",
        ),
        orden=90,
    )),
    ("CPr", _entry(
        "CPr", "TERCEROS COMPLETOS PREMIUM",
        aliases=("TERCEROS COMPLETOS PREMIUM", "TERCERO COMPLETO PREMIUM"),
        nombre_cliente="Terceros Completo Premium",
        descripcion_cliente=(
            "Responsabilidad Civil\nIncendio Total y Parcial\nRobo/Hurto Total y Parcial\n"
            "Destrucción Total por Accidente"
        ),
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        riesgos_detectados=(RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC, RUEDAS, VIDRIOS, GRANIZO, CERRADURAS, GRUA),
        detalle_tecnico=(
            "Cristales y cerraduras hasta 2 eventos acumulados por año",
            "Parabrisas y lunetas hasta 2 eventos por año",
            "Granizo hasta la suma asegurada · 2 eventos por año",
            "Inundación hasta $500.000",
            "Terremoto hasta la suma asegurada, excepto Mendoza, San Juan y San Luis",
            "Daños parciales por robo/hurto aparecido hasta 10% de la suma asegurada",
            "Reposición 0 km durante el primer año, según condiciones de cobertura",
            "Ruedas: hasta 10 años, 4 por año sin depreciación; más de 10 años, 2 por año con depreciación",
            "Reposición de llave física o electrónica por Robo Total aparecido",
        ),
        orden=100,
    )),
    ("CB", _entry(
        "CB", "TERCEROS COMPLETOS BLACK",
        aliases=("TERCEROS COMPLETOS BLACK", "TERCERO COMPLETO BLACK"),
        nombre_cliente="Terceros Completo Black",
        descripcion_cliente=(
            "Responsabilidad Civil\nIncendio Total y Parcial\nRobo/Hurto Total y Parcial\n"
            "Destrucción Total por Accidente"
        ),
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        riesgos_detectados=(RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC, RUEDAS, VIDRIOS, GRANIZO, CERRADURAS, GRUA),
        detalle_tecnico=(
            "Parabrisas y luneta sin límite de eventos anuales",
            "Cerraduras hasta la suma asegurada, sin límite de eventos",
            "Cristales laterales hasta la suma asegurada, sin límite de eventos",
            "Granizo hasta la suma asegurada",
            "Inundación hasta la suma asegurada",
            "Terremoto hasta la suma asegurada, excepto Mendoza, San Juan y San Luis",
            "Daños parciales por robo/hurto aparecido hasta la suma asegurada",
            "Reposición 0 km durante el primer año, según condiciones de cobertura",
            "Reposición ilimitada de cubiertas, sin depreciación",
            "Reposición de llave física o electrónica por Robo Total aparecido",
        ),
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
            "Responsabilidad Civil\nIncendio Total y Parcial\nRobo/Hurto Total y Parcial\n"
            "Destrucción Total por Accidente\nDaños Parciales por Accidente"
        ),
        grua=True,
        adicionales=("ruedas", "vidrios", "granizo", "cerraduras"),
        riesgos_detectados=(RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC, DP_ACC, RUEDAS, VIDRIOS, GRANIZO, CERRADURAS, GRUA),
        detalle_tecnico=(
            "Parabrisas y luneta sin límite de eventos anuales",
            "Cerraduras hasta la suma asegurada, sin límite de eventos",
            "Cristales laterales hasta la suma asegurada, sin límite de eventos",
            "Granizo hasta la suma asegurada",
            "Inundación hasta la suma asegurada",
            "Terremoto hasta la suma asegurada, excepto Mendoza, San Juan y San Luis",
            "Reposición 0 km durante el primer año, según condiciones de cobertura",
            "Reposición ilimitada de cubiertas, sin depreciación",
            "Reposición de llave física o electrónica por Robo Total aparecido",
        ),
        franquicia=True,
        orden=120,
    )),
])

# Catálogo MOTOS separado: los códigos A/A1 se repiten deliberadamente y RC significa
# Robo Clásico, no Responsabilidad Civil. Nunca se mezcla con el catálogo de autos.
CATALOGO_MOTOS_ATM = OrderedDict([
    ("RP", _entry(
        "RP", "ROBO PREMIUM MOTOS",
        aliases=("ROBO PREMIUM MOTOS", "ROBO PREMIUM MOTO", "ROBO PREMIUM"),
        nombre_cliente="Robo Premium",
        descripcion_cliente=(
            "Robo/Hurto Total\n"
            "Incendio Total y Parcial\n"
            "Destrucción Total por Accidente\n"
            "Incluye grúa"
        ),
        grua=True,
        orden=50,
        tipo_vehiculo="moto",
        tooltip=(
            "Robo Premium Motos — Robo/Hurto Total · Incendio Total y Parcial · "
            "Destrucción Total por Accidente · Incluye grúa."
        ),
    )),
    ("RC", _entry(
        "RC", "ROBO TOTAL CLASICO MOTOS",
        aliases=(
            "ROBO TOTAL CLASICO MOTOS",
            "ROBO TOTAL CLÁSICO MOTOS",
            "ROBO CLASICO MOTOS",
            "ROBO CLÁSICO MOTOS",
            "ROBO TOTAL CLASICO",
            "ROBO TOTAL CLÁSICO",
            "ROBO CLASICO",
            "ROBO CLÁSICO",
        ),
        nombre_cliente="Robo Clásico",
        descripcion_cliente=(
            "Robo/Hurto Total\n"
            "Incendio Total\n"
            "Incluye grúa\n"
            "FRANQUICIA 3%"
        ),
        grua=True,
        orden=40,
        tipo_vehiculo="moto",
        tooltip=(
            "Robo Clásico Motos — Robo/Hurto Total · Incendio Total · "
            "FRANQUICIA 3% · Incluye grúa."
        ),
        franquicia_visible="FRANQUICIA 3%",
    )),
    ("RC1", _entry(
        "RC1", "ROBO TOTAL CLASICO MOTOS SIN ASISTENCIA",
        aliases=(
            "ROBO TOTAL CLASICO MOTOS SIN ASISTENCIA",
            "ROBO TOTAL CLÁSICO MOTOS SIN ASISTENCIA",
            "ROBO CLASICO MOTOS SIN ASISTENCIA",
            "ROBO CLÁSICO MOTOS SIN ASISTENCIA",
            "ROBO TOTAL CLASICO SIN ASISTENCIA",
            "ROBO TOTAL CLÁSICO SIN ASISTENCIA",
            "ROBO CLASICO SIN ASISTENCIA",
            "ROBO CLÁSICO SIN ASISTENCIA",
        ),
        nombre_cliente="Robo Clásico sin asistencia",
        descripcion_cliente=(
            "Robo/Hurto Total\n"
            "Incendio Total\n"
            "Sin grúa\n"
            "FRANQUICIA 3%"
        ),
        grua=False,
        orden=30,
        tipo_vehiculo="moto",
        tooltip=(
            "Robo Clásico Motos sin asistencia — Robo/Hurto Total · Incendio Total · "
            "FRANQUICIA 3% · Sin grúa."
        ),
        franquicia_visible="FRANQUICIA 3%",
    )),
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
        tipo_vehiculo="moto",
        tooltip="Responsabilidad Civil · Con asistencia.",
    )),
    ("A1", _entry(
        "A1", "RESPONSABILIDAD CIVIL SIN ASISTENCIA",
        aliases=("RESPONSABILIDAD CIVIL SIN ASISTENCIA",),
        nombre_cliente="Responsabilidad Civil sin asistencia",
        descripcion_cliente=(
            "Seguro básico para circular. Cubre los daños que puedas ocasionar a terceros. "
            "Sin grúa."
        ),
        grua=False,
        orden=20,
        tipo_vehiculo="moto",
        tooltip="Responsabilidad Civil · Sin asistencia.",
    )),
])

# Alias histórico para módulos que importaban COBERTURAS_ATM.
COBERTURAS_ATM = CATALOGO_CODIGOS_ATM


def _candidatos(entry: dict) -> set[str]:
    valores = [entry.get("titulo_atm"), *(entry.get("aliases") or [])]
    return {_norm(v) for v in valores if str(v or "").strip()}


def _resolver_en_catalogo(nombre: str, catalogo: OrderedDict) -> str | None:
    n = _norm(nombre)
    if not n:
        return None
    for codigo, entry in catalogo.items():
        if n in _candidatos(entry):
            return codigo
    compacta = n.replace(" Y O ", " ").replace(" O ", " ")
    for codigo, entry in catalogo.items():
        for candidato in _candidatos(entry):
            c = candidato.replace(" Y O ", " ").replace(" O ", " ")
            if compacta == c:
                return codigo
    return None


def resolver_codigo_atm(nombre: str) -> str | None:
    """Resuelve AUTO sólo con mapeos preconfigurados; no hace fuzzy agresivo."""
    n = _norm(nombre)
    if not n:
        return None
    if n.startswith("TODO RIESGO") and "SUMA ASEGURADA" in n:
        return "TR"
    return _resolver_en_catalogo(nombre, CATALOGO_CODIGOS_ATM)


def resolver_codigo_moto_atm(nombre: str) -> str | None:
    """Resuelve MOTOS en su catálogo independiente."""
    return _resolver_en_catalogo(nombre, CATALOGO_MOTOS_ATM)


def _enriquecer_desde_catalogo(nombre: str, catalogo: OrderedDict, *, sin_asistencia: bool, tipo_vehiculo: str) -> dict:
    codigo = _resolver_en_catalogo(nombre, catalogo)
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
            "franquicia_visible": "",
            "sin_asistencia": bool(sin_asistencia),
            "remolque": None,
            "grua": None,
            "adicionales": [],
            "orden": 999,
            "tipo_vehiculo": tipo_vehiculo,
            "catalogada": False,
        }
    entry = catalogo[codigo]
    titulo_leido = re.sub(r"\s+", " ", str(nombre or "")).strip()
    return {
        "id": codigo,
        **entry,
        "nombre": entry["titulo_atm"] or titulo_leido,
        "nombre_corto": codigo,
        # Para autos se preserva el título leído como tooltip; para motos el catálogo
        # contiene el tooltip comercial solicitado (si existe).
        "tooltip": entry.get("tooltip") or titulo_leido or entry["titulo_atm"],
        "sin_asistencia": bool(sin_asistencia or entry.get("grua") is False),
        "tipo_vehiculo": tipo_vehiculo,
        "catalogada": True,
    }


def enriquecer_cobertura(nombre: str, *, sin_asistencia: bool = False) -> dict:
    codigo = resolver_codigo_atm(nombre)
    if not codigo:
        return _enriquecer_desde_catalogo(
            nombre, CATALOGO_CODIGOS_ATM, sin_asistencia=sin_asistencia, tipo_vehiculo="auto"
        )
    # Usa el flujo común para mantener el contrato histórico.
    return _enriquecer_desde_catalogo(
        nombre, CATALOGO_CODIGOS_ATM, sin_asistencia=sin_asistencia, tipo_vehiculo="auto"
    )


def enriquecer_cobertura_moto(nombre: str, *, sin_asistencia: bool = False) -> dict:
    return _enriquecer_desde_catalogo(
        nombre, CATALOGO_MOTOS_ATM, sin_asistencia=sin_asistencia, tipo_vehiculo="moto"
    )


def _catalogo_publico(catalogo: OrderedDict) -> list[dict]:
    salida = []
    for codigo, entry in catalogo.items():
        salida.append({
            "codigo": codigo,
            "titulo_atm": entry.get("titulo_atm") or "",
            "tooltip": entry.get("tooltip") or entry.get("titulo_atm") or codigo,
            "nombre_cliente": entry.get("nombre_cliente") or entry.get("titulo_atm") or codigo,
            "descripcion": entry.get("descripcion") or "",
            "descripcion_cliente": entry.get("descripcion_cliente") or entry.get("descripcion") or "",
            "remolque": entry.get("remolque"),
            "grua": entry.get("grua"),
            "adicionales": list(entry.get("adicionales") or []),
            "riesgos_detectados": list(entry.get("riesgos_detectados") or []),
            "beneficios_adicionales": list(entry.get("beneficios_adicionales") or []),
            "detalle_tecnico": list(entry.get("detalle_tecnico") or []),
            "franquicia": bool(entry.get("franquicia")),
            "franquicia_visible": entry.get("franquicia_visible") or "",
            "detectable": True,
            "orden": int(entry.get("orden") or 999),
            "tipo_vehiculo": entry.get("tipo_vehiculo") or "auto",
        })
    return salida


def catalogo_publico() -> list[dict]:
    """Catálogo AUTOS apto para matriz, tooltips y propuesta del frontend."""
    return _catalogo_publico(CATALOGO_CODIGOS_ATM)


def catalogo_motos_publico() -> list[dict]:
    """Catálogo MOTOS separado para no colisionar A/A1 ni RC con autos."""
    return _catalogo_publico(CATALOGO_MOTOS_ATM)


__all__ = [
    "COBERTURAS_ATM", "CATALOGO_CODIGOS_ATM", "CATALOGO_MOTOS_ATM",
    "resolver_codigo_atm", "resolver_codigo_moto_atm",
    "enriquecer_cobertura", "enriquecer_cobertura_moto",
    "catalogo_publico", "catalogo_motos_publico",
]
