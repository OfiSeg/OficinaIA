"""Regresiones críticas del cerebro conversacional de OficinaIA.

No usa Gemini, Flask, red ni credenciales. La intención es validar comportamiento
completo de routing/estado, no solamente buscar strings de un parche.
"""
from __future__ import annotations

from datetime import date, timedelta, datetime
from office_time import office_today
import importlib.util
from pathlib import Path
import sys
import types as pytypes
import time

import context_router
import chat_state

# chat_commands importa el despachador de Gmail/WhatsApp; para esta validación
# offline sólo necesitamos que exista su interfaz, no cargar integraciones Google.
_dispatch_stub = pytypes.ModuleType("dispatch_service")
_dispatch_stub.procesar_comando_explicito = lambda _mensaje: None
sys.modules.setdefault("dispatch_service", _dispatch_stub)
import chat_commands
from atm_cotizador import parsear_consulta_atm

ROOT = Path(__file__).resolve().parent


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# 1) ROUTER: documental vs cartera y operaciones estructuradas
# ---------------------------------------------------------------------------
ROUTER_CASES = {
    # Servicios de una compañía = documentación, aunque usen "tiene".
    "cuantos remolques tiene atm": "consulta_documental",
    "cuantas gruas tiene atm": "consulta_documental",
    "cuantos remolques ofrece federacion patronal": "consulta_documental",
    "cuantos remolques contempla federacion patronal": "consulta_documental",
    "cuantas gruas tiene Mapfre": "consulta_documental",
    "cuantos remolques tiene Zurich": "consulta_documental",
    "cuantos remolques hay en Allianz": "consulta_documental",
    "y atm en cada una de sus coberturas?": "consulta_documental",
    # Inventario propio = Excel/cartera.
    "cuantos remolques tengo en federacion patronal": "conteo_excel",
    "cuantos remolques tengo en excel": "conteo_excel",
    "cuantos asegurados tengo": "conteo_excel",
    "cuantos clientes tengo en excel": "conteo_excel",
    "cuantos registros tengo en excel": "conteo_excel",
    "cuantas polizas tengo en excel": "conteo_excel",
    # Extremos deben quedar en el dominio estructurado.
    "cual es el primer asegurado en el excel que tiene fecha de registro": "analisis_excel",
    "cual es el ultimo asegurado en excel": "analisis_excel",
    "mostrame el asegurado mas reciente de la cartera": "analisis_excel",
    "mostrame el asegurado mas antiguo de la cartera": "analisis_excel",
    "primer asegurado": "analisis_excel",
    "ultima poliza": "analisis_excel",
    # AUTO/MOTO se analizan como clase de riesgo y no como simples filas.
    "cuantos autos tengo": "analisis_excel",
    "cuantas motos tengo": "analisis_excel",
    # Comparación de compañías no es nombre de persona ni Excel.
    "donde puedo asegurar una moto": "comparacion_companias",
    "donde aseguro un auto 2001": "comparacion_companias",
    # ARCA/CUIT escritos como lenguaje natural no activan ARCA ni deben caer
    # accidentalmente en documentación por la abreviatura RC.
    "ARCA": "general",
    "CUIT": "general",
}
for pregunta, esperado in ROUTER_CASES.items():
    plan = context_router.construir_plan_base(pregunta)
    check(plan.intencion == esperado, f"Router: {pregunta!r}: esperado {esperado}, dio {plan.intencion}")


# ---------------------------------------------------------------------------
# 2) ARCA: puerta dura /cuit o /cuil. CERO heurística implícita.
# ---------------------------------------------------------------------------
_calls = {"dni": 0, "nombre": 0, "estado": 0}
_orig = {
    "resolver": chat_commands.arca_service.resolver_cuit_por_dni,
    "buscar": chat_commands.arca_service.buscar_personas_arca,
    "estado": chat_commands.arca_service.estado_padron,
}


def _fake_resolver(dni, *args, **kwargs):
    _calls["dni"] += 1
    return {"ok": True, "status": "found", "dni": str(dni), "cuit": "20433848567", "nombre": kwargs.get("nombre") or "Persona Prueba"}


def _fake_buscar(nombre, *args, **kwargs):
    _calls["nombre"] += 1
    return {
        "ok": True,
        "status": "multiple",
        "candidates": [
            {"dni": "11111111", "cuit": "20111111119", "nombre": "Juan Perez A"},
            {"dni": "22222222", "cuit": "20222222227", "nombre": "Juan Perez B"},
        ],
    }


def _fake_estado():
    _calls["estado"] += 1
    return {"cargado": True, "registros": 2, "fecha_padron": "2026-09", "backend": "test"}


chat_commands.arca_service.resolver_cuit_por_dni = _fake_resolver
chat_commands.arca_service.buscar_personas_arca = _fake_buscar
chat_commands.arca_service.estado_padron = _fake_estado
try:
    # Matriz amplia: ninguna variante sin slash puede tocar ARCA, aun si parece
    # DNI/CUIT/nombre o aunque exista contexto ARCA cacheado de un turno anterior.
    naturales = (
        "Juan Perez", "Ramiro Alejandro Herrera", "Perez Juan", "Mapfre Argentina",
        "Zurich Retiro", "Federacion Patronal", "Mercantil Andina", "San Cristobal",
        "43384856", "12345", "99999999", "20433848567", "20-43384856-7",
        "dni 43384856", "DNI: 43384856", "documento 43384856",
        "cuit 20433848567", "CUIT de Juan Perez", "cuil 20-43384856-7",
        "ARCA", "padron arca", "buscar en ARCA a Juan Perez", "buscame el cuit de Juan Perez",
        "cual fue el ultimo", "quien fue el primero", "el segundo", "y el anterior",
        "el de hoy", "el que cargue", "me pasas los datos", "quiero ver detalles",
        "donde puedo asegurar una moto", "quiero cotizar una moto", "quiero asegurar un auto 2001",
        "cuantas gruas tiene ATM", "cuantos remolques tiene Federacion Patronal",
        "cuantos asegurados tengo", "cuantas polizas tengo en excel", "cual es el ultimo asegurado",
        "hola", "gracias", "que cobertura tiene una moto 125",
    )
    contexto_candidatos = {
        "fuente": "ARCA",
        "activado_por_comando": True,
        "candidates": [
            {"dni": "11111111", "nombre": "A"},
            {"dni": "22222222", "nombre": "B"},
        ],
    }
    for q in naturales:
        r = chat_commands.parsear_cuit_arca(q, arca_context=contexto_candidatos)
        check(r is None, f"ARCA se activó sin /cuit o /cuil para {q!r}: {r}")
    check(sum(_calls.values()) == 0, f"Hubo llamadas ARCA implícitas: {_calls}")

    r = chat_commands.parsear_cuit_arca("/cuit 43384856")
    check(r and r.get("resultado", {}).get("status") == "found", "/cuit DNI no resolvió")
    check(_calls["dni"] == 1, "/cuit DNI no llamó exactamente una vez al resolver")

    r = chat_commands.parsear_cuit_arca("/cuil Juan Perez")
    check(r and r.get("resultado", {}).get("status") == "multiple", "/cuil nombre no resolvió")
    check(_calls["nombre"] == 1, "/cuil nombre no llamó exactamente una vez al buscador")
    texto_candidatos = chat_commands._formatear_resultado_arca(r.get("resultado") or {})
    check("/cuit 2" in texto_candidatos or "/cuil 2" in texto_candidatos,
          "La respuesta con candidatos ARCA no indica que la selección también exige slash")

    # La selección también exige repetir el prefijo. Sin prefijo ya fue probada arriba.
    r = chat_commands.parsear_cuit_arca("/cuit 2", arca_context=contexto_candidatos)
    check(r and r.get("seleccion") == 2, "/cuit 2 no seleccionó el segundo candidato cacheado")
    check(_calls["dni"] == 1 and _calls["nombre"] == 1, "Seleccionar candidato hizo una nueva búsqueda ARCA")

    before = dict(_calls)
    r = chat_commands.parsear_cuit_arca("/cuit")
    check(r and r.get("error"), "/cuit vacío debería devolver ayuda sin dejar modo latente")
    check(_calls == before, "/cuit vacío consultó ARCA")

    # Ningún parser natural previo puede secuestrar un slash explícito de ARCA.
    check(chat_commands.parsear_ficha_operativa("/cuit ficha Juan Perez") is None,
          "La heurística de ficha intercepta /cuit")
    check(chat_commands.parsear_ficha_operativa("/cuil expediente Juan Perez") is None,
          "La heurística de ficha intercepta /cuil")
finally:
    chat_commands.arca_service.resolver_cuit_por_dni = _orig["resolver"]
    chat_commands.arca_service.buscar_personas_arca = _orig["buscar"]
    chat_commands.arca_service.estado_padron = _orig["estado"]

# El modelo general tampoco debe tener tools ARCA disponibles.
tools_src = (ROOT / "sofia_tools.py").read_text(encoding="utf-8")
handlers_src = (ROOT / "servicios_ia.py").read_text(encoding="utf-8")
tool_defs_slice = tools_src[tools_src.index("TOOL_DEFINITIONS"):]
for nombre_tool in ("resolver_cuit_por_dni", "buscar_personas_arca", "estado_padron_arca"):
    check(f'name="{nombre_tool}"' not in tool_defs_slice, f"ARCA sigue declarado como tool general: {nombre_tool}")
handlers_slice = handlers_src[handlers_src.index("_TOOL_HANDLERS"):handlers_src.index("def _mensaje_fuente_interna_no_disponible")]
for nombre_tool in ("resolver_cuit_por_dni", "buscar_personas_arca", "estado_padron_arca"):
    check(f'"{nombre_tool}"' not in handlers_slice, f"ARCA sigue en dispatcher general: {nombre_tool}")
check("import arca_service" not in handlers_src, "servicios_ia todavía importa ARCA y podría reintroducir llamadas implícitas")

# Construir el prompt de un turno normal tampoco debe consultar el estado ARCA
# ni anunciar esas capacidades como disponibles a Gemini. El comando /cuit se
# resuelve antes de llegar a Sofia.
import capabilities
_prompt_caps = capabilities.capabilities_for_prompt()
check("Resolver CUIT/CUIL" not in _prompt_caps and "Buscar personas en ARCA" not in _prompt_caps,
      "El prompt general todavía expone capacidades ARCA fuera de /cuit o /cuil")


# ---------------------------------------------------------------------------
# 3) ESTADO: cada chat conserva su contexto independientemente.
# ---------------------------------------------------------------------------
session = {}
chat_state.guardar(session, "arca_context", {"fuente": "ARCA", "valor": "A"}, chat_id=101, ttl_seconds=60)
chat_state.guardar(session, "arca_context", {"fuente": "ARCA", "valor": "B"}, chat_id=202, ttl_seconds=60)
check(chat_state.obtener(session, "arca_context", chat_id=101)["valor"] == "A", "Chat B borró contexto de Chat A")
check(chat_state.obtener(session, "arca_context", chat_id=202)["valor"] == "B", "Chat A contaminó contexto de Chat B")
check(chat_state.obtener(session, "arca_context", chat_id=303) is None, "Contexto cruzado a un tercer chat")

# Podar un chat no debe borrar estados vigentes ajenos, pero sí retirar buckets
# vencidos de otras conversaciones para que la sesión no crezca sin límite.
store = session.get(chat_state._STORE_KEY)
store["101"]["arca_context"][chat_state._META_EXPIRES] = int(time.time()) - 1
chat_state.podar(session, chat_id=202)
check(chat_state.obtener(session, "arca_context", chat_id=101) is None, "Podado dejó un contexto vencido de otro chat")
check(chat_state.obtener(session, "arca_context", chat_id=202)["valor"] == "B", "Podado global borró contexto vigente de otro chat")


# ---------------------------------------------------------------------------
# 4) ATM legacy: año/cilindrada no son precios.
# ---------------------------------------------------------------------------
valid = parsear_consulta_atm("ATM 158561 auto")
check(not valid.get("error") and int(valid.get("precio") or 0) == 158561, "Sintaxis legacy ATM válida dejó de funcionar")
for q in (
    "ATM auto 2001 cuantos remolques tiene",
    "ATM auto 2026 tiene grua?",
    "ATM moto 110 tiene remolque?",
    "ATM moto 125 que cobertura tiene",
    "cuantas gruas tiene ATM",
):
    r = parsear_consulta_atm(q)
    check(r.get("error"), f"ATM confundió año/cilindrada con precio: {q!r} -> {r}")


# ---------------------------------------------------------------------------
# 5) Excel: conteo -> último -> anterior y fechas nuevas pisan contexto viejo.
#    Se carga el módulo con un servicios_ia mínimo para no requerir Gemini.
# ---------------------------------------------------------------------------
hoy = office_today()
filas_prueba = [
    {"ASEGURADO": "Alpha", "PATENTE": "AAA111", "CIA": "ATM", "EMITIDO DÍA:": (hoy - timedelta(days=3)).strftime("%d/%m/%Y")},
    {"ASEGURADO": "Beta", "PATENTE": "BBB222", "CIA": "ATM", "EMITIDO DÍA:": (hoy - timedelta(days=2)).strftime("%d/%m/%Y")},
    {"ASEGURADO": "Gamma", "PATENTE": "CCC333", "CIA": "ATM", "EMITIDO DÍA:": (hoy - timedelta(days=1)).strftime("%d/%m/%Y")},
    {"ASEGURADO": "Delta", "PATENTE": "DDD444", "CIA": "ATM", "EMITIDO DÍA:": hoy.strftime("%d/%m/%Y")},
]

fake = pytypes.ModuleType("servicios_ia")


def _norm(v):
    return str(v or "").strip().lower()


def _campo_por_alias(fila, aliases):
    wanted = {_norm(a).replace("ó", "o").replace("í", "i") for a in aliases if a}
    for k in fila:
        nk = _norm(k).replace("ó", "o").replace("í", "i")
        if nk in wanted:
            return k
    return None


def _parse_fecha(v):
    if isinstance(v, date):
        return v
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v), fmt).date()
        except ValueError:
            pass
    return None


def _filtrar(rows, compania=None, campo=None, valor=None, tipo_vehiculo=None, desde=None, hasta=None, campo_fecha=None):
    out = list(rows)
    if compania:
        out = [r for r in out if _norm(r.get("CIA")) == _norm(compania)]
    if tipo_vehiculo:
        token = "remolque" if _norm(tipo_vehiculo) in {"remolque", "trailer"} else _norm(tipo_vehiculo)
        out = [r for r in out if token in _norm(r.get("VEHICULO"))]
    if desde or hasta:
        d0, d1 = _parse_fecha(desde) if desde else None, _parse_fecha(hasta) if hasta else None
        out2 = []
        for r in out:
            d = _parse_fecha(r.get("EMITIDO DÍA:"))
            if d and (not d0 or d >= d0) and (not d1 or d <= d1):
                out2.append(r)
        out = out2
    return out, {}


def _buscar(**kwargs):
    limite = int(kwargs.pop("limite", 25) or 25)
    out, _ = _filtrar(filas_prueba, **{k: v for k, v in kwargs.items() if k in {"compania", "campo", "valor", "tipo_vehiculo", "desde", "hasta", "campo_fecha"}})
    return {"cantidad": len(out), "registros": out[:limite]}


def _contar(tipo_conteo="filas", **kwargs):
    out, _ = _filtrar(filas_prueba, **{k: v for k, v in kwargs.items() if k in {"compania", "campo", "valor", "tipo_vehiculo", "desde", "hasta", "campo_fecha"}})
    if tipo_conteo == "unicos":
        cantidad = len({_norm(r.get("ASEGURADO")) for r in out if r.get("ASEGURADO")})
    else:
        cantidad = len(out)
    return {"cantidad": cantidad}


fake._campo_por_alias = _campo_por_alias
fake._parsear_fecha_excel = _parse_fecha
fake._dataset_estructurado = lambda: (list(filas_prueba), "test")
fake._filtrar_filas = _filtrar
fake.buscar_registros_estructurados = _buscar
fake.contar_registros = _contar
fake._companias_mencionadas_en_consulta = lambda q: ["Mapfre"] if "mapfre" in _norm(q) else []

real_servicios = sys.modules.get("servicios_ia")
sys.modules["servicios_ia"] = fake
try:
    spec = importlib.util.spec_from_file_location("excel_context_validation", ROOT / "excel_conversation_context.py")
    excel_ctx = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = excel_ctx
    spec.loader.exec_module(excel_ctx)

    s = {}
    r = excel_ctx.responder_consulta_directa("cuantas polizas tengo en excel", session_obj=s, chat_id=1)
    check(r and "4" in r, f"Conteo Excel directo falló: {r}")
    r_first = excel_ctx.responder_consulta_directa("primer asegurado", session_obj={}, chat_id=8)
    check(r_first and "Alpha" in r_first, f"'primer asegurado' no resolvió cartera directamente: {r_first}")
    r_mapfre = excel_ctx.responder_consulta_directa("cuantos asegurados tengo en Mapfre", session_obj={}, chat_id=9)
    check(r_mapfre and "0" in r_mapfre and "Mapfre" in r_mapfre, f"Conteo por compañía documental perdió filtro: {r_mapfre}")
    r_inv = excel_ctx.responder_consulta_directa("cuantos remolques tengo en excel", session_obj={}, chat_id=10)
    check(r_inv and "0" in r_inv, f"Inventario explícito de remolques no usó filtro estructurado: {r_inv}")
    r_doc = excel_ctx.responder_consulta_directa("cuantos remolques hay en ATM", session_obj={}, chat_id=11)
    check(r_doc is None, f"Pregunta documental de remolques fue secuestrada por cartera: {r_doc}")
    for comando_slash in ("/cuit 43384856", "/cuil Juan Perez", "/envios ya ABC123", "/flota 123"):
        r_slash = excel_ctx.responder_consulta_directa(comando_slash, session_obj=s, chat_id=1)
        check(r_slash is None, f"Cartera interceptó un comando slash ajeno: {comando_slash!r} -> {r_slash}")
    r = excel_ctx.responder_consulta_directa("cual fue el ultimo", session_obj=s, chat_id=1)
    check(r and "Delta" in r, f"Follow-up último no heredó cartera: {r}")
    r = excel_ctx.responder_consulta_directa("y la patente?", session_obj=s, chat_id=1)
    check(r and "DDD444" in r, f"Follow-up de campo perdió el registro seleccionado: {r}")
    r = excel_ctx.responder_consulta_directa("y el anterior", session_obj=s, chat_id=1)
    check(r and "Gamma" in r, f"Navegación anterior no funciona: {r}")

    # Un rango nuevo debe pisar el contexto anterior, no referirse al conjunto viejo.
    r = excel_ctx.responder_consulta_directa("el de hoy", session_obj=s, chat_id=1)
    check(r and "Delta" in r, f"'el de hoy' reutilizó contexto viejo: {r}")

    # Un chat distinto no hereda el follow-up del chat 1.
    r = excel_ctx.responder_consulta_directa("cual fue el ultimo", session_obj=s, chat_id=2)
    check(r is None, f"Chat 2 heredó contexto Excel de chat 1: {r}")
    # Sin contexto de cartera, un follow-up de campo puede pertenecer a una
    # póliza/PDF u otro dominio y Excel debe dejarlo pasar.
    r = excel_ctx.responder_consulta_directa("y la patente?", session_obj={}, chat_id=99)
    check(r is None, f"Cartera secuestró un follow-up sin contexto activo: {r}")
finally:
    sys.modules.pop("excel_context_validation", None)
    if real_servicios is not None:
        sys.modules["servicios_ia"] = real_servicios
    else:
        sys.modules.pop("servicios_ia", None)



# ---------------------------------------------------------------------------
# 5.5) Analítica AUTO/MOTO: una fila no se cuenta ciegamente como vehículo.
# ---------------------------------------------------------------------------
import excel_analytics

filas_vehiculos = [
    {"ASEGURADO": "Uno", "PATENTE": "ABC123", "VEHICULO": "FIAT", "CIA": "ATM"},       # AUTO histórico
    {"ASEGURADO": "Dos", "PATENTE": "123ABC", "VEHICULO": "HONDA WAVE", "CIA": "ATM"}, # MOTO histórica
    {"ASEGURADO": "Tres", "PATENTE": "AB123CD", "VEHICULO": "TOYOTA", "CIA": "ATM"},    # AUTO Mercosur
    {"ASEGURADO": "Cuatro", "PATENTE": "A123BCD", "VEHICULO": "YAMAHA", "CIA": "ATM"},  # MOTO Mercosur
    {"ASEGURADO": "Cinco", "PATENTE": "", "VEHICULO": "", "CIA": "ATM"},                # no adivinar
]
for consulta, clase, cantidad in (
    ("cuantos autos tengo", "AUTO", 2),
    ("cuantas motos tengo", "MOTO", 2),
    ("total de autos en cartera", "AUTO", 2),
    ("cantidad de motos", "MOTO", 2),
):
    r = excel_analytics.analizar(filas_vehiculos, consulta=consulta)
    check(r.get("ok"), f"Analítica de vehículos no reconoció {consulta!r}: {r}")
    check(r.get("clase_solicitada") == clase, f"Clase incorrecta para {consulta!r}: {r}")
    check(r.get("cantidad_solicitada") == cantidad, f"Conteo incorrecto para {consulta!r}: {r}")
    check(r.get("indeterminados") == 1, f"Se adivinó un vehículo indeterminado para {consulta!r}: {r}")


# ---------------------------------------------------------------------------
# 6) Contratos de implementación que evitan regresiones silenciosas.
# ---------------------------------------------------------------------------
check('fuentes_ejecutadas' in handlers_src, "La allowlist vuelve a confundir fuente planificada con ejecutada")
check('SIN_FICHAS_DE_LA_COMPANIA' in handlers_src, "Falta aislamiento estricto de metadata")
check('_COMPANIAS_DOCUMENTALES_EXTRA' in handlers_src, "Metadata no cubre compañías conocidas fuera del catálogo operativo")
check('permitir_internet' in handlers_src and 'permitidas.add("buscar_en_internet")' in handlers_src, "Internet no está controlado por intención explícita")
check('modelo_fijado = None' in handlers_src and 'models=modelos_llamada' in handlers_src, "Gemini puede cambiar de modelo dentro del mismo turno")
check('types.Content(role="user", parts=respuestas_tools)' in handlers_src, "Function responses no conservan rol user")

print("OK - cerebro conversacional: routing, ARCA estricto, estado, ATM y follow-ups Excel")
