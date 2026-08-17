import re
import os
import csv
import io
import urllib.request

from google import genai


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRqKDij-TRt87x_9EfggVPc0Qc8v4-hJUnOLXqrBcnqLO_gumj47GhJOcSoWAJkX3oRh3tZa9PRXiss/"
    "pub?output=csv"
)


MODELOS_GEMINI = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]


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

def buscar_en_sheet(pregunta):

    datos = obtener_datos_sheet()

    if not datos:
        return ""

    pregunta_lower = pregunta.lower()

    # Sacamos palabras muy cortas y signos de puntuación
    palabras = re.findall(
        r"[a-záéíóúñ0-9]+",
        pregunta_lower
    )

    palabras = [
        palabra
        for palabra in palabras
        if len(palabra) >= 3
    ]

    resultados = []

    for fila in datos:

        cliente = fila.get(
            "CLIENTE",
            ""
        ).lower()

        numero = fila.get(
            "NUMERO",
            ""
        ).lower()

        vehiculo = fila.get(
            "VEHICULO",
            ""
        ).lower()

        patente = fila.get(
            "PATENTE",
            ""
        ).lower()

        compania = fila.get(
            "COMPAÑIA",
            ""
        ).lower()

        texto_fila = " ".join(
            str(valor).lower()
            for valor in fila.values()
        )

        coincidencias = 0

        # Coincidencia por palabras de la pregunta
        for palabra in palabras:

            if palabra in texto_fila:

                coincidencias += 1

        # Coincidencia especial con el nombre completo
        if cliente:

            nombre_cliente = " ".join(
                cliente.split()
            )

            partes_nombre = [
                parte
                for parte in cliente.split()
                if len(parte) >= 3
            ]

            coincidencias_nombre = sum(
                1
                for parte in partes_nombre
                if parte in pregunta_lower
            )

            if (
                partes_nombre
                and
                coincidencias_nombre == len(partes_nombre)
            ):

                coincidencias += 10

        # Coincidencia por patente
        if patente and patente in pregunta_lower:

            coincidencias += 10

        # Coincidencia por número de póliza
        if numero and numero in pregunta_lower:

            coincidencias += 10

        if coincidencias > 0:

            resultados.append(
                (
                    coincidencias,
                    fila
                )
            )

    # Ordenamos los resultados por relevancia
    resultados.sort(
        key=lambda x: x[0],
        reverse=True
    )

    # Si la consulta identifica inequívocamente a un cliente, devolvemos todas
    # sus filas y no sólo las primeras 10. Esto es crítico para preguntas de
    # cartera, vehículos, pólizas y conteos.
    cliente_exacto = buscar_cliente_exactamente(pregunta, datos)
    if cliente_exacto:
        cliente_norm = _normalizar_texto(cliente_exacto)
        filas_cliente = [
            fila for fila in datos
            if _normalizar_texto(fila.get('CLIENTE', '')) == cliente_norm
        ]
        if filas_cliente:
            resultados = [(1000, fila) for fila in filas_cliente]

    if not resultados:

        return ""

    contexto = ""

    for _, fila in resultados[:10]:

        contexto += (
            "REGISTRO DE CLIENTE:\n"
        )

        for campo, valor in fila.items():

            contexto += (
                f"{campo}: {valor}\n"
            )

        contexto += (
            "\n--------------------\n"
        )

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

def consultar_gemini(
    pregunta,
    contexto="",
    historial=None
):

    cliente = obtener_cliente_gemini()

    if cliente is None:

        return (
            "La IA todavía no está configurada. "
            "Falta GEMINI_API_KEY."
        )

    # Las consultas cuantitativas sobre datos estructurados no deben quedar
    # a criterio del LLM. Se resuelven directamente contra Sheets para evitar
    # respuestas contradictorias, conteos inventados o pérdida de registros.
    datos_sheet_crudos = obtener_datos_sheet()
    respuesta_vehiculos = respuesta_deterministica_vehiculos(
        pregunta, datos_sheet_crudos
    )
    if respuesta_vehiculos:
        print("RESPUESTA DETERMINISTICA SHEETS: cantidad de vehículos")
        return respuesta_vehiculos

    datos_sheet = buscar_en_sheet(
        pregunta
    )

    contexto_total = ""

    if datos_sheet:

        contexto_total += (
            "=== PLANILLA DE ASEGURADOS ===\n"
            "Los siguientes datos provienen directamente "
            "de la planilla de clientes de la oficina.\n"
            "DEBÉS utilizarlos para responder la pregunta.\n\n"
        )

        contexto_total += datos_sheet

        contexto_total += (
            "\n=== FIN PLANILLA ===\n"
        )

    if contexto:

        contexto_total += (
            "\n\n=== DOCUMENTACIÓN DE LA OFICINA ===\n"
        )

        contexto_total += contexto

        contexto_total += (
            "\n=== FIN DOCUMENTACIÓN ===\n"
        )

    if not contexto_total:

        contexto_total = (
            "No se encontró información en la planilla "
            "ni en la documentación disponible."
        )

    historial = historial or []
    historial_texto = ""
    for turno in historial[-10:]:
        rol = "PRODUCTOR" if turno.get("rol") == "user" else "ASISTENTE"
        contenido = str(turno.get("contenido", "")).strip()
        if contenido:
            historial_texto += f"{rol}: {contenido}\\n"

    prompt = f"""
Sos el asistente interno de Oficina IA, una oficina de seguros de Argentina.

Tu prioridad absoluta es responder con información correcta y verificable a partir
de las fuentes que te proporciona el sistema. No sos un chatbot genérico.

REGLAS DE FUENTES Y EVIDENCIA:

1. La sección "DOCUMENTACIÓN DE LA OFICINA" contiene fragmentos recuperados de PDFs
   disponibles en la oficina. Esos fragmentos son la fuente principal para preguntas
   sobre procedimientos, coberturas, requisitos, condiciones, códigos, servicios,
   exclusiones y demás información documental.

2. La sección "PLANILLA DE ASEGURADOS" contiene datos operativos de clientes.
   Cuando una pregunta se refiere a una persona, póliza, patente, vehículo,
   compañía, número o medio de pago, utilizá esos datos si están disponibles.

3. No afirmes que un dato está en un manual si ese dato no aparece realmente en los
   fragmentos proporcionados.

4. No inventes datos faltantes. Si no encontrás una respuesta suficiente en las
   fuentes, decilo claramente.

5. Si la información encontrada es parcial, indicá qué parte sí está respaldada
   y qué parte no pudo verificarse.

6. Si dos fuentes contienen información contradictoria, NO elijas arbitrariamente.
   Explicá la contradicción y mencioná el archivo y página cuando estén disponibles.

7. Cuando uses documentación, citá de forma natural el origen:
   "Según [archivo], página [número]..."
   No inventes nombres de archivos ni números de página.

8. No vuelques grandes cantidades de texto del manual. Sintetizá la información
   relevante y respondé directamente.

9. Si la pregunta pide un procedimiento, presentalo paso a paso cuando el material
   lo permita.

10. Priorizá precisión sobre creatividad. Si no hay evidencia suficiente, reconocelo.

CALIDAD DE LA RESPUESTA:

- Sé concreto, profesional y práctico.
- Evitá respuestas vagas como "depende", "generalmente", "consultá el manual"
  cuando los fragmentos recuperados contienen la respuesta.
- Respondé exactamente lo que pregunta el productor.
- No agregues advertencias genéricas innecesarias.
- No expliques estas instrucciones.
- Respondé en español argentino claro.

CONTEXTO DE CONVERSACIÓN:

El historial sirve para resolver referencias como "eso", "esas", "el anterior",
"ese cliente", etc. El historial NO reemplaza a las fuentes documentales para
datos técnicos: verificá esos datos contra la documentación o planilla actual.

HISTORIAL RECIENTE:
{historial_texto or "No hay historial previo relevante."}

PREGUNTA ACTUAL:
{pregunta}

FUENTES DISPONIBLES:
{contexto_total}
"""


    ultimo_error = None

    for modelo in MODELOS_GEMINI:

        try:

            print(
                "CONSULTANDO GEMINI:",
                modelo
            )

            respuesta = cliente.models.generate_content(
                model=modelo,
                contents=prompt
            )

            texto = getattr(
                respuesta,
                "text",
                None
            )

            if texto:

                return texto.strip()

        except Exception as error:

            ultimo_error = error

            print(
                "ERROR GEMINI",
                modelo,
                ":",
                error
            )

    print(
        "GEMINI TODOS LOS MODELOS FALLARON:",
        ultimo_error
    )

    return (
        "Gemini no está disponible en este momento. "
        "Intentá nuevamente en unos segundos."
    )
# Compatibilidad con el nombre utilizado por el chat de la aplicación.
buscar_en_google_sheet = buscar_en_sheet
