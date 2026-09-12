"""Contexto determinístico de registros de cartera para el chat.

Evita que un follow-up como "decime sus detalles" vuelva a una búsqueda fuzzy
cuando el turno anterior ya resolvió un conjunto exacto por fecha/filtro.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from office_time import office_today, date_string
import servicios_ia


MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def normalizar(texto: Any) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    valor = valor.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", valor).strip()


def _valor(fila: dict, *aliases: str) -> str:
    try:
        clave = servicios_ia._campo_por_alias(fila or {}, aliases)  # reutiliza aliases reales del motor
    except Exception:
        clave = None
    return str((fila or {}).get(clave, "") if clave else "").strip()


@dataclass
class RangoTemporal:
    desde: date
    hasta: date
    etiqueta: str

    def filtros(self) -> dict:
        return {
            "desde": date_string(self.desde),
            "hasta": date_string(self.hasta),
            "campo_fecha": "EMITIDO DÍA:",
        }


def resolver_rango_temporal(mensaje: str, *, hoy: date | None = None) -> RangoTemporal | None:
    hoy = hoy or office_today()
    t = normalizar(mensaje)
    if not t:
        return None

    if re.search(r"\bhoy\b", t):
        return RangoTemporal(hoy, hoy, "hoy")

    if re.search(r"\bayer\b", t):
        d = hoy - timedelta(days=1)
        return RangoTemporal(d, d, "ayer")

    if re.search(r"\beste mes\b|\bdel mes\b|\bmes corriente\b", t):
        return RangoTemporal(hoy.replace(day=1), hoy, "este mes")

    if re.search(r"\besta semana\b|\bsemana corriente\b", t):
        inicio = hoy - timedelta(days=hoy.weekday())
        return RangoTemporal(inicio, hoy, "esta semana")

    m = re.search(r"\b(?:del|desde el|desde)\s+(\d{1,2})(?:\s*/\s*(\d{1,2}))?\s+(?:para aca|hasta hoy|en adelante)\b", t)
    if m:
        dia = int(m.group(1))
        mes = int(m.group(2)) if m.group(2) else hoy.month
        try:
            d = date(hoy.year, mes, dia)
            return RangoTemporal(d, hoy, f"desde el {date_string(d)}")
        except ValueError:
            return None

    m = re.search(r"\b(?:el\s+)?(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+(\d{4}))?\b", t)
    if m and m.group(2) in MESES:
        dia = int(m.group(1))
        mes = MESES[m.group(2)]
        anio = int(m.group(3)) if m.group(3) else hoy.year
        try:
            d = date(anio, mes, dia)
            return RangoTemporal(d, d, date_string(d))
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        dia = int(m.group(1))
        mes = int(m.group(2))
        anio = int(m.group(3)) if m.group(3) else hoy.year
        if anio < 100:
            anio += 2000
        try:
            d = date(anio, mes, dia)
            return RangoTemporal(d, d, date_string(d))
        except ValueError:
            return None

    return None


def es_consulta_conteo_temporal(mensaje: str) -> bool:
    t = normalizar(mensaje)
    if not resolver_rango_temporal(mensaje):
        return False
    if not re.search(r"\b(cuantos|cuantas|cantidad|total)\b", t):
        return False
    # Evita capturar preguntas documentales de cobertura/servicios.
    if any(x in t for x in ("cubre", "cobertura", "asistencia", "servicio", "prestacion", "kilomet")):
        return False
    return any(x in t for x in (
        "emiti", "emitidos", "emitidas", "tuve", "tengo", "hicimos", "hice",
        "asegurado", "asegurados", "cliente", "clientes", "poliza", "polizas",
        "registro", "registros", "auto", "autos", "moto", "motos", "vehiculo", "vehiculos",
    ))


def _tipo_conteo(mensaje: str) -> str:
    t = normalizar(mensaje)
    return "unicos" if any(x in t for x in ("asegurado", "asegurados", "cliente", "clientes", "persona", "personas")) else "filas"


def _plural(n: int, uno: str, varios: str) -> str:
    return uno if int(n) == 1 else varios


def guardar_contexto(session_obj, *, chat_id, filtros: dict, cantidad: int, registros: list[dict] | None, etiqueta: str, origen: str):
    # La última fuente realmente usada manda. Al activar un conjunto de cartera
    # invalidamos cualquier selección ARCA vieja para que un nombre u ordinal
    # posterior no sea secuestrado por el padrón público.
    session_obj.pop("arca_context", None)
    session_obj["registro_contexto_activo"] = {
        "tipo": "registro_excel_set",
        "chat_id": str(chat_id or ""),
        "filtros": dict(filtros or {}),
        "cantidad": int(cantidad or 0),
        # Sólo se guarda una muestra chica para no inflar la cookie de sesión.
        "registros": list(registros or [])[:10],
        "etiqueta": str(etiqueta or "").strip(),
        "origen": str(origen or "").strip(),
    }


def obtener_contexto(session_obj, chat_id) -> dict | None:
    ctx = session_obj.get("registro_contexto_activo") or {}
    if not isinstance(ctx, dict):
        return None
    if str(ctx.get("chat_id") or "") != str(chat_id or ""):
        return None
    if ctx.get("tipo") != "registro_excel_set":
        return None
    return ctx


def limpiar_contexto(session_obj):
    session_obj.pop("registro_contexto_activo", None)


def responder_conteo_temporal(mensaje: str, *, session_obj, chat_id) -> str | None:
    if not es_consulta_conteo_temporal(mensaje):
        return None
    rango = resolver_rango_temporal(mensaje)
    if not rango:
        return None
    filtros = rango.filtros()
    conteo = servicios_ia.contar_registros(**filtros, tipo_conteo=_tipo_conteo(mensaje))
    filas = servicios_ia.buscar_registros_estructurados(**filtros, limite=25)
    cantidad = int(conteo.get("cantidad") if isinstance(conteo, dict) else 0)
    registros = filas.get("registros", []) if isinstance(filas, dict) else []
    guardar_contexto(
        session_obj,
        chat_id=chat_id,
        filtros=filtros,
        cantidad=cantidad,
        registros=registros,
        etiqueta=rango.etiqueta,
        origen="conteo_temporal",
    )
    tipo = _tipo_conteo(mensaje)
    if rango.etiqueta == "hoy":
        pref = "Hoy"
    elif rango.etiqueta == "ayer":
        pref = "Ayer"
    else:
        pref = f"Para {rango.etiqueta}"
    if tipo == "unicos":
        return f"{pref} encontré {cantidad} {_plural(cantidad, 'asegurado único', 'asegurados únicos')} en la cartera."
    return f"{pref} encontré {cantidad} {_plural(cantidad, 'registro emitido', 'registros emitidos')} en la cartera."


def _es_pronombre_o_followup_registro(mensaje: str) -> bool:
    t = normalizar(mensaje)
    if not t or len(t.split()) > 8:
        return False
    patrones = (
        r"\b(sus|su|ese|esa|eso|el mismo|la misma|el anterior|el de hoy|el que cargue|el que te dije)\b",
        r"^y\s+(la\s+)?(patente|cia|compania|vehiculo|medio|cp|importe|precio|mail|telefono|numero)\b",
        r"^(patente|cia|compania|vehiculo|medio de pago|cp|importe|precio|mail|telefono|numero)\??$",
        r"^(decime|dame|pasame|mostrame|mostrame|tirame)\s+(sus|su|los|las)?\s*(detalles|datos)\b",
        r"^(cuanto paga|cuanto sale|que paga|que importe)\??$",
    )
    return any(re.search(p, t) for p in patrones)


def _campo_pedido(mensaje: str) -> tuple[str, tuple[str, ...]] | None:
    t = normalizar(mensaje)
    campos = [
        ("Patente", ("PATENTE", "DOMINIO"), ("patente", "dominio")),
        ("Vehículo", ("VEHICULO", "VEHÍCULO", "MARCA MODELO", "MODELO"), ("vehiculo", "auto", "moto")),
        ("Compañía", ("CIA", "COMPAÑIA", "COMPAÑÍA", "COMPANIA", "ASEGURADORA"), ("cia", "compania", "aseguradora")),
        ("Medio de pago", ("MEDIO DE PAGO", "PAGO", "FORMA DE PAGO"), ("medio", "pago", "cuponera", "cbu", "credito")),
        ("Código postal", ("CP", "CODIGO POSTAL", "CÓDIGO POSTAL"), ("cp", "codigo postal")),
        ("Importe aprox.", ("IMPORTE APROX", "IMPORTE", "PRECIO", "PREMIO"), ("importe", "precio", "paga", "sale")),
        ("Mail", ("MAIL", "EMAIL", "CORREO"), ("mail", "email", "correo")),
        ("Teléfono/contacto", ("NUMERO", "TELEFONO", "TELÉFONO", "CELULAR"), ("telefono", "numero", "contacto")),
    ]
    for etiqueta, aliases, claves in campos:
        if any(c in t for c in claves):
            return etiqueta, aliases
    return None


def _formatear_registro(fila: dict) -> str:
    datos = [
        ("Asegurado", _valor(fila, "ASEGURADO", "CLIENTE", "NOMBRE", "NOMBRE Y APELLIDO")),
        ("Vehículo", _valor(fila, "VEHICULO", "VEHÍCULO", "MARCA MODELO", "MODELO")),
        ("Patente", _valor(fila, "PATENTE", "DOMINIO")),
        ("Compañía", _valor(fila, "CIA", "COMPAÑIA", "COMPAÑÍA", "COMPANIA", "ASEGURADORA")),
        ("Medio de pago", _valor(fila, "MEDIO DE PAGO", "PAGO", "FORMA DE PAGO")),
        ("Importe aprox.", _valor(fila, "IMPORTE APROX", "IMPORTE", "PRECIO", "PREMIO")),
        ("Código postal", _valor(fila, "CP", "CODIGO POSTAL", "CÓDIGO POSTAL")),
        ("Emitido día", _valor(fila, "EMITIDO DÍA:", "EMITIDO DIA", "EMITIDO", "FECHA EMISION", "FECHA DE EMISION")),
        ("Teléfono/contacto", _valor(fila, "NUMERO", "TELEFONO", "TELÉFONO", "CELULAR")),
        ("Mail", _valor(fila, "MAIL", "EMAIL", "CORREO")),
    ]
    lineas = [f"• **{k}:** {v}" for k, v in datos if str(v or "").strip()]
    return "\n".join(lineas) if lineas else "El registro está vacío o no tiene campos reconocibles."


def _resumen_opciones(registros: list[dict]) -> str:
    lineas = []
    for i, fila in enumerate(registros[:10], 1):
        nombre = _valor(fila, "ASEGURADO", "CLIENTE", "NOMBRE", "NOMBRE Y APELLIDO") or "Sin nombre"
        patente = _valor(fila, "PATENTE", "DOMINIO")
        vehiculo = _valor(fila, "VEHICULO", "VEHÍCULO", "MARCA MODELO", "MODELO")
        cia = _valor(fila, "CIA", "COMPAÑIA", "COMPAÑÍA", "COMPANIA", "ASEGURADORA")
        extras = " · ".join(x for x in (patente, vehiculo, cia) if x)
        lineas.append(f"{i}. {nombre}" + (f" — {extras}" if extras else ""))
    return "\n".join(lineas)


def _indice_ordinal(mensaje: str) -> int | None:
    t = normalizar(mensaje)
    mapa = {
        "primero": 0, "primera": 0, "uno": 0,
        "segundo": 1, "segunda": 1, "dos": 1,
        "tercero": 2, "tercera": 2, "tres": 2,
        "cuarto": 3, "cuarta": 3, "cuatro": 3,
        "quinto": 4, "quinta": 4, "cinco": 4,
        "sexto": 5, "sexta": 5, "seis": 5,
        "septimo": 6, "septima": 6, "siete": 6,
        "octavo": 7, "octava": 7, "ocho": 7,
        "noveno": 8, "novena": 8, "nueve": 8,
        "decimo": 9, "decima": 9, "diez": 9,
        # -1 significa "último elemento del conjunto activo" y se resuelve
        # contra el tamaño real de la lista, no como un número fijo.
        "ultimo": -1, "ultima": -1,
    }
    m = re.match(r"^(?:el|la)?\s*(\d{1,2})\s*$", t)
    if m:
        return int(m.group(1)) - 1
    for palabra, idx in mapa.items():
        if re.search(rf"\b{palabra}\b", t):
            return idx
    return None


def _indices_por_identidad_contextual(mensaje: str, registros: list[dict]) -> list[int]:
    """Resuelve nombre/patente/vehículo dentro del conjunto activo sin Gemini.

    Es deliberadamente conservador: coincidencia exacta o, para nombres de dos
    o más palabras, todas las palabras contenidas en un único nombre. No usa
    fuzzy matching para no elegir un asegurado arbitrariamente.
    """
    q = normalizar(mensaje).strip(" .,:;¿?¡!")
    q = re.sub(r"^(?:mostrame|mostrar|ver|dame|decime|pasame|el de|la de)\s+", "", q).strip()
    if not q:
        return []

    exactos: list[int] = []
    nombres_parciales: list[int] = []
    palabras_q = [x for x in q.split() if len(x) >= 2]

    for idx, fila in enumerate(registros[:10]):
        nombre = normalizar(_valor(fila, "ASEGURADO", "CLIENTE", "NOMBRE", "NOMBRE Y APELLIDO"))
        patente = normalizar(_valor(fila, "PATENTE", "DOMINIO"))
        vehiculo = normalizar(_valor(fila, "VEHICULO", "VEHÍCULO", "MARCA MODELO", "MODELO"))
        if q and q in {nombre, patente, vehiculo}:
            exactos.append(idx)
            continue
        # Nombre completo escrito en otro orden o con pequeñas diferencias de
        # espacios: exige al menos dos tokens para evitar que "juan" elija a
        # una persona al azar.
        if len(palabras_q) >= 2 and nombre and all(p in nombre.split() for p in palabras_q):
            nombres_parciales.append(idx)

    return exactos or nombres_parciales


def responder_followup_registro(mensaje: str, *, session_obj, chat_id) -> str | None:
    ctx = obtener_contexto(session_obj, chat_id)
    indice = _indice_ordinal(mensaje)
    if not ctx:
        t = normalizar(mensaje)
        if "de hoy" in t or "el hoy" in t:
            rango = RangoTemporal(office_today(), office_today(), "hoy")
            filtros_hoy = rango.filtros()
            resultado_hoy = servicios_ia.buscar_registros_estructurados(**filtros_hoy, limite=25)
            registros_hoy = list(resultado_hoy.get("registros") or []) if isinstance(resultado_hoy, dict) else []
            cantidad_hoy = int(resultado_hoy.get("cantidad") or 0) if isinstance(resultado_hoy, dict) else 0
            guardar_contexto(session_obj, chat_id=chat_id, filtros=filtros_hoy, cantidad=cantidad_hoy, registros=registros_hoy, etiqueta="hoy", origen="referencia_temporal_directa")
            if cantidad_hoy == 1 and registros_hoy:
                return _formatear_registro(registros_hoy[0])
            if cantidad_hoy > 1:
                return (
                    f"Hoy encontré {cantidad_hoy} registros, así que no voy a elegir uno arbitrariamente.\n\n"
                    f"{_resumen_opciones(registros_hoy)}\n\n"
                    "Decime cuál querés ver, por ejemplo: `el segundo`."
                )
            return "Hoy no encontré registros emitidos con fecha cargada en la cartera."
        if _es_pronombre_o_followup_registro(mensaje):
            return "¿De qué registro querés los detalles? Decime nombre, patente o fecha para ubicarlo."
        return None

    # Un contexto viejo de cartera no debe disparar una lectura de Sheets ante
    # mensajes independientes como "hola". Además de pronombres/ordinales,
    # permitimos seleccionar por nombre o patente exactos dentro del conjunto
    # anterior, por ejemplo "BAO GABRIEL ROBERTO".
    registros_ctx = list(ctx.get("registros") or [])[:10]
    coincidencias_ctx = _indices_por_identidad_contextual(mensaje, registros_ctx)
    if indice is None and not coincidencias_ctx and not _es_pronombre_o_followup_registro(mensaje):
        return None

    filtros = dict(ctx.get("filtros") or {})
    resultado = servicios_ia.buscar_registros_estructurados(**filtros, limite=25)
    registros = list(resultado.get("registros") or []) if isinstance(resultado, dict) else []
    cantidad = int(resultado.get("cantidad") or ctx.get("cantidad") or 0) if isinstance(resultado, dict) else int(ctx.get("cantidad") or 0)

    if indice is not None and registros:
        indice_real = len(registros[:10]) - 1 if indice == -1 else indice
        if 0 <= indice_real < min(len(registros), 10):
            elegido = registros[indice_real]
            guardar_contexto(session_obj, chat_id=chat_id, filtros=filtros, cantidad=1, registros=[elegido], etiqueta=ctx.get("etiqueta", ""), origen="seleccion_productor")
            return "Listo, tomo ese registro como referencia:\n\n" + _formatear_registro(elegido)
        return "No tengo esa opción en la lista anterior."

    # Recalcula la coincidencia contra los registros frescos del mismo filtro.
    coincidencias = _indices_por_identidad_contextual(mensaje, registros)
    if len(coincidencias) == 1:
        elegido = registros[coincidencias[0]]
        guardar_contexto(session_obj, chat_id=chat_id, filtros=filtros, cantidad=1, registros=[elegido], etiqueta=ctx.get("etiqueta", ""), origen="seleccion_productor_identidad")
        return "Listo, tomo ese registro como referencia:\n\n" + _formatear_registro(elegido)
    if len(coincidencias) > 1:
        opciones = [registros[i] for i in coincidencias[:10]]
        return (
            "Encontré más de un registro que coincide dentro del conjunto anterior. Elegí uno:\n\n"
            + _resumen_opciones(opciones)
        )

    if cantidad <= 0 or not registros:
        return "No tengo un registro activo para detallar. En la consulta anterior no había resultados con esos filtros."

    if cantidad > 1:
        return (
            f"Tengo {cantidad} registros en ese conjunto, así que no voy a elegir uno arbitrariamente.\n\n"
            f"{_resumen_opciones(registros)}\n\n"
            "Decime cuál querés ver, por ejemplo: `el segundo`."
        )

    fila = registros[0]
    pedido = _campo_pedido(mensaje)
    if pedido:
        etiqueta, aliases = pedido
        valor = _valor(fila, *aliases)
        return f"**{etiqueta}:** {valor or 'No consta en el registro.'}"
    return _formatear_registro(fila)
