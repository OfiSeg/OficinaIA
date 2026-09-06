"""Esquemas de herramientas disponibles para Sofia.

V20 Etapa 3: contratos de tools separados de retrieval, routing y prompt.
Este módulo declara capacidades; no ejecuta ninguna.
"""
from google.genai import types

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
            name="analizar_excel",
            description=(
                "Hace analítica exacta sobre TODO el Excel interno: agrupaciones y rankings, "
                "porcentajes, duplicados, campos vacíos, clasificación auto/moto y tipos de riesgo (incluido hogar/combinado familiar). Usala para "
                "preguntas como 'qué compañía tengo más', 'segundo porcentaje', 'ordená compañías', "
                "'patentes repetidas', 'cuántos no tienen patente' o 'tengo más motos o autos'. "
                "Puede recibir sólo consulta con la pregunta natural; el backend resolverá la "
                "operación determinísticamente. También acepta parámetros estructurados si conviene."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "consulta": {"type": "string"},
                    "operacion": {"type": "string", "enum": ["ranking", "duplicados", "vacios", "clasificacion", "clasificacion_riesgos", "porcentaje"]},
                    "campo": {"type": "string"},
                    "agrupar_por": {"type": "string"},
                    "compania": {"type": "string"},
                    "valor": {"type": "string"},
                    "excluir_valor": {"type": "string"},
                    "limite": {"type": "integer"},
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

