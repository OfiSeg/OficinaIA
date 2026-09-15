"""Comandos determinísticos del chat.

Mantiene /envios ya y /guardar asegurado sin Gemini, y agrega ARCA/CUIT
como flujo determinístico de base interna. No conoce Flask ni escribe sesión:
recibe historial/contexto/adjuntos como dependencias y devuelve payloads.
"""
from dataclasses import dataclass, field
import re

import dispatch_service
import arca_service
import insured_profile
from companias import normalizar_compania
from envios_ya_utils import normalizar_patente, normalizar_telefono_argentina, preparar_envios_ya


@dataclass
class CommandResult:
    atendido: bool = False
    respuesta: str | None = None
    propuesta_excel: dict | None = None
    texto_envios_ya: str | None = None
    libro_id: str | None = None
    payload_extra: dict = field(default_factory=dict)


def normalizar_telefono(valor):
    telefono, _error = normalizar_telefono_argentina(valor)
    return telefono


def buscar_asegurado_por_patente(patente_buscada, *, leer_excel, normalizar_encabezado, libro_id="1"):
    patente_norm = normalizar_patente(patente_buscada)
    if not patente_norm:
        return None
    datos = leer_excel(libro_id)
    filas = datos.get("filas") or []
    if not filas:
        return None
    encabezados = filas[0]
    indices = {
        normalizar_encabezado(encabezado): i
        for i, encabezado in enumerate(encabezados)
        if normalizar_encabezado(encabezado)
    }
    indice_patente = indices.get(normalizar_encabezado("PATENTE"))
    if indice_patente is None:
        return None
    for fila in filas[1:]:
        valor = fila[indice_patente] if indice_patente < len(fila) else ""
        if normalizar_patente(valor) == patente_norm:
            return {encabezados[i]: (fila[i] if i < len(fila) else "") for i in range(len(encabezados))}
    return None


def armar_texto_envios_ya(datos, *, normalizar_encabezado=None):
    # Una sola fuente de verdad para alta individual, comando histórico y masivos.
    # normalizar_encabezado se conserva en la firma por compatibilidad.
    return preparar_envios_ya(datos or {}).texto


def parsear_envios_ya(mensaje):
    texto = str(mensaje or "").strip()
    m = re.match(r"^/envios\s+ya\b\s*(.*)$", texto, re.IGNORECASE)
    if not m:
        return None
    resto = re.sub(r"^\(([^)]*)\)$", r"\1", m.group(1).strip()).strip("'\" ")
    if not resto:
        return {"error": "Usá el formato /envios ya (patente), indicando la patente del vehículo."}
    return {"patente": resto}


def parsear_guardar_asegurado(mensaje):
    texto = str(mensaje or "").strip()
    patron = re.compile(r"^/guardar\s+asegurado\b", re.IGNORECASE)
    if not patron.match(texto):
        return None
    resto = patron.sub("", texto, count=1).strip()
    campos = ("ASEGURADO", "NUMERO", "VEHICULO", "PATENTE", "CIA", "MEDIO DE PAGO", "CP", "MAIL", "TELEFONO")
    libro_id = "1"
    sufijo = re.search(r"(?:,\s*|\s+)([12])\s*$", resto)
    if sufijo:
        libro_id = sufijo.group(1)
        resto = resto[:sufijo.start()].rstrip(" ,")
    valores = re.findall(r"\(([^)]*)\)", resto)
    if valores:
        if len(valores) > len(campos):
            return {"error": "El comando tiene más campos de los esperados."}
        valores = [v.strip() for v in valores]
    elif "," in resto:
        valores = [v.strip() for v in resto.split(",")]
        if len(valores) > len(campos):
            return {"error": "El comando tiene más campos de los esperados."}
    else:
        return {"error": "Usá el formato /guardar asegurado (asegurado) (numero) (vehiculo) (patente) (cia) (medio de pago) (cp) (mail) (telefono opcional)."}

    propuesta = {campo: (valores[i] if i < len(valores) else "") for i, campo in enumerate(campos)}
    placeholders = {"ASEGURADO":"asegurado","NUMERO":"numero","VEHICULO":"vehiculo","PATENTE":"patente","CIA":"cia","MEDIO DE PAGO":"medio de pago","CP":"cp","MAIL":"mail","TELEFONO":"telefono"}
    for campo, placeholder in placeholders.items():
        if propuesta[campo].strip().lower() == placeholder:
            propuesta[campo] = ""
    propuesta["CIA"] = normalizar_compania(propuesta.get("CIA", ""))
    propuesta["ENVIOS YA"] = ""
    return {"propuesta": propuesta, "libro_id": libro_id, "valida": bool(propuesta["ASEGURADO"] and (propuesta["NUMERO"] or propuesta["PATENTE"]))}



_ORDINALES = {
    "primero": 1, "primera": 1, "uno": 1, "un": 1, "1": 1,
    "segundo": 2, "segunda": 2, "dos": 2, "2": 2,
    "tercero": 3, "tercera": 3, "tres": 3, "3": 3,
    "cuarto": 4, "cuarta": 4, "cuatro": 4, "4": 4,
    "quinto": 5, "quinta": 5, "cinco": 5, "5": 5,
    "sexto": 6, "sexta": 6, "seis": 6, "6": 6,
    "septimo": 7, "septima": 7, "séptimo": 7, "séptima": 7, "siete": 7, "7": 7,
    "octavo": 8, "octava": 8, "ocho": 8, "8": 8,
    "noveno": 9, "novena": 9, "nueve": 9, "9": 9,
    "decimo": 10, "decima": 10, "décimo": 10, "décima": 10, "diez": 10, "10": 10,
    "ultimo": -1, "ultima": -1, "último": -1, "última": -1,
}


def _norm_chat(texto):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t






def _indice_seleccion(texto):
    n = _norm_chat(texto).strip(" .")
    n = re.sub(r"^(?:el|la|los|las)\s+", "", n)
    return _ORDINALES.get(n)


def _parece_dni_aislado(texto):
    raw = str(texto or "").strip()
    if not raw:
        return False
    # Dentro de /cuit o /cuil aceptamos DNI históricos de 1 a 8 dígitos.
    # Fuera del comando esta función nunca activa ARCA.
    if not re.fullmatch(r"\d{1,2}(?:\.\d{3}){1,2}|\d{1,8}", raw):
        return False
    dig = re.sub(r"\D", "", raw)
    return 1 <= len(dig) <= 8


def _parece_cuit_aislado(texto):
    raw = str(texto or "").strip()
    return bool(re.fullmatch(r"\d{11}|\d{2}-\d{8}-\d", raw))




def _formatear_resultado_arca(resultado, titulo=None):
    status = (resultado or {}).get("status")
    if status == "padron_not_loaded":
        return (
            "El buscador ARCA está disponible, pero el padrón todavía no fue cargado/actualizado.\n\n"
            "Para cargarlo, colocá `apellidoNombreDenominacion.zip` en la carpeta de OficinaIA y ejecutá:\n\n"
            "`python importar_padron_arca.py apellidoNombreDenominacion.zip`"
        )
    if status == "invalid":
        return resultado.get("message") or "No pude interpretar el dato para buscar en ARCA."
    if status == "not_found":
        dato = resultado.get("dni_mostrar") or resultado.get("query") or "ese dato"
        return f"No encontré coincidencias en el padrón ARCA para {dato}. No invento CUIT/CUIL si el padrón no lo devuelve."
    if status == "found" and resultado.get("cuit"):
        return (
            f"CUIT/CUIL encontrado en ARCA:\n\n"
            f"• Persona: {resultado.get('nombre','')}\n"
            f"• DNI: {resultado.get('dni_mostrar') or arca_service.formatear_dni(resultado.get('dni'))}\n"
            f"• CUIT/CUIL: {resultado.get('cuit_formateado') or arca_service.formatear_cuit(resultado.get('cuit'))}\n\n"
            "Fuente: padrón ARCA interno. Esto no significa que sea asegurado de la oficina."
        )
    candidatos = list((resultado or {}).get("candidates") or [])[:10]
    if candidatos:
        encabezado = titulo or f"Personas encontradas en ARCA para: \"{resultado.get('query') or resultado.get('dni_mostrar') or ''}\""
        lineas = [encabezado.strip(), ""]
        for i, c in enumerate(candidatos, 1):
            lineas.append(f"{i}. {c.get('nombre','')}")
            lineas.append(f"   CUIT/CUIL: {c.get('cuit_formateado') or arca_service.formatear_cuit(c.get('cuit'))}")
            if c.get("dni_mostrar"):
                lineas.append(f"   DNI: {c.get('dni_mostrar')}")
        lineas.append("")
        lineas.append("Cada opción es una persona real del padrón ARCA. Para elegir una, usá el comando explícito, por ejemplo `/cuit 2` o `/cuil 2`.")
        return "\n".join(lineas)
    return "No pude obtener resultados de ARCA."


def _contexto_desde_resultado(resultado):
    candidatos = list((resultado or {}).get("candidates") or [])
    if (resultado or {}).get("status") == "found" and resultado.get("cuit"):
        candidatos = [resultado]
    return {"fuente": "ARCA", "candidates": candidatos[:10]} if candidatos else {"fuente": "ARCA"}


def _resolver_archivo_para_arca(adjuntos):
    items = [a for a in (adjuntos or []) if a is not None]
    if not items:
        return None, "No recibí un archivo del que pueda extraer DNI para buscar CUIT/CUIL."
    try:
        import personal_document_ops
        for tipo in ("dni", "licencia"):
            try:
                resultado_doc = personal_document_ops.procesar_documento_personal(items[:2], tipo_hint=tipo)
                d = resultado_doc.datos or {}
                dni = d.get("dni")
                nombre = " ".join(x for x in (d.get("apellido"), d.get("nombre")) if x).strip()
                if dni:
                    return arca_service.resolver_cuit_por_dni(dni, nombre=nombre), None
            except Exception:
                continue
    except Exception as exc:
        return None, f"No pude leer el DNI del archivo para consultar ARCA en este intento: {exc}"
    return None, "No pude detectar un DNI legible en el archivo. No hago búsqueda ARCA sólo por nombre si no hay intención y datos suficientes."


def parsear_cuit_arca(mensaje, *, historial=None, arca_context=None, source_choice_pending=None, adjuntos=None):
    """Parser ARCA deliberadamente cerrado.

    Contrato de seguridad/UX: ARCA sólo se invoca mediante ``/cuit`` o ``/cuil``.
    Un DNI, CUIT, nombre, la palabra "ARCA" o cualquier frase de lenguaje natural
    fuera de esos comandos debe seguir por el router normal y jamás consultar el
    padrón. Ni siquiera una selección ordinal puede reactivar ARCA sin repetir
    ``/cuit`` o ``/cuil``; el prefijo explícito es obligatorio en cada turno.
    """
    texto = str(mensaje or "").strip()
    if not texto:
        return None

    # ÚNICA puerta de entrada a ARCA.
    m_cmd = re.match(r"^/(?:cuit|cuil)\b\s*(.*)$", texto, re.I)
    if not m_cmd:
        return None

    resto = m_cmd.group(1).strip()
    contexto_base = {"fuente": "ARCA", "activado_por_comando": True}

    # Si el comando anterior devolvió candidatos, la selección también exige
    # el prefijo: `/cuit 2`, `/cuil el segundo`, etc.
    seleccion = _indice_seleccion(resto)
    if seleccion is not None and isinstance(arca_context, dict) and arca_context.get("activado_por_comando"):
        candidatos = list(arca_context.get("candidates") or [])
        seleccion_real = len(candidatos) if seleccion == -1 else seleccion
        if 1 <= seleccion_real <= len(candidatos):
            elegido = dict(candidatos[seleccion_real - 1])
            elegido["status"] = "found"
            elegido["ok"] = True
            return {
                "resultado": elegido,
                "contexto": {
                    "fuente": "ARCA",
                    "activado_por_comando": True,
                    "candidates": candidatos,
                },
                "seleccion": seleccion_real,
            }

    if not resto and adjuntos:
        resultado, error = _resolver_archivo_para_arca(adjuntos)
        if error:
            return {"error": error}
        contexto = _contexto_desde_resultado(resultado)
        contexto["activado_por_comando"] = True
        return {"resultado": resultado, "contexto": contexto}

    if not resto:
        # No dejamos un "modo ARCA" latente. Cada nueva búsqueda exige otra vez
        # /cuit o /cuil, evitando que el mensaje siguiente sea secuestrado.
        return {
            "error": "Usá `/cuit 43384856`, `/cuil 43384856`, `/cuit Ramiro Herrera` o adjuntá un DNI junto con `/cuit`.",
        }

    if _norm_chat(resto) in {"estado", "status"}:
        return {"estado": arca_service.estado_padron(), "contexto": contexto_base}

    if _parece_dni_aislado(resto):
        resultado = arca_service.resolver_cuit_por_dni(resto)
    elif _parece_cuit_aislado(resto):
        c = arca_service.normalizar_cuit(resto)
        resultado = arca_service.resolver_cuit_por_dni(c[2:10]) if c else {"status": "invalid"}
    else:
        # Los nombres sólo se consultan porque el usuario ya escribió /cuit o /cuil.
        resultado = arca_service.buscar_personas_arca(resto, limite=10)

    contexto = _contexto_desde_resultado(resultado)
    contexto["activado_por_comando"] = True
    return {"resultado": resultado, "contexto": contexto}


def parsear_ficha_operativa(mensaje):
    """Busca cartera por una única vía determinística con varios aliases.

    /patente, /asegurado e /info son sólo puertas de entrada al mismo motor
    (igual que /m y /mail). /ficha y /expediente se conservan por compatibilidad.
    Ninguno de estos comandos consulta ARCA ni Gemini.
    """
    texto = str(mensaje or "").strip()
    if not texto:
        return None
    m = re.match(r"^/(?:ficha|expediente|patente|asegurado|info)\b\s*(.*)$", texto, re.I)
    if m:
        objetivo = m.group(1).strip(" :;,.()")
        return {"query": objetivo} if objetivo else {
            "error": "Indicá nombre, patente, teléfono, DNI/CUIT o póliza para buscar en la cartera."
        }
    # Un comando slash ajeno nunca debe ser reinterpretado por la heurística
    # de lenguaje natural de ficha. Esto mantiene /cuit, /cuil, /envios, etc.
    # en el handler explícito que les corresponde.
    if texto.startswith("/"):
        return None
    n = _norm_chat(texto)
    if not re.search(r"\b(?:ficha|expediente)\b", n):
        return None
    # Lenguaje natural explícito: no secuestra nombres sueltos ni consultas generales.
    objetivo = re.sub(
        r"(?i)\b(?:mostrame|mostrar|ver|abrir|armame|arma|ficha|expediente|operativa|operativo|del|de|la|el|asegurado|cliente)\b",
        " ", texto,
    )
    objetivo = re.sub(r"\s+", " ", objetivo).strip(" :;,.¿?¡!")
    return {"query": objetivo} if objetivo else {"error": "Decime de qué asegurado, patente o póliza querés ver la ficha."}


def _formatear_ficha_operativa(ficha):
    status = (ficha or {}).get("status")
    if status == "not_found":
        return f"No encontré registros de cartera para {ficha.get('query') or 'esa búsqueda'}."
    if status == "multiple":
        candidatos = list(ficha.get("candidates") or [])[:10]
        lineas = ["Encontré más de un asegurado. Elegí uno:", ""]
        lineas += [f"{i}. {nombre}" for i, nombre in enumerate(candidatos, 1)]
        return "\n".join(lineas)
    if status != "found":
        return ficha.get("error") or "No pude armar la ficha operativa."
    nombre = ficha.get("asegurado") or ficha.get("query") or "Asegurado"
    total = int(ficha.get("total_registros") or 0)
    veh = len(ficha.get("vehiculos") or [])
    return f"Ficha de {nombre}: {total} registro{'s' if total != 1 else ''} y {veh} vehículo{'s' if veh != 1 else ''} relacionado{'s' if veh != 1 else ''}."

def procesar(mensaje, *, leer_excel, normalizar_encabezado, libros_excel, historial=None, arca_context=None, source_choice_pending=None, adjuntos=None, buscar_perfil=None):
    ficha_req = parsear_ficha_operativa(mensaje)
    if ficha_req is not None:
        if ficha_req.get("error"):
            return CommandResult(True, ficha_req["error"])
        ficha = insured_profile.construir_ficha(ficha_req.get("query"), leer_excel, buscar_persistente=buscar_perfil)
        return CommandResult(
            True,
            _formatear_ficha_operativa(ficha),
            payload_extra={"ficha_operativa_asegurado": ficha},
        )

    arca = parsear_cuit_arca(mensaje, historial=historial, arca_context=arca_context, source_choice_pending=source_choice_pending, adjuntos=adjuntos)
    if arca is not None:
        if arca.get("estado") is not None:
            e = arca["estado"]
            respuesta = (
                f"Estado del padrón ARCA:\n\n"
                f"• Cargado: {'sí' if e.get('cargado') else 'no'}\n"
                f"• Registros: {e.get('registros', 0)}\n"
                f"• Fecha del padrón: {e.get('fecha_padron') or '-'}\n"
                f"• Backend: {e.get('backend') or '-'}"
            )
            return CommandResult(True, respuesta, payload_extra={"arca_context": arca.get("contexto") or {"fuente":"ARCA"}})
        if arca.get("error"):
            # Un error/uso incompleto tampoco deja una fuente activa.
            return CommandResult(True, arca["error"])
        respuesta = _formatear_resultado_arca(arca.get("resultado"))
        payload = {"arca_context": arca.get("contexto") or _contexto_desde_resultado(arca.get("resultado"))}
        return CommandResult(True, respuesta, payload_extra=payload)

    despacho = dispatch_service.procesar_comando_explicito(mensaje)
    if despacho is not None:
        return CommandResult(True, despacho.get("respuesta") or "No pude completar el envío.")

    envios = parsear_envios_ya(mensaje)
    if envios is not None:
        if envios.get("error"):
            return CommandResult(True, envios["error"])
        fila = buscar_asegurado_por_patente(envios["patente"], leer_excel=leer_excel, normalizar_encabezado=normalizar_encabezado)
        if fila is None:
            return CommandResult(True, f"No encontré ningún asegurado con la patente {envios['patente'].upper()} en el Excel. Revisá que esté bien escrita o que el asegurado ya esté guardado.")
        return CommandResult(True, "Te dejo los datos listos para pegar en Envíos Ya:", texto_envios_ya=armar_texto_envios_ya(fila, normalizar_encabezado=normalizar_encabezado))

    guardar = parsear_guardar_asegurado(mensaje)
    if guardar is None:
        return CommandResult()
    if guardar.get("error"):
        return CommandResult(True, guardar["error"])
    libro_id = str(guardar.get("libro_id") or "1")
    libro = libros_excel[libro_id]
    p = guardar["propuesta"]
    respuesta = (
        f"Voy a guardar este asegurado en Excel {libro_id} ({libro['nombre']}):\n\n"
        f"ASEGURADO: {p.get('ASEGURADO','')}\nNUMERO: {p.get('NUMERO','')}\nVEHICULO: {p.get('VEHICULO','')}\n"
        f"PATENTE: {p.get('PATENTE','')}\nCIA: {p.get('CIA','')}\nMEDIO DE PAGO: {p.get('MEDIO DE PAGO','')}\n"
        f"CP: {p.get('CP','')}\nMAIL: {p.get('MAIL','')}\n\n¿Confirmás?"
    )
    propuesta = dict(p)
    propuesta["LIBRO_ID"] = libro_id
    return CommandResult(True, respuesta, propuesta_excel=propuesta, libro_id=libro_id)
