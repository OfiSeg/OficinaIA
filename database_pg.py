"""
Persistencia PostgreSQL para los metadatos de los manuales.

La base de datos principal de OficinaIA (SQLite) se conserva para usuarios,
chats y configuración. Neon PostgreSQL se utiliza exclusivamente para
los manuales.
"""
from __future__ import annotations

import os
from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS manuales (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL,
    r2_key VARCHAR(500) NOT NULL UNIQUE,
    tamaño BIGINT,
    fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _database_url():
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError(
            "Falta la variable de entorno DATABASE_URL de Neon PostgreSQL."
        )
    return value


def conectar_pg():
    return psycopg2.connect(_database_url())


def inicializar_postgres():
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(CREATE_TABLE_SQL)
        db.commit()


def listar_manuales():
    """
    Devuelve los manuales ordenados por fecha descendente.
    Las filas se convierten a dict para no acoplar la app a objetos psycopg2.
    """
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, nombre, r2_key, tamaño, fecha_subida
                FROM manuales
                ORDER BY fecha_subida DESC, id DESC
                """
            )
            return [dict(fila) for fila in cursor.fetchall()]


def obtener_manual_por_r2_key(r2_key):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, nombre, r2_key, tamaño, fecha_subida
                FROM manuales
                WHERE r2_key = %s
                """,
                (r2_key,),
            )
            fila = cursor.fetchone()
            return dict(fila) if fila else None


def registrar_manual(nombre, r2_key, tamaño):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO manuales (nombre, r2_key, tamaño)
                VALUES (%s, %s, %s)
                RETURNING id, nombre, r2_key, tamaño, fecha_subida
                """,
                (nombre, r2_key, tamaño),
            )
            fila = dict(cursor.fetchone())
        db.commit()
        return fila


def actualizar_manual(r2_key_anterior, nombre, r2_key_nuevo, tamaño):
    """
    Actualiza el registro de un manual después de subir correctamente el
    nuevo objeto a R2.
    """
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE manuales
                SET nombre = %s, r2_key = %s, tamaño = %s
                WHERE r2_key = %s
                RETURNING id, nombre, r2_key, tamaño, fecha_subida
                """,
                (nombre, r2_key_nuevo, tamaño, r2_key_anterior),
            )
            fila = cursor.fetchone()
            if not fila:
                raise LookupError("El manual a reemplazar no existe.")
            resultado = dict(fila)
        db.commit()
        return resultado


def eliminar_manual(r2_key):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "DELETE FROM manuales WHERE r2_key = %s",
                (r2_key,),
            )
            eliminado = cursor.rowcount > 0
        db.commit()
        return eliminado
