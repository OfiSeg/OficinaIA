"""Ficha operativa determinística de asegurados.

Etapa 18. Construye una vista unificada y de solo lectura a partir de los
libros internos ya existentes. No crea una base paralela y no llama a IA.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable


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


def _canonical(row: dict[str, Any], libro_id: str) -> dict[str, str]:
    asegurado = _value(row, "ASEGURADO", "CLIENTE", "NOMBRE", "NOMBRE ASEGURADO", "TITULAR")
    numero = _value(row, "NUMERO", "NRO", "TELEFONO", "TEL", "CELULAR", "WHATSAPP")
    patente = _value(row, "PATENTE", "DOMINIO", "CHAPA")
    vehiculo = _value(row, "VEHICULO", "VEHÍCULO", "MARCA MODELO", "MARCA/MODELO", "DESCRIPCION DEL VEHICULO")
    if not vehiculo:
        marca = _value(row, "MARCA", "MARCA DEL VEHICULO")
        modelo = _value(row, "MODELO", "MODELO DEL VEHICULO")
        vehiculo = " ".join(x for x in (marca, modelo) if x).strip()
    return {
        "libro_id": str(libro_id),
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
        "motor": _value(row, "MOTOR"),
        "chasis": _value(row, "CHASIS", "CHASSIS"),
        "uso": _value(row, "USO", "USO DEL VEHICULO"),
        "emitido_dia": _value(row, "EMITIDO DIA", "EMITIDO DÍA", "FECHA EMISION", "FECHA DE EMISION"),
    }


def _matches(reg: dict[str, str], query: str) -> bool:
    qn = _norm(query)
    qc = _compact(query)
    if not qn:
        return False
    for key in ("asegurado", "dni", "cuit", "patente", "numero", "telefono", "poliza"):
        raw = reg.get(key, "")
        if not raw:
            continue
        rn = _norm(raw)
        rc = _compact(raw)
        if qn == rn or (qc and qc == rc):
            return True
    # Para nombres permitimos coincidencia por tokens, no fuzzy inventado.
    nombre = _norm(reg.get("asegurado"))
    tokens = [t for t in qn.split() if len(t) >= 2]
    if nombre and len(tokens) >= 2 and all(t in nombre.split() for t in tokens):
        return True
    return False


def _dedupe_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    seen = set()
    for r in records:
        key = (
            _norm(r.get("asegurado")), _compact(r.get("patente")),
            _norm(r.get("compania")), _norm(r.get("poliza")), str(r.get("libro_id")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def construir_ficha(query: str, leer_excel: Callable[[str], dict[str, Any]], libros=("1", "2")) -> dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"status": "invalid", "error": "Indicá nombre, patente, teléfono, DNI/CUIT o póliza."}

    encontrados: list[dict[str, str]] = []
    for libro_id in libros:
        try:
            _headers, rows = _headers_rows(leer_excel(str(libro_id)))
        except Exception:
            continue
        for row in rows:
            reg = _canonical(row, str(libro_id))
            if _matches(reg, query):
                encontrados.append(reg)

    encontrados = _dedupe_records(encontrados)
    if not encontrados:
        return {"status": "not_found", "query": query, "records": []}

    nombres = []
    for r in encontrados:
        n = r.get("asegurado", "").strip()
        if n and _norm(n) not in {_norm(x) for x in nombres}:
            nombres.append(n)

    # Si una búsqueda amplia por nombre devuelve personas distintas, no las mezclamos.
    if len(nombres) > 1:
        return {
            "status": "multiple",
            "query": query,
            "candidates": nombres[:10],
            "records": encontrados,
        }

    principal = nombres[0] if nombres else (encontrados[0].get("asegurado") or query)
    vehicles = []
    companies = []
    policies = []
    contacts = {"telefono": "", "mail": "", "dni": "", "cuit": ""}
    for r in encontrados:
        if r.get("vehiculo") or r.get("patente"):
            vehicles.append({k: r.get(k, "") for k in ("vehiculo", "patente", "compania", "poliza", "cobertura", "uso", "motor", "chasis")})
        if r.get("compania") and r["compania"] not in companies:
            companies.append(r["compania"])
        if r.get("poliza") and r["poliza"] not in policies:
            policies.append(r["poliza"])
        for key in contacts:
            if not contacts[key] and r.get(key):
                contacts[key] = r[key]

    return {
        "status": "found",
        "query": query,
        "asegurado": principal,
        "contacto": contacts,
        "companias": companies,
        "polizas": policies,
        "vehiculos": vehicles,
        "registros": encontrados,
        "total_registros": len(encontrados),
        "fuentes": sorted({r.get("libro_id") for r in encontrados if r.get("libro_id")}),
    }
