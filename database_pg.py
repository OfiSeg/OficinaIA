"""
Persistencia PostgreSQL (Neon) para OficinaIA.

Chats y configuración liviana pueden seguir en SQLite local, pero todo lo que
necesita sobrevivir a un redeploy/reinicio de Render vive acá:
- manuales (índice de PDFs en R2)
- metadatos (fichas de texto cargadas a mano)
- usuarios (login: usuario, contraseña, email, rol) — con fallback a SQLite
  si no hay DATABASE_URL configurada (ej. desarrollo local sin Neon).
"""
from __future__ import annotations

import os
from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash


CREATE_TABLE_MANUALES_SQL = """
CREATE TABLE IF NOT EXISTS manuales (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL,
    r2_key VARCHAR(500) NOT NULL UNIQUE,
    tamaño BIGINT,
    fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TABLE_METADATOS_SQL = """
CREATE TABLE IF NOT EXISTS metadatos (
    id SERIAL PRIMARY KEY,
    usuario VARCHAR(120) NOT NULL DEFAULT '',
    titulo VARCHAR(200) NOT NULL,
    contenido TEXT NOT NULL DEFAULT '',
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TABLE_USUARIOS_SQL = """
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    usuario VARCHAR(120) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL DEFAULT '',
    rol VARCHAR(30) NOT NULL DEFAULT 'usuario',
    protegido BOOLEAN NOT NULL DEFAULT FALSE
);
"""

USUARIO_ADMIN_PRINCIPAL = "admin"


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
            cursor.execute(CREATE_TABLE_MANUALES_SQL)
            cursor.execute(CREATE_TABLE_METADATOS_SQL)
            cursor.execute(CREATE_TABLE_USUARIOS_SQL)
            cursor.execute(
                """
                ALTER TABLE metadatos
                ADD COLUMN IF NOT EXISTS usuario VARCHAR(120) NOT NULL DEFAULT ''
                """
            )
            # Bootstrea el admin principal si todavía no existe (primera vez
            # que se conecta a esta base de Neon) y asegura que conserve el
            # rol/protección aunque alguien lo haya tocado a mano.
            cursor.execute(
                "SELECT id FROM usuarios WHERE usuario = %s",
                (USUARIO_ADMIN_PRINCIPAL,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    INSERT INTO usuarios (usuario, password, email, rol, protegido)
                    VALUES (%s, %s, %s, 'admin', TRUE)
                    """,
                    (USUARIO_ADMIN_PRINCIPAL, generate_password_hash("1234"), ""),
                )
            else:
                cursor.execute(
                    "UPDATE usuarios SET rol='admin', protegido=TRUE WHERE usuario=%s",
                    (USUARIO_ADMIN_PRINCIPAL,),
                )
        db.commit()


# ==========================================================
# USUARIOS (login persistente entre redeploys)
# ==========================================================


def listar_usuarios():
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, usuario, email, rol, protegido
                FROM usuarios
                ORDER BY usuario COLLATE "C"
                """
            )
            return [dict(fila) for fila in cursor.fetchall()]


def obtener_usuario(usuario):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, usuario, password, email, rol, protegido
                FROM usuarios WHERE lower(usuario) = lower(%s)
                """,
                (usuario,),
            )
            fila = cursor.fetchone()
            return dict(fila) if fila else None


def obtener_usuario_por_id(usuario_id):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, usuario, password, email, rol, protegido
                FROM usuarios WHERE id = %s
                """,
                (usuario_id,),
            )
            fila = cursor.fetchone()
            return dict(fila) if fila else None


def usuario_existe(usuario):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM usuarios WHERE lower(usuario) = lower(%s)",
                (usuario,),
            )
            return cursor.fetchone() is not None


def crear_usuario(usuario, password_hash, email, rol):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO usuarios (usuario, password, email, rol, protegido)
                VALUES (%s, %s, %s, %s, FALSE)
                RETURNING id, usuario, email, rol, protegido
                """,
                (usuario, password_hash, email, rol),
            )
            fila = dict(cursor.fetchone())
        db.commit()
        return fila


def actualizar_usuario(usuario_id, email, rol, password_hash=None):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "UPDATE usuarios SET email = %s, rol = %s WHERE id = %s",
                (email, rol, usuario_id),
            )
            if password_hash:
                cursor.execute(
                    "UPDATE usuarios SET password = %s WHERE id = %s",
                    (password_hash, usuario_id),
                )
            cursor.execute(
                """
                SELECT id, usuario, email, rol, protegido
                FROM usuarios WHERE id = %s
                """,
                (usuario_id,),
            )
            fila = cursor.fetchone()
        db.commit()
        return dict(fila) if fila else None


def eliminar_usuario(usuario_id):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM usuarios WHERE id = %s", (usuario_id,))
            eliminado = cursor.rowcount > 0
        db.commit()
        return eliminado


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


# ==========================================================
# METADATOS (fichas de texto persistentes)
# ==========================================================


def listar_metadatos():
    """Lista fichas ordenadas por actualización descendente."""
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, usuario, titulo, contenido, creado_en, actualizado_en
                FROM metadatos
                ORDER BY actualizado_en DESC, id DESC
                """
            )
            return [dict(fila) for fila in cursor.fetchall()]


def obtener_metadato(metadato_id):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, usuario, titulo, contenido, creado_en, actualizado_en
                FROM metadatos
                WHERE id = %s
                """,
                (metadato_id,),
            )
            fila = cursor.fetchone()
            return dict(fila) if fila else None


def crear_metadato(usuario, titulo, contenido):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO metadatos (usuario, titulo, contenido)
                VALUES (%s, %s, %s)
                RETURNING id, usuario, titulo, contenido, creado_en, actualizado_en
                """,
                (usuario, titulo, contenido),
            )
            fila = dict(cursor.fetchone())
        db.commit()
        return fila


def actualizar_metadato(metadato_id, titulo, contenido):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE metadatos
                SET titulo = %s,
                    contenido = %s,
                    actualizado_en = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, usuario, titulo, contenido, creado_en, actualizado_en
                """,
                (titulo, contenido, metadato_id),
            )
            fila = cursor.fetchone()
            if not fila:
                return None
            resultado = dict(fila)
        db.commit()
        return resultado


def eliminar_metadato(metadato_id):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "DELETE FROM metadatos WHERE id = %s",
                (metadato_id,),
            )
            eliminado = cursor.rowcount > 0
        db.commit()
        return eliminado
