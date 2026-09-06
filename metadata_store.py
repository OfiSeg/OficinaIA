import os
from contextlib import closing

from database_pg import (
    listar_metadatos as pg_listar_metadatos,
    obtener_metadato as pg_obtener_metadato,
    crear_metadato as pg_crear_metadato,
    actualizar_metadato as pg_actualizar_metadato,
    eliminar_metadato as pg_eliminar_metadato,
)
from local_db import conectar_db


def usar_postgres():
    """True cuando la instalación está configurada para Neon/PostgreSQL."""
    return bool(os.getenv("DATABASE_URL"))


def cargar_metadatos():
    """
    Carga completa para retrieval de Sofia.

    Conserva el comportamiento histórico: intenta Neon primero y, si no está
    disponible, usa SQLite local como fallback de lectura. Esta función no es
    la usada por los CRUD HTTP, donde un error de PostgreSQL debe seguir
    propagándose en producción en vez de escribir accidentalmente en SQLite.
    """
    try:
        filas = pg_listar_metadatos()
        if filas is not None:
            print("METADATOS PG:", len(filas), "fichas cargadas.")
            return filas
    except Exception as error:
        print("METADATOS PG no disponible, intento SQLite:", error)

    try:
        with closing(conectar_db()) as db:
            rows = db.execute(
                "SELECT id, titulo, contenido, actualizado_en FROM metadatos "
                "ORDER BY actualizado_en DESC, id DESC"
            ).fetchall()
            filas = [dict(row) for row in rows]
            print("METADATOS SQLite:", len(filas), "fichas cargadas.")
            return filas
    except Exception as error:
        print("ERROR CARGANDO METADATOS (SQLite):", error)
        return []


def listar_metadatos():
    """Lista fichas para la UI. Los errores PG se propagan en producción."""
    if usar_postgres():
        return pg_listar_metadatos()

    with closing(conectar_db()) as db:
        rows = db.execute(
            "SELECT id, usuario, titulo, contenido, creado_en, actualizado_en "
            "FROM metadatos ORDER BY actualizado_en DESC, id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def obtener_metadato(metadato_id):
    if usar_postgres():
        return pg_obtener_metadato(metadato_id)

    with closing(conectar_db()) as db:
        row = db.execute(
            "SELECT id, titulo, contenido, creado_en, actualizado_en, usuario "
            "FROM metadatos WHERE id=?",
            (metadato_id,),
        ).fetchone()
        return dict(row) if row else None


def crear_metadato(usuario, titulo, contenido):
    if usar_postgres():
        return pg_crear_metadato(usuario, titulo, contenido)

    with closing(conectar_db()) as db:
        cur = db.execute(
            "INSERT INTO metadatos (usuario,titulo,contenido) VALUES (?,?,?)",
            (usuario, titulo, contenido),
        )
        db.commit()
        row = db.execute(
            "SELECT id,titulo,contenido,creado_en,actualizado_en,usuario "
            "FROM metadatos WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)


def actualizar_metadato(metadato_id, titulo, contenido):
    if usar_postgres():
        return pg_actualizar_metadato(metadato_id, titulo, contenido)

    with closing(conectar_db()) as db:
        row = db.execute(
            "SELECT id FROM metadatos WHERE id=?", (metadato_id,)
        ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE metadatos SET titulo=?, contenido=?, "
            "actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
            (titulo, contenido, metadato_id),
        )
        db.commit()
        row = db.execute(
            "SELECT id,titulo,contenido,creado_en,actualizado_en,usuario "
            "FROM metadatos WHERE id=?",
            (metadato_id,),
        ).fetchone()
        return dict(row)


def eliminar_metadato(metadato_id):
    if usar_postgres():
        return pg_eliminar_metadato(metadato_id)

    with closing(conectar_db()) as db:
        row = db.execute(
            "SELECT id FROM metadatos WHERE id=?", (metadato_id,)
        ).fetchone()
        if not row:
            return False
        db.execute("DELETE FROM metadatos WHERE id=?", (metadato_id,))
        db.commit()
        return True
