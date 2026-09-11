from __future__ import annotations

import sys
import types as pytypes
from datetime import date

# Stubs mínimos para correr en entornos sin google-genai ni integraciones externas.
try:
    import google.genai  # type: ignore
except Exception:
    google_mod = sys.modules.get("google") or pytypes.ModuleType("google")
    genai_mod = pytypes.ModuleType("google.genai")
    types_mod = pytypes.ModuleType("google.genai.types")

    class Generic:
        def __init__(self, *args, **kwargs):
            self.args = args; self.kwargs = kwargs

    for name in [
        "Tool", "FunctionDeclaration", "GenerateContentConfig",
        "AutomaticFunctionCallingConfig", "Part", "Content", "Schema", "HttpOptions",
    ]:
        setattr(types_mod, name, Generic)
    types_mod.Part.from_text = staticmethod(lambda text: ("text", text))
    types_mod.Part.from_bytes = staticmethod(lambda data, mime_type: ("bytes", mime_type, len(data)))
    types_mod.Part.from_function_response = staticmethod(lambda name, response: ("function_response", name, response))
    genai_mod.types = types_mod
    genai_mod.Client = Generic
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod

for name in ("google_sheets_service", "document_search", "metadata_store", "dispatch_service"):
    if name not in sys.modules:
        sys.modules[name] = pytypes.ModuleType(name)
sys.modules["google_sheets_service"].leer_excel = lambda libro_id="1": {"filas": []}
sys.modules["document_search"].buscar_en_documentos = lambda consulta: []
sys.modules["metadata_store"].cargar_metadatos = lambda: []
sys.modules["dispatch_service"].enviar_por_canal = lambda **kwargs: {"ok": True}

import servicios_ia
import excel_conversation_context as ctx
import chat_special

FILAS = [
    {
        "ASEGURADO": "VELAZQUE MARTIN",
        "NUMERO": "",
        "VEHICULO": "HONDA WAVE 110",
        "PATENTE": "A123BCD",
        "CIA": "ATM",
        "MEDIO DE PAGO": "CUPONERA",
        "CP": "1864",
        "EMITIDO DÍA:": "10/09/2026",
        "IMPORTE APROX": "12000",
    },
    {
        "ASEGURADO": "GEREZ MATIAS",
        "NUMERO": "0",
        "VEHICULO": "CERRO 110",
        "PATENTE": "959KGA",
        "CIA": "ATM",
        "MEDIO DE PAGO": "CUPONERA",
        "CP": "1864",
        "EMITIDO DÍA:": "",
        "IMPORTE APROX": "7900",
    },
    {
        "CLIENTE": "PEREZ JUAN",
        "VEHICULO": "FIAT UNO",
        "PATENTE": "BBB222",
        "CIA": "RIVADAVIA",
        "EMITIDO DÍA:": "10/09/2026",
    },
]


def instalar_dataset(filas):
    servicios_ia._dataset_estructurado = lambda: (list(filas), "dataset test")
    # La validación debe ser estable aunque se ejecute después del 10/09.
    ctx.office_today = lambda: date(2026, 9, 10)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_fecha_temporal_excluye_filas_sin_fecha():
    instalar_dataset(FILAS)
    r = servicios_ia.buscar_registros_estructurados(desde="10/09/2026", hasta="10/09/2026")
    nombres = " | ".join(str(f.get("ASEGURADO") or f.get("CLIENTE") or "") for f in r["registros"])
    check("VELAZQUE" in nombres, "Debe encontrar la fila emitida hoy")
    check("GEREZ" not in nombres, "Una fila sin fecha no puede satisfacer 'hoy'")


def test_conteo_hoy_y_followup_detalles_no_devuelve_gerez():
    instalar_dataset(FILAS[:2])
    session = {}
    respuesta = ctx.responder_conteo_temporal("cuantos emití hoy", session_obj=session, chat_id=99)
    check("1" in respuesta, "Debe contar un solo registro de hoy")
    detalle = ctx.responder_followup_registro("decime sus detalles", session_obj=session, chat_id=99)
    check("VELAZQUE" in detalle, "El follow-up debe detallar el registro activo de hoy")
    check("GEREZ" not in detalle, "El follow-up no debe reabrir búsqueda fuzzy hacia Gerez")


def test_pronombre_sin_contexto_pregunta():
    instalar_dataset(FILAS)
    respuesta = ctx.responder_followup_registro("decime sus detalles", session_obj={}, chat_id=1)
    check("De qué registro" in respuesta or "registro" in respuesta, "Debe pedir aclaración si no hay referente")


def test_varios_hoy_no_eligen_arbitrariamente():
    instalar_dataset(FILAS)
    session = {}
    ctx.responder_conteo_temporal("cuantos emití hoy", session_obj=session, chat_id=5)
    respuesta = ctx.responder_followup_registro("decime sus detalles", session_obj=session, chat_id=5)
    check("no voy a elegir uno arbitrariamente" in respuesta, "Varios resultados deben pedir selección")
    check("VELAZQUE" in respuesta and "PEREZ" in respuesta, "Debe mostrar opciones reales")


def test_alias_asegurado_cliente_nombre():
    instalar_dataset(FILAS)
    r1 = servicios_ia.buscar_registros_estructurados(asegurado="Velazque")
    r2 = servicios_ia.buscar_registros_estructurados(asegurado="Perez")
    check(r1["cantidad"] == 1, "Debe buscar por ASEGURADO")
    check(r2["cantidad"] == 1, "Debe buscar por CLIENTE")


def test_numero_no_es_poliza_ni_dni_en_identificador_fuerte():
    fila = {"ASEGURADO": "X", "NUMERO": "1764648", "PATENTE": "ABC123"}
    check(not servicios_ia._coincidencia_identificador("1764648", fila), "NUMERO histórico no debe funcionar como póliza/DNI fuerte")
    check(servicios_ia._coincidencia_identificador("ABC123", fila), "PATENTE sí sigue siendo identificador fuerte")


def test_intencion_puntual_no_dispara_alta_automatica():
    check(chat_special._es_consulta_puntual_sobre_adjunto("qué cobertura tiene?"), "Cobertura es pregunta puntual")
    check(not chat_special._es_pedido_procesamiento_documental("qué cobertura tiene?"), "No debe pedir pipeline operativo")
    check(chat_special._es_pedido_procesamiento_documental("procesá esta póliza"), "Procesar póliza sí habilita pipeline")


def test_rango_con_hoy_inyectado():
    rango = ctx.resolver_rango_temporal("cuántos tuve hoy", hoy=date(2026, 9, 10))
    check(rango.desde == date(2026, 9, 10) and rango.hasta == date(2026, 9, 10), "Hoy debe salir de fecha de oficina inyectada")
    rango = ctx.resolver_rango_temporal("del 5 para acá", hoy=date(2026, 9, 10))
    check(rango.desde == date(2026, 9, 5) and rango.hasta == date(2026, 9, 10), "Debe resolver del 5 para acá")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for test in tests:
        test()
        ok += 1
    print(f"VALIDACION_ETAPA2_CONTEXTO_CARTERA: {ok}/{len(tests)} OK")
