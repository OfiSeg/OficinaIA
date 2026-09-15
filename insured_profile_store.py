"""Persistencia de la ficha interna asegurado -> vehículo -> póliza.

La cartera Excel/Sheet sigue siendo una fuente operativa, no la base completa de
la ficha. Este store conserva datos que no deben perderse (póliza, cobertura,
vigencias, asistencia, importes semánticos y correcciones confirmadas) y usa
PostgreSQL/Neon cuando existe DATABASE_URL; SQLite queda como fallback local.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
from pathlib import Path
import json
import os
import re
import sqlite3
import threading
import unicodedata
from typing import Any

import runtime_config
from companias import nombre_compania, normalizar_compania

BASE_DIR = Path(__file__).resolve().parent
_LOCK = threading.Lock()
_SQLITE_READY: set[str] = set()
_PG_READY = False

SOURCE_PRIORITY = {
    "": 0,
    "desconocido": 0,
    "calculado": 100,
    "cartera": 200,
    "excel": 200,
    "perfil": 300,
    "perfil_confirmado": 350,
    "alta_confirmada": 350,
    "documento": 400,
    "manual_confirmado": 500,
}

FIELD_ALIASES = {
    "NOMBRE": ("NOMBRE", "ASEGURADO", "CLIENTE", "TITULAR"),
    "TELEFONO": ("TELEFONO", "TELÉFONO", "NUMERO", "NRO", "CELULAR", "WHATSAPP"),
    "MAIL": ("MAIL", "EMAIL", "E-MAIL", "CORREO"),
    "DNI": ("DNI", "DOCUMENTO"),
    "CUIT": ("CUIT", "CUIL", "CUIT/CUIL"),
    "VEHICULO": ("VEHICULO", "VEHÍCULO", "MARCA MODELO", "MARCA/MODELO"),
    "PATENTE": ("PATENTE", "DOMINIO", "CHAPA"),
    "COMPANIA": ("COMPANIA", "COMPAÑIA", "CIA", "ASEGURADORA"),
    "POLIZA": ("POLIZA", "PÓLIZA", "NUMERO_POLIZA", "NRO POLIZA", "NUMERO POLIZA"),
    "COBERTURA": ("COBERTURA", "PLAN", "PLAN COBERTURA"),
    "FORMA_PAGO": ("FORMA_PAGO", "FORMA DE PAGO", "MEDIO DE PAGO", "MEDIO_PAGO"),
    "PREMIO_TOTAL_PERIODO": ("PREMIO_TOTAL_PERIODO", "PREMIO TOTAL", "PREMIO C/IVA", "PREMIO"),
    "CANTIDAD_CUOTAS": ("CANTIDAD_CUOTAS", "CANTIDAD DE CUOTAS", "CUOTAS"),
    "VALOR_CUOTA": ("VALOR_CUOTA", "VALOR DE CUOTA", "IMPORTE CUOTA", "PRECIO POR CUOTA", "CUOTA"),
    "IMPORTE_PENDIENTE": ("IMPORTE_PENDIENTE", "IMPORTE PENDIENTE", "SALDO PENDIENTE", "DEUDA"),
    "FECHA_EMISION": ("FECHA_EMISION", "FECHA DE EMISION", "FECHA DE EMISIÓN", "EMITIDO DIA", "EMITIDO DÍA", "EMITIDO DÍA:"),
    "VIGENCIA_DESDE": ("VIGENCIA_DESDE", "VIGENCIA DESDE", "INICIO VIGENCIA", "DESDE"),
    "VIGENCIA_HASTA": ("VIGENCIA_HASTA", "VIGENCIA HASTA", "FIN VIGENCIA", "HASTA"),
    "VENCIMIENTO": ("VENCIMIENTO", "PROXIMO VENCIMIENTO", "PRÓXIMO VENCIMIENTO", "VENCIMIENTO CUOTA"),
    "ASISTENCIA_ESTADO": ("ASISTENCIA_ESTADO", "ESTADO ASISTENCIA", "ESTADO GRUA", "ESTADO GRÚA"),
    "ASISTENCIA_GRUA": ("ASISTENCIA_GRUA", "ASISTENCIA Y GRUA", "ASISTENCIA Y GRÚA", "GRUA", "GRÚA"),
    "MOTOR": ("MOTOR",),
    "CHASIS": ("CHASIS", "CHASSIS"),
    "USO": ("USO", "USO DEL VEHICULO", "USO DEL VEHÍCULO"),
}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).upper().strip()
    return re.sub(r"\s+", " ", text)


def _keynorm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(value))


def _clean(value: Any, max_len: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\r", " ").replace("\n", " ")).strip()[:max_len]


def _index(raw: dict) -> dict[str, Any]:
    return {_norm(k).replace("_", " "): v for k, v in (raw or {}).items()}


def canonicalizar(raw: dict | None) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    idx = _index(raw)
    out: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        value = ""
        for alias in aliases:
            candidate = idx.get(_norm(alias).replace("_", " "))
            if str(candidate or "").strip():
                value = _clean(candidate)
                break
        if field == "PATENTE":
            value = _keynorm(value)
        elif field == "COMPANIA" and value:
            value = nombre_compania(value)
        elif field == "ASISTENCIA_ESTADO" and value:
            value = _normalizar_estado_asistencia(value)
        out[field] = value
    return out


def _normalizar_estado_asistencia(value: Any) -> str:
    key = _norm(value)
    if key in {"INCLUYE", "INCLUIDA", "SI", "SÍ", "CON GRUA", "CON GRÚA", "CON ASISTENCIA"}:
        return "INCLUYE"
    if key in {"NO INCLUYE", "NO_INCLUYE", "SIN GRUA", "SIN GRÚA", "SIN ASISTENCIA", "NO"}:
        return "NO_INCLUYE"
    return "DESCONOCIDO" if key else ""


def _record_key(data: dict[str, str]) -> str:
    pat = _keynorm(data.get("PATENTE"))
    pol = _keynorm(data.get("POLIZA"))
    cia = _keynorm(normalizar_compania(data.get("COMPANIA")))
    nom = _keynorm(data.get("NOMBRE"))
    veh = _keynorm(data.get("VEHICULO"))
    if pat and pol:
        return f"PP|{pat}|{cia}|{pol}"
    if pat:
        return f"PV|{pat}|{cia}"
    if pol:
        return f"PO|{cia}|{pol}"
    return f"NV|{nom}|{veh}|{cia}"


def _sqlite_path() -> Path:
    override = str(os.getenv("INSURED_PROFILE_SQLITE_PATH") or "").strip()
    return Path(override) if override else BASE_DIR / "fichas_asegurados.db"


def _usar_postgres() -> bool:
    return bool(runtime_config.get_text("DATABASE_URL"))


def _sqlite_connect():
    path = _sqlite_path()
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    _ensure_sqlite(db, str(path))
    return db


def _ensure_sqlite(db, key: str):
    if key in _SQLITE_READY:
        return
    with _LOCK:
        if key in _SQLITE_READY:
            return
        db.executescript("""
        CREATE TABLE IF NOT EXISTS fichas_asegurados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave TEXT NOT NULL UNIQUE,
            asegurado TEXT NOT NULL DEFAULT '',
            patente TEXT NOT NULL DEFAULT '',
            poliza TEXT NOT NULL DEFAULT '',
            compania TEXT NOT NULL DEFAULT '',
            datos TEXT NOT NULL DEFAULT '{}',
            fuentes TEXT NOT NULL DEFAULT '{}',
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_por TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_fichas_patente ON fichas_asegurados(patente);
        CREATE INDEX IF NOT EXISTS idx_fichas_poliza ON fichas_asegurados(poliza);
        CREATE INDEX IF NOT EXISTS idx_fichas_asegurado ON fichas_asegurados(asegurado);
        CREATE TABLE IF NOT EXISTS eventos_fichas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ficha_id INTEGER,
            tipo TEXT NOT NULL,
            detalle TEXT NOT NULL DEFAULT '{}',
            usuario TEXT NOT NULL DEFAULT '',
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(ficha_id) REFERENCES fichas_asegurados(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_eventos_ficha ON eventos_fichas(ficha_id, creado_en DESC);
        """)
        db.commit()
        _SQLITE_READY.add(key)


def _pg_connect():
    from database_pg import conectar_pg
    db = conectar_pg()
    _ensure_pg(db)
    return db


def _ensure_pg(db):
    global _PG_READY
    if _PG_READY:
        return
    with _LOCK:
        if _PG_READY:
            return
        with db.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS fichas_asegurados (
                id SERIAL PRIMARY KEY,
                clave VARCHAR(400) NOT NULL UNIQUE,
                asegurado VARCHAR(240) NOT NULL DEFAULT '',
                patente VARCHAR(40) NOT NULL DEFAULT '',
                poliza VARCHAR(160) NOT NULL DEFAULT '',
                compania VARCHAR(160) NOT NULL DEFAULT '',
                datos JSONB NOT NULL DEFAULT '{}'::jsonb,
                fuentes JSONB NOT NULL DEFAULT '{}'::jsonb,
                creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                actualizado_por VARCHAR(120) NOT NULL DEFAULT ''
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fichas_patente ON fichas_asegurados(patente)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fichas_poliza ON fichas_asegurados(poliza)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fichas_asegurado ON fichas_asegurados(asegurado)")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS eventos_fichas (
                id SERIAL PRIMARY KEY,
                ficha_id INTEGER REFERENCES fichas_asegurados(id) ON DELETE SET NULL,
                tipo VARCHAR(80) NOT NULL,
                detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
                usuario VARCHAR(120) NOT NULL DEFAULT '',
                creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_eventos_ficha ON eventos_fichas(ficha_id, creado_en DESC)")
        db.commit()
        _PG_READY = True


def _loads(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _rowdict(row: Any) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {}


def _listar_raw() -> list[dict]:
    if _usar_postgres():
        with closing(_pg_connect()) as db:
            from psycopg2.extras import RealDictCursor
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM fichas_asegurados ORDER BY actualizado_en DESC, id DESC")
                rows = cur.fetchall()
    else:
        with closing(_sqlite_connect()) as db:
            rows = db.execute("SELECT * FROM fichas_asegurados ORDER BY actualizado_en DESC, id DESC").fetchall()
    out = []
    for raw in rows:
        row = _rowdict(raw)
        row["datos"] = _loads(row.get("datos"))
        row["fuentes"] = _loads(row.get("fuentes"))
        out.append(row)
    return out


def _same(a: Any, b: Any) -> bool:
    return _keynorm(a) == _keynorm(b) if (a or b) else True


def _candidate(existing: list[dict], incoming: dict[str, str]) -> dict | None:
    key = _record_key(incoming)
    for row in existing:
        if row.get("clave") == key:
            return row
    pat, pol = _keynorm(incoming.get("PATENTE")), _keynorm(incoming.get("POLIZA"))
    cia = _keynorm(normalizar_compania(incoming.get("COMPANIA")))
    if pat:
        candidates = [r for r in existing if _keynorm(r.get("patente")) == pat]
        if cia:
            candidates = [r for r in candidates if not r.get("compania") or _keynorm(normalizar_compania(r.get("compania"))) == cia]
        if pol:
            exact = [r for r in candidates if _keynorm(r.get("poliza")) == pol]
            if exact:
                return exact[0]
            blank = [r for r in candidates if not _keynorm(r.get("poliza"))]
            if blank:
                return blank[0]
        else:
            # Si existen varias pólizas históricas para la misma patente y la
            # entrada no identifica una póliza, no elegir una al azar. Reusar
            # sólo una ficha explícitamente "sin póliza" o una única candidata.
            blank = [r for r in candidates if not _keynorm(r.get("poliza"))]
            if len(blank) == 1:
                return blank[0]
            if len(candidates) == 1:
                return candidates[0]
    if pol:
        candidates = [r for r in existing if _keynorm(r.get("poliza")) == pol]
        if cia:
            candidates = [r for r in candidates if not r.get("compania") or _keynorm(normalizar_compania(r.get("compania"))) == cia]
        if candidates:
            return candidates[0]
    nom, veh = _keynorm(incoming.get("NOMBRE")), _keynorm(incoming.get("VEHICULO"))
    if nom and veh:
        for r in existing:
            d = r.get("datos") or {}
            if _keynorm(d.get("NOMBRE")) == nom and _keynorm(d.get("VEHICULO")) == veh:
                return r
    return None


def _canonical_source_map(raw: dict | None) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    idx = {_norm(k).replace("_", " "): str(v or "").strip() for k, v in raw.items()}
    out: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in (field, *aliases):
            value = idx.get(_norm(alias).replace("_", " "))
            if value:
                out[field] = value
                break
    return out


def _merge(existing: dict, incoming: dict[str, str], source: str, field_sources: dict[str, str] | None = None) -> tuple[dict, dict, list[dict]]:
    data = dict(existing.get("datos") or {})
    sources = dict(existing.get("fuentes") or {})
    conflicts = []
    field_sources = _canonical_source_map(field_sources)
    now = datetime.now().isoformat(timespec="seconds")
    for field, value in incoming.items():
        value = _clean(value)
        if not value:
            continue
        in_source = str(field_sources.get(field) or source or "").strip()
        in_priority = SOURCE_PRIORITY.get(in_source, SOURCE_PRIORITY.get(source, 0))
        current = _clean(data.get(field))
        meta = sources.get(field) if isinstance(sources.get(field), dict) else {}
        cur_source = str(meta.get("source") or "")
        cur_priority = SOURCE_PRIORITY.get(cur_source, 0)
        if not current:
            data[field] = value
            sources[field] = {"source": in_source, "confirmed": in_priority >= 350, "updated_at": now}
            continue
        if _same(current, value):
            if in_priority > cur_priority:
                sources[field] = {"source": in_source, "confirmed": in_priority >= 350, "updated_at": now}
            continue
        if in_source == "manual_confirmado":
            data[field] = value
            sources[field] = {"source": in_source, "confirmed": True, "updated_at": now}
            continue
        if cur_source == "manual_confirmado":
            continue
        # Dos fuentes fuertes contradictorias no se resuelven silenciosamente.
        if in_priority >= 350 and cur_priority >= 350:
            conflicts.append({"campo": field, "guardado": current, "entrante": value, "fuente_guardada": cur_source, "fuente_entrante": in_source})
            continue
        if in_priority > cur_priority or (in_priority == cur_priority and in_source == cur_source == "calculado"):
            data[field] = value
            sources[field] = {"source": in_source, "confirmed": in_priority >= 350, "updated_at": now}
    return data, sources, conflicts


def upsert(campos: dict | None, *, fuente: str, usuario: str = "", fuentes_por_campo: dict | None = None) -> dict:
    incoming = canonicalizar(campos)
    if not any(incoming.values()):
        return {"ok": False, "error": "No hay datos útiles para guardar en la ficha."}
    existing = _listar_raw()
    row = _candidate(existing, incoming)
    data, sources, conflicts = _merge(row or {}, incoming, fuente, fuentes_por_campo)
    clave = _record_key(data)
    asegurado = data.get("NOMBRE", "")
    patente = data.get("PATENTE", "")
    poliza = data.get("POLIZA", "")
    compania = data.get("COMPANIA", "")
    payload_data = json.dumps(data, ensure_ascii=False)
    payload_sources = json.dumps(sources, ensure_ascii=False)

    if _usar_postgres():
        with closing(_pg_connect()) as db:
            from psycopg2.extras import RealDictCursor
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                if row:
                    cur.execute("""
                        UPDATE fichas_asegurados SET clave=%s, asegurado=%s, patente=%s, poliza=%s, compania=%s,
                        datos=%s::jsonb, fuentes=%s::jsonb, actualizado_en=CURRENT_TIMESTAMP, actualizado_por=%s
                        WHERE id=%s RETURNING *
                    """, (clave, asegurado, patente, poliza, compania, payload_data, payload_sources, usuario, row["id"]))
                else:
                    cur.execute("""
                        INSERT INTO fichas_asegurados (clave,asegurado,patente,poliza,compania,datos,fuentes,actualizado_por)
                        VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s) RETURNING *
                    """, (clave, asegurado, patente, poliza, compania, payload_data, payload_sources, usuario))
                saved = _rowdict(cur.fetchone())
            db.commit()
    else:
        with closing(_sqlite_connect()) as db:
            if row:
                db.execute("""
                    UPDATE fichas_asegurados SET clave=?, asegurado=?, patente=?, poliza=?, compania=?, datos=?, fuentes=?,
                    actualizado_en=CURRENT_TIMESTAMP, actualizado_por=? WHERE id=?
                """, (clave, asegurado, patente, poliza, compania, payload_data, payload_sources, usuario, row["id"]))
                saved = dict(db.execute("SELECT * FROM fichas_asegurados WHERE id=?", (row["id"],)).fetchone())
            else:
                cur = db.execute("""
                    INSERT INTO fichas_asegurados (clave,asegurado,patente,poliza,compania,datos,fuentes,actualizado_por)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (clave, asegurado, patente, poliza, compania, payload_data, payload_sources, usuario))
                saved = dict(db.execute("SELECT * FROM fichas_asegurados WHERE id=?", (cur.lastrowid,)).fetchone())
            db.commit()
    saved["datos"] = _loads(saved.get("datos"))
    saved["fuentes"] = _loads(saved.get("fuentes"))
    return {"ok": True, "ficha": saved, "conflictos": conflicts}


def buscar(query: str) -> list[dict]:
    qn, qc = _norm(query), _keynorm(query)
    if not qn:
        return []
    out = []
    for row in _listar_raw():
        data = row.get("datos") or {}
        values = [data.get(k, "") for k in ("NOMBRE", "TELEFONO", "DNI", "CUIT", "PATENTE", "POLIZA")]
        matched = any(qn == _norm(v) or (qc and qc == _keynorm(v)) for v in values if v)
        if not matched:
            name = _norm(data.get("NOMBRE"))
            tokens = [t for t in qn.split() if len(t) >= 2]
            matched = bool(name and len(tokens) >= 2 and all(t in name.split() for t in tokens))
        if matched:
            out.append(row)
    return out


def registrar_evento(ficha_id: int | None, tipo: str, detalle: dict | None = None, *, usuario: str = ""):
    tipo = _clean(tipo, 80)
    if not tipo:
        return
    payload = json.dumps(detalle or {}, ensure_ascii=False)
    if _usar_postgres():
        with closing(_pg_connect()) as db:
            with db.cursor() as cur:
                cur.execute("INSERT INTO eventos_fichas (ficha_id,tipo,detalle,usuario) VALUES (%s,%s,%s::jsonb,%s)", (ficha_id, tipo, payload, usuario))
            db.commit()
    else:
        with closing(_sqlite_connect()) as db:
            db.execute("INSERT INTO eventos_fichas (ficha_id,tipo,detalle,usuario) VALUES (?,?,?,?)", (ficha_id, tipo, payload, usuario))
            db.commit()


def eventos(ficha_id: int, limite: int = 50) -> list[dict]:
    limite = max(1, min(int(limite or 50), 200))
    if _usar_postgres():
        with closing(_pg_connect()) as db:
            from psycopg2.extras import RealDictCursor
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM eventos_fichas WHERE ficha_id=%s ORDER BY creado_en DESC, id DESC LIMIT %s", (ficha_id, limite))
                rows = cur.fetchall()
    else:
        with closing(_sqlite_connect()) as db:
            rows = db.execute("SELECT * FROM eventos_fichas WHERE ficha_id=? ORDER BY creado_en DESC, id DESC LIMIT ?", (ficha_id, limite)).fetchall()
    out=[]
    for raw in rows:
        row=_rowdict(raw); row["detalle"]=_loads(row.get("detalle")); out.append(row)
    return out


__all__ = ["canonicalizar", "upsert", "buscar", "registrar_evento", "eventos", "SOURCE_PRIORITY"]
