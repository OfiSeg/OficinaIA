"""Registro liviano de fallos operativos de OficinaIA.

Nunca propaga excepciones: el panel de salud no puede convertirse en otra
fuente de errores para el usuario final.
"""
from __future__ import annotations

import os
from contextlib import closing
from datetime import datetime, timedelta


def _usar_pg() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def registrar_evento(categoria: str, nivel: str, mensaje: str, detalle: str | None = None) -> None:
    categoria = str(categoria or "general")[:40]
    nivel = str(nivel or "aviso")[:20]
    mensaje = str(mensaje or "")[:1000]
    detalle = None if detalle is None else str(detalle)[:12000]
    try:
        if _usar_pg():
            from database_pg import conectar_pg
            with closing(conectar_pg()) as db:
                with db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO eventos_sistema (categoria,nivel,mensaje,detalle_tecnico) VALUES (%s,%s,%s,%s)",
                        (categoria, nivel, mensaje, detalle),
                    )
                db.commit()
        else:
            from local_db import conectar_db
            with closing(conectar_db()) as db:
                db.execute(
                    "INSERT INTO eventos_sistema (categoria,nivel,mensaje,detalle_tecnico) VALUES (?,?,?,?)",
                    (categoria, nivel, mensaje, detalle),
                )
                db.commit()
    except Exception as exc:
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
            sql = "SELECT id,timestamp,categoria,nivel,mensaje,detalle_tecnico FROM eventos_sistema WHERE " + " AND ".join(condiciones) + " ORDER BY timestamp DESC LIMIT 1000"
            with closing(conectar_pg()) as db:
                with db.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
            return [dict(r, timestamp=r["timestamp"].isoformat() if r.get("timestamp") else "") for r in rows]

        from local_db import conectar_db
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        condiciones = ["timestamp >= ?"]
        params = [desde]
        if categoria:
            condiciones.append("categoria = ?"); params.append(categoria)
        if nivel:
            condiciones.append("nivel = ?"); params.append(nivel)
        sql = "SELECT id,timestamp,categoria,nivel,mensaje,detalle_tecnico FROM eventos_sistema WHERE " + " AND ".join(condiciones) + " ORDER BY timestamp DESC LIMIT 1000"
        with closing(conectar_db()) as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        print("AVISO: no se pudieron listar eventos de salud:", exc)
        return []


def limpiar_eventos_antiguos(dias: int = 30) -> int:
    try:
        dias = max(1, int(dias or 30))
        if _usar_pg():
            from database_pg import conectar_pg
            with closing(conectar_pg()) as db:
                with db.cursor() as cur:
                    cur.execute("DELETE FROM eventos_sistema WHERE timestamp < NOW() - (%s * INTERVAL '1 day')", (dias,))
                    n = cur.rowcount
                db.commit()
                return int(n or 0)
        from local_db import conectar_db
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        with closing(conectar_db()) as db:
            cur = db.execute("DELETE FROM eventos_sistema WHERE timestamp < ?", (desde,))
            db.commit()
            return int(cur.rowcount or 0)
    except Exception as exc:
        print("AVISO: no se pudieron limpiar eventos de salud:", exc)
        return 0
