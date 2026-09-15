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

from companias import nombre_compania, normalizar_compania, aliases_companias, detectar_compania_en_texto


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
    hit(r"\bVIDRIOS?\b|\bCRISTALES?\b|\bCRIST\.?\b|\bPARABRIS(?:AS)?\b|\bLUNETAS?\b", VIDRIOS, evidencia="Vidrios")
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

    # Códigos ATM del catálogo confirmado tienen identidad comercial propia.
    # Se resuelven antes del perfil por contenido para que B/B1 con prestaciones
    # parciales no sean aplastadas como Terceros Completo.
    if re.search(r"(?:^|\b)ATM(?:\b|$)", cia):
        if cod in {"A", "A1"}: return PERFIL_RC
        if cod == "B": return PERFIL_B
        if cod == "B1": return PERFIL_B1
        if cod in {"C", "CPR", "CB"}: return PERFIL_C_PLUS
        if cod.startswith("TR"): return PERFIL_TR

    if DP_ACC in r or re.search(r"\bTODO\s+RIESGO\b", t):
        return PERFIL_TR

    # Una denominación comercial explícita también es evidencia de familia.
    # Se usa únicamente cuando la frase está visible; no se deduce por código.
    if re.search(r"\bTERCEROS?\s+COMPLET(?:O|OS)\b", t):
        if re.search(r"\b(?:PLUS|PREMIUM|FULL|BLACK)\b", t):
            return PERFIL_C_PLUS
        return PERFIL_C

    # LB/LB1 son perfiles distintos de C1: robo parcial sólo al amparo del total.
    if {RC, INC_T, INC_P, ROB_T, ROB_P_AMP}.issubset(r):
        if DT_ACC in r:
            return PERFIL_LB
        return PERFIL_LB1

    core_c = {RC, INC_T, INC_P, ROB_T, ROB_P}
    if core_c.issubset(r):
        extras_visibles = {RUEDAS, VIDRIOS, GRANIZO, CERRADURAS}
        # Una prestación adicional explícita ya diferencia a la alternativa
        # del núcleo C. No exigimos dos extras porque distintas compañías
        # pueden ofrecer un C mejorado con un solo adicional visible.
        # La descripción final enumera únicamente lo realmente confirmado.
        if extras_visibles.intersection(r):
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

        es_allianz = "ALLIANZ" in cia
        if es_allianz:
            # Allianz D4 Alta Gama VIP: códigos 90/91/92 son el mismo producto
            # Todo Riesgo con distinta franquicia. Granizo es un adicional, no
            # una familia/nombre de cobertura.
            if cod in {"90", "91", "92"} and ("ALTA GAMA VIP" in t or "D4" in t):
                return PERFIL_TR
            if "ALTA GAMA VIP" in t and re.search(r"\b\d{1,2}(?:[.,]\d+)?\s*%", t):
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


def _nombre_comercial_explicito(texto: str, codigo: str = "") -> str:
    """Extrae un nombre comercial visible sin dejar que una segmentación lo tape.

    Regla universal: cuando la fuente trae una denominación inequívoca de
    cobertura (p. ej. ``TERCEROS COMPLETOS C2``), esa denominación tiene
    prioridad de presentación sobre rótulos de segmentación como ``CLÁSICO
    SEGMENTADO``. No depende de una compañía concreta.
    """
    t = _texto_compacto(texto)
    if not t:
        return ""

    # Código al final: ``TERCEROS COMPLETOS C2``. Se conserva porque forma
    # parte de la denominación visible de la cobertura, no porque el código
    # tenga un significado inferido por OficinaIA.
    m = re.search(r"\bTERCEROS?\s+COMPLET(?:O|OS)\s+([A-Z]{1,4}\d+(?:[.,]\d+)?)\b", t)
    if m:
        return f"Terceros Completo {m.group(1).replace(',', '.')}"

    if re.search(r"\bTERCEROS?\s+COMPLET(?:O|OS)\b", t):
        if re.search(r"\b(?:PLUS|PREMIUM|FULL|BLACK)\b", t):
            variante = re.search(r"\b(PLUS|PREMIUM|FULL|BLACK)\b", t).group(1).title()
            return f"Terceros Completo {variante}"
        return "Terceros Completo"
    if re.search(r"\b(?:D4\s+)?ALTA\s+GAMA\s+VIP\b", t):
        return "Alta Gama VIP"
    if re.search(r"\bTODO\s+RIESGO\b", t):
        return "Todo Riesgo"
    if re.search(r"\bRESP(?:ONSABILIDAD)?\.?\s*CIVIL\b", t) and not re.search(r"\b(?:ROBO|INCENDIO|TODO\s+RIESGO|TERCEROS?)\b", t):
        return "Responsabilidad Civil"
    return ""


def prestaciones_comerciales(perfil: str, riesgos: Iterable[str]) -> list[str]:
    """Prestaciones canónicas, una por línea, para cualquier renderer.

    La familia aporta el núcleo mínimo ya confirmado. Los riesgos estructurados
    agregan únicamente prestaciones explícitas. Nunca vuelve a una frase legacy.
    """
    p = str(perfil or PERFIL_SIN_CLASIFICAR).upper()
    r = set(riesgos or [])
    base_por_perfil = {
        PERFIL_RC: [RC],
        PERFIL_B: [RC, INC_T, ROB_T, DT_ACC],
        PERFIL_B1: [RC, INC_T, ROB_T],
        PERFIL_C: [RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC],
        PERFIL_C1: [RC, INC_T, INC_P, ROB_T, ROB_P],
        PERFIL_C_PLUS: [RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC],
        PERFIL_LB: [RC, INC_T, INC_P, ROB_T, ROB_P_AMP, DT_ACC],
        PERFIL_LB1: [RC, INC_T, INC_P, ROB_T, ROB_P_AMP],
        PERFIL_TR: [RC, INC_T, INC_P, ROB_T, ROB_P, DT_ACC, DP_ACC],
    }
    efectivos = []
    vistos = set()
    for risk in [*base_por_perfil.get(p, []), *list(r or [])]:
        if risk not in vistos:
            vistos.add(risk); efectivos.append(risk)

    # Combinar total/parcial en una sola prestación visual cuando ambos están.
    salida: list[str] = []
    if RC in efectivos: salida.append("Responsabilidad Civil")
    if INC_T in efectivos and INC_P in efectivos: salida.append("Incendio Total y Parcial")
    elif INC_T in efectivos: salida.append("Incendio Total")
    elif INC_P in efectivos: salida.append("Incendio Parcial")
    if ROB_T in efectivos and ROB_P in efectivos: salida.append("Robo/Hurto Total y Parcial")
    elif ROB_T in efectivos: salida.append("Robo/Hurto Total")
    elif ROB_P in efectivos: salida.append("Robo/Hurto Parcial")
    if ROB_P_AMP in efectivos: salida.append("Robo Parcial al amparo del Robo Total")
    if DT_ACC in efectivos: salida.append("Destrucción Total por Accidente")
    if DP_ACC in efectivos: salida.append("Daños Parciales por Accidente")
    for risk in (RUEDAS, BATERIA, VIDRIOS, GRANIZO, CERRADURAS):
        if risk in efectivos:
            salida.append(RISK_LABELS[risk])
    return salida


def descripcion_comercial(perfil: str, riesgos: Iterable[str], texto_fuente: str = "") -> str:
    """Descripción determinística estructurada: una prestación por línea."""
    return "\n".join(prestaciones_comerciales(perfil, riesgos))


def normalizar_cobertura(texto: str, *, compania: str = "", codigo: str = "", nombre: str = "") -> dict:
    fuente = " ".join(x for x in [nombre, texto] if x)
    deteccion = detectar_riesgos(fuente)
    perfil = clasificar_perfil(deteccion["riesgos"], texto=fuente, compania=compania, codigo=codigo)
    nombre_explicito = _nombre_comercial_explicito(nombre or texto, codigo)
    return {
        "perfil_normalizado": perfil,
        "nombre_cliente": nombre_explicito or nombre_perfil(perfil, nombre, codigo),
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
    """Devuelve un porcentaje comercial estable con formato visual es-AR."""
    limpio = _pct_visual(valor)
    visual = limpio.replace(".", ",") if limpio else ""
    return f"{visual}%" if visual else ""


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
    # Identidad de compañía centralizada: los parsers no mantienen su propia
    # lista de marcas/aliases. Primero usamos el registro canónico.
    detectada = detectar_compania_en_texto(texto)
    if detectada:
        return _canonicalizar_compania(detectada)

    t = normalizar_texto(texto)
    # Firma de plantilla AgroSalta: algunas cotizaciones no imprimen el nombre
    # de la compañía. Exigimos varios rasgos simultáneos para evitar falsos
    # positivos y dejamos el selector manual del frontend como respaldo.
    firma_agrosalta = (
        "COTIZACION DE AUTOMOTORES" in t
        and "VEHICULO COTIZADO" in t
        and "PREMIO C/IVA" in t
        and re.search(r"\bA\s*-\s*RESPONSABILIDAD\s+CIVIL\b", t)
        and re.search(r"\b(?:B1?|C1?|CF)\s*-", t)
    )
    if firma_agrosalta:
        return "AgroSalta"

    # Heurística conservadora para una compañía no registrada: usar una línea
    # corporativa sólo si contiene una palabra inequívoca de aseguradora.
    for linea in str(texto or "").splitlines()[:35]:
        limpia = re.sub(r"\s+", " ", linea).strip(" -|:")
        if 3 <= len(limpia) <= 90 and re.search(r"\b(SEGUROS?|ASEGURADORA|ASEGURADORA\s+DE\s+RIESGOS)\b", _sin_acentos(limpia), re.I):
            return _canonicalizar_compania(limpia)
    return "Compañía no identificada"


def _extraer_suma_asegurada(texto: str) -> Decimal | None:
    raw = str(texto or "")
    t = normalizar_texto(raw)

    # Primero, etiquetas inequívocas de valor del vehículo. [ \t] evita que
    # una etiqueta al final de una línea capture por error el premio de la
    # línea siguiente (caso real de PDFs ATM).
    patrones = [
        r"VALOR\s+A\s+ASEGURAR[ \t]*[:\-]?[ \t]*\$?[ \t]*([\d.,]+)",
        r"SUMA\s+ASEGURADA[ \t]*[:\-]?[ \t]*\$?[ \t]*([\d.,]+)",
        r"MONTO\s+ASEGURADO[ \t]*[:\-]?[ \t]*\$?[ \t]*([\d.,]+)",
        r"\bS\.?[ \t]*A\.?[ \t]*[:\-][ \t]*\$?[ \t]*([\d.,]+)",
        r"\bVALOR[ \t]*:[ \t]*\$[ \t]*([\d.,]+)",
    ]
    for patron in patrones:
        m = re.search(patron, t, flags=re.I)
        if m:
            n = _money_decimal(m.group(1))
            if n is not None:
                return n

    # Algunos PDFs tabulares (ATM) extraen primero el valor y después el rótulo
    # ``Valor a Asegurar`` por el orden de cajas de texto. En ese caso miramos
    # sólo una ventana corta anterior y elegimos un importe grande aislado.
    lineas = [re.sub(r"\s+", " ", x).strip() for x in raw.splitlines()]
    for idx, linea in enumerate(lineas):
        if "VALOR A ASEGURAR" not in normalizar_texto(linea):
            continue
        candidatos = []
        for previa in lineas[max(0, idx - 12):idx]:
            if re.fullmatch(r"\$?[ \t]*\d[\d.]*[,]\d{2}", previa):
                n = _money_decimal(previa)
                if n is not None and n >= Decimal("100000"):
                    candidatos.append(n)
        if candidatos:
            return max(candidatos)
    return None

def _extraer_anio(texto: str) -> str:
    raw = str(texto or "")
    t = normalizar_texto(raw)
    for patron in (r"ANO[ \t]*(?:DE[ \t]+FABRICACION[ \t]*)?[:\-]?[ \t]*((?:19|20)\d{2})", r"MODELO[ \t]*[:\-]?[ \t]*((?:19|20)\d{2})"):
        m = re.search(patron, t)
        if m:
            return m.group(1)
    # Layouts donde el año es una caja separada: priorizar un año aislado cerca
    # del bloque de vehículo y antes de la tabla de coberturas.
    pre = raw.split("Cobertura", 1)[0]
    aislados = re.findall(r"(?m)^\s*((?:19|20)\d{2})\s*$", pre)
    return aislados[-1] if aislados else ""

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

    # PDFs ATM: la descripción suele aparecer como caja independiente justo
    # antes de ``Valor a Asegurar``. Evitamos rótulos y valores numéricos.
    lineas = [re.sub(r"\s+", " ", x).strip() for x in raw.splitlines()]
    for idx, linea in enumerate(lineas):
        if "VALOR A ASEGURAR" not in normalizar_texto(linea):
            continue
        for previa in reversed(lineas[max(0, idx - 6):idx]):
            key = normalizar_texto(previa)
            if not previa or re.fullmatch(r"[\d.,$ ]+", previa):
                continue
            if key in {"NO POSEE", "AUTOMOTORES", "COTIZACION"} or re.fullmatch(r"(?:19|20)\d{2}", previa):
                continue
            if re.search(r"[A-Z]{2,}", key):
                return previa[:160]
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
    # Algunas compañías imprimen primero la familia y luego el código, p. ej.
    # ``TERCEROS COMPLETOS C2``. Sólo aceptamos el sufijo si la familia es
    # inequívoca; así no convertimos cualquier palabra final en un código.
    suffix_code = r"[A-Z]{1,4}\d+(?:[.,]\d+)?"
    m = re.search(rf"\b(?:TERCEROS?\s+COMPLET(?:O|OS)|TODO\s+RIESGO|RESPONSABILIDAD\s+CIVIL)\s+({suffix_code})\b", t)
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


def _precio_fila_tabular(bloque: str, texto_documento: str) -> Decimal | None:
    """En tablas con columna Cuota/s, usa el último importe económico de la fila.

    Admite tanto tablas con ``$`` (AgroSalta y similares) como PDFs donde el
    motor extrae Premio/Cuota como cajas numéricas sin símbolo (ATM).
    """
    doc = normalizar_texto(texto_documento)
    if not re.search(r"\b(?:CUOTA|CUOTAS|1.?\s*CUOTA|PRIMERA\s+CUOTA)\b", doc):
        return None
    lineas = [re.sub(r"\s+", " ", x).strip() for x in str(bloque or "").splitlines() if x.strip()]
    valores: list[Decimal] = []
    for linea in lineas[1:8]:
        key = normalizar_texto(linea)
        if re.search(r"\b(?:AJUS\.?\s*AUT|RESPONSABILIDAD|INCENDIO|ROBO|HURTO|DANO|DAÑOS?|GRANIZO|CRISTALES?|PARABRISAS)\b", key):
            break
        # La línea debe ser esencialmente un importe; un simple ``1`` es la
        # cantidad de cuotas, no dinero.
        m = re.fullmatch(r"\$?[ \t]*([\d.]+(?:,[0-9]{1,2})?)\s*", linea)
        if not m:
            continue
        n = _money_decimal(m.group(1))
        if n is not None and ("," in m.group(1) or "." in m.group(1)):
            valores.append(n)
    return valores[-1] if valores else None

def _franquicia_en_bloque(bloque: str) -> tuple[str, Decimal | None, str]:
    t = normalizar_texto(bloque)
    pct = ""
    imp = None
    desc = ""
    etiqueta = r"(?:FRANQUICIA|FCIA\.?|DEDUCIBLE)"
    m = re.search(rf"{etiqueta}[^\n]{{0,100}}?(\d{{1,2}}(?:[.,]\d+)?)\s*%", t, flags=re.I)
    if m:
        pct = m.group(1).replace(",", ".")
        desc = m.group(0).strip()
    m2 = re.search(rf"{etiqueta}[^\n]{{0,120}}?\$\s*([\d.,]+)", t, flags=re.I)
    if m2:
        imp = _money_decimal(m2.group(1))
        if not desc:
            desc = m2.group(0).strip()
    # Allianz puede mostrar el porcentaje junto a D4/Alta Gama VIP sin escribir
    # la palabra franquicia en el mismo renglón. Sólo activamos este fallback
    # sobre esa cabecera inequívoca.
    if not pct and re.search(r"\b(?:D4\s+)?ALTA\s+GAMA\s+VIP\b", t, flags=re.I):
        ma = re.search(r"\b(1|2|3)(?:[.,]0+)?\s*%", t)
        if ma:
            pct = ma.group(1)
            desc = f"Franquicia {pct}%"
    return pct, imp, desc

def _grua_en_bloque(bloque: str) -> bool | None:
    t = normalizar_texto(bloque)
    if re.search(r"\bSIN\s+(?:SERV(?:ICIO)?\.?\s+DE\s+)?GRUA\b|\bSIN\s+ASISTENCIA\b", t):
        return False
    if re.search(r"\bCON\s+(?:SERV(?:ICIO)?\.?\s+DE\s+)?GRUA\b|\bINCLUYE\s+GRUA\b|\bASISTENCIA\s+(?:MECANICA|VEHICULAR)\b", t):
        return True
    return None


def _granizo_allianz_en_bloque(bloque: str, compania: str) -> str:
    """Estado de granizo como adicional, exclusivamente para Allianz por ahora."""
    if "ALLIANZ" not in _texto_compacto(compania):
        return "DESCONOCIDO"
    t = normalizar_texto(bloque)
    if re.search(r"\b(?:SIN|S/)\s*GRANIZO\b|\bNO\s+INCLUYE\s+GRANIZO\b", t):
        return "NO_INCLUYE"
    if re.search(r"\bC/\s*GRANIZO\b|\bCON\s+GRANIZO\b|\bINCLUYE\s+GRANIZO\b", t):
        return "INCLUYE"
    return "DESCONOCIDO"


def _es_linea_cobertura(linea: str) -> bool:
    """Detecta cabeceras fuertes de PLAN, no prestaciones internas.

    Se consideran fuertes los códigos/etiquetas de plan y denominaciones
    comerciales inequívocas como Todo Riesgo o Terceros Completo. Esto permite
    que, cuando existe una cabecera real, líneas internas como ``INCENDIO TOTAL
    O PARCIAL`` no se conviertan en coberturas independientes.
    """
    raw = str(linea or "").strip()
    t = _texto_compacto(raw)
    if not t or len(t) < 3:
        return False
    if t.startswith(("-", "•", "*")) or t.startswith("ASEGURADO POR"):
        return False

    codigo = _extraer_codigo(raw)
    if codigo and re.search(r"\b(?:RESPONSABILIDAD|TOTALES?|PARCIALES?|TODO\s+RIESGO|TERCEROS?\s+COMPLET(?:O|OS)|ROBO|HURTO|INCENDIO|DESTRUCCION|GRANIZO|CRIST|PARABRIS|FRANQUICIA|FCIA)\b", t):
        return True
    if re.search(r"\b(?:TODO\s+RIESGO|TERCEROS?\s+COMPLET(?:O|OS))\b", t):
        return True
    if re.search(r"^\s*(?:COBERTURA|PLAN)\s+", t) and (codigo or detectar_riesgos(t)["riesgos"]):
        return True
    return False


def _es_linea_cobertura_debil(linea: str) -> bool:
    """Compatibilidad para fuentes sin cabeceras fuertes.

    Reproduce el criterio histórico (varios riesgos visibles en una misma
    línea) sólo cuando el documento completo no contiene una cabecera fuerte.
    Así se conservan speeches/cotizaciones simples sin volver a partir ATM,
    Allianz u otros PDFs tabulares por cada prestación.
    """
    t = _texto_compacto(linea)
    if not t or len(t) < 3 or t.startswith(("-", "•", "*")) or t.startswith("ASEGURADO POR"):
        return False
    d = detectar_riesgos(t)["riesgos"]
    if len(d) >= 2:
        return True
    if re.search(r"\b(?:COBERTURA|PLAN)\s+[A-Z0-9]+\b", t) and d:
        return True
    codigo = _extraer_codigo(linea)
    if codigo and re.search(r"\b(?:RESPONSABILIDAD|TOTAL(?:ES)?|PARCIAL(?:ES)?|TODO\s+RIESGO|ROBO|HURTO|INCENDIO|DESTRUCCION|GRANIZO|CRIST|PARABRIS|FRANQUICIA)\b", t):
        return True
    return False

def _candidatos_cobertura(texto: str) -> list[dict]:
    lineas = [re.sub(r"\s+", " ", x).strip() for x in str(texto or "").splitlines() if x.strip()]
    indices = [i for i, linea in enumerate(lineas) if _es_linea_cobertura(linea)]
    if not indices:
        # Si no existe ninguna cabecera fuerte, mantener compatibilidad con el
        # normalizador anterior para speeches/cotizaciones sin código.
        indices = [i for i, linea in enumerate(lineas) if _es_linea_cobertura_debil(linea)]
    # Último fallback: una cotización que sólo ofrece RC puede venir sin código
    # ni palabra PLAN. Se acepta sólo si tampoco hubo candidatos débiles.
    if not indices:
        for i, linea in enumerate(lineas):
            if re.fullmatch(r"(?:A\s*-\s*)?RESPONSABILIDAD\s+CIVIL(?:\s+SIN\s+GRUA)?", _texto_compacto(linea)):
                indices = [i]
                break
    candidatos: list[dict] = []
    vistos: set[str] = set()
    for pos, i in enumerate(indices):
        linea = lineas[i]
        fin = indices[pos + 1] if pos + 1 < len(indices) else len(lineas)
        # Una cabecera posee todo lo que sigue hasta la próxima cabecera. Para
        # evitar arrastrar pies administrativos, cortamos en marcadores fuertes.
        bloque_lineas = [linea]
        for siguiente in lineas[i + 1:fin]:
            key = normalizar_texto(siguiente)
            if re.match(r"^(?:SEGURO DE AUTO/MOTO COMBINADO|USUARIO:|COTIZACION NRO:|FECHA:|HORA:)$", key):
                break
            if key.startswith("GRUPO ABRA OF."):
                break
            bloque_lineas.append(siguiente)
        bloque = "\n".join(bloque_lineas)
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
        normal = normalizar_cobertura(cand["bloque"], compania=cia if cia != "Compañía no identificada" else "", codigo=codigo, nombre=cand["linea"])
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
            "granizo_estado": _granizo_allianz_en_bloque(cand["bloque"], cia),
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
                "granizo_estado": _granizo_allianz_en_bloque(raw, cia),
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



def evaluar_calidad_lectura(resultado: dict) -> dict:
    """Valida coherencia estructural antes de aceptar una lectura automática.

    No reinterpreta una compañía: detecta señales universales de parseo roto,
    como prestaciones convertidas en planes o precios perdidos pese a existir
    una tabla de cuotas. Sirve para decidir si conviene activar el fallback
    visual y, si no está disponible, marcar la lectura para revisión humana.
    """
    resultado = resultado if isinstance(resultado, dict) else {}
    opciones = list(resultado.get("coberturas") or [])
    fuente = str(resultado.get("texto_fuente") or "")
    t = normalizar_texto(fuente)
    advertencias: list[str] = []
    score = 100

    if not opciones:
        return {"confiable": False, "score": 0, "advertencias": ["No se extrajeron coberturas."]}

    beneficio_suelto = re.compile(
        r"^(?:RESPONSABILIDAD\s+CIVIL(?:\s+HASTA)?|INCENDIO\s+(?:TOTAL|PARCIAL)|"
        r"ROBO(?:/HURTO)?\s+(?:TOTAL|PARCIAL)|DANOS?\s+(?:TOTAL|PARCIAL)|"
        r"CRISTALES?|PARABRISAS|GRANIZO|CERRADURAS?)\b",
        re.I,
    )
    for op in opciones:
        titulo = str(op.get("nombre_original") or op.get("nombre_cliente") or "").strip()
        if titulo and beneficio_suelto.search(normalizar_texto(titulo)):
            score -= 35
            advertencias.append(
                f"Una prestación parece haber sido interpretada como cobertura: {titulo[:80]}."
            )
            break

    if re.search(r"\b(?:PREMIO|CUOTA|CUOTAS|1.?\s*CUOTA|PRIMERA\s+CUOTA)\b", t):
        con_precio = sum(bool(str(op.get("precio_cuota") or "").strip()) for op in opciones)
        ratio = con_precio / max(1, len(opciones))
        if ratio < 0.5:
            score -= 30
            advertencias.append(
                "La tabla muestra precios/cuotas pero la lectura recuperó muy pocos importes."
            )

    if "VALOR A ASEGURAR" in t or "SUMA ASEGURADA" in t:
        if not str(resultado.get("suma_asegurada") or "").strip():
            score -= 15
            advertencias.append(
                "El documento muestra suma/valor a asegurar pero no se pudo recuperar."
            )

    if re.search(r"\bTODO\s+RIESGO\b", t) and not any(
        str(op.get("perfil_normalizado")) == PERFIL_TR for op in opciones
    ):
        score -= 35
        advertencias.append(
            "El documento dice Todo Riesgo pero ninguna alternativa quedó clasificada como tal."
        )

    if re.search(r"\bTERCEROS?\s+COMPLET(?:O|OS)\b", t) and not any(
        str(op.get("perfil_normalizado")) in {PERFIL_C, PERFIL_C1, PERFIL_C_PLUS}
        for op in opciones
    ):
        score -= 35
        advertencias.append(
            "El documento dice Terceros Completo pero esa familia no sobrevivió a la lectura."
        )

    sin_clasificar = sum(
        str(op.get("perfil_normalizado")) == PERFIL_SIN_CLASIFICAR for op in opciones
    )
    if sin_clasificar == len(opciones):
        score -= 35
        advertencias.append("Todas las alternativas quedaron sin clasificar.")

    score = max(0, min(100, score))
    return {
        "confiable": score >= 65,
        "score": score,
        "advertencias": list(dict.fromkeys(advertencias)),
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
    resultado = normalizar_texto_cotizacion(texto)
    calidad = evaluar_calidad_lectura(resultado)
    resultado["calidad_lectura"] = calidad
    resultado["requiere_revision"] = not bool(calidad.get("confiable"))
    return resultado


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
            "granizo_estado": _granizo_allianz_en_bloque(fuente, cia),
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
