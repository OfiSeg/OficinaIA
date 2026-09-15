"""Ficha operativa unificada de asegurados.

Combina la cartera Excel/Sheet con la ficha persistente interna. Excel continúa
siendo la cartera operativa; la ficha interna conserva datos ricos que no deben
perderse entre sesiones (póliza, cobertura, vencimientos, asistencia, etc.).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

from insured_profile_store import SOURCE_PRIORITY
from companias import normalizar_compania, nombre_compania


def _norm(value: Any) -> str:
    t = unicodedata.normalize("NFKD", str(value or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.upper().strip()
    return re.sub(r"\s+", " ", t)


def _compact(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(value))


def _headers_rows(datos: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    filas = list((datos or {}).get("filas") or [])
    if not filas:
        return [], []
    headers = [str(x or "").strip() for x in filas[0]]
    out = []
    for fila in filas[1:]:
        if not any(str(v or "").strip() for v in fila):
            continue
        out.append({headers[i]: (fila[i] if i < len(fila) else "") for i in range(len(headers))})
    return headers, out


def _value(row: dict[str, Any], *aliases: str) -> str:
    wanted = {_norm(a) for a in aliases}
    for k, v in row.items():
        if _norm(k) in wanted and str(v or "").strip():
            return str(v).strip()
    return ""


_FIELD_TO_CANONICAL = {
    "asegurado": "NOMBRE", "numero": "TELEFONO", "telefono": "TELEFONO", "mail": "MAIL",
    "dni": "DNI", "cuit": "CUIT", "vehiculo": "VEHICULO", "patente": "PATENTE",
    "compania": "COMPANIA", "poliza": "POLIZA", "medio_pago": "FORMA_PAGO",
    "cobertura": "COBERTURA", "vencimiento": "VENCIMIENTO", "vigencia_desde": "VIGENCIA_DESDE",
    "vigencia_hasta": "VIGENCIA_HASTA", "asistencia_estado": "ASISTENCIA_ESTADO",
    "asistencia_grua": "ASISTENCIA_GRUA", "premio_total_periodo": "PREMIO_TOTAL_PERIODO",
    "cantidad_cuotas": "CANTIDAD_CUOTAS", "valor_cuota": "VALOR_CUOTA",
    "importe_pendiente": "IMPORTE_PENDIENTE", "motor": "MOTOR", "chasis": "CHASIS",
    "uso": "USO", "emitido_dia": "FECHA_EMISION",
}


def _prioridad_fuente(source: str, default: int = 300) -> int:
    return int(SOURCE_PRIORITY.get(str(source or ""), default))


def _field_priorities_from_sources(record: dict[str, Any], fuentes: dict[str, Any], default: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for field, canonical in _FIELD_TO_CANONICAL.items():
        if record.get(field) in (None, "", [], {}):
            continue
        meta = fuentes.get(canonical) if isinstance(fuentes.get(canonical), dict) else {}
        out[field] = _prioridad_fuente(meta.get("source"), default)
    # Campos legacy de presentación no deben ganar a sus conceptos semánticos.
    if record.get("importe_aprox") not in (None, "", [], {}):
        out["importe_aprox"] = default
    if record.get("importe") not in (None, "", [], {}):
        out["importe"] = out.get("importe_pendiente", default)
    return out


def _canonical(row: dict[str, Any], libro_id: str) -> dict[str, Any]:
    asegurado = _value(row, "ASEGURADO", "CLIENTE", "NOMBRE", "NOMBRE ASEGURADO", "TITULAR")
    numero = _value(row, "NUMERO", "NRO", "TELEFONO", "TEL", "CELULAR", "WHATSAPP")
    patente = _value(row, "PATENTE", "DOMINIO", "CHAPA")
    vehiculo = _value(row, "VEHICULO", "VEHÍCULO", "MARCA MODELO", "MARCA/MODELO", "DESCRIPCION DEL VEHICULO")
    if not vehiculo:
        marca = _value(row, "MARCA", "MARCA DEL VEHICULO")
        modelo = _value(row, "MODELO", "MODELO DEL VEHICULO")
        vehiculo = " ".join(x for x in (marca, modelo) if x).strip()
    record = {
        "libro_id": str(libro_id), "source_rank": 200,
        "asegurado": asegurado,
        "numero": numero,
        "telefono": _value(row, "TELEFONO", "TEL", "CELULAR", "WHATSAPP") or numero,
        "mail": _value(row, "MAIL", "EMAIL", "E-MAIL", "CORREO"),
        "dni": _value(row, "DNI", "DOCUMENTO"),
        "cuit": _value(row, "CUIT", "CUIL", "CUIT/CUIL"),
        "vehiculo": vehiculo,
        "patente": patente,
        "compania": _value(row, "CIA", "COMPAÑIA", "COMPANIA", "ASEGURADORA"),
        "poliza": _value(row, "POLIZA", "PÓLIZA", "NRO POLIZA", "NUMERO POLIZA"),
        "medio_pago": _value(row, "MEDIO DE PAGO", "MEDIO PAGO", "PAGO"),
        "cp": _value(row, "CP", "CODIGO POSTAL", "CÓDIGO POSTAL"),
        "cobertura": _value(row, "COBERTURA", "PLAN"),
        "vencimiento": _value(row, "VENCIMIENTO", "PROXIMO VENCIMIENTO", "PRÓXIMO VENCIMIENTO", "VENCIMIENTO CUOTA"),
        "vigencia_desde": _value(row, "VIGENCIA DESDE", "INICIO VIGENCIA"),
        "vigencia_hasta": _value(row, "VIGENCIA HASTA", "FIN VIGENCIA"),
        "asistencia_estado": _value(row, "ESTADO ASISTENCIA", "ASISTENCIA ESTADO"),
        "asistencia_grua": _value(row, "ASISTENCIA GRUA", "ASISTENCIA Y GRUA", "ASISTENCIA Y GRÚA", "GRUA", "GRÚA"),
        # Premio/valor de póliza y deuda real son conceptos separados.
        "premio_total_periodo": _value(row, "PREMIO TOTAL", "PREMIO C/IVA", "PREMIO"),
        "cantidad_cuotas": _value(row, "CANTIDAD CUOTAS", "CANTIDAD DE CUOTAS"),
        "valor_cuota": _value(row, "VALOR CUOTA", "VALOR DE CUOTA", "PRECIO POR CUOTA"),
        "importe_pendiente": _value(row, "IMPORTE PENDIENTE", "SALDO PENDIENTE", "DEUDA"),
        "importe_aprox": _value(row, "IMPORTE APROX", "PREMIO", "IMPORTE"),
        "importe": _value(row, "IMPORTE APROX", "PREMIO", "IMPORTE"),
        "motor": _value(row, "MOTOR"),
        "chasis": _value(row, "CHASIS", "CHASSIS"),
        "uso": _value(row, "USO", "USO DEL VEHICULO"),
        "emitido_dia": _value(row, "EMITIDO DIA", "EMITIDO DÍA", "FECHA EMISION", "FECHA DE EMISION"),
        "field_sources": {},
    }
    record["field_priority"] = {field: 200 for field, value in record.items() if field in _FIELD_TO_CANONICAL and value not in (None, "", [], {})}
    return record


def _persistent_record(row: dict[str, Any]) -> dict[str, Any]:
    data = row.get("datos") if isinstance(row.get("datos"), dict) else {}
    fuentes = row.get("fuentes") if isinstance(row.get("fuentes"), dict) else {}
    ranks = []
    for meta in fuentes.values():
        if isinstance(meta, dict):
            ranks.append(_prioridad_fuente(meta.get("source"), 300))
    rank = max(ranks or [300])
    record = {
        "libro_id": "perfil", "profile_id": row.get("id"), "source_rank": rank,
        "asegurado": str(data.get("NOMBRE") or ""),
        "numero": str(data.get("TELEFONO") or ""),
        "telefono": str(data.get("TELEFONO") or ""),
        "mail": str(data.get("MAIL") or ""),
        "dni": str(data.get("DNI") or ""), "cuit": str(data.get("CUIT") or ""),
        "vehiculo": str(data.get("VEHICULO") or ""), "patente": str(data.get("PATENTE") or ""),
        "compania": str(data.get("COMPANIA") or ""), "poliza": str(data.get("POLIZA") or ""),
        "medio_pago": str(data.get("FORMA_PAGO") or ""), "cp": str(data.get("CP") or ""),
        "cobertura": str(data.get("COBERTURA") or ""),
        "vencimiento": str(data.get("VENCIMIENTO") or ""),
        "vigencia_desde": str(data.get("VIGENCIA_DESDE") or ""),
        "vigencia_hasta": str(data.get("VIGENCIA_HASTA") or ""),
        "asistencia_estado": str(data.get("ASISTENCIA_ESTADO") or ""),
        "asistencia_grua": str(data.get("ASISTENCIA_GRUA") or ""),
        "premio_total_periodo": str(data.get("PREMIO_TOTAL_PERIODO") or ""),
        "cantidad_cuotas": str(data.get("CANTIDAD_CUOTAS") or ""),
        "valor_cuota": str(data.get("VALOR_CUOTA") or ""),
        "importe_pendiente": str(data.get("IMPORTE_PENDIENTE") or ""),
        "importe_aprox": str(data.get("PREMIO_TOTAL_PERIODO") or data.get("VALOR_CUOTA") or ""),
        "importe": str(data.get("IMPORTE_PENDIENTE") or ""),
        "motor": str(data.get("MOTOR") or ""), "chasis": str(data.get("CHASIS") or ""), "uso": str(data.get("USO") or ""),
        "emitido_dia": str(data.get("FECHA_EMISION") or ""),
        "field_sources": fuentes,
    }
    record["field_priority"] = _field_priorities_from_sources(record, fuentes, 300)
    return record


def _matches(reg: dict[str, Any], query: str) -> bool:
    qn = _norm(query); qc = _compact(query)
    if not qn:
        return False
    for key in ("asegurado", "dni", "cuit", "patente", "numero", "telefono", "poliza"):
        raw = reg.get(key, "")
        if not raw:
            continue
        rn = _norm(raw); rc = _compact(raw)
        if qn == rn or (qc and qc == rc):
            return True
    nombre = _norm(reg.get("asegurado"))
    tokens = [t for t in qn.split() if len(t) >= 2]
    return bool(nombre and len(tokens) >= 2 and all(t in nombre.split() for t in tokens))


def _company_identity(value: Any) -> str:
    return _compact(normalizar_compania(value))


def _same_record_identity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    apat, bpat = _compact(a.get("patente")), _compact(b.get("patente"))
    apol, bpol = _compact(a.get("poliza")), _compact(b.get("poliza"))
    acia, bcia = _company_identity(a.get("compania")), _company_identity(b.get("compania"))
    compania_compatible = not acia or not bcia or acia == bcia
    if not compania_compatible:
        return False
    if apat and bpat:
        if apat != bpat:
            return False
        # Misma patente puede tener pólizas históricas diferentes. Si ambos
        # números están presentes y difieren, no mezclar esas pólizas.
        return not (apol and bpol and apol != bpol)
    if apol and bpol:
        return apol == bpol
    # Último fallback sólo para registros pobres sin patente/póliza.
    anom, bnom = _norm(a.get("asegurado")), _norm(b.get("asegurado"))
    aveh, bveh = _norm(a.get("vehiculo")), _norm(b.get("vehiculo"))
    return bool(anom and anom == bnom and aveh and aveh == bveh)


def _source_meta_for_field(record: dict[str, Any], field: str) -> dict[str, Any]:
    canonical = _FIELD_TO_CANONICAL.get(field)
    fuentes = record.get("field_sources") if isinstance(record.get("field_sources"), dict) else {}
    if canonical and isinstance(fuentes.get(canonical), dict):
        return dict(fuentes[canonical])
    if record.get("libro_id") == "perfil":
        return {"source": "perfil"}
    return {"source": "cartera"}


def _merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    priorities: list[dict[str, int]] = []
    # La prioridad es POR CAMPO. Una ficha que contiene un dato manual no puede
    # hacer que otro campo meramente calculado pise un valor explícito de Excel.
    for r in records:
        idx = next((i for i, current in enumerate(groups) if _same_record_identity(current, r)), None)
        if idx is None:
            groups.append({})
            priorities.append({})
            idx = len(groups) - 1
        current = groups[idx]
        current_priority = priorities[idx]
        field_priority = r.get("field_priority") if isinstance(r.get("field_priority"), dict) else {}
        default_priority = int(r.get("source_rank") or 0)

        for field, value in r.items():
            if field in {"field_sources", "field_priority", "source_rank", "origenes"}:
                continue
            if value in (None, "", [], {}):
                continue
            incoming_priority = int(field_priority.get(field, default_priority))
            stored_priority = int(current_priority.get(field, -1))
            if field not in current or incoming_priority >= stored_priority:
                current[field] = value
                current_priority[field] = incoming_priority
                canonical = _FIELD_TO_CANONICAL.get(field)
                if canonical:
                    current.setdefault("field_sources", {})[canonical] = _source_meta_for_field(r, field)

        origins = set(current.get("origenes") or [])
        for origin in (r.get("origenes") or []):
            if origin:
                origins.add(str(origin))
        if r.get("libro_id"):
            origins.add(str(r.get("libro_id")))
        current["origenes"] = sorted(origins)

    return groups


def construir_ficha(query: str, leer_excel: Callable[[str], dict[str, Any]], libros=("1", "2"), buscar_persistente: Callable[[str], list[dict]] | None = None) -> dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"status": "invalid", "error": "Indicá nombre, patente, teléfono, DNI/CUIT o póliza."}

    encontrados: list[dict[str, Any]] = []
    for libro_id in libros:
        try:
            _headers, rows = _headers_rows(leer_excel(str(libro_id)))
        except Exception:
            continue
        for row in rows:
            reg = _canonical(row, str(libro_id))
            if _matches(reg, query):
                encontrados.append(reg)

    if buscar_persistente is not None:
        try:
            for row in buscar_persistente(query) or []:
                reg = _persistent_record(row)
                if _matches(reg, query):
                    encontrados.append(reg)
        except Exception:
            # La ficha interna no debe tumbar la búsqueda histórica de cartera.
            pass

    encontrados = _merge_records(encontrados)
    if not encontrados:
        return {"status": "not_found", "query": query, "records": []}

    nombres = []
    for r in encontrados:
        n = str(r.get("asegurado") or "").strip()
        if n and _norm(n) not in {_norm(x) for x in nombres}:
            nombres.append(n)
    if len(nombres) > 1:
        return {"status": "multiple", "query": query, "candidates": nombres[:10], "records": encontrados}

    principal = nombres[0] if nombres else (encontrados[0].get("asegurado") or query)
    vehicles=[]; companies=[]; policies=[]
    contacts={"telefono":"", "mail":"", "dni":"", "cuit":""}
    vehicle_fields=("vehiculo","patente","compania","poliza","cobertura","medio_pago","emitido_dia","vigencia_desde","vigencia_hasta","vencimiento","asistencia_estado","asistencia_grua","premio_total_periodo","cantidad_cuotas","valor_cuota","importe_pendiente","importe_aprox","importe","uso","motor","chasis","profile_id","field_sources")
    for r in encontrados:
        if r.get("vehiculo") or r.get("patente") or r.get("poliza"):
            vehicle = {k:r.get(k, "") for k in vehicle_fields}
            if vehicle.get("compania"):
                vehicle["compania"] = nombre_compania(vehicle["compania"])
            vehicles.append(vehicle)
        if r.get("compania"):
            display_company = nombre_compania(r["compania"])
            if display_company not in companies:
                companies.append(display_company)
        if r.get("poliza") and r["poliza"] not in policies: policies.append(r["poliza"])
        for key in contacts:
            if not contacts[key] and r.get(key): contacts[key]=r[key]

    origins=sorted({o for r in encontrados for o in (r.get("origenes") or [r.get("libro_id")]) if o})
    return {
        "status":"found", "query":query, "asegurado":principal, "contacto":contacts,
        "companias":companies, "polizas":policies, "vehiculos":vehicles,
        "registros":encontrados, "total_registros":len(encontrados), "fuentes":origins,
    }
