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


def _historial_texto(historial, limite=6):
    partes = []
    for item in list(historial or [])[-limite:]:
        if isinstance(item, dict):
            partes.append(str(item.get("contenido") or ""))
    return "\n".join(partes)


def _fuente_contextual_historial(historial):
    """Devuelve la fuente relevante MÁS RECIENTE, no cualquier mención vieja.

    Antes una búsqueda CUIT de varios mensajes atrás podía dejar ARCA "pegado"
    porque se escaneaban en bloque los últimos mensajes. Eso hacía que un nombre
    suelto posterior pudiera terminar en ARCA aunque la conversación ya estuviera
    trabajando con cartera.
    """
    for item in reversed(list(historial or [])[-8:]):
        if not isinstance(item, dict):
            continue
        h = _norm_chat(item.get("contenido") or "")
        if not h:
            continue
        es_arca = any(x in h for x in ("arca", "cuit", "cuil", "/cuit", "padron"))
        es_cartera = any(x in h for x in ("cartera", "asegurado", "asegurados", "poliza", "polizas", "patente", "vehiculo", "excel", "planilla"))
        if es_arca and not es_cartera:
            return "ARCA"
        if es_cartera:
            return "CARTERA"
    return None


def _contexto_es_arca(historial, arca_context=None):
    if isinstance(arca_context, dict) and arca_context.get("fuente") == "ARCA":
        return True
    return _fuente_contextual_historial(historial) == "ARCA"


def _contexto_es_cartera(historial):
    return _fuente_contextual_historial(historial) == "CARTERA"


def _indice_seleccion(texto):
    n = _norm_chat(texto).strip(" .")
    n = re.sub(r"^(?:el|la|los|las)\s+", "", n)
    return _ORDINALES.get(n)


def _parece_dni_aislado(texto):
    raw = str(texto or "").strip()
    if not raw:
        return False
    # DNI histórico: 1 a 8 dígitos, con puntos opcionales. Evita importes o texto mixto.
    if not re.fullmatch(r"\d{1,2}(?:\.\d{3}){1,2}|\d{6,8}", raw):
        return False
    dig = re.sub(r"\D", "", raw)
    return 6 <= len(dig) <= 8


def _parece_cuit_aislado(texto):
    raw = str(texto or "").strip()
    return bool(re.fullmatch(r"\d{11}|\d{2}-\d{8}-\d", raw))


def _parece_nombre_persona(texto):
    raw = str(texto or "").strip()
    if not raw or len(raw) > 80:
        return False
    if re.search(r"[0-9/@]", raw):
        return False
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{2,}", raw)
    if len(tokens) < 2 or len(tokens) > 5:
        return False
    stop = {"hola", "buen", "buenas", "gracias", "che", "consulta", "poliza", "patente", "asegurado", "seguro"}
    return not any(t.lower() in stop for t in tokens)


def _extraer_objetivo_cuit(texto):
    raw = str(texto or "").strip()
    n = _norm_chat(raw)
    if not any(x in n for x in ("cuit", "cuil", "arca", "padron")):
        return None
    # Priorizar DNI explícito en la misma frase.
    m = re.search(r"(?:dni|documento)\s*(?:de|nro|nº|numero|número)?\s*([0-9.\-]{6,15})", raw, re.I)
    if m:
        return {"tipo": "dni", "valor": m.group(1)}
    cuit = re.search(r"\b\d{2}-?\d{8}-?\d\b", raw)
    if cuit:
        return {"tipo": "cuit", "valor": cuit.group(0)}
    dni = re.search(r"\b\d{1,2}(?:\.\d{3}){1,2}\b|\b\d{6,8}\b", raw)
    if dni:
        return {"tipo": "dni", "valor": dni.group(0)}
    # Sacar palabras de intención y quedarse con el nombre.
    objetivo = re.sub(r"(?i)\b(?:buscame|buscar|busca|buscá|decime|dame|sacame|saca|sacá|resolver|resolve|resolvé|cuit|cuil|arca|padron|padrón|de|del|la|el|para|por|dni|documento|que|qué|tiene|es)\b", " ", raw)
    objetivo = re.sub(r"\s+", " ", objetivo).strip(" :;,.¿?¡!")
    if objetivo:
        return {"tipo": "nombre", "valor": objetivo}
    return {"tipo": "archivo", "valor": ""}


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
        lineas.append("Cada opción es una persona real del padrón ARCA. Si corresponde, indicame el número de opción.")
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


def parsear_cuit_arca(mensaje, *, historial=None, arca_context=None, adjuntos=None):
    texto = str(mensaje or "").strip()
    n = _norm_chat(texto)
    if not texto:
        return None

    seleccion = _indice_seleccion(texto)
    if seleccion is not None and isinstance(arca_context, dict):
        candidatos = list(arca_context.get("candidates") or [])
        seleccion_real = len(candidatos) if seleccion == -1 else seleccion
        if 1 <= seleccion_real <= len(candidatos):
            elegido = dict(candidatos[seleccion_real - 1])
            elegido["status"] = "found"
            elegido["ok"] = True
            return {"resultado": elegido, "contexto": {"fuente": "ARCA", "candidates": candidatos}, "seleccion": seleccion_real}

    m_cmd = re.match(r"^/(?:cuit|cuil)\b\s*(.*)$", texto, re.I)
    if m_cmd:
        resto = m_cmd.group(1).strip()
        if not resto and adjuntos:
            resultado, error = _resolver_archivo_para_arca(adjuntos)
            if error:
                return {"error": error, "contexto": {"fuente": "ARCA"}}
            return {"resultado": resultado, "contexto": _contexto_desde_resultado(resultado)}
        if not resto or resto.lower() in {"estado", "status"}:
            estado = arca_service.estado_padron()
            if resto.lower() in {"estado", "status"}:
                return {"estado": estado, "contexto": {"fuente": "ARCA"}}
            return {"error": "Usá `/cuit 43384856`, `/cuil 43384856`, `/cuit Ramiro Herrera` o adjuntá un DNI con `/cuit`.", "contexto": {"fuente": "ARCA"}}
        if _parece_dni_aislado(resto):
            resultado = arca_service.resolver_cuit_por_dni(resto)
        elif _parece_cuit_aislado(resto):
            c = arca_service.normalizar_cuit(resto)
            resultado = arca_service.resolver_cuit_por_dni(c[2:10]) if c else {"status": "invalid"}
        else:
            resultado = arca_service.buscar_personas_arca(resto, limite=10)
        return {"resultado": resultado, "contexto": _contexto_desde_resultado(resultado)}

    objetivo = _extraer_objetivo_cuit(texto)
    if objetivo:
        if objetivo["tipo"] == "archivo":
            resultado, error = _resolver_archivo_para_arca(adjuntos)
            if error:
                return {"error": error, "contexto": {"fuente": "ARCA"}}
        elif objetivo["tipo"] in {"dni", "cuit"}:
            val = objetivo["valor"]
            if objetivo["tipo"] == "cuit":
                c = arca_service.normalizar_cuit(val)
                val = c[2:10] if c else val
            resultado = arca_service.resolver_cuit_por_dni(val)
        else:
            resultado = arca_service.buscar_personas_arca(objetivo["valor"], limite=10)
        return {"resultado": resultado, "contexto": _contexto_desde_resultado(resultado)}

    if _parece_dni_aislado(texto) and not _contexto_es_cartera(historial):
        resultado = arca_service.resolver_cuit_por_dni(texto)
        return {"resultado": resultado, "contexto": _contexto_desde_resultado(resultado)}

    if _parece_nombre_persona(texto):
        if _contexto_es_arca(historial, arca_context):
            resultado = arca_service.buscar_personas_arca(texto, limite=10)
            return {"resultado": resultado, "contexto": _contexto_desde_resultado(resultado)}
        if not _contexto_es_cartera(historial):
            return {
                "pregunta_fuente": True,
                "respuesta": "¿Querés buscarlo en tu cartera o buscar su CUIT/CUIL en ARCA?\n\n• Mi cartera\n• Padrón ARCA / CUIT",
                "contexto": {"fuente": "ARCA"},
            }
    return None


def parsear_ficha_operativa(mensaje):
    """Detecta sólo pedidos explícitos de ficha/expediente de cartera."""
    texto = str(mensaje or "").strip()
    if not texto:
        return None
    m = re.match(r"^/(?:ficha|expediente)\b\s*(.*)$", texto, re.I)
    if m:
        objetivo = m.group(1).strip(" :;,.()")
        return {"query": objetivo} if objetivo else {"error": "Usá `/ficha Nombre Apellido` o `/ficha PATENTE`."}
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

def procesar(mensaje, *, leer_excel, normalizar_encabezado, libros_excel, historial=None, arca_context=None, adjuntos=None):
    texto_inicial = str(mensaje or "").strip()
    m_patente = re.match(r"^/patente\b\s*(.*)$", texto_inicial, re.I)
    if m_patente:
        patente = normalizar_patente(m_patente.group(1))
        if not patente:
            return CommandResult(True, "Usá `/patente ABC123` para consultar el vehículo en tu cartera.")
        ficha = insured_profile.construir_ficha(patente, leer_excel)
        return CommandResult(
            True,
            _formatear_ficha_operativa(ficha),
            payload_extra={"ficha_operativa_asegurado": ficha},
        )

    ficha_req = parsear_ficha_operativa(mensaje)
    if ficha_req is not None:
        if ficha_req.get("error"):
            return CommandResult(True, ficha_req["error"])
        ficha = insured_profile.construir_ficha(ficha_req.get("query"), leer_excel)
        return CommandResult(
            True,
            _formatear_ficha_operativa(ficha),
            payload_extra={"ficha_operativa_asegurado": ficha},
        )

    arca = parsear_cuit_arca(mensaje, historial=historial, arca_context=arca_context, adjuntos=adjuntos)
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
        if arca.get("pregunta_fuente"):
            return CommandResult(True, arca["respuesta"], payload_extra={"arca_context": arca.get("contexto") or {"fuente":"ARCA"}})
        if arca.get("error"):
            return CommandResult(True, arca["error"], payload_extra={"arca_context": arca.get("contexto") or {"fuente":"ARCA"}})
        respuesta = _formatear_resultado_arca(arca.get("resultado"))
        return CommandResult(True, respuesta, payload_extra={"arca_context": arca.get("contexto") or _contexto_desde_resultado(arca.get("resultado"))})

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
