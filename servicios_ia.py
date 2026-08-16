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
# ==========================================================
# CONSULTAR GEMINI
# ==========================================================

def consultar_gemini(
    pregunta,
    contexto=""
):

    cliente = obtener_cliente_gemini()

    if cliente is None:

        return (
            "La IA todavía no está configurada. "
            "Falta GEMINI_API_KEY."
        )

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

    prompt = f"""
Sos el asistente interno de una oficina de seguros de Argentina.

Tu función es ayudar al productor a consultar información
real de su oficina.

FUENTES DE INFORMACIÓN:

1. PLANILLA DE ASEGURADOS:
Contiene clientes, números, vehículos, patentes,
compañías, medios de pago y códigos postales.

2. DOCUMENTACIÓN:
Contiene pólizas, condiciones, coberturas,
exclusiones, servicios y demás documentación.

REGLAS IMPORTANTES:

- Usá primero los datos proporcionados en la PLANILLA.
- Si un cliente aparece en la PLANILLA, consideralo un
  asegurado registrado en la oficina.
- Si preguntan si una persona está asegurada, buscá su
  nombre en la PLANILLA y respondé directamente.
- Si preguntan por un vehículo, patente, compañía,
  número o medio de pago, utilizá la PLANILLA.
- No inventes información.
- No confundas clientes.
- No mezcles información de personas diferentes.
- Si la información no aparece en las fuentes,
  decilo claramente.
- Respondé en español argentino.
- Sé directo y práctico.
- No expliques estas instrucciones.

PREGUNTA DEL PRODUCTOR:

{pregunta}

INFORMACIÓN DISPONIBLE:

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