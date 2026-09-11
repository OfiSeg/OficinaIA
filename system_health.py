"""Registro liviano de fallos operativos de OficinaIA.

Nunca propaga excepciones: el panel de salud no puede convertirse en otra
fuente de errores. Conserva la causa raíz mediante un código opcional y evita
registrar secretos conocidos.
"""
from __future__ import annotations

import re
from contextlib import closing
from datetime import datetime, timedelta

import runtime_config

_SECRET_PATTERNS = (
    re.compile(r'(?i)(api[_ -]?key|client[_ -]?secret|refresh[_ -]?token|password|private[_ -]?key)\s*[:=]\s*[^\s,;]+'),
    re.compile(r'(?i)postgres(?:ql)?://[^\s]+'),
)


def _usar_pg() -> bool:
    return bool(runtime_config.get_text("DATABASE_URL"))


def _safe_detail(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)[:12000]
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(0).split(':', 1)[0].split('=', 1)[0] + '=[OCULTO]', text)
    return text


def _ensure_sqlite_schema(db) -> None:
    """Crea/migra la tabla de Salud si todavía no existe en SQLite local.

    Algunos módulos pueden registrar eventos antes de que `app.py` haya ejecutado
    `inicializar_base_datos()`. En una instalación local recién descomprimida eso
    producía warnings tipo `no such table: eventos_sistema` y el primer evento se
    perdía. El panel de Salud debe ser tolerante al orden de arranque.
    """
    db.execute("""CREATE TABLE IF NOT EXISTS eventos_sistema (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        categoria TEXT NOT NULL,
        nivel TEXT NOT NULL,
        mensaje TEXT NOT NULL,
        detalle_tecnico TEXT
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_eventos_sistema_fecha ON eventos_sistema(timestamp DESC)")
    cols = {fila[1] for fila in db.execute("PRAGMA table_info(eventos_sistema)").fetchall()}
    if "codigo" not in cols:
        db.execute("ALTER TABLE eventos_sistema ADD COLUMN codigo TEXT")


def _ensure_pg_schema(db) -> None:
    """Crea/migra la tabla mínima de Salud si el registrador corre temprano en PG."""
    with db.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS eventos_sistema (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            categoria TEXT NOT NULL,
            nivel TEXT NOT NULL,
            mensaje TEXT NOT NULL,
            detalle_tecnico TEXT,
            codigo VARCHAR(80)
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_eventos_sistema_fecha ON eventos_sistema (timestamp DESC)")
        cur.execute("ALTER TABLE eventos_sistema ADD COLUMN IF NOT EXISTS codigo VARCHAR(80)")


def _visible_message(value: str | None) -> str:
    """Normaliza textos históricos antes de mostrarlos en Salud.

    No modifica la base ni oculta la causa técnica; sólo evita que entradas
    antiguas sigan mostrando un nombre propio del asistente en la UI.
    """
    text = str(value or "")
    replacements = {
        "Sofia no pudo responder": "No se pudo responder",
        "Sofía no pudo responder": "No se pudo responder",
        "Sofia no pudo leer Google Sheets": "No se pudo leer Google Sheets",
        "Sofía no pudo leer Google Sheets": "No se pudo leer Google Sheets",
        "SOFIA no pudo responder": "No se pudo responder",
        "SOFIA no pudo leer Google Sheets": "No se pudo leer Google Sheets",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _normalizar_eventos_visibles(rows: list[dict]) -> list[dict]:
    salida = []
    for row in rows or []:
        data = dict(row)
        data["mensaje"] = _visible_message(data.get("mensaje"))
        salida.append(data)
    return salida

def registrar_evento(
    categoria: str,
    nivel: str,
    mensaje: str,
    detalle: str | None = None,
    codigo: str | None = None,
) -> None:
    categoria = str(categoria or "general")[:40]
    nivel = str(nivel or "aviso")[:20]
    mensaje = str(mensaje or "")[:1000]
    detalle = _safe_detail(detalle)
    codigo = str(codigo or "")[:80] or None
    try:
        if _usar_pg():
            from database_pg import conectar_pg
            with closing(conectar_pg()) as db:
                _ensure_pg_schema(db)
                with db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO eventos_sistema (categoria,nivel,mensaje,detalle_tecnico,codigo) VALUES (%s,%s,%s,%s,%s)",
                        (categoria, nivel, mensaje, detalle, codigo),
                    )
                db.commit()
        else:
            from local_db import conectar_db
            with closing(conectar_db()) as db:
                _ensure_sqlite_schema(db)
                db.execute(
                    "INSERT INTO eventos_sistema (categoria,nivel,mensaje,detalle_tecnico,codigo) VALUES (?,?,?,?,?)",
                    (categoria, nivel, mensaje, detalle, codigo),
                )
                db.commit()
    except Exception as exc:
        # Compatibilidad con bases todavía no migradas: el logging nunca debe
        # romper la operación principal.
        try:
            if _usar_pg():
                from database_pg import conectar_pg
                with closing(conectar_pg()) as db:
                    _ensure_pg_schema(db)
                    with db.cursor() as cur:
                        cur.execute(
                            "INSERT INTO eventos_sistema (categoria,nivel,mensaje,detalle_tecnico) VALUES (%s,%s,%s,%s)",
                            (categoria, nivel, mensaje, detalle),
                        )
                    db.commit()
            else:
                from local_db import conectar_db
                with closing(conectar_db()) as db:
                    _ensure_sqlite_schema(db)
                    db.execute(
                        "INSERT INTO eventos_sistema (categoria,nivel,mensaje,detalle_tecnico) VALUES (?,?,?,?)",
                        (categoria, nivel, mensaje, detalle),
                    )
                    db.commit()
        except Exception:
            print("AVISO: no se pudo registrar evento de salud:", exc)


def listar_eventos(categoria: str | None = None, nivel: str | None = None, dias: int = 7) -> list[dict]:
    try:
        dias = max(1, min(int(dias or 7), 365))
        if _usar_pg():
            from database_pg import conectar_pg
            from psycopg2.extras import RealDictCursor
            condiciones = ["timestamp >= NOW() - (%s * INTERVAL '1 day')"]
            params: list[object] = [dias]
            if categoria:
                condiciones.append("categoria = %s"); params.append(categoria)
            if nivel:
                condiciones.append("nivel = %s"); params.append(nivel)
            sql = "SELECT id,timestamp,categoria,nivel,mensaje,detalle_tecnico,codigo FROM eventos_sistema WHERE " + " AND ".join(condiciones) + " ORDER BY timestamp DESC LIMIT 1000"
            with closing(conectar_pg()) as db:
                _ensure_pg_schema(db)
                with db.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
            return _normalizar_eventos_visibles([dict(r, timestamp=r["timestamp"].isoformat() if r.get("timestamp") else "") for r in rows])

        from local_db import conectar_db
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        condiciones = ["timestamp >= ?"]
        params = [desde]
        if categoria:
            condiciones.append("categoria = ?"); params.append(categoria)
        if nivel:
            condiciones.append("nivel = ?"); params.append(nivel)
        sql = "SELECT id,timestamp,categoria,nivel,mensaje,detalle_tecnico,codigo FROM eventos_sistema WHERE " + " AND ".join(condiciones) + " ORDER BY timestamp DESC LIMIT 1000"
        with closing(conectar_db()) as db:
            _ensure_sqlite_schema(db)
            rows = db.execute(sql, params).fetchall()
        return _normalizar_eventos_visibles([dict(r) for r in rows])
    except Exception as exc:
        # Base antigua sin columna codigo: lectura compatible hasta que termine
        # la migración del próximo arranque.
        try:
            if _usar_pg():
                from database_pg import conectar_pg
                from psycopg2.extras import RealDictCursor
                condiciones = ["timestamp >= NOW() - (%s * INTERVAL '1 day')"]
                params = [max(1, min(int(dias or 7), 365))]
                if categoria: condiciones.append("categoria = %s"); params.append(categoria)
                if nivel: condiciones.append("nivel = %s"); params.append(nivel)
                sql = "SELECT id,timestamp,categoria,nivel,mensaje,detalle_tecnico FROM eventos_sistema WHERE " + " AND ".join(condiciones) + " ORDER BY timestamp DESC LIMIT 1000"
                with closing(conectar_pg()) as db:
                    _ensure_pg_schema(db)
                    with db.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute(sql, params); rows = cur.fetchall()
                return _normalizar_eventos_visibles([dict(r, codigo=None, timestamp=r["timestamp"].isoformat() if r.get("timestamp") else "") for r in rows])
            from local_db import conectar_db
            desde = (datetime.now() - timedelta(days=max(1, min(int(dias or 7), 365)))).strftime("%Y-%m-%d %H:%M:%S")
            condiciones = ["timestamp >= ?"]; params = [desde]
            if categoria: condiciones.append("categoria = ?"); params.append(categoria)
            if nivel: condiciones.append("nivel = ?"); params.append(nivel)
            sql = "SELECT id,timestamp,categoria,nivel,mensaje,detalle_tecnico FROM eventos_sistema WHERE " + " AND ".join(condiciones) + " ORDER BY timestamp DESC LIMIT 1000"
            with closing(conectar_db()) as db:
                _ensure_sqlite_schema(db)
                rows = db.execute(sql, params).fetchall()
            return _normalizar_eventos_visibles([dict(dict(r), codigo=None) for r in rows])
        except Exception:
            print("AVISO: no se pudieron listar eventos de salud:", exc)
            return []


def limpiar_eventos_antiguos(dias: int = 30) -> int:
    try:
        dias = max(1, int(dias or 30))
        if _usar_pg():
            from database_pg import conectar_pg
            with closing(conectar_pg()) as db:
                _ensure_pg_schema(db)
                with db.cursor() as cur:
                    cur.execute("DELETE FROM eventos_sistema WHERE timestamp < NOW() - (%s * INTERVAL '1 day')", (dias,))
                    n = cur.rowcount
                db.commit()
                return int(n or 0)
        from local_db import conectar_db
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        with closing(conectar_db()) as db:
            _ensure_sqlite_schema(db)
            cur = db.execute("DELETE FROM eventos_sistema WHERE timestamp < ?", (desde,))
            db.commit()
            return int(cur.rowcount or 0)
    except Exception as exc:
        print("AVISO: no se pudieron limpiar eventos de salud:", exc)
        return 0
