"""Padrón ARCA interno para resolver CUIT/CUIL y buscar personas reales.

La búsqueda es determinística: Gemini puede detectar intención y redactar,
pero los CUIT/personas salen únicamente de la base interna importada.
En producción reutiliza PostgreSQL/Neon. En desarrollo sin DATABASE_URL usa
SQLite local, siguiendo el patrón existente de OficinaIA.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import re
import sqlite3
import unicodedata
import zipfile
from typing import Iterable, Iterator, Any

import runtime_config
from local_db import conectar_db

try:  # psycopg2 existe en producción; evitamos romper tests que no lo carguen.
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
except Exception:  # pragma: no cover - sólo para entornos mínimos.
    psycopg2 = None
    RealDictCursor = None
    execute_values = None

PREFIJOS_PERSONA_HUMANA = {"20", "23", "24", "27"}
BATCH_SIZE = 5000
SQLITE_FTS_TABLE = "padron_arca_personas_fts"


@dataclass(frozen=True)
class PadronRow:
    cuit: str
    dni: str
    nombre: str
    nombre_normalizado: str
    fecha_padron: str = ""


def _usar_pg() -> bool:
    return bool(runtime_config.get_text("DATABASE_URL"))


def _conectar_pg():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 no está disponible para conectar PostgreSQL.")
    from database_pg import conectar_pg
    return conectar_pg()


def _norm_ascii(texto: Any) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    valor = "".join(c for c in valor if not unicodedata.combining(c))
    valor = valor.upper()
    valor = re.sub(r"[^A-Z0-9Ñ ]+", " ", valor)
    valor = re.sub(r"\s+", " ", valor).strip()
    return valor


def normalizar_nombre_arca(nombre: Any) -> str:
    return _norm_ascii(nombre)


def normalizar_dni(dni: Any) -> str:
    texto = str(dni or "").strip()
    texto = re.sub(r"(?i)\b(?:dni|documento|nro|nº|numero|número)\b", "", texto)
    digitos = re.sub(r"\D+", "", texto)
    # Un CUIT/CUIL completo no es DNI. Si llega acá por error, tomar bloque DNI
    # sólo cuando el prefijo corresponde a persona humana.
    if len(digitos) == 11 and digitos[:2] in PREFIJOS_PERSONA_HUMANA:
        return digitos[2:10].lstrip("0") or "0"
    return digitos.lstrip("0") or ("0" if digitos else "")


def dni_indexado(dni: Any) -> str:
    limpio = normalizar_dni(dni)
    if not limpio or not limpio.isdigit():
        return ""
    if len(limpio) > 8:
        return ""
    return limpio.zfill(8)


def formatear_dni(dni: Any) -> str:
    limpio = normalizar_dni(dni)
    if not limpio or not limpio.isdigit():
        return str(dni or "").strip()
    grupos = []
    while limpio:
        grupos.append(limpio[-3:])
        limpio = limpio[:-3]
    return ".".join(reversed(grupos))


def normalizar_cuit(cuit: Any) -> str:
    digitos = re.sub(r"\D+", "", str(cuit or ""))
    return digitos if len(digitos) == 11 and digitos.isdigit() else ""


def formatear_cuit(cuit: Any) -> str:
    c = normalizar_cuit(cuit)
    return f"{c[:2]}-{c[2:10]}-{c[10]}" if c else str(cuit or "").strip()


def es_cuit_persona_humana(cuit: Any) -> bool:
    c = normalizar_cuit(cuit)
    return bool(c and c[:2] in PREFIJOS_PERSONA_HUMANA)


def _fecha_padron_desde_nombre(nombre: str) -> str:
    m = re.search(r"(20\d{6})", str(nombre or ""))
    if not m:
        return ""
    raw = m.group(1)
    try:
        return datetime.strptime(raw, "%Y%m%d").strftime("%d/%m/%Y")
    except ValueError:
        return raw


def _parsear_linea_padron(linea: str, fecha_padron: str = "") -> PadronRow | None:
    if not linea:
        return None
    cuit = normalizar_cuit(linea[:11])
    if not cuit or not es_cuit_persona_humana(cuit):
        return None
    nombre = str(linea[11:41] or "").strip()
    if not nombre:
        return None
    nombre_norm = normalizar_nombre_arca(nombre)
    if not nombre_norm:
        return None
    return PadronRow(cuit=cuit, dni=cuit[2:10], nombre=nombre, nombre_normalizado=nombre_norm, fecha_padron=fecha_padron)


def _buscar_archivo_datos_zip(zf: zipfile.ZipFile) -> zipfile.ZipInfo:
    candidatos = [i for i in zf.infolist() if not i.is_dir() and i.file_size > 0]
    if not candidatos:
        raise ValueError("El ZIP no contiene un archivo de datos utilizable.")
    # El padrón real trae un único .tmp grande; priorizamos el mayor archivo.
    candidatos.sort(key=lambda i: i.file_size, reverse=True)
    return candidatos[0]


def _iterar_padron_zip(path_zip: str | Path) -> tuple[str, Iterator[PadronRow | None], str]:
    path = Path(path_zip)
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo: {path}")
    if not zipfile.is_zipfile(path):
        raise ValueError("El archivo indicado no es un ZIP válido.")

    zf = zipfile.ZipFile(path, "r")
    info = _buscar_archivo_datos_zip(zf)
    fecha_padron = _fecha_padron_desde_nombre(info.filename) or _fecha_padron_desde_nombre(path.name)

    def _gen() -> Iterator[PadronRow]:
        with zf:
            with zf.open(info, "r") as fh:
                for raw in fh:
                    try:
                        linea = raw.decode("latin-1", errors="ignore").rstrip("\r\n")
                    except Exception:
                        continue
                    yield _parsear_linea_padron(linea, fecha_padron=fecha_padron)

    return info.filename, _gen(), fecha_padron


def _sqlite_asegurar_esquema(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS padron_arca_personas (
            cuit TEXT PRIMARY KEY,
            dni TEXT NOT NULL,
            nombre TEXT NOT NULL,
            nombre_normalizado TEXT NOT NULL,
            fecha_padron TEXT DEFAULT '',
            importado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_padron_arca_dni ON padron_arca_personas(dni)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_padron_arca_nombre_norm ON padron_arca_personas(nombre_normalizado)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS padron_arca_estado (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            registros INTEGER NOT NULL DEFAULT 0,
            fecha_padron TEXT DEFAULT '',
            archivo_origen TEXT DEFAULT '',
            actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {SQLITE_FTS_TABLE} USING fts5(cuit UNINDEXED, dni UNINDEXED, nombre, nombre_normalizado)")
    except sqlite3.OperationalError:
        # Algunas builds mínimas de SQLite no tienen FTS5. Las consultas siguen
        # funcionando con LIKE, pero la validación lo informa indirectamente.
        pass
    db.commit()


def _pg_asegurar_esquema(db) -> None:
    with db.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS padron_arca_personas (
                cuit TEXT PRIMARY KEY,
                dni TEXT NOT NULL,
                nombre TEXT NOT NULL,
                nombre_normalizado TEXT NOT NULL,
                fecha_padron TEXT DEFAULT '',
                importado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_padron_arca_dni ON padron_arca_personas(dni)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_padron_arca_nombre_norm ON padron_arca_personas(nombre_normalizado)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_padron_arca_nombre_fts ON padron_arca_personas USING GIN (to_tsvector('simple', nombre_normalizado))")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS padron_arca_estado (
                id INTEGER PRIMARY KEY DEFAULT 1,
                registros INTEGER NOT NULL DEFAULT 0,
                fecha_padron TEXT DEFAULT '',
                archivo_origen TEXT DEFAULT '',
                actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT padron_arca_estado_singleton CHECK (id = 1)
            )
        """)
    db.commit()


def asegurar_esquema() -> None:
    if _usar_pg():
        with _conectar_pg() as db:
            _pg_asegurar_esquema(db)
    else:
        with conectar_db() as db:
            _sqlite_asegurar_esquema(db)


def _row_dict(row: Any) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _sqlite_estado(db: sqlite3.Connection) -> dict:
    _sqlite_asegurar_esquema(db)
    row = db.execute("SELECT registros, fecha_padron, archivo_origen, actualizado_en FROM padron_arca_estado WHERE id = 1").fetchone()
    if not row:
        total = db.execute("SELECT COUNT(*) AS c FROM padron_arca_personas").fetchone()["c"]
        return {"cargado": total > 0, "registros": int(total or 0), "fecha_padron": "", "archivo_origen": "", "backend": "sqlite"}
    d = _row_dict(row)
    d["cargado"] = int(d.get("registros") or 0) > 0
    d["backend"] = "sqlite"
    return d


def _pg_estado(db) -> dict:
    _pg_asegurar_esquema(db)
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT registros, fecha_padron, archivo_origen, actualizado_en FROM padron_arca_estado WHERE id = 1")
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT COUNT(*) AS c FROM padron_arca_personas")
            total = cur.fetchone()["c"]
            return {"cargado": int(total or 0) > 0, "registros": int(total or 0), "fecha_padron": "", "archivo_origen": "", "backend": "postgres"}
        d = dict(row)
    d["cargado"] = int(d.get("registros") or 0) > 0
    d["backend"] = "postgres"
    return d


def estado_padron() -> dict:
    try:
        if _usar_pg():
            with _conectar_pg() as db:
                return _pg_estado(db)
        with conectar_db() as db:
            return _sqlite_estado(db)
    except Exception as exc:
        return {"cargado": False, "registros": 0, "error": str(exc), "backend": "postgres" if _usar_pg() else "sqlite"}


def padron_disponible() -> bool:
    return bool(estado_padron().get("cargado"))


def _candidato_publico(row: dict) -> dict:
    return {
        "cuit": normalizar_cuit(row.get("cuit")),
        "cuit_formateado": formatear_cuit(row.get("cuit")),
        "dni": normalizar_dni(row.get("dni")),
        "dni_mostrar": formatear_dni(row.get("dni")),
        "nombre": str(row.get("nombre") or "").strip(),
        "source": "ARCA",
    }


def _score_nombre(nombre_norm: str, consulta_norm: str) -> tuple[int, int, int]:
    tokens_q = [t for t in consulta_norm.split() if t]
    tokens_n = [t for t in nombre_norm.split() if t]
    if not tokens_q:
        return (0, 0, 0)
    exact_order = 1 if consulta_norm == nombre_norm else 0
    same_set = 1 if set(tokens_q) == set(tokens_n) else 0
    contained = sum(1 for t in tokens_q if t in tokens_n)
    partial = sum(1 for t in tokens_q if any(t in n or n in t for n in tokens_n))
    # Orden descendente: coincidencias exactas > mismas palabras > parciales.
    return (exact_order * 100 + same_set * 50 + contained * 10 + partial, -abs(len(tokens_n) - len(tokens_q)), -len(nombre_norm))


def _ordenar_candidatos(candidatos: list[dict], consulta_norm: str) -> list[dict]:
    return sorted(
        candidatos,
        key=lambda r: _score_nombre(normalizar_nombre_arca(r.get("nombre")), consulta_norm),
        reverse=True,
    )


def _resultado_padron_no_cargado() -> dict:
    estado = estado_padron()
    return {
        "status": "padron_not_loaded",
        "ok": False,
        "message": "El buscador ARCA está disponible, pero el padrón todavía no fue cargado/actualizado.",
        "estado_padron": estado,
    }


def resolver_cuit_por_dni(dni: Any, nombre: Any = None, limite: int = 10) -> dict:
    dni_busqueda = dni_indexado(dni)
    dni_humano = normalizar_dni(dni)
    if not dni_busqueda:
        return {"status": "invalid", "ok": False, "message": "El DNI indicado no es válido para buscar en ARCA."}
    estado = estado_padron()
    if not estado.get("cargado"):
        return _resultado_padron_no_cargado()

    candidatos: list[dict] = []
    if _usar_pg():
        with _conectar_pg() as db:
            _pg_asegurar_esquema(db)
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT cuit, dni, nombre, nombre_normalizado
                    FROM padron_arca_personas
                    WHERE dni = %s
                    ORDER BY cuit
                    LIMIT %s
                    """,
                    (dni_busqueda, max(int(limite or 10), 1)),
                )
                candidatos = [dict(r) for r in cur.fetchall()]
    else:
        with conectar_db() as db:
            _sqlite_asegurar_esquema(db)
            rows = db.execute(
                """
                SELECT cuit, dni, nombre, nombre_normalizado
                FROM padron_arca_personas
                WHERE dni = ?
                ORDER BY cuit
                LIMIT ?
                """,
                (dni_busqueda, max(int(limite or 10), 1)),
            ).fetchall()
            candidatos = [_row_dict(r) for r in rows]

    if not candidatos:
        return {"status": "not_found", "ok": True, "dni": dni_humano, "dni_mostrar": formatear_dni(dni_humano), "source": "ARCA"}

    nombre_norm = normalizar_nombre_arca(nombre)
    if nombre_norm:
        candidatos = _ordenar_candidatos(candidatos, nombre_norm)
        exactos = [c for c in candidatos if set(nombre_norm.split()).issubset(set(normalizar_nombre_arca(c.get("nombre")).split()))]
        if exactos:
            candidatos = exactos

    publicos = [_candidato_publico(c) for c in candidatos[: max(int(limite or 10), 1)]]
    if len(publicos) == 1:
        item = dict(publicos[0])
        item.update({"status": "found", "ok": True, "dni": dni_humano, "dni_mostrar": formatear_dni(dni_humano), "source": "ARCA"})
        return item
    return {
        "status": "multiple",
        "ok": True,
        "dni": dni_humano,
        "dni_mostrar": formatear_dni(dni_humano),
        "candidates": publicos,
        "source": "ARCA",
    }


def buscar_personas_arca(nombre: Any, limite: int = 10) -> dict:
    consulta_norm = normalizar_nombre_arca(nombre)
    if len(consulta_norm) < 3 or not re.search(r"[A-ZÑ]", consulta_norm):
        return {"status": "invalid", "ok": False, "message": "Indicá apellido y/o nombre para buscar en ARCA."}
    estado = estado_padron()
    if not estado.get("cargado"):
        return _resultado_padron_no_cargado()
    limite = max(1, min(int(limite or 10), 10))
    tokens = [t for t in consulta_norm.split() if len(t) >= 2]
    candidatos: list[dict] = []

    if _usar_pg():
        with _conectar_pg() as db:
            _pg_asegurar_esquema(db)
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                try:
                    cur.execute(
                        """
                        SELECT cuit, dni, nombre, nombre_normalizado,
                               ts_rank(to_tsvector('simple', nombre_normalizado), plainto_tsquery('simple', %s)) AS rank
                        FROM padron_arca_personas
                        WHERE to_tsvector('simple', nombre_normalizado) @@ plainto_tsquery('simple', %s)
                        ORDER BY rank DESC, nombre_normalizado ASC
                        LIMIT %s
                        """,
                        (consulta_norm, consulta_norm, limite * 6),
                    )
                    candidatos = [dict(r) for r in cur.fetchall()]
                except Exception:
                    db.rollback()
                    where = " AND ".join(["nombre_normalizado ILIKE %s" for _ in tokens])
                    cur.execute(
                        f"SELECT cuit, dni, nombre, nombre_normalizado FROM padron_arca_personas WHERE {where} ORDER BY nombre_normalizado ASC LIMIT %s",
                        tuple(f"%{t}%" for t in tokens) + (limite * 6,),
                    )
                    candidatos = [dict(r) for r in cur.fetchall()]
    else:
        with conectar_db() as db:
            _sqlite_asegurar_esquema(db)
            try:
                # FTS5: cada token debe estar presente; evita recorrer millones en Python.
                q = " ".join(tokens)
                rows = db.execute(
                    f"SELECT cuit, dni, nombre, nombre_normalizado FROM {SQLITE_FTS_TABLE} WHERE {SQLITE_FTS_TABLE} MATCH ? LIMIT ?",
                    (q, limite * 6),
                ).fetchall()
                candidatos = [_row_dict(r) for r in rows]
            except Exception:
                where = " AND ".join(["nombre_normalizado LIKE ?" for _ in tokens])
                rows = db.execute(
                    f"SELECT cuit, dni, nombre, nombre_normalizado FROM padron_arca_personas WHERE {where} ORDER BY nombre_normalizado ASC LIMIT ?",
                    tuple(f"%{t}%" for t in tokens) + (limite * 6,),
                ).fetchall()
                candidatos = [_row_dict(r) for r in rows]

    candidatos = _ordenar_candidatos(candidatos, consulta_norm)[:limite]
    publicos = [_candidato_publico(c) for c in candidatos]
    if not publicos:
        return {"status": "not_found", "ok": True, "query": str(nombre or "").strip(), "source": "ARCA"}
    return {
        "status": "multiple" if len(publicos) > 1 else "found",
        "ok": True,
        "query": str(nombre or "").strip(),
        "candidates": publicos,
        "source": "ARCA",
        "truncado": len(candidatos) >= limite,
        "limite": limite,
    }


def _sqlite_importar(path_zip: str | Path, *, batch_size: int = BATCH_SIZE) -> dict:
    archivo_interno, rows_iter, fecha_padron = _iterar_padron_zip(path_zip)
    procesados = importados = descartados = 0
    with conectar_db() as db:
        _sqlite_asegurar_esquema(db)
        db.execute("DROP TABLE IF EXISTS padron_arca_personas_staging")
        db.execute("""
            CREATE TABLE padron_arca_personas_staging (
                cuit TEXT PRIMARY KEY,
                dni TEXT NOT NULL,
                nombre TEXT NOT NULL,
                nombre_normalizado TEXT NOT NULL,
                fecha_padron TEXT DEFAULT '',
                importado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        batch = []
        for row in rows_iter:
            procesados += 1
            if row is None:
                descartados += 1
                continue
            batch.append((row.cuit, row.dni, row.nombre, row.nombre_normalizado, row.fecha_padron))
            if len(batch) >= batch_size:
                db.executemany("INSERT OR IGNORE INTO padron_arca_personas_staging (cuit, dni, nombre, nombre_normalizado, fecha_padron) VALUES (?, ?, ?, ?, ?)", batch)
                importados += db.total_changes - importados  # aproximado hasta validación final
                batch.clear()
                if procesados % 100000 == 0:
                    print(f"Procesados: {procesados:,}")
        if batch:
            db.executemany("INSERT OR IGNORE INTO padron_arca_personas_staging (cuit, dni, nombre, nombre_normalizado, fecha_padron) VALUES (?, ?, ?, ?, ?)", batch)
        total = db.execute("SELECT COUNT(*) AS c FROM padron_arca_personas_staging").fetchone()["c"]
        if int(total or 0) <= 0:
            raise RuntimeError("La importación no produjo registros utilizables; se conserva el padrón anterior.")
        db.execute("CREATE INDEX IF NOT EXISTS idx_padron_arca_stg_dni ON padron_arca_personas_staging(dni)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_padron_arca_stg_nombre_norm ON padron_arca_personas_staging(nombre_normalizado)")
        db.execute("DROP TABLE IF EXISTS padron_arca_personas_old")
        db.execute("ALTER TABLE padron_arca_personas RENAME TO padron_arca_personas_old")
        db.execute("ALTER TABLE padron_arca_personas_staging RENAME TO padron_arca_personas")
        db.execute("DROP TABLE IF EXISTS padron_arca_personas_old")
        try:
            db.execute(f"DROP TABLE IF EXISTS {SQLITE_FTS_TABLE}")
            db.execute(f"CREATE VIRTUAL TABLE {SQLITE_FTS_TABLE} USING fts5(cuit UNINDEXED, dni UNINDEXED, nombre, nombre_normalizado)")
            db.execute(f"INSERT INTO {SQLITE_FTS_TABLE} (cuit, dni, nombre, nombre_normalizado) SELECT cuit, dni, nombre, nombre_normalizado FROM padron_arca_personas")
        except sqlite3.OperationalError as exc:
            print("AVISO: SQLite FTS5 no disponible; la búsqueda por nombre usará LIKE.", exc)
        db.execute("DELETE FROM padron_arca_estado")
        db.execute("INSERT INTO padron_arca_estado (id, registros, fecha_padron, archivo_origen, actualizado_en) VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)", (int(total), fecha_padron, archivo_interno))
        db.commit()
    return {"ok": True, "backend": "sqlite", "procesados": procesados, "importados": int(total), "descartados": max(descartados, procesados - int(total)), "fecha_padron": fecha_padron, "archivo_origen": archivo_interno}


def _pg_importar(path_zip: str | Path, *, batch_size: int = BATCH_SIZE) -> dict:
    archivo_interno, rows_iter, fecha_padron = _iterar_padron_zip(path_zip)
    procesados = 0
    descartados = 0
    with _conectar_pg() as db:
        _pg_asegurar_esquema(db)
        with db.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS padron_arca_personas_staging")
            cur.execute("""
                CREATE TABLE padron_arca_personas_staging (
                    cuit TEXT PRIMARY KEY,
                    dni TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    nombre_normalizado TEXT NOT NULL,
                    fecha_padron TEXT DEFAULT '',
                    importado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            batch = []
            for row in rows_iter:
                procesados += 1
                if row is None:
                    descartados += 1
                    continue
                batch.append((row.cuit, row.dni, row.nombre, row.nombre_normalizado, row.fecha_padron))
                if len(batch) >= batch_size:
                    execute_values(cur, "INSERT INTO padron_arca_personas_staging (cuit, dni, nombre, nombre_normalizado, fecha_padron) VALUES %s ON CONFLICT (cuit) DO NOTHING", batch)
                    batch.clear()
                    if procesados % 100000 == 0:
                        print(f"Procesados: {procesados:,}")
            if batch:
                execute_values(cur, "INSERT INTO padron_arca_personas_staging (cuit, dni, nombre, nombre_normalizado, fecha_padron) VALUES %s ON CONFLICT (cuit) DO NOTHING", batch)
            cur.execute("SELECT COUNT(*) FROM padron_arca_personas_staging")
            total = int(cur.fetchone()[0] or 0)
            if total <= 0:
                raise RuntimeError("La importación no produjo registros utilizables; se conserva el padrón anterior.")
            cur.execute("CREATE INDEX idx_padron_arca_stg_dni ON padron_arca_personas_staging(dni)")
            cur.execute("CREATE INDEX idx_padron_arca_stg_nombre_norm ON padron_arca_personas_staging(nombre_normalizado)")
            cur.execute("CREATE INDEX idx_padron_arca_stg_nombre_fts ON padron_arca_personas_staging USING GIN (to_tsvector('simple', nombre_normalizado))")
            cur.execute("DROP TABLE IF EXISTS padron_arca_personas_old")
            cur.execute("ALTER TABLE padron_arca_personas RENAME TO padron_arca_personas_old")
            cur.execute("ALTER TABLE padron_arca_personas_staging RENAME TO padron_arca_personas")
            cur.execute("DROP TABLE IF EXISTS padron_arca_personas_old")
            cur.execute("DELETE FROM padron_arca_estado")
            cur.execute(
                "INSERT INTO padron_arca_estado (id, registros, fecha_padron, archivo_origen, actualizado_en) VALUES (1, %s, %s, %s, CURRENT_TIMESTAMP)",
                (total, fecha_padron, archivo_interno),
            )
        db.commit()
    return {"ok": True, "backend": "postgres", "procesados": procesados, "importados": total, "descartados": max(descartados, procesados - total), "fecha_padron": fecha_padron, "archivo_origen": archivo_interno}


def importar_padron_arca(path_zip: str | Path, *, batch_size: int = BATCH_SIZE) -> dict:
    if _usar_pg():
        return _pg_importar(path_zip, batch_size=batch_size)
    return _sqlite_importar(path_zip, batch_size=batch_size)
