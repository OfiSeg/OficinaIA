# -*- coding: utf-8 -*-
"""Normalizador universal de coberturas para Cotizaciones de OficinaIA.

Objetivos:
- Entender coberturas por su CONTENIDO y no solamente por el código de una compañía.
- Conservar siempre el texto/código original como evidencia.
- Ser conservador: si no hay evidencia suficiente, devolver SIN_CLASIFICAR.
- Reconocer abreviaturas habituales de productores (RC, PT Acc., PTyP Inc., etc.).

El módulo no reemplaza los parsers especializados de ATM/Mercantil/Federación.
Se usa como capa común y como fallback para compañías/documentos desconocidos.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
import json
import re
import unicodedata
from typing import Iterable

import fitz

from companias import nombre_compania, normalizar_compania, aliases_companias


# Riesgos canónicos. Estos IDs son internos: los textos comerciales se generan
# de forma separada para no contaminar la fuente original.
RC = "RESPONSABILIDAD_CIVIL"
DT_ACC = "DESTRUCCION_TOTAL_ACCIDENTE"
DP_ACC = "DANOS_PARCIALES_ACCIDENTE"
INC_T = "INCENDIO_TOTAL"
INC_P = "INCENDIO_PARCIAL"
ROB_T = "ROBO_HURTO_TOTAL"
ROB_P = "ROBO_HURTO_PARCIAL"
ROB_P_AMP = "ROBO_PARCIAL_AMPARO_ROBO_TOTAL"
RUEDAS = "RUEDAS"
BATERIA = "BATERIA"
VIDRIOS = "VIDRIOS"
GRANIZO = "GRANIZO"
CERRADURAS = "CERRADURAS"
GRUA = "GRUA"

PERFIL_RC = "RC"
PERFIL_B = "B"
PERFIL_B1 = "B1"
PERFIL_C = "C"
PERFIL_C1 = "C1"
PERFIL_C_PLUS = "C_PLUS"
PERFIL_LB = "LB"
PERFIL_LB1 = "LB1"
PERFIL_TR = "TODO_RIESGO"
PERFIL_SIN_CLASIFICAR = "SIN_CLASIFICAR"


RISK_LABELS = {
    RC: "Responsabilidad Civil",
    DT_ACC: "Destrucción Total por Accidente",
    DP_ACC: "Daños Parciales por Accidente",
    INC_T: "Incendio Total",
    INC_P: "Incendio Parcial",
    ROB_T: "Robo/Hurto Total",
    ROB_P: "Robo/Hurto Parcial",
    ROB_P_AMP: "Robo Parcial al amparo del Robo Total",
    RUEDAS: "Ruedas",
    BATERIA: "Batería",
    VIDRIOS: "Vidrios",
    GRANIZO: "Granizo",
    CERRADURAS: "Cerraduras",
    GRUA: "Grúa",
}

PROFILE_LABELS = {
    PERFIL_RC: "Responsabilidad Civil",
    PERFIL_B: "Robo, Incendio y Accidente Total",
    PERFIL_B1: "Robo e Incendio Total",
    PERFIL_C: "Terceros Completo",
    PERFIL_C1: "Terceros Completo",
    PERFIL_C_PLUS: "Terceros Completo Plus",
    PERFIL_LB: "Robo e Incendio + Robo Parcial al Amparo + Accidente Total",
    PERFIL_LB1: "Robo e Incendio + Robo Parcial al Amparo",
    PERFIL_TR: "Todo Riesgo",
    PERFIL_SIN_CLASIFICAR: "Cobertura",
}

PROFILE_ORDER = {
    PERFIL_RC: 10,
    PERFIL_B1: 30,
    PERFIL_B: 40,
    PERFIL_C1: 55,
    PERFIL_LB1: 57,
    PERFIL_C: 60,
    PERFIL_LB: 62,
    PERFIL_C_PLUS: 70,
    PERFIL_TR: 80,
    PERFIL_SIN_CLASIFICAR: 90,
}


def _sin_acentos(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(ch for ch in valor if not unicodedata.combining(ch))


def normalizar_texto(texto: str) -> str:
    valor = _sin_acentos(texto).upper().replace("\r", "\n")
    valor = valor.replace("–", "-").replace("—", "-")
    valor = re.sub(r"[\t ]+", " ", valor)
    return valor.strip()


def _texto_compacto(texto: str) -> str:
    return re.sub(r"\s+", " ", normalizar_texto(texto)).strip()


def _agregar(riesgos: set[str], *items: str) -> None:
    for item in items:
        if item:
            riesgos.add(item)


def detectar_riesgos(texto: str) -> dict:
    """Detecta riesgos explícitos y abreviaturas frecuentes.

    Importante: evita interpretar un código aislado (por ejemplo "C") como una
    cobertura. El contenido debe contener lenguaje de riesgos o abreviaturas.
    """
    t = _texto_compacto(texto)
    riesgos: set[str] = set()
    evidencias: list[str] = []

    def hit(patron: str, *items: str, evidencia: str | None = None) -> bool:
        if re.search(patron, t, flags=re.I):
            _agregar(riesgos, *items)
            evidencias.append(evidencia or patron)
            return True
        return False

    # Responsabilidad civil.
    hit(r"\bRESP(?:ONSABILIDAD)?\.?\s*CIVIL\b|\bR\.?\s*C\.?\b", RC, evidencia="RC")

    # Todo Riesgo / daños parciales por accidente.
    if hit(r"\bTODO\s+RIESGO\b|\bT\.?\s*D\.?\s*(?:1|2|3)?\b", DP_ACC, evidencia="Todo Riesgo"):
        # Un Todo Riesgo automotor presupone el núcleo de daños totales/incendio/robo.
        # Esta expansión es una normalización de perfil, no una lectura literal de un código aislado.
        _agregar(riesgos, RC, DT_ACC, INC_T, INC_P, ROB_T, ROB_P)

    hit(
        r"\b(?:PERD(?:IDA)?|DESTR(?:UCCION)?)\.?\s+TOTAL\s+(?:POR\s+)?ACCID(?:ENTE)?\b|"
        r"\bP\.?\s*T\.?\s*(?:ACC|AC)\.?\b|\bPT\s*(?:ACC|AC)\b",
        DT_ACC,
        evidencia="Pérdida/Destrucción Total por Accidente",
    )
    hit(r"\bDANOS?\s+PARCIALES?\s+(?:POR\s+)?ACCID(?:ENTE)?\b", DP_ACC, evidencia="Daños Parciales por Accidente")

    # Incendio. Primero los patrones total+parcial para que una abreviatura PTyP
    # se expanda correctamente.
    incendio_ambos = hit(
        r"\bINCENDIO\s+(?:TOTAL\s*(?:Y|/|E)\s*PARCIAL|TOTAL\s+Y/O\s+PARCIAL|TOTAL\s+O\s+PARCIAL)\b|"
        r"\bP\.?\s*T\.?\s*Y\s*P\.?\s*INC\.?\b|\bP\.?T\.?Y?P\.?\s*IN(?:C)?\.?\b|\bPTY?P\s*IN(?:C)?\.?\b|"
        r"\bP\.?\s*TOTAL\s*(?:Y|/)\s*PARCIAL\s+INC\.?\b|\bPTOTAL\s*(?:Y|/)\s*PARCIAL\s+INC\.?\b",
        INC_T, INC_P,
        evidencia="Incendio Total y Parcial",
    )
    if not incendio_ambos:
        hit(r"\bINCENDIO\s+TOTAL\b|\bP\.?\s*TOTAL\s+INC\.?\b|\bPTOTAL\s+INC\.?\b", INC_T, evidencia="Incendio Total")
        hit(r"\bINCENDIO\s+PARCIAL\b|\bP\.?\s*PARCIAL\s+INC\.?\b", INC_P, evidencia="Incendio Parcial")

    # Robo/hurto explícito.
    robo_ambos = hit(
        r"\b(?:ROBO|HURTO)(?:\s*/\s*HURTO)?\s+(?:TOTAL\s*(?:Y|/|E)\s*PARCIAL|TOTAL\s+Y/O\s+PARCIAL|TOTAL\s+O\s+PARCIAL)\b|"
        r"\bROBO\s+TOTAL\s*(?:Y|/)\s*PARCIAL\b",
        ROB_T, ROB_P,
        evidencia="Robo/Hurto Total y Parcial",
    )
    if not robo_ambos:
        hit(r"\b(?:ROBO|HURTO)(?:\s*/\s*HURTO)?\s+TOTAL\b|\bROBO\s+TOT\.?\b", ROB_T, evidencia="Robo/Hurto Total")
        hit(r"\b(?:ROBO|HURTO)(?:\s*/\s*HURTO)?\s+PARCIAL\b|\bR\.?\s*PARC\.?\b", ROB_P, evidencia="Robo/Hurto Parcial")

    # Abreviaturas de Federación y formatos equivalentes usados en tablas.
    # "PERD TOTAL Accid. Inc. y Robo" usa TOTAL como calificador de los tres riesgos.
    if re.search(r"\bPERD(?:IDA)?\s+TOTAL\b.*\bACCID", t) and re.search(r"\bINC\.?\b", t) and re.search(r"\bROBO\b", t):
        _agregar(riesgos, DT_ACC, INC_T, ROB_T)
        evidencias.append("PERD TOTAL Accid. Inc. y Robo")
    elif re.search(r"\bPERD(?:IDA)?\s+TOTAL\b.*\bINC\.?\b.*\bROBO\b", t):
        _agregar(riesgos, INC_T, ROB_T)
        evidencias.append("PERD TOTAL Inc. y Robo")

    # Cuando el documento dice PTyP Inc. y Robo, la construcción comercial indica
    # Total y Parcial para ambos riesgos.
    if re.search(r"(?:P\.?T\.?Y?P\.?|PTY?P|P\.?\s*T\.?\s*Y\s*P\.?|P\.?\s*TOTAL\s*(?:Y|/)\s*PARCIAL).*\bIN(?:C)?\.?\b.*\bROBO\b", t):
        _agregar(riesgos, INC_T, INC_P, ROB_T, ROB_P)
        evidencias.append("PTyP Inc. y Robo")

    # Robo parcial al amparo del robo total: no equivale a robo parcial pleno.
    if re.search(r"\bRP\s*(?:AMP|AMPAR(?:O|ADO)?)\.?\s*(?:TOT|TOTAL)\.?\b|ROBO\s+PARCIAL\s+(?:AL\s+)?AMPARO\s+(?:DEL\s+)?ROBO\s+TOTAL", t):
        riesgos.discard(ROB_P)
        _agregar(riesgos, ROB_T, ROB_P_AMP)
        evidencias.append("Robo Parcial al amparo del Robo Total")

    # En algunas tablas aparece "RP TOT." para el concepto de robo parcial ligado
    # al robo total. Solo se interpreta así cuando ya hay robo total en el mismo texto.
    if ROB_T in riesgos and re.search(r"\bRP\s+TOT\.?\b", t):
        riesgos.discard(ROB_P)
        _agregar(riesgos, ROB_P_AMP)
        evidencias.append("RP TOT.")

    hit(r"\bRUEDAS?\b|\bNEUMATICOS?\b", RUEDAS, evidencia="Ruedas")
    hit(r"\bBATERI(?:A|AS)\b", BATERIA, evidencia="Batería")
    hit(r"\bVIDRIOS?\b|\bCRISTALES?\b|\bPARABRISAS\b|\bLUNETA\b", VIDRIOS, evidencia="Vidrios")
    hit(r"\bGRANIZO\b", GRANIZO, evidencia="Granizo")
    hit(r"\bCERRADURAS?\b|\bCERRAJERIA\b", CERRADURAS, evidencia="Cerraduras")
    hit(r"\b(?:SERVICIO\s+DE\s+)?GRUA\b|\bREMOLQUE\b|\bASISTENCIA\s+(?:MECANICA|VEHICULAR)\b", GRUA, evidencia="Grúa/Asistencia")

    # Resúmenes tabulares frecuentes en cotizadores de compañías distintas.
    # No dependen del código B/C: la descripción visible aporta el significado.
    if re.search(r"\bTOTALES?\s+Y\s+PARCIALES?\s+CON\s+DESTRUCCION\s+TOTAL\b|\bTOT\.?\s*Y\s*PARC\.?\s*C/?\s*DESTRUC\.?\s*TOTAL\b", t):
        _agregar(riesgos, RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC)
        evidencias.append("Totales y parciales con destrucción total")
    elif re.search(r"\bTOTALES?\s+Y\s+PARCIALES?\s+SIN\s+DESTRUCCION\s+TOTAL\b", t):
        _agregar(riesgos, RC, INC_T, INC_P, ROB_T, ROB_P)
        evidencias.append("Totales y parciales sin destrucción total")
    elif re.search(r"\bTOTALES?\s+CON\s+DESTRUCCION\s+TOTAL\b", t):
        _agregar(riesgos, RC, INC_T, ROB_T, DT_ACC)
        evidencias.append("Totales con destrucción total")
    elif re.search(r"\bTOTALES?\s+SIN\s+DESTRUCCION\s+TOTAL\b", t):
        _agregar(riesgos, RC, INC_T, ROB_T)
        evidencias.append("Totales sin destrucción total")

    # Otra redacción frecuente: "destrucción total por accidente, total y parcial
    # por incendio y robo/hurto". Se expande sólo cuando la frase está visible.
    if re.search(r"DESTRUCCION\s+TOTAL.*TOTAL\s+Y\s+PARCIAL.*INCENDIO.*ROBO", t):
        _agregar(riesgos, RC, DT_ACC, INC_T, INC_P, ROB_T, ROB_P)
        evidencias.append("Destrucción total + incendio/robo total y parcial")

    return {
        "riesgos": sorted(riesgos),
        "evidencias": list(dict.fromkeys(evidencias)),
    }


def clasificar_perfil(riesgos: Iterable[str], texto: str = "", compania: str = "", codigo: str = "") -> str:
    r = set(riesgos or [])
    t = _texto_compacto(texto)
    cia = _texto_compacto(compania)
    cod = _texto_compacto(codigo).replace(" ", "")

    if DP_ACC in r or re.search(r"\bTODO\s+RIESGO\b", t):
        return PERFIL_TR

    # LB/LB1 son perfiles distintos de C1: robo parcial sólo al amparo del total.
    if {RC, INC_T, INC_P, ROB_T, ROB_P_AMP}.issubset(r):
        if DT_ACC in r:
            return PERFIL_LB
        return PERFIL_LB1

    core_c = {RC, INC_T, INC_P, ROB_T, ROB_P}
    if core_c.issubset(r):
        extras_visibles = {VIDRIOS, GRANIZO, CERRADURAS}
        if extras_visibles.issubset(r) or len(extras_visibles.intersection(r)) >= 2:
            return PERFIL_C_PLUS
        if DT_ACC in r:
            return PERFIL_C
        return PERFIL_C1

    if {RC, INC_T, ROB_T, DT_ACC}.issubset(r):
        return PERFIL_B
    if {RC, INC_T, ROB_T}.issubset(r) and DT_ACC not in r:
        return PERFIL_B1
    if r == {RC} or (RC in r and len(r - {GRUA}) == 1):
        return PERFIL_RC

    # Códigos conocidos sólo se usan como ayuda cuando la compañía también está
    # identificada. Nunca se aplica esta parte a una compañía desconocida.
    if cia:
        es_federacion = "FEDERACION PATRONAL" in cia
        if es_federacion:
            if cod == "LB":
                return PERFIL_LB
            if cod == "LB1":
                return PERFIL_LB1
            if cod == "CF":
                return PERFIL_C_PLUS
            if cod == "C":
                return PERFIL_C
            if cod == "C1":
                return PERFIL_C1
            if cod == "B":
                return PERFIL_B
            if cod == "B1":
                return PERFIL_B1
            if cod.startswith("TD"):
                return PERFIL_TR
            if cod in {"A", "A4"}:
                return PERFIL_RC

        es_mercantil = "MERCANTIL ANDINA" in cia
        if es_mercantil:
            if cod == "A":
                return PERFIL_RC
            if cod == "B":
                return PERFIL_B
            if cod == "B1":
                return PERFIL_B1
            if cod in {"MB", "MBASICA", "MBASICA"}:
                return PERFIL_C
            if cod in {"MP", "MPLUS"}:
                return PERFIL_C_PLUS
            if cod.startswith("D2") or cod in {"D3", "D4", "D5"}:
                return PERFIL_TR

        es_atm = re.search(r"(?:^|\b)ATM(?:\b|$)", cia) is not None
        if es_atm:
            if cod in {"A", "A1"}:
                return PERFIL_RC
            if cod == "B":
                return PERFIL_B
            if cod == "B1":
                return PERFIL_B1
            if cod == "C":
                return PERFIL_C
            if cod.startswith("TR"):
                return PERFIL_TR

    return PERFIL_SIN_CLASIFICAR


def nombre_perfil(perfil: str, nombre_original: str = "", codigo_original: str = "") -> str:
    p = str(perfil or PERFIL_SIN_CLASIFICAR).strip().upper()
    if p != PERFIL_SIN_CLASIFICAR:
        return PROFILE_LABELS.get(p, "Cobertura")
    return str(nombre_original or codigo_original or "Cobertura").strip()


def descripcion_comercial(perfil: str, riesgos: Iterable[str], texto_fuente: str = "") -> str:
    """Devuelve speech determinístico y conservador.

    Para C normal se omiten ruedas/batería aunque estén conocidas internamente.
    Los adicionales se exponen para C_PLUS/equivalentes confirmados o cuando la
    evidencia explícita los ubica claramente en ese perfil superior.
    """
    p = str(perfil or PERFIL_SIN_CLASIFICAR).upper()
    r = set(riesgos or [])

    if p == PERFIL_RC:
        return "Responsabilidad civil."
    if p == PERFIL_B:
        return "Responsabilidad civil, incendio total, robo/hurto total y destrucción total por accidente."
    if p == PERFIL_B1:
        return "Responsabilidad civil, incendio total y robo/hurto total."
    if p == PERFIL_C:
        return "Responsabilidad civil, incendio total y parcial, robo/hurto total y parcial y destrucción total por accidente."
    if p == PERFIL_C1:
        return "Responsabilidad civil, incendio total y parcial y robo/hurto total y parcial."
    if p == PERFIL_C_PLUS:
        base = "Responsabilidad civil, incendio total y parcial, robo/hurto total y parcial y destrucción total por accidente."
        extras = []
        for risk, label in ((RUEDAS, "ruedas"), (VIDRIOS, "vidrios"), (GRANIZO, "granizo"), (CERRADURAS, "cerraduras")):
            if risk in r:
                extras.append(label)
        # En perfiles C_PLUS conocidos, el set clásico puede venir normalizado por
        # código aun si el PDF no repite cada palabra. Si no hay extras explícitos,
        # no inventar para compañía desconocida: queda sólo el núcleo.
        if extras:
            return base + " Cubre " + ", ".join(extras[:-1]) + (" y " + extras[-1] if len(extras) > 1 else extras[0]) + "."
        return base
    if p == PERFIL_LB:
        return "Responsabilidad civil, incendio total y parcial, robo/hurto total, robo parcial al amparo del robo total y destrucción total por accidente."
    if p == PERFIL_LB1:
        return "Responsabilidad civil, incendio total y parcial, robo/hurto total y robo parcial al amparo del robo total."
    if p == PERFIL_TR:
        return "Responsabilidad civil, incendio total y parcial, robo/hurto total y parcial, destrucción total y daños parciales por accidente."

    # Sin perfil seguro: explayar sólo riesgos explícitos en un orden comercial.
    orden = [RC, ROB_T, ROB_P, ROB_P_AMP, INC_T, INC_P, DT_ACC, DP_ACC, RUEDAS, BATERIA, VIDRIOS, GRANIZO, CERRADURAS]
    labels = [RISK_LABELS[x] for x in orden if x in r]
    if not labels:
        return ""
    return ", ".join(labels) + "."


def normalizar_cobertura(texto: str, *, compania: str = "", codigo: str = "", nombre: str = "") -> dict:
    deteccion = detectar_riesgos(" ".join(x for x in [nombre, texto] if x))
    perfil = clasificar_perfil(deteccion["riesgos"], texto=" ".join([nombre, texto]), compania=compania, codigo=codigo)
    return {
        "perfil_normalizado": perfil,
        "nombre_cliente": nombre_perfil(perfil, nombre, codigo),
        "descripcion_cliente": descripcion_comercial(perfil, deteccion["riesgos"], texto),
        "riesgos_detectados": deteccion["riesgos"],
        "evidencias": deteccion["evidencias"],
        "texto_fuente": str(texto or "").strip(),
        "codigo_original": str(codigo or "").strip(),
        "nombre_original": str(nombre or "").strip(),
    }


def _money_decimal(texto: str) -> Decimal | None:
    raw = str(texto or "").strip().replace("$", "").replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        partes = raw.split(",")
        raw = raw.replace(".", "").replace(",", ".") if len(partes[-1]) in {1, 2} else raw.replace(",", "")
    elif "." in raw:
        partes = raw.split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            raw = raw.replace(".", "")
    raw = re.sub(r"[^0-9.-]", "", raw)
    try:
        n = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return n if n > 0 else None


def _fmt_money(valor: Decimal | None) -> str:
    if valor is None:
        return ""
    q = valor.quantize(Decimal("0.01"))
    entero, dec = f"{q:.2f}".split(".")
    return "$" + f"{int(entero):,}".replace(",", ".") + f",{dec}"


def _canonicalizar_compania(nombre: str) -> str:
    crudo = str(nombre or "").strip()
    if not crudo or crudo == "Compañía no identificada":
        return crudo or "Compañía no identificada"
    codigo = normalizar_compania(crudo)
    codigos_conocidos = {cod for cod, _display in aliases_companias().values()}
    if codigo in codigos_conocidos:
        return nombre_compania(crudo)
    return crudo


def _pct_visual(valor: str) -> str:
    raw = re.sub(r"(?:\s*%)+\s*$", "", str(valor or "").strip()).replace(",", ".")
    try:
        d = Decimal(raw)
    except Exception:
        return raw
    if d == d.to_integral():
        return str(int(d))
    return format(d.normalize(), "f")


def normalizar_porcentaje(valor) -> str:
    """Devuelve un porcentaje comercial estable con un único signo final."""
    limpio = _pct_visual(valor)
    return f"{limpio}%" if limpio else ""


def _aplicar_modelo_comercial(opciones: list[dict]) -> list[dict]:
    """Completa una representación comercial única sin perder el dato fuente.

    La variante de grúa sólo sube al título cuando dentro de la misma familia
    existen las dos alternativas. Todo Riesgo siempre conserva su franquicia
    explícita como variante comercial.
    """
    grupos_grua: dict[str, set[bool]] = {}
    for item in opciones:
        familia = str(item.get("perfil_normalizado") or PERFIL_SIN_CLASIFICAR)
        grua = item.get("servicio_grua")
        if isinstance(grua, bool):
            grupos_grua.setdefault(familia, set()).add(grua)

    for item in opciones:
        perfil = str(item.get("perfil_normalizado") or PERFIL_SIN_CLASIFICAR)
        nombre = str(item.get("nombre_cliente") or item.get("nombre_original") or item.get("codigo_original") or "Cobertura").strip()
        variantes: list[str] = []
        pct = normalizar_porcentaje(item.get("franquicia_pct"))
        if perfil == PERFIL_TR and pct:
            variantes.append(f"FRANQUICIA {pct}")
        grua = item.get("servicio_grua")
        if isinstance(grua, bool) and grupos_grua.get(perfil) == {False, True}:
            variantes.append("CON GRÚA" if grua else "SIN GRÚA")
        item["codigo"] = str(item.get("codigo_original") or "").strip()
        item["familia"] = perfil
        item["nombre_comercial"] = nombre
        item["variante_comercial"] = " · ".join(variantes)
        item["titulo_comercial"] = " · ".join([nombre, *variantes])
        item["tiene_grua"] = grua if isinstance(grua, bool) else None
        item["orden_comercial"] = PROFILE_ORDER.get(perfil, 90)
    return opciones


def _codigo_visual_cobertura(codigo: str, perfil: str, franquicia_pct: str) -> str:
    # Regla universal acordada: Todo Riesgo se identifica visualmente por el
    # porcentaje real de franquicia, independientemente de cómo lo llame la cia.
    # Ej.: 1,5% -> D1.5 ; 2% -> D2 ; 3% -> D3.
    if str(perfil or "").upper() == PERFIL_TR and str(franquicia_pct or "").strip():
        return "D" + _pct_visual(franquicia_pct)
    return str(codigo or perfil or "COB").strip() or "COB"


def _ordenar_coberturas(opciones: list[dict]) -> list[dict]:
    """Ordena de menor a mayor protección y franquicias TR en forma estable."""
    salida = list(opciones or [])

    def clave(par):
        indice, item = par
        perfil = str(item.get("perfil_normalizado") or PERFIL_SIN_CLASIFICAR)
        try:
            franquicia = Decimal(str(item.get("franquicia_pct") or "").replace("%", "").replace(",", "."))
        except Exception:
            franquicia = Decimal("9999")
        return (PROFILE_ORDER.get(perfil, 90), franquicia if perfil == PERFIL_TR else Decimal("0"), indice)

    return [item for _indice, item in sorted(enumerate(salida), key=clave)]


def _detectar_compania(texto: str) -> str:
    t = normalizar_texto(texto)
    conocidas = [
        (r"\bFEDERACION\s+PATRONAL\b", "Federación Patronal"),
        (r"\bLA\s+MERCANTIL\s+ANDINA\b|\bMERCANTIL\s+ANDINA\b", "Mercantil Andina"),
        (r"\bATM\s+SEGUROS\b|\bATM\b", "ATM"),
        (r"\bSANCOR\s+SEGUROS\b", "Sancor Seguros"),
        (r"\bSAN\s+CRISTOBAL\b", "San Cristóbal"),
        (r"\b(?:COMPANIA\s+DE\s+SEGUROS\s+)?AGRO\s*SALTA\b|\bAGS\s+SEGUROS\b", "AgroSalta"),
        (r"\bRIVADAVIA\s+SEGUROS\b|\bSEGUROS\s+RIVADAVIA\b", "Rivadavia"),
        (r"\bALLIANZ\b", "Allianz"),
        (r"\bMAPFRE\b", "MAPFRE"),
        (r"\bPROVINCIA\s+SEGUROS\b", "Provincia Seguros"),
        (r"\bRIO\s+URUGUAY\s+SEGUROS\b", "Río Uruguay Seguros"),
        (r"\bTRIUNFO\s+SEGUROS\b", "Triunfo Seguros"),
        (r"\bPARANA\s+SEGUROS\b", "Paraná Seguros"),
    ]
    for patron, nombre in conocidas:
        if re.search(patron, t):
            return _canonicalizar_compania(nombre)

    # Heurística conservadora para una compañía no registrada: usar una línea
    # corporativa sólo si contiene una palabra inequívoca de aseguradora.
    for linea in str(texto or "").splitlines()[:35]:
        limpia = re.sub(r"\s+", " ", linea).strip(" -|:")
        if 3 <= len(limpia) <= 90 and re.search(r"\b(SEGUROS?|ASEGURADORA|ASEGURADORA\s+DE\s+RIESGOS)\b", _sin_acentos(limpia), re.I):
            return _canonicalizar_compania(limpia)
    return "Compañía no identificada"


def _extraer_suma_asegurada(texto: str) -> Decimal | None:
    patrones = [
        r"SUMA\s+ASEGURADA\s*[:\-]?\s*\$?\s*([\d.,]+)",
        r"MONTO\s+ASEGURADO\s*[:\-]?\s*\$?\s*([\d.,]+)",
        r"\bS\.?\s*A\.?\s*[:\-]\s*\$?\s*([\d.,]+)",
        r"\bVALOR\s*[:\-]\s*\$\s*([\d.,]+)",
    ]
    t = normalizar_texto(texto)
    for patron in patrones:
        m = re.search(patron, t, flags=re.I)
        if m:
            n = _money_decimal(m.group(1))
            if n is not None:
                return n
    return None


def _extraer_anio(texto: str) -> str:
    t = normalizar_texto(texto)
    for patron in (r"ANO\s+(?:DE\s+FABRICACION\s*)?[:\-]?\s*((?:19|20)\d{2})", r"MODELO\s*[:\-]?\s*((?:19|20)\d{2})"):
        m = re.search(patron, t)
        if m:
            return m.group(1)
    return ""


def _extraer_vehiculo(texto: str) -> str:
    raw = str(texto or "")
    # Preferir el submodelo/modelo explícito antes que el rótulo "Vehículo cotizado".
    for patron in (
        r"(?im)^\s*SUBMODELO\s*[:\-]\s*(.+)$",
        r"(?im)^\s*MODELO\s*[:\-]\s*(.+)$",
        r"(?im)^\s*VEHICULO\s*[:\-]\s*(.+)$",
        r"(?im)^\s*UNIDAD\s*[:\-]\s*(.+)$",
    ):
        m = re.search(patron, raw)
        if m:
            val = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(val) > 2:
                return val[:160]
    return ""


def _extraer_codigo(linea: str) -> str:
    raw = str(linea or "").strip()
    # A/B1/C+/CM/TD3/D2 0030/códigos numéricos (90/91/92), etc.
    code = r"(?:D2\s+\d{4}|[A-Z]{1,5}\+?\d?(?:[.,]\d+)?|\d{2,3})"
    patrones = [
        rf"^(?:COBERTURA|PLAN)\s+({code})\b",
        rf"^({code})\s*(?:-|:|\|)",
    ]
    t = normalizar_texto(raw)
    for patron in patrones:
        m = re.search(patron, t, flags=re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip().upper().replace(",", ".")
    return ""


def _precio_en_bloque(bloque: str) -> Decimal | None:
    t = normalizar_texto(bloque)
    patrones = [
        r"(?:POR\s+CUOTA|VALOR\s+CUOTA|CUOTA|PRECIO|PREMIO\s+MENSUAL|PREMIO)\s*[:\-]?\s*\$?\s*([\d.,]+)",
        r"\$\s*([\d.]+,[0-9]{2})\s*(?:POR\s+CUOTA|MENSUAL)",
    ]
    for patron in patrones:
        m = re.search(patron, t, flags=re.I)
        if m:
            n = _money_decimal(m.group(1))
            if n is not None:
                return n
    return None


def _precio_fila_tabular(linea: str, texto_documento: str) -> Decimal | None:
    """En tablas con columna Cuota/s, el último importe de la fila es la cuota."""
    doc = normalizar_texto(texto_documento)
    if not re.search(r"\b(?:CUOTA|CUOTAS|PRIMERA\s+CUOTA)\b", doc):
        return None
    valores = re.findall(r"\$\s*([\d.]+(?:,[0-9]{1,2})?)", str(linea or ""))
    if not valores:
        return None
    return _money_decimal(valores[-1])


def _franquicia_en_bloque(bloque: str) -> tuple[str, Decimal | None, str]:
    t = normalizar_texto(bloque)
    pct = ""
    imp = None
    desc = ""
    m = re.search(r"FRANQUICIA[^\n]{0,100}?(\d{1,2}(?:[.,]\d+)?)\s*%", t, flags=re.I)
    if m:
        pct = m.group(1).replace(",", ".")
        desc = m.group(0).strip()
    m2 = re.search(r"FRANQUICIA[^\n]{0,120}?\$\s*([\d.,]+)", t, flags=re.I)
    if m2:
        imp = _money_decimal(m2.group(1))
        if not desc:
            desc = m2.group(0).strip()
    return pct, imp, desc


def _grua_en_bloque(bloque: str) -> bool | None:
    t = normalizar_texto(bloque)
    if re.search(r"\bSIN\s+(?:SERV(?:ICIO)?\.?\s+DE\s+)?GRUA\b|\bSIN\s+ASISTENCIA\b", t):
        return False
    if re.search(r"\bCON\s+(?:SERV(?:ICIO)?\.?\s+DE\s+)?GRUA\b|\bINCLUYE\s+GRUA\b|\bASISTENCIA\s+(?:MECANICA|VEHICULAR)\b", t):
        return True
    return None


def _es_linea_cobertura(linea: str) -> bool:
    t = _texto_compacto(linea)
    if not t or len(t) < 3:
        return False
    if t.startswith(("-", "•", "*")) or re.search(r"\bPLANES?\s+(?:CF|TD|TODO RIESGO)\b", t) or t.startswith("ASEGURADO POR"):
        return False
    d = detectar_riesgos(t)["riesgos"]
    if len(d) >= 2:
        return True
    if re.search(r"\b(?:COBERTURA|PLAN)\s+[A-Z0-9]+\b", t) and d:
        return True
    # Fila tabular de cotizador: código + descripción aseguradora + importes.
    codigo = _extraer_codigo(linea)
    if codigo and re.search(r"\b(?:RESPONSABILIDAD|TOTAL(?:ES)?|PARCIAL(?:ES)?|TODO\s+RIESGO|ROBO|HURTO|INCENDIO|DESTRUCCION|GRANIZO|CRIST|PARABRIS|FRANQUICIA)\b", t):
        return True
    return False


def _candidatos_cobertura(texto: str) -> list[dict]:
    lineas = [re.sub(r"\s+", " ", x).strip() for x in str(texto or "").splitlines() if x.strip()]
    candidatos: list[dict] = []
    vistos: set[str] = set()
    for i, linea in enumerate(lineas):
        if not _es_linea_cobertura(linea):
            continue
        # Incluimos líneas cercanas para capturar precio/franquicia/asistencia sin
        # extender tanto el bloque como para mezclar la cobertura siguiente.
        vecinas = [linea]
        for j in range(i + 1, min(i + 5, len(lineas))):
            if j > i + 1 and _es_linea_cobertura(lineas[j]):
                break
            vecinas.append(lineas[j])
        bloque = "\n".join(vecinas)
        clave = _texto_compacto(linea)
        if clave in vistos:
            continue
        vistos.add(clave)
        candidatos.append({"linea": linea, "bloque": bloque, "codigo": _extraer_codigo(linea)})
    return candidatos


def normalizar_texto_cotizacion(texto: str, *, compania: str = "") -> dict:
    raw = str(texto or "").strip()
    if not raw:
        raise ValueError("No recibí texto para normalizar.")
    cia = _canonicalizar_compania(str(compania or "").strip() or _detectar_compania(raw))
    suma = _extraer_suma_asegurada(raw)
    anio = _extraer_anio(raw)
    vehiculo = _extraer_vehiculo(raw)
    opciones = []

    for idx, cand in enumerate(_candidatos_cobertura(raw), start=1):
        codigo = cand["codigo"]
        normal = normalizar_cobertura(cand["linea"], compania=cia if cia != "Compañía no identificada" else "", codigo=codigo, nombre=cand["linea"])
        if normal["perfil_normalizado"] == PERFIL_SIN_CLASIFICAR and not normal["riesgos_detectados"]:
            continue
        precio = _precio_en_bloque(cand["bloque"]) or _precio_fila_tabular(cand["bloque"], raw)
        franquicia_pct, franquicia_importe, franquicia_desc = _franquicia_en_bloque(cand["bloque"])
        grua = _grua_en_bloque(cand["bloque"])
        opciones.append({
            "uid": f"generica-{idx}",
            "codigo_original": codigo,
            "codigo_visual": _codigo_visual_cobertura(codigo, normal["perfil_normalizado"], franquicia_pct),
            "nombre_original": cand["linea"],
            "texto_fuente": cand["bloque"],
            "perfil_normalizado": normal["perfil_normalizado"],
            "nombre_cliente": normal["nombre_cliente"],
            "descripcion_cliente": normal["descripcion_cliente"],
            "riesgos_detectados": normal["riesgos_detectados"],
            "evidencias": normal["evidencias"],
            "precio_cuota": str(precio) if precio is not None else None,
            "precio_cuota_formateado": _fmt_money(precio),
            "franquicia_pct": franquicia_pct,
            "franquicia_importe": str(franquicia_importe) if franquicia_importe is not None else None,
            "franquicia_importe_formateado": _fmt_money(franquicia_importe),
            "franquicia_descripcion": franquicia_desc,
            "servicio_grua": grua,
        })

    # Si no encontramos una fila/plan pero el texto completo describe claramente
    # una cobertura, devolver una sola alternativa. Esto permite pegar párrafos o
    # PDFs simples sin estructura tabular.
    if not opciones:
        normal = normalizar_cobertura(raw, compania=cia if cia != "Compañía no identificada" else "")
        if normal["riesgos_detectados"]:
            precio = _precio_en_bloque(raw)
            franquicia_pct, franquicia_importe, franquicia_desc = _franquicia_en_bloque(raw)
            opciones.append({
                "uid": "generica-1",
                "codigo_original": "",
                "codigo_visual": _codigo_visual_cobertura("", normal["perfil_normalizado"] if normal["perfil_normalizado"] != PERFIL_SIN_CLASIFICAR else "COB", franquicia_pct),
                "nombre_original": "",
                "texto_fuente": raw[:2200],
                "perfil_normalizado": normal["perfil_normalizado"],
                "nombre_cliente": normal["nombre_cliente"],
                "descripcion_cliente": normal["descripcion_cliente"],
                "riesgos_detectados": normal["riesgos_detectados"],
                "evidencias": normal["evidencias"],
                "precio_cuota": str(precio) if precio is not None else None,
                "precio_cuota_formateado": _fmt_money(precio),
                "franquicia_pct": franquicia_pct,
                "franquicia_importe": str(franquicia_importe) if franquicia_importe is not None else None,
                "franquicia_importe_formateado": _fmt_money(franquicia_importe),
                "franquicia_descripcion": franquicia_desc,
                "servicio_grua": _grua_en_bloque(raw),
            })

    opciones = _aplicar_modelo_comercial(_ordenar_coberturas(opciones))
    return {
        "es_cotizacion_generica": bool(opciones),
        "compania": cia,
        "compania_detectada": cia,
        "compania_confirmada": "",
        "vehiculo": vehiculo,
        "anio": anio,
        "suma_asegurada": str(suma) if suma is not None else None,
        "suma_asegurada_formateada": _fmt_money(suma),
        "coberturas": opciones,
        "cantidad": len(opciones),
        "texto_fuente": raw[:12000],
    }


def extraer_cotizacion_generica_pdf(pdf_bytes: bytes) -> dict:
    if not pdf_bytes:
        raise ValueError("El PDF está vacío.")
    try:
        doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
    except Exception as exc:
        raise ValueError("No pude abrir el PDF de cotización.") from exc
    try:
        if doc.page_count < 1:
            raise ValueError("El PDF no contiene páginas.")
        paginas = [page.get_text("text") or "" for page in doc[: min(doc.page_count, 8)]]
    finally:
        doc.close()
    texto = "\n".join(paginas).strip()
    if not texto:
        return {"es_cotizacion_generica": False, "motivo": "El PDF no contiene texto extraíble."}
    return normalizar_texto_cotizacion(texto)


# -------------------------
# Fallback visual universal
# -------------------------
# Se importa en forma diferida para que el normalizador de texto/PDF siga
# funcionando aunque Gemini no esté configurado en un entorno local.

_GENERIC_VISION_INSTRUCTION = r"""
Sos un lector ESTRICTO de cotizaciones de seguros de automotores/motovehículos.
La compañía puede ser cualquiera. Tu trabajo es TRANSCRIBIR lo visible, no explicar ni inferir coberturas.

Devolvé SOLO JSON válido:
{
  "es_cotizacion": true,
  "compania": "texto visible o vacío",
  "vehiculo": "texto visible o vacío",
  "anio": "2026 o vacío",
  "suma_asegurada": "importe normalizado o vacío",
  "coberturas": [
    {
      "codigo": "código visible o vacío",
      "nombre": "nombre/descripcion visible",
      "descripcion": "texto completo visible de riesgos/abreviaturas",
      "precio": "importe por cuota si es inequívoco o vacío",
      "franquicia_pct": "porcentaje visible o vacío",
      "franquicia_importe": "importe visible o vacío",
      "grua": "si|no|desconocido"
    }
  ],
  "advertencias": []
}

Reglas:
- Transcribí TODAS las alternativas/tarjetas visibles; no te quedes sólo con la primera.
- Si hay varias alternativas con el mismo código pero distinta franquicia/precio, devolvelas TODAS por separado.
- No supongas qué significa B/C/CF/etc. si no hay descripción visible.
- Conservá abreviaturas visibles como RC, PT Acc., PTyP Inc., RP Amp Tot., etc.
- En Todo Riesgo, copiá siempre el porcentaje y el importe de franquicia si aparecen.
- No inventes precio, franquicia, grúa ni suma asegurada.
- Si no parece una cotización, es_cotizacion=false.
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
    raise ValueError("La lectura de cotización no devolvió JSON válido.")


def _normalizar_dato_vision(dato: dict) -> dict:
    if not bool(dato.get("es_cotizacion")):
        return {"es_cotizacion_generica": False}

    cia = _canonicalizar_compania(str(dato.get("compania") or "").strip() or "Compañía no identificada")
    suma = _money_decimal(dato.get("suma_asegurada"))
    opciones = []
    for idx, item in enumerate(dato.get("coberturas") or [], start=1):
        if not isinstance(item, dict):
            continue
        codigo = str(item.get("codigo") or "").strip()
        nombre = str(item.get("nombre") or "").strip()
        descripcion = str(item.get("descripcion") or "").strip()
        fuente = " ".join(x for x in [nombre, descripcion] if x).strip()
        normal = normalizar_cobertura(fuente, compania=cia if cia != "Compañía no identificada" else "", codigo=codigo, nombre=nombre)
        precio = _money_decimal(item.get("precio"))
        franquicia_importe = _money_decimal(item.get("franquicia_importe"))
        grua_raw = str(item.get("grua") or "").strip().lower()
        grua = True if grua_raw in {"si", "sí", "true"} else False if grua_raw in {"no", "false"} else None
        opciones.append({
            "uid": f"generica-vision-{idx}",
            "codigo_original": codigo,
            "codigo_visual": _codigo_visual_cobertura(
                codigo or (normal["perfil_normalizado"] if normal["perfil_normalizado"] != PERFIL_SIN_CLASIFICAR else f"OP{idx}"),
                normal["perfil_normalizado"],
                str(item.get("franquicia_pct") or "").strip(),
            ),
            "nombre_original": nombre,
            "texto_fuente": fuente,
            "perfil_normalizado": normal["perfil_normalizado"],
            "nombre_cliente": normal["nombre_cliente"],
            "descripcion_cliente": normal["descripcion_cliente"],
            "riesgos_detectados": normal["riesgos_detectados"],
            "evidencias": normal["evidencias"],
            "precio_cuota": str(precio) if precio is not None else None,
            "precio_cuota_formateado": _fmt_money(precio),
            "franquicia_pct": str(item.get("franquicia_pct") or "").strip(),
            "franquicia_importe": str(franquicia_importe) if franquicia_importe is not None else None,
            "franquicia_importe_formateado": _fmt_money(franquicia_importe),
            "servicio_grua": grua,
        })

    opciones = _aplicar_modelo_comercial(_ordenar_coberturas(opciones))
    return {
        "es_cotizacion_generica": bool(opciones),
        "compania": cia,
        "compania_detectada": cia,
        "compania_confirmada": "",
        "vehiculo": str(dato.get("vehiculo") or "").strip(),
        "anio": str(dato.get("anio") or "").strip(),
        "suma_asegurada": str(suma) if suma is not None else None,
        "suma_asegurada_formateada": _fmt_money(suma),
        "coberturas": opciones,
        "cantidad": len(opciones),
        "advertencias": [str(x).strip() for x in (dato.get("advertencias") or []) if str(x).strip()],
    }


def extraer_cotizacion_generica_pdf_vision(pdf_bytes: bytes) -> dict:
    """Fallback visual para PDFs escaneados o con texto imposible de estructurar."""
    from google.genai import types
    from ai_gateway import DEFAULT_MODELS, generate_with_fallback, obtener_cliente_gemini

    if not pdf_bytes:
        raise ValueError("El PDF está vacío.")
    try:
        doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
    except Exception as exc:
        raise ValueError("No pude abrir el PDF de cotización.") from exc
    imagenes = []
    try:
        for page in list(doc)[:2]:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.55, 1.55), alpha=False)
            imagenes.append(pix.tobytes("png"))
    finally:
        doc.close()
    if not imagenes:
        return {"es_cotizacion_generica": False}

    cliente = obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")
    partes = ["Transcribí esta cotización exactamente según el esquema JSON indicado."]
    partes.extend(types.Part.from_bytes(data=data, mime_type="image/png") for data in imagenes)
    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=3200,
        response_mime_type="application/json",
        system_instruction=_GENERIC_VISION_INSTRUCTION.strip(),
    )
    respuesta, _modelo = generate_with_fallback(
        client=cliente,
        models=DEFAULT_MODELS,
        contents=partes,
        config=config,
        log_prefix="GEMINI COTIZACION PDF UNIVERSAL",
        response_validator=lambda r: _json_robusto(getattr(r, "text", "")),
    )
    return _normalizar_dato_vision(_json_robusto(getattr(respuesta, "text", "")))


def extraer_cotizacion_generica_imagen(adjunto) -> dict:
    from google.genai import types
    from ai_gateway import DEFAULT_MODELS, generate_with_fallback, obtener_cliente_gemini
    from attachment_vision import renderizar_para_vision

    media = renderizar_para_vision(adjunto, max_paginas=1, escala_pdf=1.7)
    if not media:
        raise ValueError("No recibí una imagen válida para leer la cotización.")
    cliente = obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")
    partes = [
        "Transcribí esta cotización exactamente según el esquema JSON indicado.",
        types.Part.from_bytes(data=media[0].data, mime_type=media[0].mime_type),
    ]
    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=2600,
        response_mime_type="application/json",
        system_instruction=_GENERIC_VISION_INSTRUCTION.strip(),
    )
    respuesta, _modelo = generate_with_fallback(
        client=cliente,
        models=DEFAULT_MODELS,
        contents=partes,
        config=config,
        log_prefix="GEMINI COTIZACION UNIVERSAL",
        response_validator=lambda r: _json_robusto(getattr(r, "text", "")),
    )
    dato = _json_robusto(getattr(respuesta, "text", ""))
    return _normalizar_dato_vision(dato)


__all__ = [
    "detectar_riesgos",
    "clasificar_perfil",
    "normalizar_cobertura",
    "normalizar_porcentaje",
    "normalizar_texto_cotizacion",
    "extraer_cotizacion_generica_pdf",
    "extraer_cotizacion_generica_pdf_vision",
    "extraer_cotizacion_generica_imagen",
    "PERFIL_RC", "PERFIL_B", "PERFIL_B1", "PERFIL_C", "PERFIL_C1",
    "PERFIL_C_PLUS", "PERFIL_LB", "PERFIL_LB1", "PERFIL_TR", "PERFIL_SIN_CLASIFICAR",
]
