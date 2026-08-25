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

CREATE_TABLE_POLIZAS_SQL = """
CREATE TABLE IF NOT EXISTS polizas (
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

CREATE_TABLE_CONFIGURACION_SQL = """
CREATE TABLE IF NOT EXISTS configuracion (
    id INTEGER PRIMARY KEY DEFAULT 1,
    datos JSONB NOT NULL DEFAULT '{}'::jsonb,
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT configuracion_singleton CHECK (id = 1)
);
"""

CREATE_TABLE_DOCUMENTO_INTERNO_SQL = """
CREATE TABLE IF NOT EXISTS documento_interno (
    id INTEGER PRIMARY KEY DEFAULT 1,
    contenido TEXT NOT NULL DEFAULT '',
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT documento_interno_singleton CHECK (id = 1)
);
"""

CREATE_TABLE_CONVERSACIONES_SQL = """
CREATE TABLE IF NOT EXISTS conversaciones (
    id SERIAL PRIMARY KEY,
    usuario VARCHAR(120) NOT NULL,
    titulo VARCHAR(200) NOT NULL DEFAULT 'Nueva conversación',
    tipo VARCHAR(30) NOT NULL DEFAULT '',
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TABLE_MENSAJES_SQL = """
CREATE TABLE IF NOT EXISTS mensajes (
    id SERIAL PRIMARY KEY,
    conversacion_id INTEGER NOT NULL REFERENCES conversaciones(id) ON DELETE CASCADE,
    rol VARCHAR(20) NOT NULL,
    contenido TEXT NOT NULL,
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Estado de trabajo de una flota en curso, atado a una conversación. Guarda
# los datos generales de la póliza y la lista completa de vehículos (con sus
# campos conocidos/pendientes y la fila del Excel donde ya se guardó cada
# uno, si corresponde) para poder retomar la tarea en cualquier mensaje
# posterior sin que el usuario tenga que repetir nada.
CREATE_TABLE_FLOTAS_ACTIVAS_SQL = """
CREATE TABLE IF NOT EXISTS flotas_activas (
    conversacion_id INTEGER PRIMARY KEY REFERENCES conversaciones(id) ON DELETE CASCADE,
    estado VARCHAR(30) NOT NULL DEFAULT 'nueva',
    libro_id VARCHAR(10) NOT NULL DEFAULT '2',
    datos_generales JSONB NOT NULL DEFAULT '{}'::jsonb,
    vehiculos JSONB NOT NULL DEFAULT '[]'::jsonb,
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# P0.2 — Bandeja de pendientes (sobrevive a redeploys en Neon).
CREATE_TABLE_PENDIENTES_SQL = """
CREATE TABLE IF NOT EXISTS pendientes (
    id SERIAL PRIMARY KEY,
    usuario VARCHAR(120) NOT NULL,
    tipo VARCHAR(40) NOT NULL DEFAULT 'generico',
    titulo VARCHAR(200) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pendientes_usuario_estado
    ON pendientes (usuario, estado);
"""

USUARIO_ADMIN_PRINCIPAL = "admin"

# Tipos/estados alineados con pendientes_ops.py
PENDIENTES_TIPOS = {"excel", "metadato", "flota", "coti", "whatsapp", "generico", "pdf_ficha"}
PENDIENTES_ESTADOS = {"pendiente", "hecho", "descartado"}


def _database_url():
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError(
            "Falta la variable de entorno DATABASE_URL de Neon PostgreSQL."
        )
    return value


def conectar_pg():
    return psycopg2.connect(_database_url())


def _json_safe_row(fila: dict) -> dict:
    """P1.0 — Convierte datetime de Postgres a ISO string para jsonify."""
    from datetime import datetime, date

    out = {}
    for k, v in (fila or {}).items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def inicializar_postgres():
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(CREATE_TABLE_MANUALES_SQL)
            cursor.execute(CREATE_TABLE_POLIZAS_SQL)
            cursor.execute(CREATE_TABLE_METADATOS_SQL)
            cursor.execute(CREATE_TABLE_USUARIOS_SQL)
            cursor.execute(CREATE_TABLE_CONFIGURACION_SQL)
            cursor.execute(CREATE_TABLE_DOCUMENTO_INTERNO_SQL)
            cursor.execute(CREATE_TABLE_CONVERSACIONES_SQL)
            cursor.execute(CREATE_TABLE_MENSAJES_SQL)
            cursor.execute(CREATE_TABLE_FLOTAS_ACTIVAS_SQL)
            cursor.execute(CREATE_TABLE_PENDIENTES_SQL)
            cursor.execute(
                """
                ALTER TABLE metadatos
                ADD COLUMN IF NOT EXISTS usuario VARCHAR(120) NOT NULL DEFAULT ''
                """
            )
            # P2.6 / Tanda C — tipo de chat (flota|coti|alta|envios|…)
            cursor.execute(
                """
                ALTER TABLE conversaciones
                ADD COLUMN IF NOT EXISTS tipo VARCHAR(30) NOT NULL DEFAULT ''
                """
            )
            # Bootstrap del admin principal si todavía no existe (primera vez
            # que se conecta a esta base de Neon) y asegura que conserve el
            # rol/protección aunque alguien lo haya tocado a mano.
            # P0.4 — No seedear "1234" en prod. Usar ADMIN_INITIAL_PASSWORD
            # o no crear el usuario (el operador debe crearlo a mano).
            cursor.execute(
                "SELECT id FROM usuarios WHERE usuario = %s",
                (USUARIO_ADMIN_PRINCIPAL,),
            )
            if cursor.fetchone() is None:
                initial = (os.getenv("ADMIN_INITIAL_PASSWORD") or "").strip()
                if not initial or initial == "1234":
                    print(
                        "ADVERTENCIA P0.4: no se crea usuario 'admin' en Neon "
                        "sin ADMIN_INITIAL_PASSWORD fuerte. Definila en el panel "
                        "de Render o creá el usuario manualmente."
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO usuarios (usuario, password, email, rol, protegido)
                        VALUES (%s, %s, %s, 'admin', TRUE)
                        """,
                        (USUARIO_ADMIN_PRINCIPAL, generate_password_hash(initial), ""),
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
# PÓLIZAS (PDFs en R2, metadatos en Neon)
# ==========================================================


def listar_polizas():
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, nombre, r2_key, tamaño, fecha_subida
                FROM polizas
                ORDER BY fecha_subida DESC, id DESC
                """
            )
            return [dict(fila) for fila in cursor.fetchall()]


def obtener_poliza_por_r2_key(r2_key):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, nombre, r2_key, tamaño, fecha_subida
                FROM polizas
                WHERE r2_key = %s
                """,
                (r2_key,),
            )
            fila = cursor.fetchone()
            return dict(fila) if fila else None


def registrar_poliza(nombre, r2_key, tamaño):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO polizas (nombre, r2_key, tamaño)
                VALUES (%s, %s, %s)
                RETURNING id, nombre, r2_key, tamaño, fecha_subida
                """,
                (nombre, r2_key, tamaño),
            )
            fila = dict(cursor.fetchone())
        db.commit()
        return fila


def eliminar_poliza(r2_key):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "DELETE FROM polizas WHERE r2_key = %s",
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
            return [_json_safe_row(dict(fila)) for fila in cursor.fetchall()]


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
            return _json_safe_row(dict(fila)) if fila else None


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
            fila = _json_safe_row(dict(cursor.fetchone()))
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
            resultado = _json_safe_row(dict(fila))
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


# ==========================================================
# CONFIGURACIÓN GLOBAL (fila única, sobrevive a redeploys)
# ==========================================================

import json as _json


def obtener_configuracion():
    """Devuelve el dict de configuración guardado en Neon, o None si
    todavía no se guardó nada (primera vez)."""
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute("SELECT datos FROM configuracion WHERE id = 1")
            fila = cursor.fetchone()
            if not fila:
                return None
            datos = fila[0]
            # psycopg2 puede devolver JSONB ya parseado (dict) o como texto
            # según la versión; cubrimos ambos casos.
            if isinstance(datos, str):
                try:
                    datos = _json.loads(datos)
                except Exception:
                    return None
            return datos if isinstance(datos, dict) else None


def guardar_configuracion(config: dict):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO configuracion (id, datos, actualizado_en)
                VALUES (1, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE
                SET datos = EXCLUDED.datos, actualizado_en = CURRENT_TIMESTAMP
                """,
                (_json.dumps(config, ensure_ascii=False),),
            )
        db.commit()
    return config


# ==========================================================
# DOCUMENTO INTERNO (Word en texto plano, fila única en Neon)
# ==========================================================


def obtener_documento_interno():
    """Devuelve el texto guardado, o None si nunca se guardó nada."""
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute("SELECT contenido FROM documento_interno WHERE id = 1")
            fila = cursor.fetchone()
            return fila[0] if fila else None


def guardar_documento_interno(contenido: str):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO documento_interno (id, contenido, actualizado_en)
                VALUES (1, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE
                SET contenido = EXCLUDED.contenido, actualizado_en = CURRENT_TIMESTAMP
                """,
                (contenido or "",),
            )
        db.commit()


# ==========================================================
# CONVERSACIONES Y MENSAJES (chats persistentes entre redeploys)
# ==========================================================


def crear_conversacion(usuario, titulo="Nueva conversación"):
    titulo = (titulo or "Nueva conversación")[:200]
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO conversaciones (usuario, titulo)
                VALUES (%s, %s)
                RETURNING id
                """,
                (usuario, titulo),
            )
            chat_id = cursor.fetchone()["id"]
        db.commit()
        return chat_id


def listar_chats(usuario):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, titulo, COALESCE(tipo, '') AS tipo, creado_en, actualizado_en
                FROM conversaciones
                WHERE usuario = %s
                ORDER BY actualizado_en DESC, id DESC
                """,
                (usuario,),
            )
            return [_json_safe_row(dict(fila)) for fila in cursor.fetchall()]


def actualizar_tipo_chat(chat_id, usuario, tipo):
    """Persiste el tipo operativo del chat (flota/coti/alta/envios). No pisa si ya hay tipo."""
    tipo = (tipo or "").strip().lower()[:30]
    if not tipo:
        return False
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                """
                UPDATE conversaciones
                SET tipo = %s
                WHERE id = %s AND usuario = %s
                  AND (tipo IS NULL OR tipo = '')
                """,
                (tipo, chat_id, usuario),
            )
            ok = cursor.rowcount > 0
        db.commit()
        return ok


def listar_mensajes_historial(chat_id, usuario, limite=10):
    """Últimos N mensajes del chat para Gemini (server-side, P1.3)."""
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT id FROM conversaciones WHERE id = %s AND usuario = %s",
                (chat_id, usuario),
            )
            if cursor.fetchone() is None:
                return []
            cursor.execute(
                """
                SELECT rol, contenido
                FROM mensajes
                WHERE conversacion_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (chat_id, limite),
            )
            rows = list(cursor.fetchall())
            rows.reverse()
            return [
                {"rol": r["rol"], "contenido": r["contenido"]}
                for r in rows
                if r.get("rol") in ("user", "assistant") and str(r.get("contenido") or "").strip()
            ]


def validar_chat(chat_id, usuario):
    """Devuelve True si la conversación existe y pertenece al usuario."""
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM conversaciones WHERE id = %s AND usuario = %s",
                (chat_id, usuario),
            )
            return cursor.fetchone() is not None


def obtener_chat_con_mensajes(chat_id, usuario):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT id, titulo FROM conversaciones WHERE id = %s AND usuario = %s",
                (chat_id, usuario),
            )
            chat = cursor.fetchone()
            if not chat:
                return None, None
            cursor.execute(
                """
                SELECT id, rol, contenido, creado_en
                FROM mensajes
                WHERE conversacion_id = %s
                ORDER BY id
                """,
                (chat_id,),
            )
            mensajes = [_json_safe_row(dict(fila)) for fila in cursor.fetchall()]
            return dict(chat), mensajes


def eliminar_chat(chat_id, usuario):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM conversaciones WHERE id = %s AND usuario = %s",
                (chat_id, usuario),
            )
            if cursor.fetchone() is None:
                return False
            # mensajes se borran solos por el ON DELETE CASCADE, pero lo
            # dejamos explícito por claridad y por si algún día se saca el FK.
            cursor.execute("DELETE FROM mensajes WHERE conversacion_id = %s", (chat_id,))
            cursor.execute("DELETE FROM conversaciones WHERE id = %s", (chat_id,))
        db.commit()
        return True



def obtener_titulo_chat(chat_id, usuario):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT titulo FROM conversaciones WHERE id = %s AND usuario = %s",
                (chat_id, usuario),
            )
            fila = cursor.fetchone()
            return fila["titulo"] if fila else None


def actualizar_titulo_chat(chat_id, usuario, titulo):
    titulo = (titulo or "Nueva conversación")[:200]
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                """
                UPDATE conversaciones
                SET titulo = %s, actualizado_en = CURRENT_TIMESTAMP
                WHERE id = %s AND usuario = %s
                """,
                (titulo, chat_id, usuario),
            )
            ok = cursor.rowcount > 0
        db.commit()
        return ok


def agregar_mensaje(chat_id, rol, contenido):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO mensajes (conversacion_id, rol, contenido) VALUES (%s, %s, %s)",
                (chat_id, rol, contenido),
            )
            cursor.execute(
                "UPDATE conversaciones SET actualizado_en = CURRENT_TIMESTAMP WHERE id = %s",
                (chat_id,),
            )
        db.commit()


# ==========================================================
# FLOTA ACTIVA (contexto de trabajo persistente de /flota)
# ==========================================================


def obtener_flota_activa(chat_id):
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT conversacion_id, estado, libro_id, datos_generales, vehiculos
                FROM flotas_activas WHERE conversacion_id = %s
                """,
                (chat_id,),
            )
            fila = cursor.fetchone()
            return dict(fila) if fila else None


def guardar_flota_activa(chat_id, estado, libro_id, datos_generales, vehiculos):
    import json as _json

    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO flotas_activas (conversacion_id, estado, libro_id, datos_generales, vehiculos, actualizado_en)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (conversacion_id) DO UPDATE SET
                    estado = EXCLUDED.estado,
                    libro_id = EXCLUDED.libro_id,
                    datos_generales = EXCLUDED.datos_generales,
                    vehiculos = EXCLUDED.vehiculos,
                    actualizado_en = CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    estado,
                    libro_id,
                    _json.dumps(datos_generales or {}),
                    _json.dumps(vehiculos or []),
                ),
            )
        db.commit()


def borrar_flota_activa(chat_id):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM flotas_activas WHERE conversacion_id = %s", (chat_id,))
        db.commit()


# ==========================================================
# PENDIENTES (bandeja de trabajo a medias — P0.2)
# ==========================================================


def listar_pendientes(usuario, estado="pendiente", limite=100):
    estado = (estado or "pendiente").strip().lower()
    if estado not in PENDIENTES_ESTADOS:
        estado = "pendiente"
    with closing(conectar_pg()) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, tipo, titulo, payload, estado, creado_en, actualizado_en
                FROM pendientes
                WHERE usuario = %s AND estado = %s
                ORDER BY actualizado_en DESC, id DESC
                LIMIT %s
                """,
                (usuario, estado, limite),
            )
            out = []
            for fila in cursor.fetchall():
                item = _json_safe_row(dict(fila))
                payload = item.get("payload")
                if isinstance(payload, str):
                    import json as _json
                    try:
                        item["payload"] = _json.loads(payload)
                    except Exception:
                        item["payload"] = {}
                elif payload is None:
                    item["payload"] = {}
                out.append(item)
            return out


def contar_pendientes(usuario, estado="pendiente") -> int:
    estado = (estado or "pendiente").strip().lower()
    if estado not in PENDIENTES_ESTADOS:
        estado = "pendiente"
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pendientes WHERE usuario = %s AND estado = %s",
                (usuario, estado),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)


def crear_pendiente(usuario, tipo, titulo, payload=None):
    import json as _json

    tipo = (tipo or "generico").strip().lower()
    if tipo not in PENDIENTES_TIPOS:
        tipo = "generico"
    titulo = (titulo or "Pendiente").strip()[:200] or "Pendiente"
    payload_obj = payload if isinstance(payload, dict) else {}
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO pendientes (usuario, tipo, titulo, payload, estado)
                VALUES (%s, %s, %s, %s::jsonb, 'pendiente')
                RETURNING id
                """,
                (usuario, tipo, titulo, _json.dumps(payload_obj, ensure_ascii=False)),
            )
            pid = cursor.fetchone()[0]
        db.commit()
        return pid


def editar_pendiente(pendiente_id, usuario, tipo=None, titulo=None, payload=None, estado=None):
    """Actualización parcial (Tanda 8), espejo de pendientes_ops.editar pero
    contra Postgres. Sólo toca los campos que vengan distintos de None."""
    import json as _json

    campos = []
    valores = []
    if tipo is not None:
        tipo = (tipo or "generico").strip().lower()
        if tipo not in PENDIENTES_TIPOS:
            tipo = "generico"
        campos.append("tipo = %s")
        valores.append(tipo)
    if titulo is not None:
        campos.append("titulo = %s")
        valores.append((titulo or "Pendiente").strip()[:200] or "Pendiente")
    if payload is not None:
        campos.append("payload = %s::jsonb")
        valores.append(_json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False))
    if estado is not None:
        estado = (estado or "").strip().lower()
        if estado not in PENDIENTES_ESTADOS:
            return False
        campos.append("estado = %s")
        valores.append(estado)
    if not campos:
        return False
    campos.append("actualizado_en = CURRENT_TIMESTAMP")
    valores.extend([pendiente_id, usuario])
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                f"UPDATE pendientes SET {', '.join(campos)} WHERE id = %s AND usuario = %s",
                valores,
            )
            ok = cursor.rowcount > 0
        db.commit()
        return ok


def actualizar_estado_pendiente(pendiente_id, usuario, estado):
    estado = (estado or "").strip().lower()
    if estado not in PENDIENTES_ESTADOS:
        return False
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pendientes
                SET estado = %s, actualizado_en = CURRENT_TIMESTAMP
                WHERE id = %s AND usuario = %s
                """,
                (estado, pendiente_id, usuario),
            )
            ok = cursor.rowcount > 0
        db.commit()
        return ok


def eliminar_pendiente(pendiente_id, usuario):
    with closing(conectar_pg()) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "DELETE FROM pendientes WHERE id = %s AND usuario = %s",
                (pendiente_id, usuario),
            )
            ok = cursor.rowcount > 0
        db.commit()
        return ok
