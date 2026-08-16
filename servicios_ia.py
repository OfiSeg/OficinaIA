import os
from google import genai


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
            "La IA todavía no está configurada. "
            "Falta GEMINI_API_KEY."
        )

    prompt = f"""
Sos el asistente interno de una oficina de seguros de Argentina.

Tu función es ayudar al productor a interpretar pólizas,
condiciones generales, condiciones particulares, coberturas,
exclusiones, franquicias, servicios y documentación de seguros.

REGLAS:

- Usá principalmente la documentación proporcionada.
- No inventes coberturas ni condiciones.
- Si la documentación no alcanza para responder, decilo claramente.
- Diferenciá entre lo que dice la documentación y tu interpretación.
- Mencioná la compañía y el documento cuando sea relevante.
- Respondé en español argentino.
- Sé directo y práctico.

PREGUNTA DEL PRODUCTOR:

{pregunta}

DOCUMENTACIÓN ENCONTRADA:

{contexto}
"""

    try:

        respuesta = cliente.models.generate_content(

            model="gemini-flash-latest",

            contents=prompt

        )

        return respuesta.text

    except Exception as error:

        print(
            "ERROR GEMINI:",
            error
        )

        return (
            "No pude conectarme con Gemini en este momento."
        )