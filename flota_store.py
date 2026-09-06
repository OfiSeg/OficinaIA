"""Persistencia aislada del snapshot de /flota.

No contiene reglas conversacionales ni parsing. Recibe las dependencias de
persistencia por inyección para no importar app.py ni crear ciclos.
"""
import json
from contextlib import closing


class FlotaStore:
    def __init__(self, usar_pg, conectar_db, pg_obtener, pg_guardar, pg_borrar):
        self._usar_pg = usar_pg
        self._conectar_db = conectar_db
        self._pg_obtener = pg_obtener
        self._pg_guardar = pg_guardar
        self._pg_borrar = pg_borrar

    def obtener(self, chat_id):
        if self._usar_pg():
            return self._pg_obtener(chat_id)
        with closing(self._conectar_db()) as db:
            fila = db.execute(
                "SELECT conversacion_id, estado, libro_id, datos_generales, vehiculos "
                "FROM flotas_activas WHERE conversacion_id=?",
                (chat_id,),
            ).fetchone()
            if not fila:
                return None
            return {
                "conversacion_id": fila[0],
                "estado": fila[1],
                "libro_id": fila[2],
                "datos_generales": json.loads(fila[3] or "{}"),
                "vehiculos": json.loads(fila[4] or "[]"),
            }

    def guardar(self, chat_id, estado, libro_id, datos_generales, vehiculos):
        if self._usar_pg():
            self._pg_guardar(chat_id, estado, libro_id, datos_generales, vehiculos)
            return
        with closing(self._conectar_db()) as db:
            db.execute(
                """
                INSERT INTO flotas_activas (conversacion_id, estado, libro_id, datos_generales, vehiculos, actualizado_en)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(conversacion_id) DO UPDATE SET
                    estado=excluded.estado,
                    libro_id=excluded.libro_id,
                    datos_generales=excluded.datos_generales,
                    vehiculos=excluded.vehiculos,
                    actualizado_en=CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    estado,
                    libro_id,
                    json.dumps(datos_generales or {}, ensure_ascii=False),
                    json.dumps(vehiculos or [], ensure_ascii=False),
                ),
            )
            db.commit()

    def borrar(self, chat_id):
        if self._usar_pg():
            self._pg_borrar(chat_id)
            return
        with closing(self._conectar_db()) as db:
            db.execute("DELETE FROM flotas_activas WHERE conversacion_id=?", (chat_id,))
            db.commit()
