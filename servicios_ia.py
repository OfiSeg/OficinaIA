import re
import os
import time
from datetime import datetime, date
from pathlib import Path
from google import genai
from google.genai import types
from openpyxl import load_workbook
from companias import normalizar_compania, aliases_companias

try:
    from storage_r2 import descargar_excel_interno, EXCEL_INTERNO_R2_KEY
except Exception:
    descargar_excel_interno = None
    EXCEL_INTERNO_R2_KEY = "excel_interno.xlsx"


# ==========================================================
# CONFIGURACIÓN
# ==========================================================



MODELOS_GEMINI = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
]

# Cache por proceso. OficinaIA mantiene 1 worker mientras el Excel/R2 sea la
# fuente de verdad; con múltiples workers este cache NO sería compartido.
_CACHE_EXCEL = {"datos": None, "cargado_en": 0.0}
TTL_CACHE_EXCEL_SEGUNDOS = 10

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
        api_key=api_key,
        # El timeout del SDK está expresado en milisegundos. Evita que una
        # llamada lenta consuma por sí sola gran parte del timeout de Gunicorn.
        http_options=types.HttpOptions(timeout=30000),
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
    """Asegura el Excel interno para la IA usando la misma fuente que la UI (P0.6).

    Si R2 está configurado, SIEMPRE descarga de R2 (aunque exista copia local
    del repo). Así Gemini no trabaja con el xlsx versionado en git mientras
    la grilla de /notas ya tiene la versión de nube.
    """
    if descargar_excel_interno is None:
        return EXCEL_INTERNO.exists()
    try:
        ok = bool(descargar_excel_interno(EXCEL_INTERNO, EXCEL_INTERNO_R2_KEY))
        if ok:
            return True
        return EXCEL_INTERNO.exists()
    except Exception as error:
        print("ERROR RECUPERANDO EXCEL INTERNO PARA IA:", error)
        return EXCEL_INTERNO.exists()


def invalidar_cache_excel_interno():
    """Invalida la copia en memoria después de una escritura confirmada."""
    _CACHE_EXCEL["datos"] = None
    _CACHE_EXCEL["cargado_en"] = 0.0


def _cargar_excel_interno():
    ahora = time.monotonic()
    cache = _CACHE_EXCEL.get("datos")
    if cache is not None and (ahora - _CACHE_EXCEL["cargado_en"]) < TTL_CACHE_EXCEL_SEGUNDOS:
        return cache

    if not _asegurar_excel_local_para_ia():
        return []
    try:
        wb = load_workbook(EXCEL_INTERNO, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            wb.close()
            _CACHE_EXCEL["datos"] = []
            _CACHE_EXCEL["cargado_en"] = ahora
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
        _CACHE_EXCEL["datos"] = datos
        _CACHE_EXCEL["cargado_en"] = time.monotonic()
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
    alias: codigo_display[0]
    for alias, codigo_display in aliases_companias().items()
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
            mencionadas.add(_normalizar_texto(normalizar_compania(canon)))
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
                "ÚNICA herramienta autorizada para cantidades sobre el Excel interno. "
                "Cuenta de forma exacta sobre TODO el dataset, nunca sobre una muestra. "
                "Filtra opcionalmente por compañía, campo/valor, tipo de vehículo y rango "
                "de fecha de emisión. Usá tipo_conteo='unicos' sólo cuando el usuario pida "
                "personas/asegurados únicos; para pólizas, vehículos, remolques o registros "
                "usá 'filas'."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "compania": {"type": "string"},
                    "campo": {"type": "string"},
                    "valor": {"type": "string"},
                    "tipo_vehiculo": {"type": "string", "description": "Substring del campo VEHICULO, ej. remolque, trailer, moto."},
                    "desde": {"type": "string", "description": "Fecha desde inclusive, DD/MM/AAAA."},
                    "hasta": {"type": "string", "description": "Fecha hasta inclusive, DD/MM/AAAA."},
                    "campo_fecha": {"type": "string", "description": "Opcional; por defecto usa EMITIDO DÍA:."},
                    "tipo_conteo": {"type": "string", "enum": ["filas", "unicos"]},
                },
            },
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
            name="comparar_companias",
            description=(
                "Busca de forma transversal en las fichas internas de TODAS las compañías soportadas. "
                "Usala para preguntas del tipo '¿en qué compañía puedo emitir...?', '¿quién toma...?', "
                "'¿qué compañía acepta...?', '¿dónde aseguro...?' o comparaciones entre compañías. "
                "Devuelve evidencia por compañía y distingue entre información encontrada y compañía sin evidencia. "
                "Nunca debe interpretarse ausencia de evidencia como rechazo de la compañía."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Riesgo o condición a comparar, por ejemplo: auto modelo 1956, moto 1994, uso Uber, pickup comercial."
                    }
                },
                "required": ["consulta"],
            },
        ),
        types.FunctionDeclaration(
            name="proponer_registro_excel",
            description=(
                "Cuando el usuario pide guardar o agregar un asegurado a la planilla, "
                "proponé un registro usando EXACTAMENTE estas claves: ASEGURADO, NUMERO, "
                "VEHICULO, PATENTE, ENVIOS YA, CIA, MEDIO DE PAGO, CP, MAIL, TELEFONO. "
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
                            "TELEFONO": {"type": "string", "description": "Teléfono de contacto. Nunca uses DNI ni número de póliza como teléfono."},
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


def _parsear_fecha_excel(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or '').strip()
    if not texto:
        return None
    # Cubre fecha real serializada por openpyxl y los formatos históricos.
    for fmt in (
        '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d',
        '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S',
    ):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            pass
    return None


def _filtrar_filas(
    filas, compania=None, campo=None, valor=None,
    tipo_vehiculo=None, desde=None, hasta=None, campo_fecha=None,
):
    salida = list(filas)
    filtros = {}

    if compania:
        objetivo = _normalizar_texto(normalizar_compania(compania))
        campos = []
        for f in salida[:20]:
            for alias in ('CIA', 'COMPAÑIA', 'COMPANIA', 'COMPAÑÍA', 'ASEGURADORA', 'COMPANIA DE SEGUROS'):
                c = _campo_por_alias(f, (alias,))
                if c and c not in campos:
                    campos.append(c)
        salida = [
            f for f in salida
            if any(_normalizar_texto(normalizar_compania(f.get(c, ''))) == objetivo for c in campos)
        ]
        filtros['compania'] = normalizar_compania(compania)

    if tipo_vehiculo:
        objetivo = _normalizar_texto(tipo_vehiculo)
        equivalencias_tipo = {
            'remolque': {'remolque', 'trailer'},
            'remolques': {'remolque', 'trailer'},
            'trailer': {'remolque', 'trailer'},
            'trailers': {'remolque', 'trailer'},
        }
        objetivos = equivalencias_tipo.get(objetivo, {objetivo})
        aliases_vehiculo = ('VEHICULO', 'VEHÍCULO', 'TIPO VEHICULO', 'TIPO DE VEHICULO', 'MARCA MODELO')
        def coincide_tipo(fila):
            clave = _campo_por_alias(fila, aliases_vehiculo)
            texto_vehiculo = _normalizar_texto(fila.get(clave, '') if clave else '')
            return any(token in texto_vehiculo for token in objetivos)
        salida = [f for f in salida if coincide_tipo(f)]
        filtros['tipo_vehiculo'] = str(tipo_vehiculo).strip()
        if len(objetivos) > 1:
            filtros['sinonimos_tipo_vehiculo'] = sorted(objetivos)

    if campo and valor is not None:
        objetivo = _normalizar_texto(valor)
        salida = [f for f in salida if objetivo in _normalizar_texto(_valor_campo(f, campo) or '')]
        filtros['campo'] = str(campo).strip()
        filtros['valor'] = str(valor).strip()

    if desde or hasta:
        desde_fecha = _parsear_fecha_excel(desde) if desde else None
        hasta_fecha = _parsear_fecha_excel(hasta) if hasta else None
        if desde and desde_fecha is None:
            raise ValueError('Fecha desde inválida. Usá DD/MM/AAAA.')
        if hasta and hasta_fecha is None:
            raise ValueError('Fecha hasta inválida. Usá DD/MM/AAAA.')
        aliases_fecha = (campo_fecha,) if campo_fecha else ('EMITIDO DÍA:', 'EMITIDO DIA', 'EMITIDO', 'FECHA EMISION', 'FECHA DE EMISION')
        filtradas = []
        for f in salida:
            clave_fecha = _campo_por_alias(f, aliases_fecha)
            fecha = _parsear_fecha_excel(f.get(clave_fecha, '') if clave_fecha else '')
            if fecha is None:
                continue
            if desde_fecha and fecha < desde_fecha:
                continue
            if hasta_fecha and fecha > hasta_fecha:
                continue
            filtradas.append(f)
        salida = filtradas
        if desde_fecha:
            filtros['desde'] = desde_fecha.strftime('%d/%m/%Y')
        if hasta_fecha:
            filtros['hasta'] = hasta_fecha.strftime('%d/%m/%Y')
        filtros['campo_fecha'] = campo_fecha or 'EMITIDO DÍA:'

    return salida, filtros


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


def contar_registros(
    compania=None, campo=None, valor=None, tipo_vehiculo=None,
    desde=None, hasta=None, campo_fecha=None, tipo_conteo='filas',
):
    """Conteo determinístico sobre el dataset COMPLETO, nunca sobre previews."""
    datos, fuente = _dataset_estructurado()
    filas, filtros = _filtrar_filas(
        datos, compania=compania, campo=campo, valor=valor,
        tipo_vehiculo=tipo_vehiculo, desde=desde, hasta=hasta, campo_fecha=campo_fecha,
    )
    campo_identidad = _campo_identidad_principal(filas)
    filas_unicas = _deduplicar_personas(filas) if campo_identidad else filas
    tipo = _normalizar_texto(tipo_conteo or 'filas')
    cantidad = len(filas_unicas) if tipo in {'unicos', 'unico', 'personas', 'asegurados'} else len(filas)
    return {
        'fuente': fuente,
        'cantidad': cantidad,
        'tipo_conteo': 'unicos' if tipo in {'unicos', 'unico', 'personas', 'asegurados'} else 'filas',
        'total_filas': len(filas),
        'total_unicos': len(filas_unicas),
        'campo_identidad': campo_identidad,
        'filtros_aplicados': filtros,
        'dataset_total_filas': len(datos),
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
        "TELEFONO",
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

    propuesta["CIA"] = normalizar_compania(propuesta.get("CIA", ""))

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


# V16: el universo de comparación se deriva de la misma fuente de verdad de
# compañías/alias que usa el resto de OficinaIA. Así una compañía nueva no
# queda afuera del comparador por olvidar agregarla a una segunda lista fija.
def _companias_comparables():
    vistas = []
    for _alias, (_codigo, display) in aliases_companias().items():
        if display and display not in vistas:
            vistas.append(display)
    return tuple(vistas)


def _aliases_por_compania_visible():
    grupos = {nombre: set() for nombre in _companias_comparables()}
    for alias, (_codigo, display) in aliases_companias().items():
        if display in grupos:
            grupos[display].add(_normalizar_texto(alias))
            grupos[display].add(_normalizar_texto(display))
    return grupos


def _texto_menciona_compania(texto_norm, aliases):
    for alias in aliases:
        alias = str(alias or "").strip()
        if not alias:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", texto_norm):
            return True
    return False


def _es_consulta_comparativa_companias(pregunta):
    """Detecta consultas de colocación/comparación que deben revisar varias compañías.

    Es deliberadamente acotado: no intenta clasificar todo el chat, sólo evita que una
    pregunta como '¿en qué compañía puedo emitir un auto 56?' termine buscando una
    única compañía o una única ficha.
    """
    t = _normalizar_texto(pregunta)
    if not t:
        return False
    patrones = (
        r"\ben que compania\b",
        r"\ben cuales companias\b",
        r"\bque compania (?:toma|acepta|asegura|emite|cotiza)\b",
        r"\bque companias (?:toman|aceptan|aseguran|emiten|cotizan)\b",
        r"\bdonde (?:puedo )?(?:emitir|asegurar|cotizar|colocar)\b",
        r"\bquien (?:toma|acepta|asegura|emite|cotiza)\b",
        r"\bquienes (?:toman|aceptan|aseguran|emiten|cotizan)\b",
        r"\bcompar(?:a|ame|ar)\b.*\bcompan",
        r"\bcual compania me sirve\b",
        r"\bque compania me sirve\b",
    )
    return any(re.search(p, t) for p in patrones)


def _consulta_comparativa_enriquecida(consulta):
    """Agrega vocabulario de aceptación sin cambiar el riesgo consultado.

    Las fichas suelen hablar de 'antigüedad', 'sin excepción de año', 'admisión' o
    'vehículos aceptados', mientras el usuario dice simplemente 'auto 56'.
    """
    texto = str(consulta or "").strip()
    norm = _normalizar_texto(texto)
    extras = ["acepta", "toma", "emision", "asegurable", "condiciones"]
    if any(x in norm for x in ("auto", "automovil", "vehiculo", "moto", "pickup", "pick up")):
        extras.extend(["ano", "modelo", "antiguedad", "sin excepcion de ano"])
    return f"{texto} {' '.join(extras)}".strip()


def _consulta_comparativa_con_historial(pregunta, historial=None):
    """Completa follow-ups breves usando el último riesgo comparativo del historial.

    Ej.: después de "tengo un auto 56, ¿dónde lo aseguro?", una pregunta
    "¿otras alternativas?" conserva automáticamente "auto 56" como riesgo.
    """
    pregunta = str(pregunta or "").strip()
    historial = historial or []
    norm = _normalizar_texto(pregunta)

    followups = (
        "otras alternativas", "otra alternativa", "alguna otra", "algunas otras",
        "que otra", "que otras", "otra opcion", "otras opciones", "y alguna mas",
        "alguna mas",
    )
    es_followup = any(frase in norm for frase in followups)
    if not es_followup and norm.startswith("y "):
        alias_norm = {_normalizar_texto(a) for a in aliases_companias().keys()}
        es_followup = any(
            re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", norm)
            for a in alias_norm if a
        )
    if not es_followup:
        return pregunta

    # Buscamos hacia atrás el último mensaje del usuario con intención de colocación
    # o con un riesgo vehicular concreto.
    for turno in reversed(historial[-12:]):
        if turno.get("rol") != "user":
            continue
        anterior = str(turno.get("contenido") or "").strip()
        if not anterior:
            continue
        anterior_norm = _normalizar_texto(anterior)
        if (
            _es_consulta_comparativa_companias(anterior)
            or re.search(r"\b(auto|automovil|vehiculo|moto|pickup|pick up|camioneta)\b", anterior_norm)
        ):
            return f"{anterior}\nSEGUIMIENTO DEL USUARIO: {pregunta}"

    return pregunta


def _extraer_anio_vehiculo(consulta):
    """Extrae un año/modelo vehicular razonable para validaciones de antigüedad."""
    texto = _normalizar_texto(consulta)
    hoy = datetime.now().year

    # Primero años explícitos de 4 dígitos.
    candidatos = [int(x) for x in re.findall(r"\b(19\d{2}|20\d{2})\b", texto)]
    candidatos = [x for x in candidatos if 1900 <= x <= hoy]
    if candidatos:
        return candidatos[-1]

    # Luego abreviaturas típicas de oficina: "auto 56", "moto 94", "modelo 05".
    m = re.search(
        r"\b(?:auto|automovil|vehiculo|moto|pickup|pick up|camioneta|modelo)\s+(?:modelo\s+)?['’]?(\d{2})\b",
        texto,
    )
    if not m:
        return None

    corto = int(m.group(1))
    corte = hoy % 100
    anio = 2000 + corto if corto <= corte else 1900 + corto
    return anio if 1900 <= anio <= hoy else None


def _limites_antiguedad_en_texto(texto):
    """Devuelve límites máximos de antigüedad expresados de forma inequívoca."""
    norm = _normalizar_texto(texto)
    patrones = (
        r"(?:hasta|maximo|maxima|antiguedad maxima|limite de antiguedad|no mayor a|no superior a)\s*(?:de\s*)?(\d{1,3})\s*anos",
        r"(\d{1,3})\s*anos\s*(?:de antiguedad\s*)?(?:maximo|maxima|como maximo)",
    )
    valores = []
    for pat in patrones:
        for n in re.findall(pat, norm):
            try:
                valores.append(int(n))
            except Exception:
                pass
    return [n for n in valores if 0 < n < 150]


def _evaluar_evidencia_por_antiguedad(consulta, evidencia):
    """Valida compatibilidad temporal cuando la evidencia contiene un límite claro.

    No intenta decidir reglas comerciales complejas: sólo evita contradicciones
    matemáticas como recomendar un vehículo de 70 años donde el máximo es 30.
    """
    anio = _extraer_anio_vehiculo(consulta)
    if not anio:
        return {
            "anio_vehiculo": None,
            "antiguedad_aprox": None,
            "estado": "SIN_VALIDACION_NUMERICA",
            "detalle": "",
        }

    hoy = datetime.now().year
    antiguedad = hoy - anio
    contenido = "\n".join(str(x.get("contenido") or "") for x in evidencia)
    norm = _normalizar_texto(contenido)

    frases_sin_limite = (
        "sin excepcion de ano", "sin excepcion del ano", "sin limite de antiguedad",
        "sin limite de ano", "cualquier ano", "todos los anos",
    )
    if any(frase in norm for frase in frases_sin_limite):
        return {
            "anio_vehiculo": anio,
            "antiguedad_aprox": antiguedad,
            "estado": "COMPATIBLE_POR_ANTIGUEDAD",
            "detalle": f"El vehículo modelo {anio} tiene aproximadamente {antiguedad} años y la evidencia indica que no hay límite/excepción de año.",
        }

    limites = _limites_antiguedad_en_texto(contenido)
    if limites:
        limite = min(limites)
        if antiguedad > limite:
            return {
                "anio_vehiculo": anio,
                "antiguedad_aprox": antiguedad,
                "estado": "NO_COMPATIBLE_POR_ANTIGUEDAD",
                "limite_detectado": limite,
                "detalle": f"El vehículo modelo {anio} tiene aproximadamente {antiguedad} años, que supera el máximo detectado de {limite} años.",
            }
        return {
            "anio_vehiculo": anio,
            "antiguedad_aprox": antiguedad,
            "estado": "COMPATIBLE_POR_LIMITE_DE_ANTIGUEDAD",
            "limite_detectado": limite,
            "detalle": f"El vehículo modelo {anio} tiene aproximadamente {antiguedad} años y no supera el máximo detectado de {limite} años.",
        }

    return {
        "anio_vehiculo": anio,
        "antiguedad_aprox": antiguedad,
        "estado": "SIN_VALIDACION_NUMERICA",
        "detalle": f"Modelo {anio}: antigüedad aproximada {antiguedad} años. La evidencia recuperada no contiene un límite inequívoco de antigüedad.",
    }


def _clasificar_compatibilidad_documental(consulta, evidencia, validacion):
    """Clasifica sólo lo que la evidencia permite afirmar.

    Ausencia de prohibición nunca equivale a aceptación. Para recomendar una
    compañía hace falta una regla positiva de admisión/aceptación o un límite
    de antigüedad explícito compatible con el riesgo consultado.
    """
    if not evidencia:
        return {
            "estado": "SIN_INFORMACION_SUFICIENTE",
            "detalle": "No hay evidencia positiva suficiente para confirmar aceptación.",
        }

    if (validacion or {}).get("estado") == "NO_COMPATIBLE_POR_ANTIGUEDAD":
        return {
            "estado": "NO_COMPATIBLE_CONFIRMADO",
            "detalle": str((validacion or {}).get("detalle") or "La restricción de antigüedad descarta el riesgo."),
        }

    texto = _normalizar_texto("\n".join(str(x.get("contenido") or "") for x in evidencia))
    negativos = (
        r"\bno (?:se )?(?:acepta|aceptan|toma|toman|asegura|aseguran|admite|admiten|emite|emiten)\b",
        r"\b(?:riesgo|vehiculo|vehiculos) no (?:aceptable|asegurable|admisible)\b",
        r"\b(?:queda|quedan) excluid[oa]s?\b",
    )
    if any(re.search(p, texto) for p in negativos):
        return {
            "estado": "NO_COMPATIBLE_CONFIRMADO",
            "detalle": "La evidencia recuperada contiene una exclusión o rechazo explícito.",
        }

    positivos = (
        r"\bsin (?:excepcion|limite).{0,35}(?:ano|antiguedad)\b",
        r"\bcualquier ano\b",
        r"\b(?:se )?(?:acepta|aceptan|toma|toman|admite|admiten)\b",
        r"\b(?:vehiculos?|unidades?) (?:aceptados?|admitidos?|asegurables?)\b",
        r"\b(?:antiguedad maxima|maximo|maxima|hasta)\s*(?:de\s*)?\d{1,3}\s*anos\b",
    )
    hay_regla_positiva = any(re.search(p, texto) for p in positivos)
    estado_validacion = (validacion or {}).get("estado")
    if hay_regla_positiva and estado_validacion in {
        "COMPATIBLE_POR_ANTIGUEDAD",
        "COMPATIBLE_POR_LIMITE_DE_ANTIGUEDAD",
        "SIN_VALIDACION_NUMERICA",
    }:
        return {
            "estado": "COMPATIBLE_CONFIRMADO",
            "detalle": "Hay evidencia positiva de admisión compatible con la restricción temporal detectada.",
        }

    return {
        "estado": "SIN_INFORMACION_SUFICIENTE",
        "detalle": "La ficha puede ser relevante, pero no confirma de forma positiva que este riesgo sea aceptado.",
    }


def comparar_companias(consulta):
    """Recuperación transversal determinística sobre metadatos internos.

    Devuelve evidencia separada por compañía. Una compañía sin evidencia queda como
    'sin evidencia' y jamás como 'no acepta'. Esto permite que Gemini sintetice una
    comparación fiable sin confundir ausencia documental con rechazo comercial.
    """
    try:
        fichas = _cargar_metadatos()
    except Exception as error:
        print("ERROR comparar_companias al cargar metadatos:", error)
        return {
            "cantidad": 0,
            "companias_con_evidencia": 0,
            "companias": [],
            "fuente": "Metadatos internos",
            "error": "No se pudieron cargar los metadatos.",
        }

    consulta_busqueda = _consulta_comparativa_enriquecida(consulta)
    grupos_alias = _aliases_por_compania_visible()
    salida = []

    for compania in _companias_comparables():
        alias_norm = grupos_alias.get(compania, {_normalizar_texto(compania)})
        candidatos = []
        for ficha in fichas:
            titulo = str(ficha.get("titulo") or "")
            contenido_total = str(ficha.get("contenido") or "")
            texto_ficha_norm = _normalizar_texto(f"{titulo}\n{contenido_total}")

            # La ficha debe pertenecer razonablemente a la compañía actual.
            # Esto evita atribuir a ATM una condición que en realidad pertenecía a AGS.
            if not _texto_menciona_compania(texto_ficha_norm, alias_norm):
                continue

            for fragmento in _chunks_metadato(contenido_total):
                score = _puntuar_metadato(
                    f"{compania} {consulta_busqueda}",
                    f"{titulo}\n{fragmento}",
                )
                if score <= 0:
                    continue
                candidatos.append({
                    "id": ficha.get("id"),
                    "titulo": titulo,
                    "contenido": fragmento,
                    "puntuacion": score,
                    "actualizado_en": ficha.get("actualizado_en"),
                })

        candidatos.sort(key=lambda x: x["puntuacion"], reverse=True)
        evidencia = candidatos[:3]
        validacion = _evaluar_evidencia_por_antiguedad(consulta, evidencia) if evidencia else {
            "anio_vehiculo": _extraer_anio_vehiculo(consulta),
            "antiguedad_aprox": (
                datetime.now().year - _extraer_anio_vehiculo(consulta)
                if _extraer_anio_vehiculo(consulta) else None
            ),
            "estado": "SIN_EVIDENCIA",
            "detalle": "No hay evidencia interna suficiente para validar esta compañía.",
        }
        compatibilidad = _clasificar_compatibilidad_documental(consulta, evidencia, validacion)
        salida.append({
            "compania": compania,
            "tiene_evidencia": bool(evidencia),
            "compatibilidad": compatibilidad,
            "validacion": validacion,
            "evidencia": evidencia,
        })

    con_evidencia = sum(1 for item in salida if item["tiene_evidencia"])
    compatibles_confirmadas = sum(
        1 for item in salida
        if (item.get("compatibilidad") or {}).get("estado") == "COMPATIBLE_CONFIRMADO"
    )
    print(
        f"COMPARACION COMPANIAS: consulta={consulta!r} "
        f"companias={len(salida)} con_evidencia={con_evidencia}"
    )
    return {
        "cantidad": con_evidencia,
        "companias_con_evidencia": con_evidencia,
        "companias_compatibles_confirmadas": compatibles_confirmadas,
        "companias_evaluadas": len(salida),
        "companias": salida,
        "fuente": "Metadatos internos por compañía",
        "regla": (
            "Sin evidencia significa información no confirmada; no significa que la compañía rechace el riesgo."
        ),
    }


def _formatear_contexto_comparativo(resultado):
    if not isinstance(resultado, dict):
        return ""
    lineas = [
        "CONSULTA TRANSVERSAL ENTRE COMPAÑÍAS (fuente: metadatos internos):",
        "Regla: 'sin evidencia' NO significa 'no acepta'; sólo significa que no está confirmado con las fichas disponibles.",
    ]
    sin_evidencia = []
    for item in resultado.get("companias", []):
        compania = item.get("compania", "")
        evidencia = item.get("evidencia") or []
        if not evidencia:
            sin_evidencia.append(compania)
            continue
        lineas.append(f"\n{compania}:")
        compatibilidad = item.get("compatibilidad") or {}
        if compatibilidad.get("estado"):
            lineas.append(
                f"- COMPATIBILIDAD DOCUMENTAL: {compatibilidad.get('estado')}"
                + (f" — {compatibilidad.get('detalle')}" if compatibilidad.get("detalle") else "")
            )
        validacion = item.get("validacion") or {}
        if validacion.get("estado"):
            detalle_validacion = str(validacion.get("detalle") or "").strip()
            lineas.append(
                f"- VALIDACION: {validacion.get('estado')}"
                + (f" — {detalle_validacion}" if detalle_validacion else "")
            )
        for ev in evidencia[:2]:
            titulo = str(ev.get("titulo") or "").strip()
            contenido = str(ev.get("contenido") or "").strip()
            if len(contenido) > 900:
                contenido = contenido[:900].rsplit(" ", 1)[0] + "…"
            lineas.append(f"- {titulo}: {contenido}" if titulo else f"- {contenido}")
    if sin_evidencia:
        lineas.append("\nSin evidencia suficiente en metadatos para: " + ", ".join(sin_evidencia) + ".")
    return "\n".join(lineas)


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
    "comparar_companias": comparar_companias,
    "proponer_registro_excel": proponer_registro_excel,
    "guardar_metadato_relevante": guardar_metadato_relevante,
    "buscar_vehiculos": buscar_vehiculos,
    "buscar_en_internet": buscar_en_internet,
}


def _ejecutar_tool(nombre, argumentos, cache=None):
    """Ejecuta una herramienta una sola vez por request cuando es cacheable.

    V16 elimina el concepto de "reintento obligatorio" dirigido por el modelo.
    Una búsqueda vacía se informa como tal y el turno puede terminar sin abrir
    cadenas de llamadas cada vez más caras. El cache vive sólo dentro de
    consultar_gemini(), por lo que nunca contamina requests posteriores.
    """
    handler = _TOOL_HANDLERS.get(nombre)
    if not handler:
        return {"error": f"Herramienta desconocida: {nombre}"}

    herramientas_busqueda = {
        "buscar_en_manuales",
        "buscar_en_metadatos",
        "comparar_companias",
        "consultar_excel",
        "buscar_vehiculos",
        "buscar_en_internet",
    }
    herramientas_cacheables = {
        "buscar_en_manuales",
        "buscar_en_metadatos",
        "comparar_companias",
        "consultar_excel",
        "buscar_vehiculos",
    }

    clave_cache = None
    if cache is not None and nombre in herramientas_cacheables:
        try:
            clave_cache = (
                nombre,
                json.dumps(argumentos or {}, ensure_ascii=False, sort_keys=True, default=str),
            )
            if clave_cache in cache:
                return cache[clave_cache]
        except Exception:
            clave_cache = None

    try:
        resultado = handler(**argumentos)
        if isinstance(resultado, dict) and nombre in herramientas_busqueda:
            cantidad = resultado.get("cantidad")
            if cantidad == 0 or resultado.get("error"):
                resultado = dict(resultado)
                resultado["busqueda_vacia"] = True
        if cache is not None and clave_cache is not None:
            cache[clave_cache] = resultado
        return resultado
    except Exception as error:
        print(f"ERROR TOOL {nombre}:", error)
        resultado = {
            "error": f"No se pudo ejecutar {nombre}.",
            "cantidad": 0,
            "busqueda_vacia": True,
        }
        if cache is not None and clave_cache is not None:
            cache[clave_cache] = resultado
        return resultado



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


def _compactar_historial_para_modelo(historial, max_chars=8000, max_por_turno=1800):
    """Convierte el historial visible en memoria conversacional liviana.

    La UI y la base conservan los mensajes completos. Sólo el contexto enviado
    a Gemini se recorta por presupuesto real de caracteres, para que un análisis
    de PDF, un tabulado o una respuesta extensa no siga pesando en todos los
    turnos posteriores. El historial sirve para entender continuaciones; nunca
    representa una operación todavía activa.
    """
    seleccionados = []
    usados = 0
    for turno in reversed((historial or [])[-16:]):
        if not isinstance(turno, dict):
            continue
        rol = turno.get("rol")
        if rol not in {"user", "assistant"}:
            continue
        contenido = str(turno.get("contenido", "") or "").strip()
        if not contenido:
            continue

        # Los bloques tabulados pueden ser enormes y no aportan contexto
        # conversacional en el turno siguiente.
        if contenido.count("\t") >= 8:
            lineas = [ln for ln in contenido.splitlines() if "\t" not in ln]
            contenido = "\n".join(lineas).strip() or "[Resultado tabulado omitido del contexto]"

        if len(contenido) > max_por_turno:
            cabeza = max_por_turno - 280
            contenido = contenido[:cabeza].rstrip() + " … [resumen recortado] … " + contenido[-240:].lstrip()

        linea = f"{'USUARIO' if rol == 'user' else 'ASISTENTE'}: {contenido}"
        costo = len(linea) + 1
        if seleccionados and usados + costo > max_chars:
            break
        if costo > max_chars:
            linea = linea[:max_chars]
            costo = len(linea)
        seleccionados.append(linea)
        usados += costo

    seleccionados.reverse()
    return "\n".join(seleccionados) or "Sin historial relevante."


def consultar_gemini(pregunta, contexto="", historial=None):
    cliente = obtener_cliente_gemini()
    if cliente is None:
        return "La IA todavía no está configurada. Falta GEMINI_API_KEY."

    historial = historial or []
    historial_texto = _compactar_historial_para_modelo(historial)
    # Cache estrictamente efímero: nace y muere dentro de este turno.
    tool_cache = {}

    contexto_comparativo = ""
    pregunta_comparativa = _consulta_comparativa_con_historial(pregunta, historial)
    if (
        _es_consulta_comparativa_companias(pregunta_comparativa)
        or pregunta_comparativa != str(pregunta or "").strip()
    ):
        try:
            resultado_comparativo = _ejecutar_tool(
                "comparar_companias", {"consulta": pregunta_comparativa}, cache=tool_cache
            )
            contexto_comparativo = _formatear_contexto_comparativo(resultado_comparativo)
        except Exception as error:
            print("ERROR PRECONTEXTO COMPARATIVO:", error)
            contexto_comparativo = ""

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    prompt = f"""
Sos el asistente interno de OficinaIA, una oficina de seguros de Argentina.
Respondé la pregunta completa y no inventes datos.
FECHA ACTUAL DEL SISTEMA: {fecha_hoy}

REGLAS:
- Si el usuario saluda, agradece, comenta algo, escribe una frase coloquial o simplemente sigue una conversación, respondé de forma natural usando el historial. No fuerces una herramienta ni un flujo estructurado si no hace falta.
- El HISTORIAL es memoria conversacional, no estado de ejecución. Una operación de PDF, /flota, Excel, manuales o herramientas terminó al responder el turno en que se ejecutó. Nunca reactives una operación anterior sólo porque aparece en el historial.
- Si la pregunta actual es una continuación inequívoca (por ejemplo "¿alguna otra?" después de una consulta de colocación), podés usar el historial sólo para completar los datos mínimos que faltan.
- Si falta un dato concreto para poder hacer lo pedido, pedí solamente ese dato.
- Si ni con el historial se puede determinar razonablemente qué quiere el usuario, respondé exactamente: "Reformulame la pregunta."
- Una entrada poco clara nunca es motivo para inventar datos ni para forzar una operación de Excel, PDF, flota o metadatos.
- OficinaIA puede haber recuperado METADATOS INTERNOS PRIORITARIOS antes de esta llamada. Si aparecen dentro del contexto, utilizalos directamente como fuente prioritaria; no afirmes que el dato no está disponible si está allí.
- Si el contexto ya contiene metadatos suficientes para responder, no vuelvas a llamar buscar_en_metadatos() innecesariamente. Podés usarla nuevamente únicamente si necesitás información adicional o una búsqueda más específica.
- Elegí las herramientas necesarias según el significado de la pregunta.
- CONSULTAS TRANSVERSALES / COLOCACIÓN: si el usuario pregunta "¿en qué compañía puedo emitir...?", "¿quién toma...?", "¿qué compañía acepta...?", "¿dónde puedo asegurar...?" o pide comparar compañías, NO busques una sola compañía. Usá el CONTEXTO COMPARATIVO ya recuperado si está presente. No vuelvas a llamar comparar_companias para repetir la misma búsqueda dentro del mismo turno.
- En comparaciones, clasificá la evidencia con tres estados conceptuales: COMPATIBLE CONFIRMADO, NO COMPATIBLE CONFIRMADO y SIN INFORMACIÓN SUFICIENTE. Jamás conviertas "no encontré información" en "no lo toma".
- Sólo presentes como alternativa real una compañía cuyo CONTEXTO COMPARATIVO marque COMPATIBILIDAD DOCUMENTAL: COMPATIBLE_CONFIRMADO. Tener una ficha relacionada, no encontrar una prohibición o quedar como SIN INFORMACIÓN SUFICIENTE NO habilita a recomendarla. Nunca inventes "consulta especial" ni excepciones no documentadas.
- Si existe al menos una compañía con compatibilidad confirmada, respondé con esa opción aunque no puedas confirmar las demás.
- Para frases abreviadas de oficina como "auto 56", interpretá el número como año/modelo del vehículo cuando el contexto lo haga razonable (por ejemplo, 1956). Si hubiera una ambigüedad real, indicá brevemente la interpretación usada en vez de bloquear la consulta.
- VALIDACIÓN DE RESTRICCIONES: antes de recomendar una compañía, verificá que TODAS las restricciones numéricas recuperadas sean compatibles con el riesgo concreto. Si el vehículo es modelo 1956 y la fecha actual es 2026, tiene aproximadamente 70 años. Una ficha que diga "máximo 30 años" DESCARTA esa alternativa: nunca la presentes como opción.
- Si el CONTEXTO COMPARATIVO incluye validacion.estado="NO_COMPATIBLE_POR_ANTIGUEDAD", esa compañía NO puede recomendarse para ese vehículo salvo que exista otra evidencia explícita y más específica que contradiga el límite general; si hay contradicción, marcala como REVISAR/confirmar y no inventes.
- Si validacion.estado indica compatibilidad por antigüedad, eso sólo valida el requisito temporal: todavía respetá cualquier otra condición de la evidencia (uso, inspección, club de clásicos, cobertura, tipo de vehículo, etc.).
- CONTINUIDAD: expresiones como "otras alternativas", "alguna otra", "¿y AgroSalta?" o "¿qué otra?" continúan el mismo riesgo de la pregunta anterior. No pierdas año/modelo/uso/cobertura ya establecidos y no reinicies la búsqueda como si fuera una consulta nueva.
- En un seguimiento de "otras alternativas", evitá repetir como nuevas opciones las compañías ya mencionadas salvo que necesites corregir una respuesta anterior.
- FUENTE PRINCIPAL Y AUTOSUFICIENTE: buscar_en_metadatos (fichas cargadas a
  mano). Para coberturas, asistencia, remolque, grúas, límites, condiciones,
  procedimientos y datos de compañías, buscá primero ahí y, si hay resultado
  razonable, respondé con eso. NO hace falta abrir manuales en PDF además,
  salvo que el propio resultado de metadatos sea insuficiente o contradictorio.
- buscar_en_manuales (PDFs completos) es una herramienta PESADA y de uso
  EXCEPCIONAL: implica descargar y procesar archivos grandes. Usala ÚNICAMENTE
  cuando el usuario pida explícitamente un manual, documento o PDF por nombre,
  o cuando metadatos haya dado 0 resultados Y el usuario insista en que la
  información debería existir. EXCEPCIÓN: en una consulta transversal de colocación/comparación,
  si el contexto comparativo no alcanza, podés hacer UNA búsqueda genérica en manuales para ampliar
  la evidencia; no descargues manual por manual de todas las compañías.
- Si metadatos da 0 resultados en un tema puntual, está bien responder que no
  tenés esa ficha cargada y sugerir cargarla (guardar_metadato_relevante),
  en lugar de encadenar automáticamente una búsqueda en PDFs.
- No afirmes que la información no existe solo porque la primera búsqueda dio 0;
  probá una reformulación de la MISMA búsqueda en metadatos (sinónimos:
  remolque/grúa/asistencia/auxilio/traslado, singular/plural) antes de descartar.
- REGLA CRÍTICA DE EXACTITUD NUMÉRICA: cualquier cantidad, total, suma, promedio o porcentaje sobre datos internos debe provenir literalmente del resultado de una herramienta determinística. Nunca lo estimes, redondees, extrapoles ni lo calcules mirando filas visibles.
- ARITMÉTICA DE CONDICIONES: para validar años, edades, antigüedades y límites de aceptación, compará explícitamente los valores antes de concluir. No recomiendes una opción que contradiga matemáticamente el límite recuperado.
- Para TODO conteo del Excel interno usá contar_registros. consultar_excel devuelve una muestra para inspección y NUNCA es una fuente válida para contar. No cuentes visualmente registros, previews ni resultados truncados.
- Desambiguación importante: "¿cuántos remolques/trailers tiene ATM?" o "¿cuántos tenemos asegurados?" significa contar vehículos/registros del Excel; usá contar_registros. En cambio, "¿cuántos servicios de remolque/grúa cubre ATM?" es una consulta de cobertura y va a metadatos. Mirá palabras como "tenemos", "asegurados", "vehículos" versus "cubre", "asistencia", "servicios".
- En contar_registros usá tipo_conteo="unicos" sólo para personas/asegurados únicos. Para pólizas, vehículos, remolques, trailers y registros usá tipo_conteo="filas".
- Para preguntas temporales calculá el rango desde/hasta a partir de la fecha actual indicada abajo y pasalo a contar_registros en DD/MM/AAAA.
- Para vehículos/patentes, usá buscar_vehiculos.
- Para datos estructurados generales (asegurados, pólizas en planilla), usá consultar_excel.
- Si el usuario pide guardar o agregar un asegurado/registro a la planilla, usá
  proponer_registro_excel. Las columnas reales y únicas son:
  ASEGURADO, NUMERO, VEHICULO, PATENTE, ENVIOS YA, CIA, MEDIO DE PAGO, CP, MAIL, TELEFONO.
  NUMERO puede ser DNI o número de póliza. Intentá completar todos los campos presentes.
  Si falta un campo, dejalo vacío; nunca inventes ni omitas silenciosamente un campo
  que el usuario haya dado. La propuesta siempre requiere confirmación.
- Si el usuario usa el comando /guardar asegurado, respetá el orden histórico:
  ASEGURADO, NUMERO, VEHICULO, PATENTE, CIA, MEDIO DE PAGO, CP, MAIL, y TELEFONO como noveno campo opcional.
  ENVIOS YA sigue siendo opcional y no forma parte del comando corto. No reinterpretes ese orden.
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
- CÓMO COMUNICAR (esto aplica siempre, incluso cuando la información de base sea
  compleja): hablá como un asistente junior de seguros que le explica el resultado
  a un compañero de oficina, no como un programa. Frases cortas, palabras comunes.
  Contá primero qué pasó y después qué hay que hacer. Si hay varios problemas
  distintos, separalos en oraciones simples en vez de amontonarlos en una sola
  frase larga con paréntesis. Decí con claridad qué quedó completo y qué falta.
  Nunca uses en la respuesta al usuario palabras como "estado", "payload",
  "parser", "item", "null", "None", "fallback", "bloque" (salvo que te refieras
  literalmente al texto para pegar en Excel), "filas afectadas" o cualquier
  término que suene a log de sistema o jerga de programador. La información
  interna puede ser compleja; la respuesta al usuario tiene que ser simple.

HISTORIAL:
{historial_texto}

CONTEXTO COMPARATIVO AUTOMÁTICO:
{contexto_comparativo or 'No aplica a esta consulta o no hubo evidencia transversal previa.'}

CONTEXTO DOCUMENTAL YA DISPONIBLE:
{contexto or 'No hay contexto documental previo.'}

PREGUNTA:
{pregunta}
"""

    contents = [prompt]
    propuesta_excel = None
    propuesta_metadato = None

    # V16: las búsquedas vacías ya no abren un "reintento obligatorio".
    # El modelo recibe el resultado vacío/error y puede responder con claridad.
    # Esto evita que las consultas difíciles sean justamente las que más
    # llamadas encadenen y más se acerquen al timeout del único worker.
    total_tool_calls = 0
    MAX_TOOL_CALLS = 8

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

            if propuesta_excel or propuesta_metadato:
                return texto, propuesta_excel, propuesta_metadato
            return texto

        contents.append(
            respuesta.candidates[0].content
            if getattr(respuesta, "candidates", None)
            else respuesta
        )

        for call in calls:
            nombre = getattr(call, "name", "")
            argumentos = dict(getattr(call, "args", {}) or {})
            print("GEMINI TOOL CALL:", nombre, argumentos)

            total_tool_calls += 1
            if total_tool_calls > MAX_TOOL_CALLS:
                resultado = {
                    "error": "Se alcanzó el límite de herramientas para este turno.",
                    "cantidad": 0,
                }
            else:
                resultado = _ejecutar_tool(nombre, argumentos, cache=tool_cache)

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

    if propuesta_excel or propuesta_metadato:
        return (
            "No pude completar la consulta después de consultar las fuentes disponibles.",
            propuesta_excel,
            propuesta_metadato,
        )
    return "No pude completar la consulta después de consultar las fuentes disponibles."
