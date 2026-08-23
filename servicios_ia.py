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
    palabras = list(_expandir_sinonimos_tokens(palabras))
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
# SINÓNIMOS DE DOMINIO (seguros)
# ==========================================================
# El dataset no siempre usa la misma palabra que el usuario ("grúa" en la
# pregunta, "remolque" en la planilla). Sin esto, la primera búsqueda daba 0
# resultados y el prompt forzaba un segundo (y tercer...) intento en el mismo
# request, lo que terminaba en timeout (502) o en una cadena de errores (500).
# Expandiendo la CONSULTA con sinónimos, la primera búsqueda ya encuentra la
# fila correcta la gran mayoría de las veces.
_SINONIMOS_DOMINIO = [
    {"grua", "gruas", "remolque", "remolques", "auxilio", "traslado", "arrastre", "acarreo"},
    {"asistencia", "asistencias", "sat", "auxilio", "socorro"},
    {"choque", "choques", "colision", "colisiones", "siniestro", "siniestros", "accidente", "accidentes"},
    {"robo", "robos", "hurto", "hurtos"},
    {"cristales", "cristal", "vidrios", "vidrio", "parabrisas", "lunas"},
    {"franquicia", "franquicias", "deducible", "deducibles"},
    {"poliza", "polizas"},
    {"vencimiento", "vencimientos", "renovacion", "renovaciones"},
    {"vehiculo", "vehiculos", "auto", "autos", "unidad", "unidades", "rodado", "rodados"},
]


def _expandir_sinonimos_tokens(tokens):
    """Devuelve el conjunto de tokens original + sinónimos conocidos."""
    base = {t for t in tokens if t}
    expandido = set(base)
    for grupo in _SINONIMOS_DOMINIO:
        if base & grupo:
            expandido |= grupo
    return expandido



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
            description=(
                "Busca fragmentos relevantes en los manuales y PDFs de OficinaIA. "
                "Fuente SECUNDARIA respecto a buscar_en_metadatos. Usar después de "
                "metadatos, o cuando metadatos devolvió 0 resultados y la consulta "
                "requiere documentación formal de la compañía (coberturas, "
                "asistencia, remolque, procedimientos)."
            ),
            parameters_json_schema={"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]},
        ),
        types.FunctionDeclaration(
            name="buscar_en_metadatos",
            description=(
                "FUENTE PRIORITARIA. Busca en fichas de texto cargadas manualmente "
                "por la oficina (contenido copiado de PDFs escaneados, no legibles "
                "o resúmenes operativos). Debe usarse ANTES que buscar_en_manuales "
                "en cualquier consulta sobre coberturas, asistencia, remolque, "
                "grúas, límites, condiciones, procedimientos o datos de compañías. "
                "Si devuelve resultados útiles, se puede responder con ellos."
            ),
            parameters_json_schema={"type": "object", "properties": {"consulta": {"type": "string"}}, "required": ["consulta"]},
        ),
        types.FunctionDeclaration(
            name="proponer_registro_excel",
            description=(
                "Cuando el usuario pide guardar o agregar un asegurado a la planilla, "
                "proponé un registro usando EXACTAMENTE estas claves: ASEGURADO, NUMERO, "
                "VEHICULO, PATENTE, ENVIOS YA, CIA, MEDIO DE PAGO, CP, MAIL. "
                "NUMERO acepta DNI o número de póliza según el caso. Nunca inventes un "
                "dato: si falta, dejalo como cadena vacía para que el usuario lo confirme. "
                "Intentá completar siempre todos los campos que estén presentes en el "
                "mensaje, aunque el texto libre no tenga comas. Ejemplo: "
                "'ramiro herrera, 1141492756, Brava Nevada 125, AC123BC, ATM' se mapea "
                "a ASEGURADO=ramiro herrera, NUMERO=1141492756, VEHICULO=Brava Nevada 125, "
                "PATENTE=AC123BC, CIA=ATM. Si el usuario usa sólo espacios como separadores "
                "y la frase es ambigua, no adivines silenciosamente: completá lo seguro y "
                "dejá el resto vacío. Otro ejemplo: 'Juan Perez 123456 ATM' permite "
                "ASEGURADO=Juan Perez, NUMERO=123456, CIA=ATM si no hay datos suficientes "
                "para inferir vehículo o patente. La tool sólo propone; no guarda nada."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "campos": {
                        "type": "object",
                        "properties": {
                            "ASEGURADO": {"type": "string", "description": "Nombre completo del asegurado."},
                            "NUMERO": {"type": "string", "description": "DNI o número de póliza, según el caso."},
                            "VEHICULO": {"type": "string", "description": "Marca/modelo/tipo del vehículo."},
                            "PATENTE": {"type": "string", "description": "Patente del vehículo."},
                            "ENVIOS YA": {"type": "string", "description": "Dato de Envíos Ya, si corresponde."},
                            "CIA": {"type": "string", "description": "Compañía aseguradora."},
                            "MEDIO DE PAGO": {"type": "string", "description": "Medio de pago."},
                            "CP": {"type": "string", "description": "Código postal."},
                            "MAIL": {"type": "string", "description": "Correo electrónico."},
                        },
                        "additionalProperties": False,
                    }
                },
                "required": ["campos"],
            },
        ),
        types.FunctionDeclaration(
            name="guardar_metadato_relevante",
            description=(
                "Propone una ficha de metadato reutilizable cuando la respuesta contiene "
                "un dato objetivo, estable y útil para consultas futuras: por ejemplo una "
                "cantidad de grúas de una compañía, un límite de cobertura, una condición "
                "puntual o un requisito específico. NO guardes conversaciones completas, "
                "opiniones, explicaciones generales, preguntas ni datos temporales. "
                "Usá sólo información respaldada por los resultados de las herramientas "
                "consultadas en esta misma conversación. La propuesta requiere confirmación "
                "del usuario antes de escribirse en la base. Si ya existe un metadato igual "
                "o muy similar, no propongas otro."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "titulo": {
                        "type": "string",
                        "description": "Título corto y descriptivo, idealmente incluyendo compañía y tema."
                    },
                    "contenido": {
                        "type": "string",
                        "description": "El dato puntual reutilizable, en 1-4 frases, sin copiar la conversación completa."
                    },
                },
                "required": ["titulo", "contenido"],
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
    """
    Prepara una propuesta de alta; nunca escribe directamente en el Excel.

    Las claves se normalizan contra el esquema real de la planilla. Los campos
    faltantes se conservan vacíos para que el usuario pueda completarlos en la
    confirmación, en lugar de desaparecer silenciosamente.
    """
    campos_validos = (
        "ASEGURADO",
        "NUMERO",
        "VEHICULO",
        "PATENTE",
        "ENVIOS YA",
        "CIA",
        "MEDIO DE PAGO",
        "CP",
        "MAIL",
    )
    if not isinstance(campos, dict):
        return {"propuesta": {}, "valida": False}

    propuesta = {
        campo: str(campos.get(campo, "") or "").strip()
        for campo in campos_validos
    }

    # Nunca aceptar claves inventadas por el modelo.
    for clave, valor in campos.items():
        clave_norm = _normalizar_texto(clave)
        for campo in campos_validos:
            if _normalizar_texto(campo) == clave_norm:
                propuesta[campo] = str(valor or "").strip()
                break

    tiene_asegurado = bool(propuesta["ASEGURADO"])
    tiene_identificador = bool(propuesta["NUMERO"] or propuesta["PATENTE"])

    return {
        "propuesta": propuesta,
        "valida": bool(tiene_asegurado and tiene_identificador),
        "faltantes_minimos": [
            campo for campo, ok in (
                ("ASEGURADO", tiene_asegurado),
                ("NUMERO o PATENTE", tiene_identificador),
            ) if not ok
        ],
    }


def guardar_metadato_relevante(titulo, contenido):
    """
    Prepara una propuesta de metadato reutilizable; nunca escribe directamente.

    Sólo se aceptan datos objetivos y relativamente estables que puedan
    responder consultas futuras: cifras, cantidades, límites o condiciones
    puntuales de una compañía. Se reutiliza la misma recuperación existente
    para evitar proponer duplicados obvios.
    """
    titulo = str(titulo or "").strip()
    contenido = str(contenido or "").strip()

    if not titulo or not contenido:
        return {"propuesta": None, "valida": False}

    if len(titulo) > 200:
        titulo = titulo[:200]

    # No guardar conversaciones, opiniones, instrucciones temporales ni
    # texto demasiado largo. El metadato debe ser una ficha puntual.
    if len(contenido) > 1200:
        contenido = contenido[:1200].rsplit(" ", 1)[0].strip()

    texto = _normalizar_texto(f"{titulo} {contenido}")
    patrones_descartables = (
        "creo que", "me parece", "quizas", "quiza", "podrias",
        "te recomiendo", "como puedo", "que opinas",
    )
    if any(patron in texto for patron in patrones_descartables):
        return {"propuesta": None, "valida": False, "motivo": "dato_no_objetivo"}

    try:
        existentes = _cargar_metadatos()
        for ficha in existentes:
            if _normalizar_texto(contenido) == _normalizar_texto(ficha.get("contenido", "")):
                return {
                    "propuesta": None,
                    "valida": False,
                    "duplicado": True,
                    "metadato_existente": {
                        "id": ficha.get("id"),
                        "titulo": ficha.get("titulo"),
                    },
                }
    except Exception as error:
        print("ERROR VALIDANDO METADATO PROPUESTO:", error)

    return {
        "propuesta": {
            "titulo": titulo,
            "contenido": contenido,
        },
        "valida": True,
    }



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
    """Carga las fichas de texto compartidas por toda la oficina.

    Intenta primero Neon/Postgres (persistente entre redeploys). Si no está
    disponible, cae a SQLite local para desarrollo.
    """
    # 1) Neon (persistente)
    try:
        from database_pg import listar_metadatos as listar_metadatos_pg
        filas = listar_metadatos_pg()
        if filas is not None:
            print("METADATOS PG:", len(filas), "fichas cargadas.")
            return filas
    except Exception as error:
        print("METADATOS PG no disponible, intento SQLite:", error)

    # 2) SQLite (local / fallback)
    try:
        from app import conectar_db
        with conectar_db() as db:
            rows = db.execute(
                "SELECT id, titulo, contenido, actualizado_en FROM metadatos "
                "ORDER BY actualizado_en DESC, id DESC"
            ).fetchall()
            filas = [dict(row) for row in rows]
            print("METADATOS SQLite:", len(filas), "fichas cargadas.")
            return filas
    except Exception as error:
        print("ERROR CARGANDO METADATOS (SQLite):", error)
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


def _raiz_simple(palabra):
    """Raíz muy simplificada para acercar singular/plural y variaciones
    cercanas (ej. 'grúas'~'grúa', 'remolques'~'remolque') cuando el token
    exacto no matcheó. No es un stemmer real, solo recorta sufijos comunes.
    Esta función faltaba en el archivo original (bug pre-existente) y hacía
    que CUALQUIER búsqueda en metadatos reventara con NameError."""
    p = str(palabra or "")
    for sufijo in ("iciones", "ciones", "mente", "es", "s"):
        if len(p) > len(sufijo) + 3 and p.endswith(sufijo):
            return p[: -len(sufijo)]
    return p


def _puntuar_metadato(consulta, texto):
    consulta_norm = _normalizar_texto(consulta)
    texto_norm = _normalizar_texto(texto)
    if not consulta_norm or not texto_norm:
        return 0
    tokens = [p for p in re.findall(r"[a-z0-9]+", consulta_norm) if len(p) >= 3]
    if not tokens:
        return 0
    tokens = list(_expandir_sinonimos_tokens(tokens))
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
    Fuente prioritaria frente a manuales/PDFs.
    """
    try:
        fichas = _cargar_metadatos()
    except Exception as error:
        print("ERROR buscar_en_metadatos al cargar:", error)
        return {
            "cantidad": 0,
            "fichas": [],
            "fuente": "Metadatos internos",
            "error": "No se pudieron cargar los metadatos.",
        }

    resultados = []
    for ficha in fichas:
        titulo = str(ficha.get("titulo") or "")
        for fragmento in _chunks_metadato(ficha.get("contenido", "")):
            puntuacion = _puntuar_metadato(consulta, f"{titulo}\n{fragmento}")
            if puntuacion <= 0:
                continue
            resultados.append({
                "id": ficha.get("id"),
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
    print(
        f"RETRIEVAL METADATOS: consulta={consulta!r} "
        f"fichas_cargadas={len(fichas)} fragmentos={len(salida)}"
    )
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
        objetivos = _expandir_sinonimos_tokens([_normalizar_texto(tipo)])
        filas = [
            f for f in filas
            if any(o in _normalizar_texto(f.get(campo_tipo, "")) for o in objetivos)
        ]
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
    "guardar_metadato_relevante": guardar_metadato_relevante,
    "buscar_vehiculos": buscar_vehiculos,
    "buscar_en_internet": buscar_en_internet,
}


def _ejecutar_tool(nombre, argumentos):
    handler = _TOOL_HANDLERS.get(nombre)
    if not handler:
        return {"error": f"Herramienta desconocida: {nombre}"}

    herramientas_busqueda = {
        "buscar_en_manuales",
        "buscar_en_metadatos",
        "consultar_excel",
        "buscar_vehiculos",
        "buscar_en_internet",
    }

    def _marcar_vacia(resultado, motivo=""):
        resultado = dict(resultado) if isinstance(resultado, dict) else {"error": str(resultado)}
        resultado["busqueda_vacia"] = True
        resultado["instruccion_reintento"] = (
            "No cierres la respuesta todavía. Debe realizarse una segunda "
            "búsqueda con términos descompuestos o sinónimos relevantes. "
            "Orden obligatorio para consultas documentales: "
            "1) buscar_en_metadatos (prioridad) → 2) buscar_en_manuales. "
            "Si ya buscaste metadatos y dio 0, probá manuales/PDFs. "
            "Si ya buscaste manuales, reformulá o usá sinónimos "
            "(remolque/grúa/asistencia/auxilio/traslado)."
            + (f" Motivo: {motivo}" if motivo else "")
        )
        return resultado

    try:
        resultado = handler(**argumentos)
        if isinstance(resultado, dict) and nombre in herramientas_busqueda:
            cantidad = resultado.get("cantidad")
            # cantidad 0 o presencia de error → forzar reintento
            if cantidad == 0 or resultado.get("error"):
                resultado = _marcar_vacia(
                    resultado,
                    motivo=resultado.get("error") or "sin resultados",
                )
        return resultado
    except Exception as error:
        print(f"ERROR TOOL {nombre}:", error)
        # También marcar vacía para que el flujo de segundo intento se active
        return _marcar_vacia(
            {"error": f"No se pudo ejecutar {nombre}.", "cantidad": 0},
            motivo=str(error),
        )



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
- OficinaIA puede haber recuperado METADATOS INTERNOS PRIORITARIOS antes de esta llamada. Si aparecen dentro del contexto, utilizalos directamente como fuente prioritaria; no afirmes que el dato no está disponible si está allí.
- Si el contexto ya contiene metadatos suficientes para responder, no vuelvas a llamar buscar_en_metadatos() innecesariamente. Podés usarla nuevamente únicamente si necesitás información adicional o una búsqueda más específica.
- Elegí las herramientas necesarias según el significado de la pregunta.
- FUENTE PRINCIPAL Y AUTOSUFICIENTE: buscar_en_metadatos (fichas cargadas a
  mano). Para coberturas, asistencia, remolque, grúas, límites, condiciones,
  procedimientos y datos de compañías, buscá primero ahí y, si hay resultado
  razonable, respondé con eso. NO hace falta abrir manuales en PDF además,
  salvo que el propio resultado de metadatos sea insuficiente o contradictorio.
- buscar_en_manuales (PDFs completos) es una herramienta PESADA y de uso
  EXCEPCIONAL: implica descargar y procesar archivos grandes. Usala ÚNICAMENTE
  cuando el usuario pida explícitamente un manual, documento o PDF por nombre,
  o cuando metadatos haya dado 0 resultados Y el usuario insista en que la
  información debería existir. Nunca la uses como paso automático de rutina.
- Si metadatos da 0 resultados en un tema puntual, está bien responder que no
  tenés esa ficha cargada y sugerir cargarla (guardar_metadato_relevante),
  en lugar de encadenar automáticamente una búsqueda en PDFs.
- No afirmes que la información no existe solo porque la primera búsqueda dio 0;
  probá una reformulación de la MISMA búsqueda en metadatos (sinónimos:
  remolque/grúa/asistencia/auxilio/traslado, singular/plural) antes de descartar.
- Para conteos, usá contar_registros y confiá en su total; nunca cuentes manualmente un subconjunto.
- Para vehículos/patentes, usá buscar_vehiculos.
- Para datos estructurados generales (asegurados, pólizas en planilla), usá consultar_excel.
- Si el usuario pide guardar o agregar un asegurado/registro a la planilla, usá
  proponer_registro_excel. Las columnas reales y únicas son:
  ASEGURADO, NUMERO, VEHICULO, PATENTE, ENVIOS YA, CIA, MEDIO DE PAGO, CP, MAIL.
  NUMERO puede ser DNI o número de póliza. Intentá completar todos los campos presentes.
  Si falta un campo, dejalo vacío; nunca inventes ni omitas silenciosamente un campo
  que el usuario haya dado. La propuesta siempre requiere confirmación.
- Si el usuario usa el comando /guardar asegurado, respetá exactamente el orden:
  ASEGURADO, NUMERO, VEHICULO, PATENTE, CIA, MEDIO DE PAGO, CP, MAIL.
  ENVIOS YA es opcional. No reinterpretes ese orden.
- Si necesitás información pública actualizada, usá buscar_en_internet (también
  es una herramienta de uso puntual, no automático).
- Podés llamar varias herramientas en la misma consulta y combinar sus resultados.
- Si un identificador concreto aparece en la pregunta, no mezcles registros de otros identificadores.
- Contestá todos los puntos de una pregunta múltiple.
- Si después de reformular la búsqueda en metadatos seguís sin evidencia y el
  usuario no pidió explícitamente un manual/PDF, decilo claramente y ofrecé
  cargar una ficha nueva con guardar_metadato_relevante.
- Si la respuesta contiene un dato objetivo, estable y reutilizable para consultas futuras
  (por ejemplo una cantidad de grúas, un límite de cobertura o una condición puntual
  de una compañía), podés llamar guardar_metadato_relevante para PROPONER una ficha.
  No propongas metadatos para conversación descartable, opiniones, saludos, preguntas,
  explicaciones generales ni datos claramente temporales. Nunca guardes directamente.
- Respondé en español argentino claro y profesional, como alguien de una oficina de seguros.
- Cuando el mensaje sea para un cliente, usá la identidad de San José Seguros (cordial, cercana, sin frases robóticas).
- FORMATO: escribí primero de forma natural. Usá formato solo si mejora la lectura.
  Preferí viñetas con • y **negrita** puntual para datos importantes.
  Evitá ###, ####, ***, --- y >>> como decoración. Un nivel de jerarquía alcanza en casi todos los casos.
  Si piden un mensaje para WhatsApp, entregá únicamente el texto listo para copiar y enviar, sin notas ni explicaciones de formato.
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
    propuesta_metadato = None

    # Si una búsqueda devuelve 0, el modelo no puede cerrar la respuesta en ese turno:
    # debe existir al menos una nueva llamada de búsqueda antes de permitir texto final.
    reintento_pendiente = False
    fuentes_reintentadas = set()
    # buscar_en_manuales y buscar_en_internet quedan afuera de este set a
    # propósito: son herramientas pesadas (PDFs completos / búsqueda web) y
    # no deben disparar una vuelta forzada adicional si dan 0 resultados. El
    # reintento automático solo aplica a las fuentes livianas (metadatos,
    # excel, vehículos), que es donde vale la pena insistir con sinónimos
    # antes de responder "no tengo esa información".
    herramientas_busqueda = {
        "buscar_en_metadatos",
        "consultar_excel",
        "buscar_vehiculos",
    }

    # Antes eran 6 vueltas x hasta 3 modelos cada una (hasta 18 llamadas a
    # Gemini encadenadas en un mismo request). Con timeout de gunicorn en
    # 180s, eso terminaba en 502 (timeout) o 500. Con los sinónimos de dominio
    # ya aplicados en la búsqueda, la primera consulta casi siempre encuentra
    # el dato; 3 vueltas alcanzan de sobra para el flujo normal + 1 reintento.
    LIMITE_VUELTAS = 3
    for _ in range(LIMITE_VUELTAS):
        ultimo_error = None
        respuesta = None

        for modelo in MODELOS_GEMINI:
            try:
                config = types.GenerateContentConfig(
                    temperature=0.05,
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
            if propuesta_excel or propuesta_metadato:
                return (
                    "Gemini no está disponible en este momento. La propuesta quedó "
                    "pendiente de confirmación.",
                    propuesta_excel,
                    propuesta_metadato,
                )
            return "Gemini no está disponible en este momento. Intentá nuevamente en unos segundos."

        calls = _partes_function_calls(respuesta)
        if not calls:
            texto = _contenido_respuesta(respuesta) or "No pude generar una respuesta con la información disponible."

            if reintento_pendiente:
                # No se permite cerrar con un "no encontré" o cualquier texto final
                # después de una búsqueda vacía sin que exista una segunda búsqueda.
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text=(
                                "CONTROL DE RECUPERACIÓN: una herramienta de búsqueda "
                                "devolvió 0 resultados o error. No respondas todavía. "
                                "Hacé ahora una segunda búsqueda en buscar_en_metadatos "
                                "con sinónimos (remolque/grúa/asistencia/auxilio/traslado) "
                                "u otra formulación. NO uses buscar_en_manuales salvo que "
                                "el usuario haya pedido explícitamente un manual/PDF por "
                                "nombre: es una herramienta pesada de uso excepcional. "
                                "Sólo después de ese segundo intento en metadatos podés "
                                "responder, aunque sea para decir que no tenés esa ficha "
                                "cargada."
                            )
                        )],
                    )
                )
                continue

            if propuesta_excel or propuesta_metadato:
                return texto, propuesta_excel, propuesta_metadato
            return texto

        contents.append(
            respuesta.candidates[0].content
            if getattr(respuesta, "candidates", None)
            else respuesta
        )

        busqueda_realizada_despues_de_cero = False

        for call in calls:
            nombre = getattr(call, "name", "")
            argumentos = dict(getattr(call, "args", {}) or {})
            print("GEMINI TOOL CALL:", nombre, argumentos)

            if reintento_pendiente and nombre in herramientas_busqueda:
                # La llamada actual satisface el segundo intento obligatorio,
                # aunque el modelo haya elegido una fuente complementaria.
                busqueda_realizada_despues_de_cero = True
                fuentes_reintentadas.add(nombre)

            resultado = _ejecutar_tool(nombre, argumentos)

            if (
                isinstance(resultado, dict)
                and resultado.get("busqueda_vacia")
                and nombre in herramientas_busqueda
                and nombre not in fuentes_reintentadas
            ):
                reintento_pendiente = True

            if nombre == "proponer_registro_excel":
                propuesta_excel = (
                    resultado.get("propuesta")
                    if isinstance(resultado, dict)
                    else None
                )

            if nombre == "guardar_metadato_relevante":
                propuesta_metadato = (
                    resultado.get("propuesta")
                    if isinstance(resultado, dict)
                    else None
                )

            contents.append(types.Part.from_function_response(
                name=nombre,
                response={"resultado": resultado},
            ))

        if busqueda_realizada_despues_de_cero:
            reintento_pendiente = False

    if propuesta_excel or propuesta_metadato:
        return (
            "No pude completar la consulta después de consultar las fuentes disponibles.",
            propuesta_excel,
            propuesta_metadato,
        )
    return "No pude completar la consulta después de consultar las fuentes disponibles."
