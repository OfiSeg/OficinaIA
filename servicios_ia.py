import re
import os
from pathlib import Path
from google import genai
from google.genai import types
from openpyxl import load_workbook

try:
    from storage_r2 import descargar_excel_interno, EXCEL_INTERNO_R2_KEY
except Exception:
    descargar_excel_interno = None
    EXCEL_INTERNO_R2_KEY = "excel_interno.xlsx"


# ==========================================================
# CONFIGURACIÓN
# ==========================================================



MODELOS_GEMINI = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]

BASE_DIR = Path(__file__).resolve().parent
EXCEL_INTERNO = BASE_DIR / "excel_interno.xlsx"


# ==========================================================
# GEMINI
# ==========================================================

def obtener_cliente_gemini():

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    return genai.Client(
        api_key=api_key
    )



def _texto_fila(fila):
    return " ".join(str(v or "") for v in fila.values()).strip()

def _coincidencia_identificador(pregunta, fila):
    """Devuelve True si la consulta contiene un identificador fuerte de esa fila."""
    q = _normalizar_texto(pregunta)
    for campo in ("PATENTE", "NUMERO", "NRO", "POLIZA", "PÓLIZA"):
        valor = str(fila.get(campo, "")).strip()
        if valor and _normalizar_texto(valor) in q:
            return True
    return False

def _asegurar_excel_local_para_ia():
    """Recupera el Excel interno desde R2 si la copia local no existe.
    No modifica app.py y evita que el chat trabaje con un archivo inexistente
    en una instancia nueva de Render.
    """
    if EXCEL_INTERNO.exists():
        return True
    if descargar_excel_interno is None:
        return False
    try:
        return bool(descargar_excel_interno(EXCEL_INTERNO, EXCEL_INTERNO_R2_KEY))
    except Exception as error:
        print("ERROR RECUPERANDO EXCEL INTERNO PARA IA:", error)
        return False


def _cargar_excel_interno():
    if not _asegurar_excel_local_para_ia():
        return []
    try:
        wb = load_workbook(EXCEL_INTERNO, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            wb.close()
            return []
        headers = [str(x or "").strip().upper() for x in rows[0]]
        datos = []
        for row in rows[1:]:
            fila = {
                headers[i] if i < len(headers) and headers[i] else f"COLUMNA_{i+1}":
                str(row[i] or "").strip()
                for i in range(min(len(headers), len(row)))
            }
            if any(fila.values()):
                datos.append(fila)
        wb.close()
        print("EXCEL INTERNO IA:", len(datos), "registros cargados.")
        return datos
    except Exception as error:
        print("ERROR EXCEL INTERNO:", error)
        return []


def _buscar_en_registros(pregunta, datos, etiqueta):
    if not datos:
        return []

    q = _normalizar_texto(pregunta)
    palabras = [p for p in re.findall(r"[a-z0-9]+", q) if len(p) >= 3]
    cliente_exacto = buscar_cliente_exactamente(pregunta, datos) if any("CLIENTE" in f for f in datos) else None

    # Identificador fuerte: restringimos el contexto únicamente a las filas
    # que contienen ese identificador. Esto evita mezclar pólizas/patentes.
    identificadas = [f for f in datos if _coincidencia_identificador(pregunta, f)]
    if identificadas:
        return [(1000, f) for f in identificadas]

    if cliente_exacto:
        cliente_norm = _normalizar_texto(cliente_exacto)
        filas_cliente = [
            f for f in datos
            if _normalizar_texto(f.get("CLIENTE", "")) == cliente_norm
        ]
        if filas_cliente:
            return [(900, f) for f in filas_cliente]

    resultados = []
    for fila in datos:
        texto = _normalizar_texto(_texto_fila(fila))
        coincidencias = sum(1 for palabra in palabras if palabra in texto)
        if coincidencias:
            resultados.append((coincidencias, fila))
    # Si la consulta nombra una compañía, devolvemos TODAS sus filas.
    # Esto es imprescindible para conteos, listados y agrupaciones: un top-N
    # semántico no puede representar el dataset completo.
    companias = _companias_mencionadas(pregunta, datos)
    if companias:
        campos_cia = _campos_compania(datos)
        filas_compania = [
            f for f in datos
            if any(
                _normalizar_texto(f.get(campo, "")) in companias
                for campo in campos_cia
            )
        ]
        if filas_compania:
            return [(50, f) for f in filas_compania]

    resultados.sort(key=lambda x: x[0], reverse=True)
    return resultados[:50]


# ==========================================================
# CONSULTAS ESTRUCTURADAS SOBRE EL DATASET COMPLETO
# ==========================================================

_ALIAS_CIAS = {
    "ags": "ags",
    "agrosalta": "agrosalta",
    "atm": "atm",
    "prof": "prof",
    "rivadavia": "rivadavia",
    "triunfo": "triunfo",
    "san cristobal": "san cristobal",
    "sancristobal": "sancristobal",
    "mercantil andina": "mercantil andina",
    "mercantilandina": "mercantilandina",
    "euroamerica": "euroamerica",
    "euro america": "euro america",
    "federacion patronal": "federacion patronal",
    "federacion": "federacion",
}


def _identidad_unica(fila):
    # Conserva la lógica original: primero identificadores fuertes y luego
    # cliente/asegurado/nombre y, como último recurso, póliza.
    for aliases in (
        ("DNI", "DOCUMENTO", "CUIT", "CUIL"),
        ("CLIENTE", "ASEGURADO", "NOMBRE"),
        ("POLIZA", "PÓLIZA"),
    ):
        clave = _campo_por_alias(fila, aliases)
        if clave and str(fila.get(clave, "")).strip():
            return _normalizar_texto(fila.get(clave, ""))
    return None


def _deduplicar_personas(filas):
    """Deduplica sólo cuando hay un identificador razonablemente confiable."""
    if not filas:
        return []
    ids = []
    sin_id = []
    vistos = set()
    for fila in filas:
        ident = _identidad_unica(fila)
        if ident:
            if ident in vistos:
                continue
            vistos.add(ident)
            ids.append(fila)
        else:
            sin_id.append(fila)
    return ids + sin_id


def _campo_identidad_principal(datos):
    if not datos:
        return None
    aliases = (
        "DNI", "DOCUMENTO", "CUIT", "CUIL",
        "CLIENTE", "ASEGURADO", "NOMBRE",
    )
    for fila in datos[: min(len(datos), 20)]:
        campo = _campo_por_alias(fila, aliases)
        if campo and any(str(f.get(campo, "")).strip() for f in datos):
            return campo
    return None


def _campos_compania(datos):
    if not datos:
        return []
    candidatos = ("CIA", "COMPAÑIA", "COMPANIA", "COMPAÑÍA", "ASEGURADORA", "COMPANIA DE SEGUROS")
    presentes = set()
    for fila in datos[: min(len(datos), 3)]:
        presentes.update(str(k).strip().upper() for k in fila.keys())
    return [c for c in candidatos if c in presentes]


def _companias_mencionadas(pregunta, datos):
    q = _normalizar_texto(pregunta)
    mencionadas = set()
    for alias, canon in _ALIAS_CIAS.items():
        if re.search(rf"\b{re.escape(_normalizar_texto(alias))}\b", q):
            mencionadas.add(_normalizar_texto(canon))
    return mencionadas


def _campo_por_alias(fila, aliases):
    for alias in aliases:
        for clave in fila.keys():
            if _normalizar_texto(clave) == _normalizar_texto(alias):
                return clave
    return None


def _filas_por_companias(pregunta, datos):
    mencionadas = _companias_mencionadas(pregunta, datos)
    campos = _campos_compania(datos)
    if not mencionadas or not campos:
        return datos
    salida = []
    for fila in datos:
        valor = next((fila.get(c, "") for c in campos), "")
        if _normalizar_texto(valor) in mencionadas:
            salida.append(fila)
    return salida



def buscar_en_excel_interno(pregunta):
    datos = _cargar_excel_interno()
    resultados = _buscar_en_registros(pregunta, datos, "Excel interno")
    if not resultados:
        return ""

    contexto = "FUENTE: Excel interno de OficinaIA\n"
    for _, fila in resultados:
        contexto += "REGISTRO INTERNO:\n"
        for campo, valor in fila.items():
            contexto += f"{campo}: {valor}\n"
        contexto += "\n--------------------\n"
    return contexto


def _normalizar_texto(texto):
    import unicodedata
    texto = str(texto or '').lower().strip()
    texto = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in texto if not unicodedata.combining(c))



# ==========================================================
# CONSULTAR GEMINI
# ==========================================================

def _tokens_relevancia(texto):
    return [p for p in re.findall(r"[a-z0-9]+", _normalizar_texto(texto)) if len(p) >= 3]


def _puntuar_fuente(pregunta, contenido, prioridad=0):
    """Puntúa una fuente por relevancia, sin confundir cantidad con calidad."""
    q = _normalizar_texto(pregunta)
    tokens = set(_tokens_relevancia(q))
    texto = _normalizar_texto(contenido)
    if not tokens or not texto:
        return prioridad

    score = prioridad
    score += sum(1 for token in tokens if token in texto)

    # Identificadores concretos pesan mucho más que coincidencias generales.
    for patron in (
        r"\b[a-z]{2,4}\d{2,6}\b",          # patente/código
        r"\b\d{5,12}\b",                   # número/póliza
    ):
        for identificador in re.findall(patron, q):
            if identificador in texto:
                score += 30

    if len(q) >= 12 and q in texto:
        score += 25
    return score


def _documentos_desde_contexto(contexto):
    """
    Convierte los fragmentos recuperados de PDFs en fuentes individuales.
    Así Gemini no recibe 7 documentos sólo porque todos tuvieron alguna
    coincidencia: cada archivo compite como una fuente propia.
    """
    fuentes = {}

    # PDF adjunto: es la fuente explícita que el usuario puso en el chat.
    adjunto = re.search(
        r"===== PDF ADJUNTADO EN EL CHAT =====(.*?)===== FIN PDF ADJUNTADO =====",
        contexto or "",
        flags=re.S,
    )
    if adjunto:
        bloque = adjunto.group(1).strip()
        m = re.search(r"ARCHIVO:\s*([^\n]+)", bloque)
        nombre = m.group(1).strip() if m else "PDF adjunto"
        fuentes[f"PDF adjunto \"{nombre}\""] = bloque

    # Fragmentos de documentación normal.
    bloques = re.findall(
        r"===== FRAGMENTO DE DOCUMENTO =====(.*?)(?=^===== FRAGMENTO DE DOCUMENTO =====|\Z)",
        contexto or "",
        flags=re.S | re.M,
    )
    for bloque in bloques:
        m = re.search(r"ARCHIVO:\s*([^\n]+)", bloque)
        if not m:
            continue
        nombre = m.group(1).strip()
        clave = f'Manual/documento "{nombre}"'
        fuentes[clave] = fuentes.get(clave, "") + "\n" + bloque.strip()

    return fuentes


def _agregar_fuentes(respuesta, fuentes, uso_web=False):
    texto = str(respuesta or "").strip()
    if not texto:
        return texto

    # El modelo ya recibe instrucciones de citar las fuentes seleccionadas.
    # Este respaldo sólo agrega las que realmente se seleccionaron, nunca
    # todas las fuentes consultadas durante el ranking.
    existentes = _normalizar_texto(texto)
    faltantes = [
        fuente for fuente in fuentes
        if _normalizar_texto(fuente) not in existentes
    ]

    if uso_web and not any(
        palabra in existentes
        for palabra in ("internet", "informacion publica", "sitio oficial")
    ):
        if len(fuentes) < 2:
            faltantes.append("Información pública de Internet")

    if not faltantes:
        return texto
    return texto + "\n\n**Fuentes:** " + " · ".join(faltantes)


# ==========================================================
# FUNCTION CALLING DE GEMINI
# ==========================================================

TOOL_DEFINITIONS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="consultar_excel",
            description=(
                "Busca filas relevantes en los datos estructurados de OficinaIA. "
                "Busca únicamente en el Excel interno de OficinaIA. "
                "Devuelve filas relevantes y la fuente."
            ),
            parameters_json_schema={"type": "object", "properties": {"pregunta_o_filtro": {"type": "string"}}, "required": ["pregunta_o_filtro"]},
        ),
        types.FunctionDeclaration(
            name="contar_registros",
            description=(
                "Realiza conteos exactos sobre TODAS las filas del dataset estructurado. "
                "Puede filtrar por compañía, campo y valor. Para personas, deduplica usando "
                "la lógica validada de OficinaIA. Nunca recorta a top-N."
            ),
            parameters_json_schema={"type": "object", "properties": {"compania": {"type": "string"}, "campo": {"type": "string"}, "valor": {"type": "string"}}},
        ),
        types.FunctionDeclaration(
            name="buscar_en_manuales",
            description="Busca fragmentos relevantes en los manuales y PDFs de OficinaIA.",
            parameters_json_schema={"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]},
        ),
        types.FunctionDeclaration(
            name="buscar_en_metadatos",
            description=(
                "Busca en fichas de texto cargadas manualmente por la oficina, "
                "normalmente contenido copiado de PDFs escaneados o no legibles "
                "automáticamente. Usar cuando la pregunta pueda estar respondida "
                "por información cargada a mano."
            ),
            parameters_json_schema={"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]},
        ),
        types.FunctionDeclaration(
            name="proponer_registro_excel",
            description=(
                "Cuando la conversación contiene datos suficientes de un asegurado "
                "(cliente, póliza, patente, compañía, etc.) y el usuario pide guardarlo "
                "o agregarlo a la planilla, arma un registro propuesto con esos campos "
                "para que el usuario lo confirme antes de guardarlo. No guarda nada "
                "directamente."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "campos": {
                        "type": "object",
                        "description": "Pares campo:valor detectados, por ejemplo CLIENTE, POLIZA, PATENTE, CIA."
                    }
                },
                "required": ["campos"],
            },
        ),
        types.FunctionDeclaration(
            name="buscar_vehiculos",
            description="Busca vehículos y patentes en los registros estructurados, filtrando opcionalmente por compañía, tipo o cliente.",
            parameters_json_schema={"type": "object", "properties": {"compania": {"type": "string"}, "tipo": {"type": "string"}, "cliente": {"type": "string"}}},
        ),
        types.FunctionDeclaration(
            name="buscar_en_internet",
            description="Busca información pública actualizada en Internet cuando sea necesaria para responder la pregunta.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "consulta": types.Schema(type="STRING", description="Consulta de búsqueda web."),
                },
                required=["consulta"],
            ),
        ),
    ])
]


def _dataset_estructurado():
    return _cargar_excel_interno(), "Excel interno"


def _valor_campo(fila, campo):
    if not campo:
        return None
    clave = _campo_por_alias(fila, (campo,))
    return fila.get(clave, "") if clave else None


def _filtrar_filas(filas, compania=None, campo=None, valor=None):
    salida = list(filas)
    if compania:
        objetivo = _normalizar_texto(compania)
        campos = []
        for f in salida[:20]:
            for alias in ("CIA", "COMPAÑIA", "COMPANIA", "COMPAÑÍA", "ASEGURADORA", "COMPANIA DE SEGUROS"):
                c = _campo_por_alias(f, (alias,))
                if c and c not in campos:
                    campos.append(c)
        salida = [f for f in salida if _normalizar_texto(next((f.get(c, "") for c in campos), "")) == objetivo]
    if campo and valor is not None:
        objetivo = _normalizar_texto(valor)
        salida = [f for f in salida if objetivo in _normalizar_texto(_valor_campo(f, campo) or "")]
    return salida


def consultar_excel(pregunta_o_filtro):
    """Herramienta de búsqueda estructurada; no decide intención."""
    interno = _cargar_excel_interno()
    datos, fuente = _dataset_estructurado()
    if not datos:
        return {"fuente": fuente, "registros": [], "cantidad": 0}

    q = _normalizar_texto(pregunta_o_filtro)
    identificadas = [f for f in datos if _coincidencia_identificador(pregunta_o_filtro, f)]
    if identificadas:
        filas = identificadas
    else:
        palabras = [p for p in re.findall(r"[a-z0-9]+", q) if len(p) >= 3]
        puntuadas = []
        for fila in datos:
            texto = _normalizar_texto(_texto_fila(fila))
            score = sum(1 for palabra in palabras if palabra in texto)
            if score:
                puntuadas.append((score, fila))
        puntuadas.sort(key=lambda x: x[0], reverse=True)
        filas = [fila for _, fila in puntuadas[:100]]

    return {
        "fuente": fuente,
        "cantidad": len(filas),
        "registros": filas,
    }


def contar_registros(compania=None, campo=None, valor=None):
    datos, fuente = _dataset_estructurado()
    filas = _filtrar_filas(datos, compania=compania, campo=campo, valor=valor)
    campo_identidad = _campo_identidad_principal(filas)
    if campo_identidad:
        filas_contadas = _deduplicar_personas(filas)
    else:
        filas_contadas = filas
    return {
        "fuente": fuente,
        "total_filas": len(filas),
        "campo_identidad": campo_identidad,
        "total_unicos": len(filas_contadas),
    }


def proponer_registro_excel(campos):
    """Prepara una propuesta de alta; nunca escribe directamente en el Excel."""
    if not isinstance(campos, dict):
        return {"propuesta": {}}
    propuesta = {
        str(clave).strip(): str(valor).strip()
        for clave, valor in campos.items()
        if str(clave).strip() and str(valor).strip()
    }
    return {"propuesta": propuesta}


def buscar_en_manuales(consulta):
    """Reutiliza buscar_en_documentos de app.py sin alterar su lógica."""
    try:
        from app import buscar_en_documentos
        resultados = buscar_en_documentos(consulta)
        return {
            "cantidad": len(resultados),
            "fragmentos": resultados,
        }
    except Exception as error:
        print("ERROR BUSCANDO EN MANUALES:", error)
        return {"cantidad": 0, "fragmentos": [], "error": "No se pudieron consultar los manuales."}



def _cargar_metadatos():
    """Carga las fichas de texto compartidas por toda la oficina."""
    try:
        from app import conectar_db
        with conectar_db() as db:
            rows = db.execute(
                "SELECT id, titulo, contenido, actualizado_en FROM metadatos "
                "ORDER BY actualizado_en DESC, id DESC"
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as error:
        print("ERROR CARGANDO METADATOS:", error)
        return []


def _chunks_metadato(contenido, chunk_chars=1400, overlap=220):
    """Divide fichas largas en fragmentos manejables para la recuperación."""
    texto = str(contenido or "").strip()
    if not texto:
        return []
    if len(texto) <= chunk_chars:
        return [texto]
    chunks = []
    inicio = 0
    while inicio < len(texto):
        fin = min(len(texto), inicio + chunk_chars)
        if fin < len(texto):
            corte = max(
                texto.rfind("\n", inicio + 700, fin),
                texto.rfind(". ", inicio + 700, fin),
                texto.rfind("; ", inicio + 700, fin),
            )
            if corte > inicio + 700:
                fin = corte + 1
        fragmento = texto[inicio:fin].strip()
        if fragmento:
            chunks.append(fragmento)
        if fin >= len(texto):
            break
        inicio = max(inicio + 1, fin - overlap)
    return chunks


def _puntuar_metadato(consulta, texto):
    consulta_norm = _normalizar_texto(consulta)
    texto_norm = _normalizar_texto(texto)
    if not consulta_norm or not texto_norm:
        return 0
    tokens = [p for p in re.findall(r"[a-z0-9]+", consulta_norm) if len(p) >= 3]
    if not tokens:
        return 0
    puntuacion = 0
    if len(consulta_norm) >= 8 and consulta_norm in texto_norm:
        puntuacion += 30
    palabras_texto = set(re.findall(r"[a-z0-9]+", texto_norm))
    for i in range(len(tokens) - 1):
        if f"{tokens[i]} {tokens[i+1]}" in texto_norm:
            puntuacion += 10
    for token in tokens:
        if token in palabras_texto:
            puntuacion += min(8, 2 + texto_norm.count(token))
        elif _raiz_simple(token) in {_raiz_simple(x) for x in palabras_texto}:
            puntuacion += 3
    return puntuacion


def buscar_en_metadatos(consulta):
    """
    Busca información en fichas de texto cargadas manualmente por la oficina.
    Las fichas son compartidas entre usuarios y se recuperan por relevancia.
    """
    resultados = []
    for ficha in _cargar_metadatos():
        titulo = str(ficha.get("titulo") or "")
        for fragmento in _chunks_metadato(ficha.get("contenido", "")):
            puntuacion = _puntuar_metadato(consulta, f"{titulo}\n{fragmento}")
            if puntuacion <= 0:
                continue
            resultados.append({
                "id": ficha["id"],
                "titulo": titulo,
                "contenido": fragmento,
                "actualizado_en": ficha.get("actualizado_en"),
                "puntuacion": puntuacion,
            })
    resultados.sort(key=lambda x: x["puntuacion"], reverse=True)
    # Mantener un contexto acotado, priorizando fichas distintas.
    salida = []
    vistos = set()
    for resultado in resultados:
        clave = (resultado["id"], resultado["contenido"])
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append(resultado)
        if len(salida) >= 12:
            break
    return {
        "cantidad": len(salida),
        "fichas": salida,
        "fuente": "Metadatos internos",
    }


def _buscar_vehiculos_filtrados(datos, compania=None, tipo=None, cliente=None):
    filas = list(datos)
    if compania:
        filas = _filtrar_filas(filas, compania=compania)
    if cliente:
        objetivo = _normalizar_texto(cliente)
        filas = [f for f in filas if objetivo in _normalizar_texto(_valor_campo(f, "CLIENTE") or _valor_campo(f, "ASEGURADO") or "")]
    campo_tipo = _campo_por_alias(filas[0], ("TIPO_VEHICULO", "TIPO DE VEHICULO", "TIPO DE VEHÍCULO", "VEHICULO", "VEHÍCULO", "VH")) if filas else None
    if tipo and campo_tipo:
        objetivo = _normalizar_texto(tipo)
        filas = [f for f in filas if objetivo in _normalizar_texto(f.get(campo_tipo, ""))]
    resultado = []
    vistos = set()
    for f in filas:
        veh = str(_valor_campo(f, "VEHICULO") or _valor_campo(f, "VH") or "").strip()
        pat = str(_valor_campo(f, "PATENTE") or "").strip()
        if not veh and not pat:
            continue
        clave = _normalizar_texto(pat or veh)
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(f)
    return resultado


def buscar_vehiculos(compania=None, tipo=None, cliente=None):
    datos, fuente = _dataset_estructurado()
    filas = _buscar_vehiculos_filtrados(datos, compania=compania, tipo=tipo, cliente=cliente)
    return {"fuente": fuente, "cantidad": len(filas), "vehiculos": filas}


def buscar_en_internet(consulta):
    """Ejecuta una búsqueda web mediante la capacidad de Google Search de Gemini."""
    cliente = obtener_cliente_gemini()
    if cliente is None:
        return {"resultado": "Internet no disponible: falta GEMINI_API_KEY."}
    try:
        config = types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2048,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
        respuesta = cliente.models.generate_content(
            model=MODELOS_GEMINI[0],
            contents=consulta,
            config=config,
        )
        return {"resultado": getattr(respuesta, "text", "") or "No encontré resultados públicos suficientes."}
    except Exception as error:
        print("ERROR BUSQUEDA INTERNET:", error)
        return {"resultado": "No se pudo completar la búsqueda en Internet."}


_TOOL_HANDLERS = {
    "consultar_excel": consultar_excel,
    "contar_registros": contar_registros,
    "buscar_en_manuales": buscar_en_manuales,
    "buscar_en_metadatos": buscar_en_metadatos,
    "proponer_registro_excel": proponer_registro_excel,
    "buscar_vehiculos": buscar_vehiculos,
    "buscar_en_internet": buscar_en_internet,
}


def _ejecutar_tool(nombre, argumentos):
    handler = _TOOL_HANDLERS.get(nombre)
    if not handler:
        return {"error": f"Herramienta desconocida: {nombre}"}
    try:
        return handler(**argumentos)
    except Exception as error:
        print(f"ERROR TOOL {nombre}:", error)
        return {"error": f"No se pudo ejecutar {nombre}."}


def _contenido_respuesta(respuesta):
    texto = getattr(respuesta, "text", None)
    if texto:
        return texto.strip()
    return ""


def _partes_function_calls(respuesta):
    calls = []
    candidatos = getattr(respuesta, "function_calls", None)
    if candidatos:
        for call in candidatos:
            calls.append(call)
        return calls
    for candidato in getattr(respuesta, "candidates", []) or []:
        contenido = getattr(candidato, "content", None)
        for parte in getattr(contenido, "parts", []) or []:
            call = getattr(parte, "function_call", None)
            if call:
                calls.append(call)
    return calls


def consultar_gemini(pregunta, contexto="", historial=None):
    cliente = obtener_cliente_gemini()
    if cliente is None:
        return "La IA todavía no está configurada. Falta GEMINI_API_KEY."

    historial = historial or []
    historial_texto = "\n".join(
        f"{'USUARIO' if turno.get('rol') == 'user' else 'ASISTENTE'}: {str(turno.get('contenido', '')).strip()}"
        for turno in historial[-10:]
        if str(turno.get('contenido', '')).strip()
    ) or "Sin historial relevante."

    prompt = f"""
Sos el asistente interno de OficinaIA, una oficina de seguros de Argentina.
Respondé la pregunta completa y no inventes datos.

REGLAS:
- Elegí las herramientas necesarias. No adivines la fuente mediante palabras clave: decidí por el significado de la pregunta.
- Para conteos, usá contar_registros y confiá en su total; nunca cuentes manualmente un subconjunto.
- Para vehículos/patentes, usá buscar_vehiculos.
- Para manuales, pólizas, coberturas, procedimientos o asistencia, usá buscar_en_manuales.
- Para información cargada manualmente de PDFs no legibles, usá buscar_en_metadatos.
- Si el usuario pide guardar o agregar un asegurado/registro a la planilla, usá proponer_registro_excel con los datos detectados; nunca lo guardes vos directamente.
- Para datos estructurados generales, usá consultar_excel.
- Si necesitás información pública actualizada, usá buscar_en_internet.
- Podés llamar varias herramientas en la misma consulta y combinar sus resultados.
- Si un identificador concreto aparece en la pregunta, no mezcles registros de otros identificadores.
- Contestá todos los puntos de una pregunta múltiple.
- Si la evidencia no alcanza, decilo claramente.
- Respondé en español argentino claro y profesional.
- No menciones el funcionamiento interno de las herramientas salvo que sea necesario.

HISTORIAL:
{historial_texto}

CONTEXTO DOCUMENTAL YA DISPONIBLE:
{contexto or 'No hay contexto documental previo.'}

PREGUNTA:
{pregunta}
"""

    contents = [prompt]
    propuesta_excel = None
    for _ in range(5):
        ultimo_error = None
        respuesta = None
        for modelo in MODELOS_GEMINI:
            try:
                config = types.GenerateContentConfig(
                    temperature=0.15,
                    max_output_tokens=4096,
                    tools=TOOL_DEFINITIONS,
                )
                respuesta = cliente.models.generate_content(
                    model=modelo,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as error:
                ultimo_error = error
                print("ERROR GEMINI", modelo, ":", error)
        if respuesta is None:
            print("GEMINI TODOS LOS MODELOS FALLARON:", ultimo_error)
            return "Gemini no está disponible en este momento. Intentá nuevamente en unos segundos."

        calls = _partes_function_calls(respuesta)
        if not calls:
            texto = _contenido_respuesta(respuesta) or "No pude generar una respuesta con la información disponible."
            if propuesta_excel:
                return texto, propuesta_excel
            return texto

        # Conservamos la respuesta del modelo en el historial de contents y agregamos
        # las respuestas de las herramientas. El SDK de Gemini acepta los objetos de
        # respuesta generados por el modelo y los FunctionResponse en el siguiente turno.
        contents.append(respuesta.candidates[0].content if getattr(respuesta, "candidates", None) else respuesta)
        for call in calls:
            nombre = getattr(call, "name", "")
            argumentos = dict(getattr(call, "args", {}) or {})
            print("GEMINI TOOL CALL:", nombre, argumentos)
            resultado = _ejecutar_tool(nombre, argumentos)
            if nombre == "proponer_registro_excel":
                propuesta_excel = resultado.get("propuesta") if isinstance(resultado, dict) else None
            contents.append(types.Part.from_function_response(
                name=nombre,
                response={"resultado": resultado},
            ))

    if propuesta_excel:
        return "No pude completar la consulta después de consultar las fuentes disponibles.", propuesta_excel
    return "No pude completar la consulta después de consultar las fuentes disponibles."

