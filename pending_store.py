"""Persistencia de Pendientes de OficinaIA.

V20 Etapa 17: concentra PostgreSQL/SQLite y deja a Flask como transporte.
No importa app, Flask, session ni request.
"""
from contextlib import closing

import pendientes_ops


class PendingStore:
    def __init__(self, *, usar_pg, conectar_db, pg):
        self._usar_pg = usar_pg
        self._conectar_db = conectar_db
        self._pg = pg

    @staticmethod
    def normalizar_estado(estado, *, default="pendiente"):
        estado = str(estado or default).strip().lower()
        return estado if estado in pendientes_ops.ESTADOS_VALIDOS else default

    @staticmethod
    def validar_estado(estado):
        return str(estado or "").strip().lower() in pendientes_ops.ESTADOS_VALIDOS

    def listar(self, usuario, *, estado="pendiente", limite=100):
        estado = self.normalizar_estado(estado)
        if self._usar_pg():
            items = self._pg["listar"](usuario, estado=estado, limite=limite)
            total = self._pg["contar"](usuario, estado="pendiente")
            return items, total
        with closing(self._conectar_db()) as db:
            pendientes_ops.asegurar_tabla(db)
            items = pendientes_ops.listar(db, usuario, estado=estado, limite=limite)
            total = pendientes_ops.contar(db, usuario, estado="pendiente")
            return items, total

    def crear(self, usuario, *, tipo="generico", titulo="Pendiente", payload=None):
        payload = payload if isinstance(payload, dict) else {}
        if self._usar_pg():
            pid = self._pg["crear"](usuario, tipo, titulo, payload)
            total = self._pg["contar"](usuario, estado="pendiente")
            return pid, total
        with closing(self._conectar_db()) as db:
            pendientes_ops.asegurar_tabla(db)
            pid = pendientes_ops.crear(db, usuario, tipo, titulo, payload)
            total = pendientes_ops.contar(db, usuario, estado="pendiente")
            return pid, total

    def editar(self, pendiente_id, usuario, *, tipo=None, titulo=None, payload=None, estado=None):
        if self._usar_pg():
            ok = self._pg["editar"](
                pendiente_id,
                usuario,
                tipo=tipo,
                titulo=titulo,
                payload=payload,
                estado=estado,
            )
            total = self._pg["contar"](usuario, estado="pendiente")
            return bool(ok), total
        with closing(self._conectar_db()) as db:
            pendientes_ops.asegurar_tabla(db)
            ok = pendientes_ops.editar(
                db,
                pendiente_id,
                usuario,
                tipo=tipo,
                titulo=titulo,
                payload=payload,
                estado=estado,
            )
            total = pendientes_ops.contar(db, usuario, estado="pendiente")
            return bool(ok), total

    def eliminar(self, pendiente_id, usuario):
        if self._usar_pg():
            ok = self._pg["eliminar"](pendiente_id, usuario)
            total = self._pg["contar"](usuario, estado="pendiente")
            return bool(ok), total
        with closing(self._conectar_db()) as db:
            pendientes_ops.asegurar_tabla(db)
            ok = pendientes_ops.eliminar(db, pendiente_id, usuario)
            total = pendientes_ops.contar(db, usuario, estado="pendiente")
            return bool(ok), total
