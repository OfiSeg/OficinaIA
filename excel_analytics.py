"""Analítica determinística sobre el Excel interno de OficinaIA.

No conoce Flask, Gemini, R2 ni persistencia. Recibe filas ya cargadas y devuelve
resultados exactos para agrupaciones, porcentajes, vacíos, duplicados y
clasificación auto/moto.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import re
import unicodedata
from typing import Iterable

from companias import normalizar_compania, aliases_companias


def _norm(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def _plate(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _field(row: dict, aliases: Iterable[str]) -> str | None:
    wanted = {_norm(x) for x in aliases}
    for key in row.keys():
        if _norm(key) in wanted:
            return key
    return None


def _value(row: dict, aliases: Iterable[str]):
    key = _field(row, aliases)
    return row.get(key, "") if key else ""


COMPANY_ALIASES = ("CIA", "COMPAÑIA", "COMPANIA", "COMPAÑÍA", "ASEGURADORA", "COMPANIA DE SEGUROS")
PLATE_ALIASES = ("PATENTE", "DOMINIO")
VEHICLE_ALIASES = ("VEHICULO", "VEHÍCULO", "TIPO VEHICULO", "TIPO DE VEHICULO", "MARCA MODELO", "VH")
PERSON_ALIASES = ("DNI", "DOCUMENTO", "CUIT", "CUIL", "ASEGURADO", "CLIENTE", "NOMBRE")


# Formatos argentinos históricos y Mercosur.
# Auto histórico: ABC123. Moto histórica: 123ABC.
# Auto Mercosur: AB123CD. Moto Mercosur: A123BCD.
def clasificar_patente_argentina(value: str) -> str:
    p = _plate(value)
    if re.fullmatch(r"[A-Z]{3}\d{3}", p):
        return "AUTO"
    if re.fullmatch(r"\d{3}[A-Z]{3}", p):
        return "MOTO"
    if re.fullmatch(r"[A-Z]{2}\d{3}[A-Z]{2}", p):
        return "AUTO"
    if re.fullmatch(r"[A-Z]\d{3}[A-Z]{3}", p):
        return "MOTO"
    return "INDETERMINADO"


def clasificar_vehiculo(row: dict) -> str:
    """Clasifica auto/moto con reglas determinísticas y fallback conservador.

    La patente manda cuando encaja en un formato registral conocido. Sólo cuando
    no alcanza se mira el texto VEHICULO. Si sigue sin evidencia, no se adivina.
    """
    por_patente = clasificar_patente_argentina(_value(row, PLATE_ALIASES))
    if por_patente != "INDETERMINADO":
        return por_patente

    text = _norm(_value(row, VEHICLE_ALIASES))
    if not text:
        return "INDETERMINADO"

    # Evidencia textual fuerte para motos.
    moto_tokens = (
        "moto", "motocicleta", "scooter", "ciclomotor", "cuatriciclo",
        "ybr", "wave", "cg ", "biz", "crypton", "motomel", "corven",
        "zanella", "gilera", "mondial", "brava", "bajaj", "rouser",
    )
    if any(token in f" {text} " for token in moto_tokens):
        return "MOTO"

    # Remolques/trailers no son auto ni moto.
    if any(token in text for token in ("trailer", "remolque", "acoplado")):
        return "OTRO"

    # Un texto de vehículo sin señal de moto se mantiene indeterminado. Evita
    # convertir todo lo desconocido en auto por defecto.
    return "INDETERMINADO"



HOME_TERMS = (
    "hogar", "combinado familiar", "seguro de hogar", "seguro hogar",
    "vivienda", "casa", "departamento", "depto",
)


def clasificar_riesgo(row: dict) -> str:
    """Clasifica el tipo de riesgo sin confundir registros de cartera con vehículos.

    AUTO/MOTO se resuelven con la clasificación registral existente. Hogar/Combinado
    se detecta por texto explícito en VEHICULO/PATENTE. Remolques/acoplados quedan
    como OTRO_VEHICULAR. Lo que no puede demostrarse queda INDETERMINADO.
    """
    vehicle_text = _norm(_value(row, VEHICLE_ALIASES))
    plate_text = _norm(_value(row, PLATE_ALIASES))
    combined = f"{vehicle_text} {plate_text}".strip()

    if any(term in combined for term in HOME_TERMS):
        return "HOGAR_COMBINADO"

    vehicle_class = clasificar_vehiculo(row)
    if vehicle_class == "AUTO":
        return "AUTO"
    if vehicle_class == "MOTO":
        return "MOTO"
    if vehicle_class == "OTRO":
        return "OTRO_VEHICULAR"
    return "INDETERMINADO"


def clasificacion_riesgos(rows: list[dict], compania: str | None = None) -> dict:
    base = _filter_company(rows, compania)
    counts = Counter(clasificar_riesgo(r) for r in base)
    vehiculos_confirmados = counts.get("AUTO", 0) + counts.get("MOTO", 0) + counts.get("OTRO_VEHICULAR", 0)
    return {
        "ok": True,
        "operacion": "clasificacion_riesgos",
        "total_registros": len(base),
        "autos": counts.get("AUTO", 0),
        "motos": counts.get("MOTO", 0),
        "otros_vehiculares": counts.get("OTRO_VEHICULAR", 0),
        "hogar_combinado": counts.get("HOGAR_COMBINADO", 0),
        "indeterminados": counts.get("INDETERMINADO", 0),
        "vehiculos_confirmados": vehiculos_confirmados,
        "nota": "Registros de cartera, vehículos y riesgos de hogar son conceptos distintos; los indeterminados no se cuentan como vehículos.",
    }


def _is_home_query(q: str) -> bool:
    return any(term in q for term in ("hogar", "combinado familiar", "combinados familiares", "seguro de hogar", "seguros de hogar", "vivienda"))


def _home_rows(rows: list[dict], company: str | None = None) -> list[dict]:
    return [r for r in _filter_company(rows, company) if clasificar_riesgo(r) == "HOGAR_COMBINADO"]

def _canonical_company(row: dict) -> str:
    raw = str(_value(row, COMPANY_ALIASES) or "").strip()
    if not raw:
        return ""
    raw_n = _norm(raw)
    aliases = aliases_companias()
    if raw_n in aliases:
        codigo, display = aliases[raw_n]
        return str(display or codigo).strip()
    codigo = str(normalizar_compania(raw) or raw).strip()
    for _alias, (code, display) in aliases.items():
        if _norm(code) == _norm(codigo):
            return str(display or code).strip()
    return codigo


def _filter_company(rows: list[dict], company: str | None) -> list[dict]:
    if not company:
        return list(rows)
    target = _norm(normalizar_compania(company))
    return [r for r in rows if _norm(normalizar_compania(_value(r, COMPANY_ALIASES))) == target]


def _find_field(rows: list[dict], requested: str) -> str | None:
    if not rows:
        return None
    aliases = {
        "compania": COMPANY_ALIASES,
        "cia": COMPANY_ALIASES,
        "patente": PLATE_ALIASES,
        "vehiculo": VEHICLE_ALIASES,
        "asegurado": ("ASEGURADO", "CLIENTE", "NOMBRE"),
        "numero": ("NUMERO", "NRO", "DNI", "POLIZA", "PÓLIZA"),
    }.get(_norm(requested), (requested,))
    for row in rows[:20]:
        key = _field(row, aliases)
        if key:
            return key
    return None


def ranking(rows: list[dict], agrupar_por: str = "compania", compania: str | None = None,
            incluir_porcentaje: bool = True, limite: int | None = None) -> dict:
    base = _filter_company(rows, compania)
    field = _find_field(base, agrupar_por)
    if not field:
        return {"ok": False, "error": f"No existe el campo para agrupar: {agrupar_por}", "cantidad": 0}

    counts = Counter()
    for row in base:
        raw = str(row.get(field, "") or "").strip()
        if not raw:
            continue
        label = _canonical_company(row) if _norm(agrupar_por) in {"compania", "cia"} else raw
        counts[label] += 1

    total = sum(counts.values())
    ordered = sorted(counts.items(), key=lambda x: (-x[1], _norm(x[0])))
    if limite and limite > 0:
        ordered = ordered[:limite]
    result = []
    for pos, (label, count) in enumerate(ordered, 1):
        item = {"posicion": pos, "valor": label, "cantidad": count}
        if incluir_porcentaje:
            item["porcentaje"] = round((count / total * 100) if total else 0.0, 2)
        result.append(item)
    return {"ok": True, "operacion": "ranking", "agrupar_por": agrupar_por, "total": total, "resultados": result}


def duplicados(rows: list[dict], campo: str = "patente", compania: str | None = None) -> dict:
    base = _filter_company(rows, compania)
    field = _find_field(base, campo)
    if not field:
        return {"ok": False, "error": f"No existe el campo: {campo}", "cantidad": 0}
    groups = defaultdict(list)
    for row in base:
        raw = str(row.get(field, "") or "").strip()
        if not raw:
            continue
        key = _plate(raw) if _norm(campo) == "patente" else _norm(raw)
        if key:
            groups[key].append(row)
    items = [{"valor": key, "cantidad": len(group)} for key, group in groups.items() if len(group) > 1]
    items.sort(key=lambda x: (-x["cantidad"], x["valor"]))
    return {"ok": True, "operacion": "duplicados", "campo": campo, "cantidad": len(items), "resultados": items}


def vacios(rows: list[dict], campo: str, compania: str | None = None) -> dict:
    base = _filter_company(rows, compania)
    field = _find_field(base, campo)
    if not field:
        return {"ok": False, "error": f"No existe el campo: {campo}", "cantidad": 0}
    empty = [r for r in base if not str(r.get(field, "") or "").strip()]
    return {"ok": True, "operacion": "vacios", "campo": campo, "cantidad": len(empty), "total": len(base)}


def clasificacion(rows: list[dict], compania: str | None = None) -> dict:
    risk = clasificacion_riesgos(rows, compania)
    autos = risk["autos"]
    motos = risk["motos"]
    return {
        "ok": True,
        "operacion": "clasificacion_vehiculos",
        "total": risk["total_registros"],
        "autos": autos,
        "motos": motos,
        "otros": risk["otros_vehiculares"],
        "hogar_combinado": risk["hogar_combinado"],
        "indeterminados": risk["indeterminados"],
        "vehiculos_confirmados": risk["vehiculos_confirmados"],
        "diferencia_auto_moto": abs(autos - motos),
        "mayoria": "AUTO" if autos > motos else "MOTO" if motos > autos else "EMPATE",
        "regla": "AUTO/MOTO por patente argentina y fallback textual conservador. Hogar/Combinado se separa de vehículos; lo no demostrable queda INDETERMINADO.",
    }


def porcentaje(rows: list[dict], campo: str = "compania", valor: str | None = None,
               excluir_valor: str | None = None) -> dict:
    field = _find_field(rows, campo)
    if not field:
        return {"ok": False, "error": f"No existe el campo: {campo}", "cantidad": 0}
    total = len(rows)
    if _norm(campo) in {"compania", "cia"}:
        def normalized(r): return _norm(normalizar_compania(r.get(field, "")))
        target = _norm(normalizar_compania(valor)) if valor else None
        excluded = _norm(normalizar_compania(excluir_valor)) if excluir_valor else None
    else:
        def normalized(r): return _norm(r.get(field, ""))
        target = _norm(valor) if valor else None
        excluded = _norm(excluir_valor) if excluir_valor else None

    if excluded is not None:
        selected = [r for r in rows if normalized(r) != excluded]
    elif target is not None:
        selected = [r for r in rows if normalized(r) == target]
    else:
        return {"ok": False, "error": "Falta valor o excluir_valor para calcular el porcentaje.", "cantidad": 0}
    count = len(selected)
    return {"ok": True, "operacion": "porcentaje", "campo": campo, "cantidad": count, "total": total,
            "porcentaje": round((count / total * 100) if total else 0.0, 2)}


def _company_from_query(q: str) -> str | None:
    """Detecta una compañía mencionada literalmente, priorizando el alias más largo."""
    hits = []
    for alias, (codigo, display) in aliases_companias().items():
        an = _norm(alias)
        if not an:
            continue
        m = re.search(rf"(?<![a-z0-9]){re.escape(an)}(?![a-z0-9])", q)
        if m:
            hits.append((m.start(), len(an), str(display or codigo)))
    if not hits:
        return None
    hits.sort(key=lambda x: (x[0], x[1]))
    return hits[-1][2]


def _classification_name(q: str) -> str | None:
    has_auto = bool(re.search(r"\bautos?\b|\bautomotores?\b", q))
    has_moto = bool(re.search(r"\bmotos?\b|\bmotocicletas?\b|\bmotovehiculos?\b", q))
    if has_auto and not has_moto:
        return "AUTO"
    if has_moto and not has_auto:
        return "MOTO"
    return None


def _rows_by_class(rows: list[dict], clase: str | None) -> list[dict]:
    if not clase:
        return list(rows)
    return [r for r in rows if clasificar_vehiculo(r) == clase]


def ranking_compuesto(rows: list[dict], *, clase: str | None = None,
                      compania: str | None = None) -> dict:
    """Ranking de compañías sobre un subconjunto, conservando denominadores explícitos."""
    base_company = _filter_company(rows, compania)
    base = _rows_by_class(base_company, clase)
    counts = Counter(_canonical_company(r) for r in base if _canonical_company(r))
    con_compania = sum(counts.values())
    sin_compania = len(base) - con_compania
    ordered = sorted(counts.items(), key=lambda x: (-x[1], _norm(x[0])))
    result = []
    for pos, (label, count) in enumerate(ordered, 1):
        result.append({
            "posicion": pos, "valor": label, "cantidad": count,
            # El porcentaje usa TODO el subconjunto como denominador, incluso filas sin compañía.
            "porcentaje": round((count / len(base) * 100) if base else 0.0, 2),
        })
    return {
        "ok": True, "operacion": "ranking_compuesto", "clase": clase,
        "filtro_compania": compania, "total_subconjunto": len(base),
        "con_compania": con_compania, "sin_compania": sin_compania,
        "resultados": result,
    }


def _answer_analytic_clause(rows: list[dict], consulta: str) -> dict:
    """Compone primitivas analíticas para una cláusula de lenguaje natural."""
    q = _norm(consulta)
    company = _company_from_query(q)
    mref = re.search(r"referente resuelto:\s*([^\]\n]+)", q)
    if mref:
        company = mref.group(1).strip()
    clase = _classification_name(q)

    # Hogar / combinado familiar es un riesgo de cartera, no un vehículo.
    # Soporta singular/plural y formulaciones con OR: "combinado familiar o seguro de hogar".
    if _is_home_query(q):
        home = _home_rows(rows, company)
        return {
            "ok": True, "operacion": "conteo_riesgo", "categoria": "HOGAR_COMBINADO",
            "compania": company, "cantidad": len(home), "total_registros": len(_filter_company(rows, company)),
            "registros": home[:50],
            "nota": "Combinado familiar/seguro de hogar se cuenta como riesgo de cartera y se excluye del conteo de vehículos.",
        }

    # Si preguntan cuántos vehículos hay, no equivaler 'filas del Excel' a vehículos.
    if ("vehiculo" in q or "vehiculos" in q) and any(x in q for x in ("cuanto", "cantidad", "total")) and not clase:
        risk = clasificacion_riesgos(rows, company)
        risk["cantidad"] = risk["vehiculos_confirmados"]
        return risk

    if any(x in q for x in ("duplicad", "repetid")) and ("patente" in q or "dominio" in q):
        return duplicados(rows, "patente", company)
    if any(x in q for x in ("sin patente", "no tienen patente", "no tiene patente", "patente vacia", "patentes vacias", "patente en blanco")):
        return vacios(rows, "patente", company)

    # AUTO/MOTO de una compañía: composición filtro -> clasificación -> conteo.
    if company and ("auto" in q or "moto" in q):
        result = clasificacion(rows, company)
        result["compania"] = company
        if clase:
            result["clase_solicitada"] = clase
            result["cantidad_solicitada"] = result["autos"] if clase == "AUTO" else result["motos"]
        return result

    # Ranking dentro de una clase: clase -> agrupar compañía -> ordenar -> porcentaje.
    if clase and ("compania" in q or "cartera" in q) and any(x in q for x in ("mas", "mayor", "menos", "menor", "ranking", "ordena", "porcentaje")):
        result = ranking_compuesto(rows, clase=clase)
        if result["resultados"]:
            result["primero"] = result["resultados"][0]
        return result

    # Comparación global auto/moto.
    if ("moto" in q and "auto" in q) and any(x in q for x in ("mas", "cuantos", "cantidad", "diferencia", "porcentaje")):
        return clasificacion(rows, company)

    # Porcentaje de una compañía o su complemento.
    if "porcentaje" in q and company:
        first = _norm(company).split()[0]
        negated = bool(re.search(rf"\b(?:no|excepto|sin)\b.{{0,30}}{re.escape(first)}", q))
        return porcentaje(rows, "compania", excluir_valor=company if negated else None, valor=None if negated else company)

    # Ranking general y consultas ordinales/diferencias.
    if "compania" in q or "cartera" in q:
        if any(x in q for x in ("porcentaje", "representa", "mayor", "menor", "segundo", "segunda", "ordena", "ordenar", "ranking", "mas tengo", "menos tengo")):
            result = ranking_compuesto(rows)
            items = result.get("resultados", [])
            if any(x in q for x in ("segundo", "segunda")) and len(items) >= 2:
                result["seleccion"] = items[1]
                if any(x in q for x in ("diferencia", "cuantos menos", "cuanto menos", "menos tiene")):
                    result["comparado_con_primero"] = items[0]
                    result["diferencia_con_primero"] = items[0]["cantidad"] - items[1]["cantidad"]
            elif items:
                result["primero"] = items[0]
            return result

    # Conteo simple de compañía heredada o literal.
    if company and any(x in q for x in ("vehiculo", "vehiculos", "registros", "polizas", "poliza")):
        filtered = _filter_company(rows, company)
        return {"ok": True, "operacion": "conteo_compania", "compania": company,
                "cantidad": len(filtered), "total": len(rows)}

    return {"ok": False, "error": "La cláusula no corresponde a una operación analítica determinística reconocida.", "cantidad": 0}


def _natural_query(rows: list[dict], consulta: str) -> dict:
    """Analiza una o varias cláusulas y compone operaciones exactas.

    Si el usuario hace dos preguntas en el mismo mensaje, cada cláusula se resuelve
    independientemente sobre el mismo dataset y se devuelve un resultado compuesto.
    """
    raw = str(consulta or "").strip()
    # Separar preguntas reales; conservar el referente resuelto en todas las cláusulas.
    ref = None
    mref = re.search(r"\[REFERENTE RESUELTO:\s*([^\]]+)\]", raw, flags=re.I)
    if mref:
        ref = mref.group(1).strip()
    clean = re.sub(r"\[REFERENTE RESUELTO:[^\]]+\]", "", raw, flags=re.I).strip()
    clauses = [x.strip(" \n\t¿?") for x in re.split(r"[?]+", clean) if x.strip(" \n\t¿?")]
    if not clauses:
        clauses = [clean]
    results = []
    for clause in clauses:
        enriched = clause + (f"\n[REFERENTE RESUELTO: {ref}]" if ref else "")
        r = _answer_analytic_clause(rows, enriched)
        if r.get("ok"):
            r["consulta_parcial"] = clause
            results.append(r)
    if len(results) > 1:
        return {"ok": True, "operacion": "compuesta", "total_dataset": len(rows), "resultados": results}
    if len(results) == 1:
        return results[0]
    return {"ok": False, "error": "La consulta no corresponde a una operación analítica determinística reconocida.", "cantidad": 0}

def analizar(rows: list[dict], consulta: str | None = None, operacion: str | None = None,
             campo: str | None = None, agrupar_por: str | None = None,
             compania: str | None = None, valor: str | None = None,
             excluir_valor: str | None = None, limite: int | None = None) -> dict:
    op = _norm(operacion)
    if not op:
        return _natural_query(rows, consulta or "")
    if op in {"ranking", "agrupar", "agrupacion"}:
        return ranking(rows, agrupar_por or campo or "compania", compania, True, limite)
    if op in {"duplicados", "duplicado"}:
        return duplicados(rows, campo or "patente", compania)
    if op in {"vacios", "faltantes", "sin_dato"}:
        return vacios(rows, campo or "patente", compania)
    if op in {"clasificacion", "clasificar_vehiculos", "autos_motos"}:
        return clasificacion(rows, compania)
    if op in {"clasificacion_riesgos", "riesgos", "tipos_riesgo"}:
        return clasificacion_riesgos(rows, compania)
    if op in {"porcentaje", "proporcion"}:
        return porcentaje(rows, campo or "compania", valor, excluir_valor)
    return {"ok": False, "error": f"Operación analítica no soportada: {operacion}", "cantidad": 0}
