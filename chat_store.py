"""Persistencia de conversaciones de OficinaIA.

V20 Etapa 16: concentra PostgreSQL/SQLite y deja a Flask como transporte.
No importa app, Flask, session ni request.
"""
from contextlib import closing


class ChatStore:
    def __init__(self, *, usar_pg, conectar_db, pg):
        self._usar_pg = usar_pg
        self._conectar_db = conectar_db
        self._pg = pg

    def crear(self, usuario, titulo="Nueva conversación"):
        titulo = (titulo or "Nueva conversación")[:100] or "Nueva conversación"
        if self._usar_pg():
            return self._pg["crear"](usuario, titulo)
        with closing(self._conectar_db()) as db:
            cur = db.execute("INSERT INTO conversaciones (usuario,titulo) VALUES (?,?)", (usuario, titulo))
            db.commit()
            return cur.lastrowid

    def validar(self, chat_id, usuario):
        if self._usar_pg():
            return bool(self._pg["validar"](chat_id, usuario))
        with closing(self._conectar_db()) as db:
            return db.execute("SELECT id FROM conversaciones WHERE id=? AND usuario=?", (chat_id, usuario)).fetchone() is not None

    def guardar_mensaje(self, chat_id, rol, contenido):
        if self._usar_pg():
            self._pg["agregar_mensaje"](chat_id, rol, contenido)
            return
        with closing(self._conectar_db()) as db:
            db.execute("INSERT INTO mensajes (conversacion_id,rol,contenido) VALUES (?,?,?)", (chat_id, rol, contenido))
            db.execute("UPDATE conversaciones SET actualizado_en=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
            db.commit()

    def historial(self, chat_id, usuario, limite=10):
        if not chat_id:
            return []
        if self._usar_pg():
            return self._pg["historial"](chat_id, usuario, limite=limite)
        with closing(self._conectar_db()) as db:
            if not db.execute("SELECT id FROM conversaciones WHERE id=? AND usuario=?", (chat_id, usuario)).fetchone():
                return []
            rows = db.execute("SELECT rol, contenido FROM mensajes WHERE conversacion_id=? ORDER BY id DESC LIMIT ?", (chat_id, limite)).fetchall()
            return [{"rol": r["rol"], "contenido": r["contenido"]} for r in reversed(list(rows))
                    if r["rol"] in ("user", "assistant") and str(r["contenido"] or "").strip()]

    def listar(self, usuario):
        if self._usar_pg():
            return self._pg["listar"](usuario)
        with closing(self._conectar_db()) as db:
            rows = db.execute("SELECT id,titulo,COALESCE(tipo,'') AS tipo,creado_en,actualizado_en FROM conversaciones WHERE usuario=? ORDER BY actualizado_en DESC, id DESC", (usuario,)).fetchall()
            return [dict(r) for r in rows]

    def obtener(self, chat_id, usuario):
        if self._usar_pg():
            return self._pg["obtener"](chat_id, usuario)
        with closing(self._conectar_db()) as db:
            chat = db.execute("SELECT id,titulo FROM conversaciones WHERE id=? AND usuario=?", (chat_id, usuario)).fetchone()
            if not chat:
                return None, []
            mensajes = db.execute("SELECT id,rol,contenido,creado_en FROM mensajes WHERE conversacion_id=? ORDER BY id", (chat_id,)).fetchall()
            return dict(chat), [dict(x) for x in mensajes]

    def eliminar(self, chat_id, usuario):
        if self._usar_pg():
            return bool(self._pg["eliminar"](chat_id, usuario))
        with closing(self._conectar_db()) as db:
            row = db.execute("SELECT id FROM conversaciones WHERE id=? AND usuario=?", (chat_id, usuario)).fetchone()
            if not row:
                return False
            db.execute("DELETE FROM mensajes WHERE conversacion_id=?", (chat_id,))
            db.execute("DELETE FROM conversaciones WHERE id=?", (chat_id,))
            db.commit()
            return True

    def asignar_tipo_si_vacio(self, chat_id, usuario, tipo):
        if not chat_id or not tipo:
            return False
        if self._usar_pg():
            return bool(self._pg["actualizar_tipo"](chat_id, usuario, tipo))
        with closing(self._conectar_db()) as db:
            cur = db.execute("UPDATE conversaciones SET tipo=? WHERE id=? AND usuario=? AND (tipo IS NULL OR tipo='')", (tipo, chat_id, usuario))
            db.commit()
            return cur.rowcount > 0

    def obtener_titulo(self, chat_id, usuario):
        if self._usar_pg():
            return self._pg["obtener_titulo"](chat_id, usuario)
        with closing(self._conectar_db()) as db:
            row = db.execute("SELECT titulo FROM conversaciones WHERE id=? AND usuario=?", (chat_id, usuario)).fetchone()
            return row["titulo"] if row else None

    def actualizar_titulo(self, chat_id, usuario, titulo):
        titulo = (titulo or "").strip()[:100] or "Nueva conversación"
        if self._usar_pg():
            return bool(self._pg["actualizar_titulo"](chat_id, usuario, titulo))
        with closing(self._conectar_db()) as db:
            cur = db.execute("UPDATE conversaciones SET titulo=?, actualizado_en=CURRENT_TIMESTAMP WHERE id=? AND usuario=?", (titulo, chat_id, usuario))
            db.commit()
            return cur.rowcount > 0
