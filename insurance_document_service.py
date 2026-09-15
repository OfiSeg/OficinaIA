# -*- coding: utf-8 -*-
"""Documentos institucionales de Seguros San José desde una ficha canónica.

Principio: las fuentes (Alta, póliza, Sheet/Excel) pueden ser distintas, pero
las plantillas consumen siempre el mismo conjunto de campos. Este módulo no
consulta IA y nunca inventa datos faltantes.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
import calendar
import re
import unicodedata
import os
import shutil
import subprocess
import tempfile
import zipfile
from typing import Any

from docx import Document

from companias import nombre_compania, texto_asistencia_compania
from office_time import office_date_string


TIPOS = {
    "bienvenida": {
        "template": "bienvenida.docx",
        "titulo": "Bienvenida",
        "campos": [
            "NOMBRE", "VEHICULO", "PATENTE", "COMPANIA", "COBERTURA", "POLIZA",
            "FECHA_EMISION", "FORMA_PAGO", "VENCIMIENTO", "ASISTENCIA_ESTADO", "ASISTENCIA_GRUA",
        ],
        # La asistencia puede no estar documentada; no se inventa y el bloque se
        # oculta limpio. El resto forma la información operativa de bienvenida.
        "requeridos": [
            "NOMBRE", "VEHICULO", "PATENTE", "COMPANIA", "COBERTURA",
            "FECHA_EMISION", "FORMA_PAGO", "VENCIMIENTO",
        ],
    },
    "pago_pendiente": {
        "template": "pago_pendiente.docx",
        "titulo": "Aviso de pago pendiente",
        "campos": [
            "NOMBRE", "VEHICULO", "PATENTE", "COMPANIA", "POLIZA", "IMPORTE_PENDIENTE",
            "VENCIMIENTO", "FORMA_PAGO", "INSTRUCCION_PAGO",
        ],
        "requeridos": [
            "NOMBRE", "VEHICULO", "PATENTE", "COMPANIA", "IMPORTE_PENDIENTE",
            "VENCIMIENTO", "FORMA_PAGO", "INSTRUCCION_PAGO",
        ],
    },
    "baja": {
        "template": "baja.docx",
        "titulo": "Confirmación de baja",
        "campos": [
            "NOMBRE", "VEHICULO", "PATENTE", "COMPANIA", "POLIZA",
            "FECHA_BAJA", "MOTIVO_BAJA",
        ],
        "requeridos": [
            "NOMBRE", "VEHICULO", "PATENTE", "COMPANIA",
            "FECHA_BAJA", "MOTIVO_BAJA",
        ],
    },
}

LABELS = {
    "NOMBRE": "Asegurado/a",
    "VEHICULO": "Vehículo",
    "PATENTE": "Patente",
    "COMPANIA": "Compañía",
    "COBERTURA": "Cobertura",
    "POLIZA": "Póliza",
    "FECHA_EMISION": "Fecha de emisión",
    "FORMA_PAGO": "Forma de pago",
    "VENCIMIENTO": "Vencimiento",
    "ASISTENCIA_ESTADO": "Estado asistencia/grúa",
    "ASISTENCIA_GRUA": "Asistencia y grúa",
    "VIGENCIA_DESDE": "Vigencia desde",
    "VIGENCIA_HASTA": "Vigencia hasta",
    "PREMIO_TOTAL_PERIODO": "Premio total del período",
    "CANTIDAD_CUOTAS": "Cantidad de cuotas",
    "VALOR_CUOTA": "Valor de cuota",
    "IMPORTE_PENDIENTE": "Importe pendiente",
    "IMPORTE": "Importe pendiente",  # alias de plantilla histórica
    "INSTRUCCION_PAGO": "Instrucción de pago",
    "FECHA_BAJA": "Fecha efectiva de baja",
    "MOTIVO_BAJA": "Motivo de baja",
}

ALIASES = {
    "NOMBRE": ("NOMBRE", "ASEGURADO", "CLIENTE", "TITULAR"),
    "VEHICULO": ("VEHICULO", "VEHÍCULO", "MARCA MODELO", "MARCA/MODELO"),
    "PATENTE": ("PATENTE", "DOMINIO", "CHAPA"),
    "COMPANIA": ("COMPANIA", "COMPAÑIA", "CIA", "ASEGURADORA"),
    "COBERTURA": ("COBERTURA", "PLAN", "PLAN COBERTURA"),
    "POLIZA": ("POLIZA", "PÓLIZA", "NUMERO_POLIZA", "NRO POLIZA", "NUMERO POLIZA"),
    "FECHA_EMISION": ("FECHA_EMISION", "FECHA DE EMISION", "EMITIDO DÍA:", "EMITIDO DIA", "EMITIDO_DIA"),
    "FORMA_PAGO": ("FORMA_PAGO", "FORMA DE PAGO", "MEDIO DE PAGO", "MEDIO_PAGO"),
    "VENCIMIENTO": ("VENCIMIENTO", "PROXIMO VENCIMIENTO", "PRÓXIMO VENCIMIENTO", "VENCIMIENTO CUOTA"),
    "VIGENCIA_DESDE": ("VIGENCIA_DESDE", "VIGENCIA DESDE", "INICIO VIGENCIA"),
    "VIGENCIA_HASTA": ("VIGENCIA_HASTA", "VIGENCIA HASTA", "FIN VIGENCIA"),
    "ASISTENCIA_ESTADO": ("ASISTENCIA_ESTADO", "ESTADO ASISTENCIA", "ESTADO GRUA", "ESTADO GRÚA"),
    "ASISTENCIA_GRUA": ("ASISTENCIA_GRUA", "ASISTENCIA Y GRUA", "ASISTENCIA Y GRÚA", "GRUA", "GRÚA"),
    "PREMIO_TOTAL_PERIODO": ("PREMIO_TOTAL_PERIODO", "PREMIO TOTAL", "PREMIO C/IVA", "PREMIO"),
    "CANTIDAD_CUOTAS": ("CANTIDAD_CUOTAS", "CANTIDAD DE CUOTAS", "CANTIDAD CUOTAS"),
    "VALOR_CUOTA": ("VALOR_CUOTA", "VALOR DE CUOTA", "PRECIO POR CUOTA", "IMPORTE CUOTA", "CUOTA"),
    "IMPORTE_PENDIENTE": ("IMPORTE_PENDIENTE", "IMPORTE PENDIENTE", "SALDO PENDIENTE", "DEUDA"),
    # Pago pendiente es un concepto propio: nunca reutilizar premio o importe
    # aproximado de póliza como si fuera una deuda confirmada.
    "IMPORTE": ("IMPORTE", "IMPORTE PENDIENTE", "IMPORTE_PENDIENTE", "SALDO PENDIENTE", "DEUDA"),
    "INSTRUCCION_PAGO": ("INSTRUCCION_PAGO", "INSTRUCCION PAGO", "INSTRUCCIÓN DE PAGO"),
    "FECHA_BAJA": ("FECHA_BAJA", "FECHA BAJA", "FECHA EFECTIVA DE BAJA"),
    "MOTIVO_BAJA": ("MOTIVO_BAJA", "MOTIVO BAJA", "MOTIVO DE BAJA"),
    "TELEFONO": ("TELEFONO", "TELÉFONO", "NUMERO", "CELULAR", "WHATSAPP"),
    "MAIL": ("MAIL", "EMAIL", "E-MAIL", "CORREO"),
}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().replace("_", " ").strip()
    return re.sub(r"\s+", " ", text)


def _clean(value: Any, max_len: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("\r", " ").replace("\n", " ")).strip()
    return text[:max_len]


def normalizar_campos(raw: dict | None) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    index = {_norm(k): v for k, v in raw.items()}
    out: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        value = ""
        for alias in aliases:
            candidate = index.get(_norm(alias))
            if str(candidate or "").strip():
                value = _clean(candidate)
                break
        if canonical == "PATENTE":
            value = re.sub(r"\s+", "", value).upper()
        elif canonical == "COMPANIA" and value:
            value = nombre_compania(value)
        elif canonical == "ASISTENCIA_ESTADO" and value:
            key = _norm(value)
            if key in {"INCLUYE", "INCLUIDA", "SI", "CON GRUA", "CON ASISTENCIA"}:
                value = "INCLUYE"
            elif key in {"NO INCLUYE", "NO INCLUYE GRUA", "SIN GRUA", "SIN ASISTENCIA", "NO"}:
                value = "NO_INCLUYE"
            else:
                value = "DESCONOCIDO"
        out[canonical] = value
    return out


def _record_to_fields(record: dict) -> dict[str, str]:
    if not isinstance(record, dict):
        return {}
    return normalizar_campos({
        "ASEGURADO": record.get("asegurado"),
        "TELEFONO": record.get("telefono") or record.get("numero"),
        "MAIL": record.get("mail"),
        "VEHICULO": record.get("vehiculo"),
        "PATENTE": record.get("patente"),
        "COMPANIA": record.get("compania"),
        "POLIZA": record.get("poliza"),
        "COBERTURA": record.get("cobertura"),
        "MEDIO DE PAGO": record.get("medio_pago"),
        "FECHA_EMISION": record.get("emitido_dia"),
        "VENCIMIENTO": record.get("vencimiento"),
        "VIGENCIA_DESDE": record.get("vigencia_desde"),
        "VIGENCIA_HASTA": record.get("vigencia_hasta"),
        "ASISTENCIA_ESTADO": record.get("asistencia_estado"),
        "ASISTENCIA_GRUA": record.get("asistencia_grua"),
        "PREMIO_TOTAL_PERIODO": record.get("premio_total_periodo"),
        "CANTIDAD_CUOTAS": record.get("cantidad_cuotas"),
        "VALOR_CUOTA": record.get("valor_cuota"),
        "IMPORTE_PENDIENTE": record.get("importe_pendiente"),
    })


def datos_desde_ficha(ficha: dict | None, *, patente: str = "", poliza: str = "") -> tuple[dict[str, str], list[dict], dict[str, str]]:
    """Obtiene una única ficha documental sin mezclar vehículos en silencio.

    Devuelve también la fuente resuelta por campo para conservar prioridad al
    editar/generar el documento.
    """
    ficha = ficha if isinstance(ficha, dict) else {}
    if ficha.get("status") != "found":
        return {}, [], {}
    records = [x for x in (ficha.get("registros") or []) if isinstance(x, dict)]
    pat = re.sub(r"[^A-Z0-9]", "", _norm(patente))
    pol = _norm(poliza)
    if pat:
        records = [r for r in records if re.sub(r"[^A-Z0-9]", "", _norm(r.get("patente"))) == pat]
    if pol:
        records = [r for r in records if _norm(r.get("poliza")) == pol]
    if not records:
        return {}, [], {}

    keys = {
        (re.sub(r"[^A-Z0-9]", "", _norm(r.get("patente"))), _norm(r.get("poliza")))
        for r in records
    }
    if len(keys) > 1:
        return {}, records, {}

    record = records[0]
    fields = _record_to_fields(record)
    raw_sources = record.get("field_sources") if isinstance(record.get("field_sources"), dict) else {}
    sources: dict[str, str] = {}
    for key in fields:
        meta = raw_sources.get(key) if isinstance(raw_sources.get(key), dict) else {}
        source = str(meta.get("source") or "").strip()
        sources[key] = source or "cartera"

    contacto = ficha.get("contacto") if isinstance(ficha.get("contacto"), dict) else {}
    if not fields.get("NOMBRE"):
        fields["NOMBRE"] = _clean(ficha.get("asegurado"))
        if fields["NOMBRE"]:
            sources["NOMBRE"] = "cartera"
    if contacto:
        if not fields.get("TELEFONO"):
            fields["TELEFONO"] = _clean(contacto.get("telefono"))
            if fields["TELEFONO"]:
                sources["TELEFONO"] = "cartera"
        if not fields.get("MAIL"):
            fields["MAIL"] = _clean(contacto.get("mail"))
            if fields["MAIL"]:
                sources["MAIL"] = "cartera"
    return fields, [], sources



def _asistencia_negativa(texto: str) -> bool:
    key = _norm(texto)
    return bool(re.search(r"\bSIN(?: SERVICIO DE)? GRUA\b|\bSIN ASISTENCIA\b|\bNO INCLUYE(?: SERVICIO DE)? GRUA\b|\bNO INCLUYE ASISTENCIA\b", key))


def _asistencia_tiene_contacto(texto: str) -> bool:
    # Si la póliza/ficha ya trae un canal concreto, lo respetamos: puede ser un
    # prestador específico y no corresponde reemplazarlo por el contacto general.
    compact = re.sub(r"\D", "", str(texto or ""))
    key = _norm(texto)
    return len(compact) >= 7 or "WHATSAPP" in key or "SMS" in key


def _estado_asistencia(fields: dict[str, str]) -> str:
    explicit = _norm(fields.get("ASISTENCIA_ESTADO"))
    if explicit in {"INCLUYE", "NO_INCLUYE", "DESCONOCIDO"}:
        return explicit
    actual = _norm(fields.get("ASISTENCIA_GRUA"))
    cobertura = _norm(fields.get("COBERTURA"))
    combined = f"{actual} {cobertura}"
    if re.search(r"\bSIN(?: SERVICIO DE)? GRUA\b|\bSIN ASISTENCIA\b|\bNO INCLUYE(?: SERVICIO DE)? GRUA\b", combined):
        return "NO_INCLUYE"
    if re.search(r"\bCON(?: SERVICIO DE)? GRUA\b|\bINCLUYE(?: SERVICIO DE)? GRUA\b|\bINCLUYE ASISTENCIA\b", combined):
        return "INCLUYE"
    return "DESCONOCIDO"


def enriquecer_asistencia_grua(fields: dict[str, str]) -> dict[str, str]:
    """Separa inclusión de servicio de sus canales de contacto.

    La compañía jamás implica por sí sola que una póliza incluya grúa. El
    catálogo sólo agrega teléfonos cuando el estado ya es INCLUYE.
    """
    out = dict(fields or {})
    estado = _estado_asistencia(out)
    out["ASISTENCIA_ESTADO"] = estado
    actual = _clean(out.get("ASISTENCIA_GRUA"))

    if estado == "NO_INCLUYE":
        out["ASISTENCIA_GRUA"] = "Esta cobertura no incluye servicio de grúa/asistencia."
        return out
    if estado != "INCLUYE":
        # Desconocido: no inventar texto ni teléfono; el panel permite resolverlo manualmente.
        out["ASISTENCIA_GRUA"] = actual if actual and not _asistencia_negativa(actual) else ""
        return out
    if not actual or _asistencia_negativa(actual):
        actual = "Incluye servicio de asistencia."
    if _asistencia_tiene_contacto(actual):
        out["ASISTENCIA_GRUA"] = actual
        return out
    contacto = texto_asistencia_compania(out.get("COMPANIA"), solo_asistencia=True)
    if contacto and _norm(contacto) not in _norm(actual):
        actual = f"{actual.rstrip('.')}. {contacto}"
    out["ASISTENCIA_GRUA"] = actual
    return out


_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y")

def _parse_date(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.split("T", 1)[0].strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None

def _format_date(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""

def _add_months(value, months: int = 1):
    """Suma meses sin dependencias externas, recortando al último día válido."""
    month_index = (value.month - 1) + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)

def _add_years(value, years: int = 1):
    """Suma años; 29/02 cae en 28/02 cuando el año destino no es bisiesto."""
    year = value.year + int(years)
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return value.replace(year=year, day=day)

def completar_fechas(fields: dict[str, str], sources: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Aplica reglas sólo como fallback; una fecha explícita siempre prevalece."""
    out = dict(fields or {}); src = dict(sources or {})
    emision = _parse_date(out.get("FECHA_EMISION"))
    if not emision:
        return out, src
    if not out.get("VIGENCIA_DESDE"):
        out["VIGENCIA_DESDE"] = _format_date(emision); src["VIGENCIA_DESDE"] = "calculado"
    if not out.get("VIGENCIA_HASTA"):
        out["VIGENCIA_HASTA"] = _format_date(_add_years(emision, 1)); src["VIGENCIA_HASTA"] = "calculado"
    if not out.get("VENCIMIENTO"):
        due = _add_months(emision, 1)
        if _norm(out.get("COMPANIA")) == "ATM":
            due = due + timedelta(days=5)
        out["VENCIMIENTO"] = _format_date(due); src["VENCIMIENTO"] = "calculado"
    return out, src


def _vencimiento_recurrente_bienvenida(fecha_emision: str, compania: str) -> str:
    emision = _parse_date(fecha_emision)
    if not emision:
        return ""
    dia = emision
    if _norm(compania) == "ATM":
        dia = emision + timedelta(days=5)
    return f"Todos los {dia.day} de cada mes"


def _same(a: str, b: str) -> bool:
    if not a or not b:
        return True
    if a == b:
        return True
    if re.sub(r"[^A-Z0-9]", "", _norm(a)) == re.sub(r"[^A-Z0-9]", "", _norm(b)):
        return True
    return False


def preparar(tipo: str, *, ficha: dict | None = None, campos: dict | None = None,
             extras: dict | None = None, patente: str = "", poliza: str = "") -> dict:
    tipo = str(tipo or "").strip().lower()
    if tipo not in TIPOS:
        raise ValueError("Tipo de documento no válido.")

    sheet, ambiguos, sheet_sources = datos_desde_ficha(ficha, patente=patente, poliza=poliza)
    current = normalizar_campos(campos)
    overrides = normalizar_campos(extras)
    if tipo == "bienvenida":
        # La bienvenida no hereda emisión/vencimiento históricos de cartera o
        # del flujo anterior: hoy + regla de compañía son la fuente por defecto.
        sheet.pop("FECHA_EMISION", None); sheet.pop("VENCIMIENTO", None)
        sheet_sources.pop("FECHA_EMISION", None); sheet_sources.pop("VENCIMIENTO", None)
        current.pop("FECHA_EMISION", None); current.pop("VENCIMIENTO", None)

    merged: dict[str, str] = {}
    sources: dict[str, str] = {}
    conflicts: list[dict] = []

    for key, value in sheet.items():
        if value:
            merged[key] = value
            sources[key] = sheet_sources.get(key) or "cartera"

    # Los campos visibles del flujo actual (Alta/póliza) prevalecen: el usuario
    # puede revisarlos antes de guardar/generar. Si contradicen cartera dejamos
    # trazabilidad, pero no volvemos a elegir por heurística.
    for key, value in current.items():
        if not value:
            continue
        if merged.get(key):
            if _same(merged[key], value):
                # Mismo dato: conservar la procedencia ya resuelta de la ficha.
                continue
            conflicts.append({"campo": key, "cartera": merged[key], "actual": value, "resuelto_por": "pendiente_confirmacion"})
        merged[key] = value
        sources[key] = "documento"

    # Extras son edición explícita del panel documental y por eso tienen la
    # máxima autoridad del flujo.
    for key, value in overrides.items():
        if value:
            merged[key] = value
            sources[key] = "manual_confirmado"

    if tipo == "bienvenida":
        # La bienvenida usa el día real de generación como emisión por defecto;
        # no hereda una fecha vieja de Excel/ficha. La edición manual del panel
        # sigue teniendo prioridad absoluta.
        if overrides.get("FECHA_EMISION"):
            merged["FECHA_EMISION"] = overrides["FECHA_EMISION"]
            sources["FECHA_EMISION"] = "manual_confirmado"
        else:
            merged["FECHA_EMISION"] = office_date_string()
            sources["FECHA_EMISION"] = "sistema_hoy"
        if overrides.get("VENCIMIENTO"):
            merged["VENCIMIENTO"] = overrides["VENCIMIENTO"]
            sources["VENCIMIENTO"] = "manual_confirmado"
        else:
            merged["VENCIMIENTO"] = _vencimiento_recurrente_bienvenida(merged.get("FECHA_EMISION"), merged.get("COMPANIA"))
            sources["VENCIMIENTO"] = "calculado"

    # Sólo la Bienvenida usa fechas derivadas. En Pago pendiente el vencimiento
    # corresponde a una deuda concreta y debe venir explícito de la fuente o
    # cargarse manualmente; nunca se deduce de la emisión.
    if tipo == "bienvenida":
        merged, sources = completar_fechas(merged, sources)

    if tipo == "bienvenida":
        asistencia_antes = _clean(merged.get("ASISTENCIA_GRUA"))
        merged = enriquecer_asistencia_grua(merged)
        if merged.get("ASISTENCIA_GRUA") and _clean(merged.get("ASISTENCIA_GRUA")) != asistencia_antes:
            sources["ASISTENCIA_GRUA"] = "calculado"
        if merged.get("ASISTENCIA_ESTADO") and not sources.get("ASISTENCIA_ESTADO"):
            sources["ASISTENCIA_ESTADO"] = "calculado"

    campos_tipo = TIPOS[tipo]["campos"]
    # Un documento sólo debe pedir confirmación por conflictos que realmente
    # muestra/consume. Diferencias de teléfono/mail no deben bloquear una Baja,
    # por ejemplo, porque esos campos ni siquiera forman parte de esa plantilla.
    conflicts = [c for c in conflicts if c.get("campo") in campos_tipo]
    result_fields = {key: merged.get(key, "") for key in campos_tipo}
    missing = [key for key in TIPOS[tipo]["requeridos"] if not result_fields.get(key)]
    return {
        "tipo": tipo,
        "titulo": TIPOS[tipo]["titulo"],
        "campos": result_fields,
        "labels": {key: LABELS.get(key, key) for key in campos_tipo},
        "faltantes": missing,
        "conflictos": conflicts,
        "registros_ambiguos": ambiguos,
        "fuentes": {key: sources.get(key, "") for key in campos_tipo},
    }


def _iter_paragraphs(doc: Document):
    for p in doc.paragraphs:
        yield p
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p
    for section in doc.sections:
        for container in (section.header, section.footer):
            for p in container.paragraphs:
                yield p
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            yield p


def _remove_paragraph(paragraph):
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)
    paragraph._p = paragraph._element = None


def _format_ars(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("$"):
        return raw
    limpio = raw.replace(" ", "")
    if not re.fullmatch(r"-?[\d.,]+", limpio):
        return raw
    try:
        if "," in limpio:
            # es-AR: puntos de miles, coma decimal.
            numero = float(limpio.replace(".", "").replace(",", "."))
        elif "." in limpio:
            partes = limpio.split(".")
            numero = float(limpio.replace(".", "")) if all(len(x) == 3 for x in partes[1:]) else float(limpio)
        else:
            numero = float(limpio)
        entero = int(round(numero))
        return "$" + f"{entero:,}".replace(",", ".")
    except Exception:
        return raw


def _replace_placeholders(doc: Document, fields: dict[str, str]):
    # Los placeholders de las plantillas se encuentran en runs independientes;
    # igualmente soportamos varios marcadores dentro de un mismo run.
    paragraphs = list(_iter_paragraphs(doc))
    for p in paragraphs:
        if p._element is None:
            continue
        for run in p.runs:
            text = run.text
            if "{{" not in text:
                continue
            for key, value in fields.items():
                text = text.replace("{{" + key + "}}", value or "")
            run.text = text

    # Bienvenida: si no hay dato confirmado de asistencia, no mostramos un
    # encabezado vacío ni inventamos "incluye grúa".
    if not fields.get("ASISTENCIA_GRUA"):
        paragraphs = list(_iter_paragraphs(doc))
        for p in paragraphs:
            text = _norm(p.text)
            if text in {"ASISTENCIA Y GRUA", "{{ASISTENCIA GRUA}}", "{{ASISTENCIA_GRUA}}"}:
                _remove_paragraph(p)

    # Póliza es opcional: si está vacía, desaparece la línea completa en vez de
    # dejar una etiqueta sin valor. Si el usuario escribe 0, se respeta 0.
    if not str(fields.get("POLIZA") or "").strip():
        for p in list(_iter_paragraphs(doc)):
            if p._element is not None and _norm(p.text).startswith("POLIZA ·"):
                _remove_paragraph(p)


def _safe_filename(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return text[:90] or "documento"


def generar_docx(tipo: str, fields: dict[str, str], *, templates_dir: Path) -> tuple[BytesIO, str]:
    tipo = str(tipo or "").strip().lower()
    if tipo not in TIPOS:
        raise ValueError("Tipo de documento no válido.")
    clean = normalizar_campos(fields)
    if tipo == "bienvenida":
        if not clean.get("FECHA_EMISION"):
            clean["FECHA_EMISION"] = office_date_string()
        if not clean.get("VENCIMIENTO"):
            clean["VENCIMIENTO"] = _vencimiento_recurrente_bienvenida(clean.get("FECHA_EMISION"), clean.get("COMPANIA"))
    clean, _ = completar_fechas(clean, {})
    # Sólo validar los campos que pertenecen al documento pedido.
    doc_fields = {key: clean.get(key, "") for key in TIPOS[tipo]["campos"]}
    if tipo == "bienvenida":
        doc_fields = enriquecer_asistencia_grua(doc_fields)
    missing = [key for key in TIPOS[tipo]["requeridos"] if not doc_fields.get(key)]
    if missing:
        labels = ", ".join(LABELS.get(x, x) for x in missing)
        raise ValueError(f"Faltan datos para generar el documento: {labels}.")

    template = Path(templates_dir) / TIPOS[tipo]["template"]
    if not template.exists():
        raise FileNotFoundError(f"No existe la plantilla {template.name}.")
    doc = Document(template)
    render_fields = dict(doc_fields)
    if tipo == "pago_pendiente":
        render_fields["IMPORTE"] = _format_ars(doc_fields.get("IMPORTE_PENDIENTE", ""))
    _replace_placeholders(doc, render_fields)

    # Guard rail: nunca entregar un Word con variables sin resolver.
    remaining = []
    for p in _iter_paragraphs(doc):
        if p._element is not None and re.search(r"\{\{[A-Z0-9_]+\}\}", p.text or ""):
            remaining.append(p.text)
    if remaining:
        raise ValueError("La plantilla contiene campos sin resolver.")

    out = BytesIO()
    doc.save(out)
    out.seek(0)
    name = _safe_filename(doc_fields.get("NOMBRE") or doc_fields.get("PATENTE") or "asegurado")
    filename = f"{tipo}_{name}.docx"
    return out, filename


def _libreoffice_bin() -> str | None:
    configurado = str(os.getenv("LIBREOFFICE_BIN") or "").strip()
    if configurado:
        return shutil.which(configurado) or (configurado if Path(configurado).exists() else None)
    encontrado = shutil.which("libreoffice") or shutil.which("soffice")
    if encontrado:
        return encontrado
    # En Windows la instalación estándar de LibreOffice normalmente no agrega
    # soffice.exe al PATH. Detectamos las rutas habituales para que OficinaIA
    # local pueda exportar PDF/PNG/JPG sin configuración extra.
    if os.name == "nt":
        candidatos = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
        ]
        for candidato in candidatos:
            if candidato.exists():
                return str(candidato)
    return None


def generar_documento(tipo: str, fields: dict[str, str], *, templates_dir: Path, formato: str = "docx") -> tuple[BytesIO, str, str]:
    """Genera DOCX/PDF/PNG/JPG desde el mismo documento maestro."""
    formato = str(formato or "docx").lower().strip()
    if formato not in {"docx", "pdf", "png", "jpg"}:
        raise ValueError("Formato de documento no válido.")
    docx, docx_name = generar_docx(tipo, fields, templates_dir=templates_dir)
    if formato == "docx":
        return docx, docx_name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    executable = _libreoffice_bin()
    if not executable:
        raise RuntimeError("LibreOffice no está disponible en el servidor para convertir este documento.")
    with tempfile.TemporaryDirectory(prefix="oia_doc_") as temp:
        root = Path(temp)
        docx_path = root / docx_name
        docx_path.write_bytes(docx.getvalue())
        profile = root / ".lo-profile"; profile.mkdir(exist_ok=True)
        cmd = [executable, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(root), str(docx_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=75, check=False)
        pdf_path = root / f"{docx_path.stem}.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            detail = (result.stderr or result.stdout or "").strip()[-500:]
            raise RuntimeError("No pude convertir el Word a PDF." + (f" {detail}" if detail else ""))
        if formato == "pdf":
            return BytesIO(pdf_path.read_bytes()), f"{docx_path.stem}.pdf", "application/pdf"

        try:
            import fitz
        except Exception as exc:
            raise RuntimeError("PyMuPDF no está disponible para generar imágenes.") from exc
        outputs=[]
        with fitz.open(pdf_path) as pdf:
            for idx, page in enumerate(pdf, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2.4, 2.4), alpha=False)
                ext = "jpg" if formato == "jpg" else "png"
                data = pix.tobytes("jpeg", jpg_quality=94) if formato == "jpg" else pix.tobytes("png")
                outputs.append((f"{docx_path.stem}_{idx:02d}.{ext}", data))
        if not outputs:
            raise RuntimeError("El PDF no contiene páginas para exportar como imagen.")
        mime = "image/jpeg" if formato == "jpg" else "image/png"
        if len(outputs) == 1:
            return BytesIO(outputs[0][1]), outputs[0][0], mime
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in outputs:
                zf.writestr(name, data)
        zip_buffer.seek(0)
        return zip_buffer, f"{docx_path.stem}_{formato}.zip", "application/zip"


__all__ = [
    "TIPOS", "LABELS", "normalizar_campos", "datos_desde_ficha", "enriquecer_asistencia_grua", "completar_fechas", "preparar", "generar_docx", "generar_documento"
]
