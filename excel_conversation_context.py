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
import chat_state


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


def _compactar_registro_contexto(fila: dict, *, detalle: bool) -> dict:
    """Guarda sólo los campos necesarios para continuidad conversacional.

    Flask persiste la sesión en cookie; copiar filas completas de Excel por varios
    chats puede superar el límite práctico del header. El contexto necesita
    identidad para listas y, cuando ya hay un único registro seleccionado, los
    campos que realmente se pueden pedir en un follow-up.
    """
    campos = [
        ("ASEGURADO", ("ASEGURADO", "CLIENTE", "NOMBRE", "NOMBRE Y APELLIDO")),
        ("VEHICULO", ("VEHICULO", "VEHÍCULO", "MARCA MODELO", "MODELO")),
        ("PATENTE", ("PATENTE", "DOMINIO")),
        ("CIA", ("CIA", "COMPAÑIA", "COMPAÑÍA", "COMPANIA", "ASEGURADORA")),
    ]
    if detalle:
        campos.extend([
            ("MEDIO DE PAGO", ("MEDIO DE PAGO", "PAGO", "FORMA DE PAGO")),
            ("IMPORTE APROX", ("IMPORTE APROX", "IMPORTE", "PRECIO", "PREMIO")),
            ("CP", ("CP", "CODIGO POSTAL", "CÓDIGO POSTAL")),
            ("EMITIDO DÍA:", ("EMITIDO DÍA:", "EMITIDO DIA", "EMITIDO", "FECHA EMISION", "FECHA DE EMISION", "FECHA DE REGISTRO")),
            ("NUMERO", ("NUMERO", "TELEFONO", "TELÉFONO", "CELULAR")),
            ("MAIL", ("MAIL", "EMAIL", "CORREO")),
        ])
    compacto = {}
    for destino, aliases in campos:
        valor = _valor(fila or {}, *aliases)
        if valor:
            compacto[destino] = valor
    return compacto


def guardar_contexto(session_obj, *, chat_id, filtros: dict, cantidad: int, registros: list[dict] | None, etiqueta: str, origen: str, extras: dict | None = None):
    # Una única política de estado efímero gobierna cartera/ARCA/alta.
    # Al confirmar CARTERA se invalida ARCA y el contexto expira solo.
    chat_state.cambiar_fuente(session_obj, "CARTERA", chat_id=chat_id)
    cantidad_int = int(cantidad or 0)
    muestra = list(registros or [])[:10]
    # Para una selección única retenemos sus campos detallables; para un
    # conjunto sólo identidad/resumen. Esto mantiene la cookie acotada sin
    # perder selección por nombre/patente ni follow-ups del registro elegido.
    registros_contexto = [
        _compactar_registro_contexto(fila, detalle=(cantidad_int == 1))
        for fila in muestra
    ]
    payload = {
        "tipo": "registro_excel_set",
        "filtros": dict(filtros or {}),
        "cantidad": cantidad_int,
        "registros": registros_contexto,
        "etiqueta": str(etiqueta or "").strip(),
        "origen": str(origen or "").strip(),
    }
    if isinstance(extras, dict):
        payload.update(extras)
    return chat_state.guardar(
        session_obj,
        "registro_contexto_activo",
        payload,
        chat_id=chat_id,
    )


def obtener_contexto(session_obj, chat_id) -> dict | None:
    ctx = chat_state.obtener(session_obj, "registro_contexto_activo", chat_id=chat_id)
    if not isinstance(ctx, dict) or ctx.get("tipo") != "registro_excel_set":
        return None
    return ctx


def limpiar_contexto(session_obj, chat_id=None):
    chat_state.limpiar(session_obj, "registro_contexto_activo", chat_id=chat_id)


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
    """Detecta follow-ups inequívocos sobre UN registro de cartera.

    Pronombres como ``su``/``sus`` por sí solos son demasiado ambiguos: también se
    usan para compañías ("sus coberturas", "sus grúas"). Por eso sólo activamos
    este contexto cuando el mensaje pide campos/detalles propios de un registro.
    """
    t = normalizar(mensaje)
    if not t or len(t.split()) > 10:
        return False

    # Señales documentales/de compañía: nunca deben caer al contexto de cartera.
    if any(x in t for x in (
        "cobertura", "coberturas", "grua", "gruas", "remolque", "remolques",
        "asistencia", "servicio", "servicios", "franquicia", "franquicias",
        "incendio", "robo", "destruccion", "responsabilidad civil", "rc",
    )):
        return False

    patrones = (
        r"^y\s+(la\s+)?(patente|cia|compania|vehiculo|medio|cp|importe|precio|mail|telefono|numero)\b",
        r"^(patente|cia|compania|vehiculo|medio de pago|cp|importe|precio|mail|telefono|numero)\??$",
        r"^(decime|dame|pasame|mostrame|tirame)\s+(sus|su|los|las)?\s*(detalles|datos)\b",
        r"^(sus|su)\s+(patente|cia|compania|vehiculo|medio de pago|cp|importe|precio|mail|telefono|numero)\b",
        r"^(cuanto paga|cuanto sale|que paga|que importe)\??$",
        r"^(ese|esa|el mismo|la misma|el que cargue|el que te dije)\s*(registro|asegurado|cliente)?\s*(detalles|datos)?\??$",
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




def _es_consulta_conteo_simple(mensaje: str) -> bool:
    t = normalizar(mensaje)
    if not re.search(r"\b(cuantos|cuantas|cantidad|total)\b", t):
        return False
    if resolver_rango_temporal(mensaje):
        return False
    # Servicios/coberturas pertenecen al dominio documental; no contar filas.
    if any(x in t for x in (
        "cobertura", "coberturas", "cubre", "cubren", "asistencia", "asistencias",
        "servicio", "servicios", "prestacion", "prestaciones", "kilomet", "franquicia",
    )):
        return False
    entidades = (
        "asegurado", "asegurados", "cliente", "clientes", "persona", "personas",
        "poliza", "polizas", "registro", "registros",
        "remolque", "remolques", "trailer", "trailers", "grua", "gruas",
    )
    if not any(x in t for x in entidades):
        return False
    # Remolque/grúa en tercera persona suele ser asistencia de compañía. Sólo
    # contamos filas cuando el usuario marca posesión/cartera de forma explícita.
    if any(x in t for x in ("remolque", "remolques", "trailer", "trailers", "grua", "gruas")):
        return bool(re.search(r"\b(tengo|tenemos|mis)\b", t) or any(x in t for x in ("mi cartera", "en excel", "en el excel", "planilla")))
    return any(x in t for x in ("tengo", "tenemos", "mi cartera", "cartera", "excel", "planilla", "hay"))


def _filtros_contexto_base(mensaje: str) -> dict:
    """Extrae filtros inequívocos sin delegar semántica a Gemini."""
    t = normalizar(mensaje)
    filtros: dict = {}
    try:
        from companias import aliases_companias
        candidatos = []
        for alias, (_codigo, display) in aliases_companias().items():
            a = normalizar(alias)
            d = normalizar(display)
            for token in {a, d}:
                if token and re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", t):
                    candidatos.append((len(token), display))
        if candidatos:
            candidatos.sort(reverse=True)
            filtros["compania"] = candidatos[0][1]
    except Exception:
        pass
    if not filtros.get("compania"):
        # El dominio documental conoce además aseguradoras no incluidas en la
        # tabla histórica de códigos de emisión. Si aparece una sola de ellas,
        # también sirve como filtro literal de cartera (el motor normaliza ambos
        # lados y no necesita inventar un código canónico nuevo).
        try:
            detectar = getattr(servicios_ia, "_companias_mencionadas_en_consulta", None)
            mencionadas = list(detectar(mensaje) or []) if callable(detectar) else []
            if len(mencionadas) == 1:
                filtros["compania"] = mencionadas[0]
        except Exception:
            pass
    if any(x in t for x in ("remolque", "remolques", "trailer", "trailers")):
        filtros["tipo_vehiculo"] = "remolque"
    elif any(x in t for x in ("grua", "gruas")):
        filtros["tipo_vehiculo"] = "grua"
    return filtros


def responder_conteo_simple(mensaje: str, *, session_obj, chat_id) -> str | None:
    if not _es_consulta_conteo_simple(mensaje):
        return None
    filtros = _filtros_contexto_base(mensaje)
    tipo = _tipo_conteo(mensaje)
    conteo = servicios_ia.contar_registros(**filtros, tipo_conteo=tipo)
    filas = servicios_ia.buscar_registros_estructurados(**filtros, limite=25)
    cantidad = int((conteo or {}).get("cantidad") or 0)
    registros = list((filas or {}).get("registros") or [])
    guardar_contexto(
        session_obj, chat_id=chat_id, filtros=filtros, cantidad=cantidad,
        registros=registros, etiqueta="cartera", origen="conteo_simple",
    )
    compania = str(filtros.get("compania") or "").strip()
    pref = f"En {compania}, " if compania else ""
    if tipo == "unicos":
        return f"{pref}tenés {cantidad} {_plural(cantidad, 'asegurado único', 'asegurados únicos')} en la cartera."
    return f"{pref}hay {cantidad} {_plural(cantidad, 'registro', 'registros')} cargados en el Excel interno."


def _filas_filtradas_completas(filtros: dict) -> list[dict]:
    """Devuelve el conjunto completo; nunca usa previews truncadas."""
    datos, _fuente = servicios_ia._dataset_estructurado()
    permitidos = {"compania", "campo", "valor", "tipo_vehiculo", "desde", "hasta", "campo_fecha"}
    base_kwargs = {k: v for k, v in dict(filtros or {}).items() if k in permitidos and v not in (None, "")}
    filas, _ = servicios_ia._filtrar_filas(datos, **base_kwargs)
    return list(filas)


def _ordenar_registros_cronologicos(filtros: dict) -> list[tuple[int, dict, date | None]]:
    filas = _filas_filtradas_completas(filtros)
    fecha_aliases = ("EMITIDO DÍA:", "EMITIDO DIA", "EMITIDO", "FECHA EMISION", "FECHA DE EMISION", "FECHA DE REGISTRO")
    con_fecha: list[tuple[int, dict, date]] = []
    sin_fecha: list[tuple[int, dict, None]] = []
    for pos, fila in enumerate(filas):
        clave = servicios_ia._campo_por_alias(fila, fecha_aliases)
        fecha = servicios_ia._parsear_fecha_excel(fila.get(clave, "") if clave else "")
        if fecha is None:
            sin_fecha.append((pos, fila, None))
        else:
            con_fecha.append((pos, fila, fecha))
    # Fecha y, en empates, orden físico del Excel. Así "último" es estable.
    con_fecha.sort(key=lambda x: (x[2], x[0]))
    return con_fecha if con_fecha else sin_fecha


def _tipo_extremo(mensaje: str) -> str | None:
    t = normalizar(mensaje)
    if re.search(r"\b(ultimo|ultima|mas reciente|reciente|ultimo cargado|ultima cargada|ultimo registrado|ultima registrada)\b", t):
        return "ultimo"
    if re.search(r"\b(primer|primero|primera|mas antiguo|mas antigua|primer registrado|primera registrada)\b", t):
        return "primero"
    return None


def _es_consulta_extremo_explicita(mensaje: str) -> bool:
    if not _tipo_extremo(mensaje):
        return False
    t = normalizar(mensaje)
    # Estas entidades son inequívocamente de cartera dentro del producto; no
    # obligamos al usuario a repetir "Excel/cartera" para preguntar, por
    # ejemplo, "primer asegurado" o "última póliza".
    entidades = ("asegurado", "asegurados", "cliente", "clientes", "registro", "registros", "poliza", "polizas")
    return any(re.search(rf"(?<![a-z0-9]){re.escape(x)}(?![a-z0-9])", t) for x in entidades)


def _respuesta_extremo(mensaje: str, *, session_obj, chat_id, filtros: dict, origen: str) -> str | None:
    tipo = _tipo_extremo(mensaje)
    if not tipo:
        return None
    ordenados = _ordenar_registros_cronologicos(filtros)
    if not ordenados:
        return "No encontré registros de cartera con esos filtros."
    idx = len(ordenados) - 1 if tipo == "ultimo" else 0
    _pos_fisica, fila, fecha = ordenados[idx]
    guardar_contexto(
        session_obj, chat_id=chat_id, filtros=filtros, cantidad=1, registros=[fila],
        etiqueta="registro seleccionado", origen=origen,
        extras={"navegacion_posicion": idx, "navegacion_total": len(ordenados)},
    )
    nombre = _valor(fila, "ASEGURADO", "CLIENTE", "NOMBRE", "NOMBRE Y APELLIDO") or "Sin nombre"
    if fecha is not None:
        etiqueta = "último" if tipo == "ultimo" else "primer"
        return f"El {etiqueta} asegurado con fecha de registro es **{nombre}**, del **{date_string(fecha)}**.\n\n" + _formatear_registro(fila)
    etiqueta = "último" if tipo == "ultimo" else "primer"
    return f"El {etiqueta} registro del Excel es **{nombre}**. No tiene una fecha de registro interpretable cargada.\n\n" + _formatear_registro(fila)


def responder_extremo_registro(mensaje: str, *, session_obj, chat_id) -> str | None:
    ctx = obtener_contexto(session_obj, chat_id)
    if _es_consulta_extremo_explicita(mensaje):
        filtros = _filtros_contexto_base(mensaje)
        return _respuesta_extremo(mensaje, session_obj=session_obj, chat_id=chat_id, filtros=filtros, origen="extremo_explicito")
    # Follow-up corto como "cuál fue el último" sólo se resuelve si YA hay un
    # contexto real de cartera. Nunca crea cartera a partir del historial textual.
    if ctx and _tipo_extremo(mensaje) and len(normalizar(mensaje).split()) <= 7:
        return _respuesta_extremo(mensaje, session_obj=session_obj, chat_id=chat_id, filtros=dict(ctx.get("filtros") or {}), origen="extremo_followup")
    return None


def responder_navegacion_registro(mensaje: str, *, session_obj, chat_id) -> str | None:
    ctx = obtener_contexto(session_obj, chat_id)
    if not ctx:
        return None
    t = normalizar(mensaje).strip(" .¿?!")
    delta = None
    if re.fullmatch(r"(?:y\s+)?(?:el\s+)?anterior", t):
        delta = -1
    elif re.fullmatch(r"(?:y\s+)?(?:el\s+)?siguiente", t):
        delta = 1
    if delta is None or "navegacion_posicion" not in ctx:
        return None
    ordenados = _ordenar_registros_cronologicos(dict(ctx.get("filtros") or {}))
    actual = int(ctx.get("navegacion_posicion") or 0)
    nuevo = actual + delta
    if not (0 <= nuevo < len(ordenados)):
        return "No hay otro registro en esa dirección dentro del conjunto actual."
    _pos, fila, _fecha = ordenados[nuevo]
    guardar_contexto(
        session_obj, chat_id=chat_id, filtros=dict(ctx.get("filtros") or {}), cantidad=1,
        registros=[fila], etiqueta=ctx.get("etiqueta", ""), origen="navegacion_registro",
        extras={"navegacion_posicion": nuevo, "navegacion_total": len(ordenados)},
    )
    return _formatear_registro(fila)


def responder_referencia_temporal_registro(mensaje: str, *, session_obj, chat_id) -> str | None:
    """Resuelve referencias singulares explícitas como ``el de hoy``.

    Una fecha mencionada en el turno actual SIEMPRE reemplaza el rango viejo; no
    se interpreta como pronombre del conjunto anterior. Si hay más de un registro
    no elegimos arbitrariamente.
    """
    t = normalizar(mensaje).strip(" .¿?!")
    match = re.fullmatch(r"(?:y\s+)?(?:el\s+)?de\s+(hoy|ayer)", t)
    if not match:
        return None
    rango = resolver_rango_temporal(match.group(1))
    if not rango:
        return None
    filtros = rango.filtros()
    resultado = servicios_ia.buscar_registros_estructurados(**filtros, limite=25)
    registros = list((resultado or {}).get("registros") or [])
    cantidad = int((resultado or {}).get("cantidad") or 0)
    guardar_contexto(
        session_obj, chat_id=chat_id, filtros=filtros, cantidad=cantidad,
        registros=registros, etiqueta=rango.etiqueta, origen="referencia_temporal_directa",
    )
    if cantidad == 0:
        return f"No encontré registros emitidos {rango.etiqueta} con fecha cargada en la cartera."
    if cantidad == 1 and registros:
        return _formatear_registro(registros[0])
    return (
        f"{rango.etiqueta.capitalize()} encontré {cantidad} registros, así que no voy a elegir uno arbitrariamente.\n\n"
        f"{_resumen_opciones(registros)}\n\n"
        "Decime cuál querés ver, por ejemplo: `el segundo`."
    )


def responder_consulta_directa(mensaje: str, *, session_obj, chat_id) -> str | None:
    """Entrada determinística única para cartera antes de Gemini."""
    # Los comandos slash tienen dueño propio (/cuit, /cuil, /envios, /flota,
    # etc.). La capa de cartera nunca debe adelantarse a ellos por una palabra
    # o número contenido en el argumento del comando.
    if str(mensaje or "").lstrip().startswith("/"):
        return None

    # Una referencia temporal nueva tiene prioridad sobre cualquier contexto viejo.
    temporal = responder_conteo_temporal(mensaje, session_obj=session_obj, chat_id=chat_id)
    if temporal is not None:
        return temporal
    referencia_temporal = responder_referencia_temporal_registro(mensaje, session_obj=session_obj, chat_id=chat_id)
    if referencia_temporal is not None:
        return referencia_temporal
    conteo = responder_conteo_simple(mensaje, session_obj=session_obj, chat_id=chat_id)
    if conteo is not None:
        return conteo
    extremo = responder_extremo_registro(mensaje, session_obj=session_obj, chat_id=chat_id)
    if extremo is not None:
        return extremo
    nav = responder_navegacion_registro(mensaje, session_obj=session_obj, chat_id=chat_id)
    if nav is not None:
        return nav
    return responder_followup_registro(mensaje, session_obj=session_obj, chat_id=chat_id)

def responder_followup_registro(mensaje: str, *, session_obj, chat_id) -> str | None:
    ctx = obtener_contexto(session_obj, chat_id)
    indice = _indice_ordinal(mensaje)
    if not ctx:
        # Sin un contexto de cartera realmente activo, una frase breve como
        # "y la patente?" no pertenece automáticamente a Excel. Puede estar
        # siguiendo una póliza/PDF u otro dominio del chat, así que dejamos que
        # el router normal la resuelva en vez de secuestrarla con una
        # aclaración de Cartera.
        return None

    # Un contexto viejo de cartera no debe disparar una lectura de Sheets ante
    # mensajes independientes como "hola". Además de pronombres/ordinales,
    # permitimos seleccionar por nombre o patente exactos dentro del conjunto
    # anterior, por ejemplo "BAO GABRIEL ROBERTO".
    registros_ctx = list(ctx.get("registros") or [])[:10]
    coincidencias_ctx = _indices_por_identidad_contextual(mensaje, registros_ctx)
    es_followup = _es_pronombre_o_followup_registro(mensaje)
    if indice is None and not coincidencias_ctx and not es_followup:
        return None

    # Si el turno anterior ya seleccionó exactamente un registro (por ejemplo
    # "cuál fue el último"), ese registro es la fuente del follow-up. No volver
    # a consultar el filtro base porque podría representar toda la cartera y
    # convertir una selección única en cientos de resultados.
    cantidad_ctx = int(ctx.get("cantidad") or 0)
    if indice is None and es_followup and cantidad_ctx == 1 and len(registros_ctx) == 1:
        fila = registros_ctx[0]
        pedido = _campo_pedido(mensaje)
        if pedido:
            etiqueta, aliases = pedido
            valor = _valor(fila, *aliases)
            return f"**{etiqueta}:** {valor or 'No consta en el registro.'}"
        return _formatear_registro(fila)

    filtros = dict(ctx.get("filtros") or {})
    resultado = servicios_ia.buscar_registros_estructurados(**filtros, limite=25)
    registros = list(resultado.get("registros") or []) if isinstance(resultado, dict) else []
    cantidad = int(resultado.get("cantidad") or ctx.get("cantidad") or 0) if isinstance(resultado, dict) else int(ctx.get("cantidad") or 0)

    if indice is not None and registros:
        indice_real = indice
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
