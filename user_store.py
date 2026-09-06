from __future__ import annotations

import re
from contextlib import closing

ROLES_VALIDOS = {"admin", "usuario"}


def validar_email(email: str) -> bool:
    return not email or bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(email)))


class UserStore:
    def __init__(self, *, usar_pg, conectar_db, pg, hash_password=None):
        self.usar_pg = bool(usar_pg)
        self.conectar_db = conectar_db
        self.pg = pg
        self.hash_password = hash_password or self._default_hash_password

    @staticmethod
    def _default_hash_password(password):
        from werkzeug.security import generate_password_hash
        return self.hash_password(password)

    def obtener_por_usuario(self, usuario):
        if self.usar_pg:
            try:
                return self.pg["obtener_usuario"](usuario)
            except Exception as error:
                print("ERROR obtener_usuario PG:", error)
                return None
        with closing(self.conectar_db()) as db:
            return db.execute("SELECT id,usuario,password,email,rol,protegido FROM usuarios WHERE usuario=?", (usuario,)).fetchone()

    def obtener_por_id(self, usuario_id):
        if self.usar_pg:
            try:
                return self.pg["obtener_usuario_por_id"](usuario_id)
            except Exception as error:
                print("ERROR obtener_usuario_por_id PG:", error)
                return None
        with closing(self.conectar_db()) as db:
            return db.execute("SELECT id,usuario,password,email,rol,protegido FROM usuarios WHERE id=?", (usuario_id,)).fetchone()

    def listar(self):
        if self.usar_pg:
            return self.pg["listar_usuarios"]()
        with closing(self.conectar_db()) as db:
            return db.execute("SELECT id,usuario,email,rol,protegido FROM usuarios ORDER BY usuario COLLATE NOCASE").fetchall()

    def crear(self, usuario, password, email, rol):
        if self.usar_pg:
            if self.pg["usuario_existe"](usuario):
                return None, "Ese usuario ya existe.", 409
            fila = self.pg["crear_usuario"](usuario, self.hash_password(password), email, rol)
            nuevo_id = fila["id"] if isinstance(fila, dict) else fila
            return nuevo_id, None, 200
        with closing(self.conectar_db()) as db:
            if db.execute("SELECT 1 FROM usuarios WHERE lower(usuario)=lower(?)", (usuario,)).fetchone():
                return None, "Ese usuario ya existe.", 409
            cur = db.execute("INSERT INTO usuarios (usuario,password,email,rol,protegido) VALUES (?,?,?,?,0)", (usuario, self.hash_password(password), email, rol))
            db.commit()
            return cur.lastrowid, None, 200

    def actualizar(self, usuario_id, email, rol, password=""):
        if self.usar_pg:
            self.pg["actualizar_usuario"](usuario_id, email, rol, self.hash_password(password) if password else None)
            return
        with closing(self.conectar_db()) as db:
            db.execute("UPDATE usuarios SET email=?,rol=? WHERE id=?", (email, rol, usuario_id))
            if password:
                db.execute("UPDATE usuarios SET password=? WHERE id=?", (self.hash_password(password), usuario_id))
            db.commit()

    def eliminar(self, usuario_id):
        if self.usar_pg:
            self.pg["eliminar_usuario"](usuario_id)
            return
        with closing(self.conectar_db()) as db:
            db.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
            db.commit()
