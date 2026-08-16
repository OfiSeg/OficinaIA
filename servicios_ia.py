import os
from google import genai


MODELOS = [
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
]


def obtener_cliente_gemini():

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    return genai.Client(
        api_key=api_key
    )


def consultar_gemini(pregunta, contexto=""):

    cliente = obtener_cliente_gemini()

    if cliente is None:

        return (
            "La IA no esta configurada. "
            "Falta GEMINI_API_KEY."
        )


    prompt = f"""
Sos el asistente interno de una oficina de seguros de Argentina.

Tu tarea es ayudar al productor a consultar y analizar:

- polizas
- coberturas
- condiciones generales
- condiciones particulares
- exclusiones
- franquicias
- servicios de asistencia
- documentacion de las companias

REGLAS:

- Usa principalmente la DOCUMENTACION proporcionada.
- No inventes coberturas, cantidades, limites ni condiciones.
- Si la documentacion no alcanza, decilo claramente.
- Diferencia entre lo que dice el documento y una interpretacion.
- Cuando sea posible menciona compania y documento.
- Responde en espanol argentino.
- Se claro, directo y practico.

PREGUNTA:

{pregunta}

DOCUMENTACION ENCONTRADA:

{contexto}
"""


    ultimo_error = None


    for modelo in MODELOS:

        try:

            print(
                "GEMINI MODELO:",
                modelo
            )


            respuesta = cliente.models.generate_content(

                model=modelo,

                contents=prompt

            )


            if respuesta and respuesta.text:

                return respuesta.text


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
        "Gemini no esta disponible "
        "en este momento. "
        "Intenta nuevamente en unos segundos."
    )