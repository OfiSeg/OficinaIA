# -*- coding: utf-8 -*-
"""Bandeja de pendientes de OficinaIA (propuestas, fichas, tareas)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

TIPOS_VALIDOS = {"excel", "metadato", "flota", "coti", "whatsapp", "generico", "pdf_ficha"}
ESTADOS_VALIDOS = {"pendiente", "hecho", "descartado"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def asegurar_tabla(db: sqlite3.Connection):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS pendientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL,
            tipo TEXT NOT NULL,
            titulo TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            estado TEXT NOT NULL DEFAULT 'pendiente',
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_pendientes_usuario_estado ON pendientes(usuario, estado)"
    )


def listar(db: sqlite3.Connection, usuario: str, estado: str = "pendiente", limite: int = 100):
    rows = db.execute(
        """
        SELECT id, tipo, titulo, payload, estado, creado_en, actualizado_en
        FROM pendientes
        WHERE usuario=? AND estado=?
        ORDER BY actualizado_en DESC, id DESC
        LIMIT ?
        """,
        (usuario, estado, limite),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["payload"] = json.loads(item.get("payload") or "{}")
        except Exception:
            item["payload"] = {}
        out.append(item)
    return out


def contar(db: sqlite3.Connection, usuario: str, estado: str = "pendiente") -> int:
    row = db.execute(
        "SELECT COUNT(*) AS c FROM pendientes WHERE usuario=? AND estado=?",
        (usuario, estado),
    ).fetchone()
    return int(row["c"] if row else 0)


def crear(db: sqlite3.Connection, usuario: str, tipo: str, titulo: str, payload: dict | None = None):
    tipo = (tipo or "generico").strip().lower()
    if tipo not in TIPOS_VALIDOS:
        tipo = "generico"
    titulo = (titulo or "Pendiente").strip()[:200] or "Pendiente"
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    now = _now()
    cur = db.execute(
        """
        INSERT INTO pendientes (usuario, tipo, titulo, payload, estado, creado_en, actualizado_en)
        VALUES (?,?,?,?, 'pendiente', ?, ?)
        """,
        (usuario, tipo, titulo, payload_json, now, now),
    )
    db.commit()
    return cur.lastrowid


def actualizar_estado(db: sqlite3.Connection, pendiente_id: int, usuario: str, estado: str):
    if estado not in ESTADOS_VALIDOS:
        return False
    cur = db.execute(
        """
        UPDATE pendientes
        SET estado=?, actualizado_en=?
        WHERE id=? AND usuario=?
        """,
        (estado, _now(), pendiente_id, usuario),
    )
    db.commit()
    return cur.rowcount > 0


def obtener(db: sqlite3.Connection, pendiente_id: int, usuario: str):
    row = db.execute(
        "SELECT id, tipo, titulo, payload, estado, creado_en, actualizado_en FROM pendientes WHERE id=? AND usuario=?",
        (pendiente_id, usuario),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["payload"] = json.loads(item.get("payload") or "{}")
    except Exception:
        item["payload"] = {}
    return item


def eliminar(db: sqlite3.Connection, pendiente_id: int, usuario: str):
    cur = db.execute("DELETE FROM pendientes WHERE id=? AND usuario=?", (pendiente_id, usuario))
    db.commit()
    return cur.rowcount > 0
