import re
import os
import csv
import io
import urllib.request
from pathlib import Path
from google import genai
from google.genai import types
from openpyxl import load_workbook


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRqKDij-TRt87x_9EfggVPc0Qc8v4-hJUnOLXqrBcnqLO_gumj47GhJOcSoWAJkX3oRh3tZa9PRXiss/"
    "pub?output=csv"
)


MODELOS_GEMINI = [
    # Modelo estable recomendado actualmente por Google para producción.
    "gemini-3.5-flash",
    # Fallback económico/rápido.
    "gemini-3.1-flash-lite",
]

BASE_DIR = Path(__file__).resolve().parent
EXCEL_INTERNO = BASE_DIR / "excel_interno.xlsx"


# ==========================================================
# GEMINI
# ==========================================================

def obtener_cliente_gemini():

    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()

    if not api_key:
        return None

    return genai.Client(
        api_key=api_key
    )


# ==========================================================
# GOOGLE SHEETS
# ==========================================================

def obtener_datos_sheet():

    try:

        with urllib.request.urlopen(
            SHEET_URL,
            timeout=15
        ) as respuesta:

            contenido = respuesta.read().decode(
                "utf-8-sig"
            )

        lector = csv.DictReader(
            io.StringIO(contenido)
        )

        datos = []

        for fila in lector:

            fila_limpia = {
                str(k).strip().upper():
                str(v).strip()
                for k, v in fila.items()
                if k is not None
            }

            if any(fila_limpia.values()):

                datos.append(
                    fila_limpia
                )

        print(
            "GOOGLE SHEETS: "
            + str(len(datos))
            + " registros cargados."
        )

        return datos

    except Exception as error:

        print(
            "ERROR GOOGLE SHEETS:",
            error
        )

        return []


# ==========================================================
# BUSCAR EN GOOGLE SHEETS
# ==========================================================

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

def _cargar_excel_interno():
    if not EXCEL_INTERNO.exists():
        return []
    try:
        wb = load_workbook(EXCEL_INTERNO, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
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
    resultados.sort(key=lambda x: x[0], reverse=True)
    return resultados[:50]

def buscar_en_sheet(pregunta):
    datos = obtener_datos_sheet()
    resultados = _buscar_en_registros(pregunta, datos, "Google Sheets")
    if not resultados:
        return ""

    contexto = "FUENTE: Excel externo / Google Sheets\n"
    for _, fila in resultados:
        contexto += "REGISTRO DE CLIENTE:\n"
        for campo, valor in fila.items():
            contexto += f"{campo}: {valor}\n"
        contexto += "\n--------------------\n"
    return contexto

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


def _es_pregunta_cantidad_vehiculos(pregunta):
    q = _normalizar_texto(pregunta)
    return bool(re.search(r"\bcuant[oa]s?\b.*\bvehicul", q) or re.search(r"\bnumero\s+de\s+vehicul", q))


def buscar_cliente_exactamente(pregunta, datos=None):
    """Encuentra el/los clientes cuyo nombre aparece en la consulta.
    Prioriza coincidencia por nombre completo y luego por todas las partes
    significativas del nombre, evitando que una fila ajena gane por palabras
    genéricas como 'tiene' o 'vehículo'.
    """
    datos = datos if datos is not None else obtener_datos_sheet()
    q = _normalizar_texto(pregunta)
    candidatos = []
    vistos = set()
    for fila in datos:
        cliente_original = str(fila.get('CLIENTE', '')).strip()
        cliente = _normalizar_texto(cliente_original)
        if not cliente or cliente in vistos:
            continue
        vistos.add(cliente)
        if cliente in q:
            candidatos.append((1000 + len(cliente.split()), cliente_original))
            continue
        partes = [x for x in re.findall(r'[a-z0-9]+', cliente) if len(x) >= 3]
        coincidencias = sum(1 for parte in partes if re.search(rf'\b{re.escape(parte)}\b', q))
        if partes and coincidencias == len(partes):
            candidatos.append((900 + len(partes), cliente_original))
        elif len(partes) >= 2 and coincidencias >= 2:
            candidatos.append((500 + coincidencias, cliente_original))
    candidatos.sort(reverse=True)
    if not candidatos:
        return None
    mejor = candidatos[0][0]
    nombres = [nombre for puntaje, nombre in candidatos if puntaje >= mejor - 50]
    return nombres[0] if nombres else None


def respuesta_deterministica_vehiculos(pregunta, datos=None):
    """Resuelve preguntas de cantidad de vehículos directamente desde Sheets.
    Evita que el LLM haga aritmética o invente/omita registros.
    """
    if not _es_pregunta_cantidad_vehiculos(pregunta):
        return None
    datos = datos if datos is not None else obtener_datos_sheet()
    cliente = buscar_cliente_exactamente(pregunta, datos)
    if not cliente:
        return None
    cliente_norm = _normalizar_texto(cliente)
    filas = [f for f in datos if _normalizar_texto(f.get('CLIENTE', '')) == cliente_norm]
    vehiculos = []
    vistos = set()
    for fila in filas:
        vehiculo = str(fila.get('VEHICULO', '')).strip()
        patente = str(fila.get('PATENTE', '')).strip()
        if not vehiculo and not patente:
            continue
        clave = _normalizar_texto(patente) if patente else _normalizar_texto(vehiculo)
        if clave in vistos:
            continue
        vistos.add(clave)
        vehiculos.append(fila)
    if not vehiculos:
        return f'{cliente} no tiene vehículos registrados en la planilla disponible.'
    lineas = [f'{cliente} tiene registrados {len(vehiculos)} vehículos:']
    for i, fila in enumerate(vehiculos, 1):
        partes = []
        if fila.get('VEHICULO'): partes.append(str(fila['VEHICULO']).strip())
        if fila.get('PATENTE'): partes.append(f"Patente {str(fila['PATENTE']).strip()}")
        if fila.get('COMPAÑIA'): partes.append(str(fila['COMPAÑIA']).strip())
        lineas.append(f"{i}. {' — '.join(partes)}")
    return '\n'.join(lineas)


# ==========================================================
# CONSULTAR GEMINI
# ==========================================================

def _pregunta_requiere_internet(pregunta):
    q = _normalizar_texto(pregunta)
    claves = (
        "internet", "web", "online", "actual", "actualizado", "hoy",
        "precio actual", "sitio web", "pagina oficial", "buscar en internet",
        "contrasta", "contrastar", "publica", "publico", "publica"
    )
    return any(c in q for c in claves)

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


def _seleccionar_fuentes(pregunta, contexto_interno, contexto_externo, contexto):
    """
    Selecciona como máximo 2 fuentes reales para el contexto de Gemini.
    La información puede contener muchas filas/chunks dentro de una misma
    fuente; lo que limitamos es la cantidad de fuentes distintas.
    """
    candidatos = []

    if contexto_interno:
        candidatos.append({
            "nombre": "Excel interno",
            "contenido": contexto_interno,
            "prioridad": 80,
        })

    if contexto_externo:
        candidatos.append({
            "nombre": "Excel externo / Google Sheets",
            "contenido": contexto_externo,
            "prioridad": 75,
        })

    for nombre, contenido in _documentos_desde_contexto(contexto).items():
        # Un PDF adjunto tiene prioridad porque fue elegido explícitamente
        # por el usuario en esta consulta.
        prioridad = 110 if nombre.startswith("PDF adjunto") else 65
        candidatos.append({
            "nombre": nombre,
            "contenido": contenido,
            "prioridad": prioridad,
        })

    if not candidatos:
        return [], []

    for candidato in candidatos:
        candidato["score"] = _puntuar_fuente(
            pregunta,
            candidato["contenido"],
            candidato["prioridad"],
        )

    candidatos.sort(key=lambda x: x["score"], reverse=True)

    # Una fuente claramente dominante es preferible a una segunda marginal.
    seleccionados = [candidatos[0]]
    if len(candidatos) > 1:
        primera = candidatos[0]
        segunda = candidatos[1]
        diferencia = primera["score"] - segunda["score"]
        if segunda["score"] >= max(3, primera["score"] * 0.55) or diferencia <= 4:
            seleccionados.append(segunda)

    # Nunca más de dos fuentes.
    seleccionados = seleccionados[:2]

    nombres = [x["nombre"] for x in seleccionados]
    bloques = []
    for fuente in seleccionados:
        bloques.append(
            f"===== FUENTE SELECCIONADA: {fuente['nombre']} =====\n"
            f"{fuente['contenido'].strip()}\n"
            f"===== FIN FUENTE: {fuente['nombre']} ====="
        )
    return nombres, bloques


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


def consultar_gemini(pregunta, contexto="", historial=None):
    cliente = obtener_cliente_gemini()
    if cliente is None:
        return "La IA todavía no está configurada. Falta GEMINI_API_KEY."

    datos_sheet_crudos = obtener_datos_sheet()
    respuesta_vehiculos = respuesta_deterministica_vehiculos(pregunta, datos_sheet_crudos)
    if respuesta_vehiculos:
        return _agregar_fuentes(
            respuesta_vehiculos,
            ["Excel externo / Google Sheets"],
        )

    # Recuperación completa de los Excel: se buscan todos los registros
    # relevantes, no sólo las primeras 10 filas.
    contexto_interno = buscar_en_excel_interno(pregunta)
    contexto_externo = (
        ""
        if "FUENTE: Excel externo / Google Sheets" in contexto
        else buscar_en_sheet(pregunta)
    )

    fuentes_seleccionadas, bloques_fuente = _seleccionar_fuentes(
        pregunta,
        contexto_interno,
        contexto_externo,
        contexto,
    )

    contexto_total = "\n\n".join(bloques_fuente)
    if not contexto_total:
        contexto_total = (
            "No se encontró información suficientemente relevante en los "
            "datos internos ni en la documentación disponible."
        )

    historial = historial or []
    historial_texto = ""
    for turno in historial[-10:]:
        rol = "USUARIO" if turno.get("rol") == "user" else "ASISTENTE"
        contenido = str(turno.get("contenido", "")).strip()
        if contenido:
            historial_texto += f"{rol}: {contenido}\n"

    uso_web = _pregunta_requiere_internet(pregunta)

    prompt = f"""
Sos el asistente interno de OficinaIA, una oficina de seguros de Argentina.

OBJETIVO PRINCIPAL
Respondé la pregunta completa, no solamente la primera parte que puedas
contestar. Primero identificá mentalmente todos los puntos solicitados y
verificá que la respuesta cubra cada uno. Sé preciso, directo y útil.

SELECCIÓN DE INFORMACIÓN
- Usá principalmente la información interna de OficinaIA.
- El contexto que recibís abajo ya fue seleccionado por relevancia.
- Priorizá una sola fuente cuando sea suficiente.
- Como regla general, utilizá como máximo 2 fuentes distintas.
- No menciones ni inventes fuentes que no estén en "FUENTES SELECCIONADAS".
- Si una fuente contiene toda la información necesaria, no agregues otra.
- No repitas el mismo dato porque aparezca en dos fuentes.
- Si dos fuentes se contradicen, explicá la diferencia y no inventes cuál es correcta.
- Internet sólo complementa la información interna cuando la pregunta lo pide,
  necesita actualidad o resulta realmente necesario.

REGLA CRÍTICA: NO MEZCLES REGISTROS
Si la consulta contiene una patente, número de póliza, cliente u otro
identificador concreto, respondé únicamente con los registros que correspondan
a ese identificador. No uses otro asegurado, póliza o patente como ejemplo.
Si hay varios registros del mismo identificador, podés utilizarlos todos.
Si la consulta es general o pide una comparación, sí podés combinar registros.

COMPLETITUD
Si la pregunta tiene varios puntos, contestalos todos en la misma respuesta.
Por ejemplo, si pide medio de pago + documentación + procedimiento + condiciones,
cubrir cada uno si la evidencia está disponible.
No cortes una respuesta válida por hacerla breve.
No agregues relleno, introducciones genéricas ni información no solicitada.

EXCEL Y REGISTROS
Cuando una consulta depende de varias filas, utilizá todas las filas relevantes
que hayan sido recuperadas para ese caso. No supongas que una cantidad fija de
filas representa todo el resultado.
No mezcles clientes, pólizas o patentes distintas.

DOCUMENTOS
Cuando uses un PDF/manual, indicá el nombre del archivo y, si está disponible,
la página relevante. No cites documentos sólo porque fueron consultados:
citá únicamente los que realmente sustentan la respuesta.

NO INVENTAR
Si la evidencia no alcanza para confirmar un dato, decilo claramente.
Ejemplo: "No encontré información suficiente en los documentos disponibles
para confirmar ese dato."
Nunca completes datos faltantes con suposiciones.

FUENTES
Al final incluí una línea breve de **Fuentes:** con sólo las fuentes realmente
utilizadas. Idealmente será una fuente; como máximo, dos, salvo que sea
estrictamente necesario para resolver la consulta.
No listes fuentes irrelevantes.

ESTILO
- Español argentino claro y profesional.
- Pregunta simple: respuesta directa.
- Pregunta compleja: respuesta ordenada por puntos cuando ayude.
- No uses siempre la misma estructura.
- Evitá repeticiones y explicaciones innecesarias.

HISTORIAL
{historial_texto or "Sin historial relevante."}

PREGUNTA
{pregunta}

FUENTES SELECCIONADAS
{contexto_total}
"""

    ultimo_error = None
    for modelo in MODELOS_GEMINI:
        try:
            print(
                "CONSULTANDO GEMINI:",
                modelo,
                "web=",
                uso_web,
                "fuentes=",
                fuentes_seleccionadas,
            )
            config_kwargs = {
                # No enviamos temperature/top_p/top_k: los modelos nuevos
                # pueden rechazarlos y provocar errores 400.
                "max_output_tokens": 4096,
            }
            if uso_web:
                config_kwargs["tools"] = [
                    types.Tool(google_search=types.GoogleSearch())
                ]

            config = types.GenerateContentConfig(**config_kwargs)
            respuesta = cliente.models.generate_content(
                model=modelo,
                contents=prompt,
                config=config,
            )
            texto = getattr(respuesta, "text", None)
            if texto:
                return _agregar_fuentes(
                    texto.strip(),
                    fuentes_seleccionadas,
                    uso_web=uso_web,
                )

        except Exception as error:
            ultimo_error = error
            print(f"ERROR GEMINI {modelo}: {type(error).__name__}: {error}")

    print("GEMINI TODOS LOS MODELOS FALLARON:", ultimo_error)
    return "Gemini no está disponible en este momento. Intentá nuevamente en unos segundos."

# Compatibilidad con el nombre utilizado por el chat de la aplicación.
buscar_en_google_sheet = buscar_en_sheet
