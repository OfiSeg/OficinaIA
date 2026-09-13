"""Validación de regresiones críticas del router conversacional.
No requiere Gemini, Flask ni credenciales externas.
"""
from pathlib import Path
import re
import context_router

ROOT = Path(__file__).resolve().parent


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)

# Las frases reportadas deben ser documentales, no inventario Excel.
for q in (
    "y atm en cada una de sus coberturas?",
    "cuantas gruas tiene atm en cada una de sus coberturas",
    "cuantos remolques contempla federacion patronal",
):
    plan = context_router.construir_plan_base(q)
    check(plan.intencion == "consulta_documental", f"Router incorrecto: {q!r} -> {plan}")

# El handler especial no debe usar respuesta_chat_atm y sólo puede abrir la UI
# ante sintaxis legacy realmente calculable.
special = (ROOT / "chat_special.py").read_text(encoding="utf-8")
check("respuesta_chat_atm" not in special, "Sigue activa la calculadora textual ATM")
check("parsear_consulta_atm" in special and "abrir_cotizador_atm" in special, "No quedó redirección segura a Cotizaciones")

# 'sus' no puede ser disparador universal de cartera.
excel_ctx = (ROOT / "excel_conversation_context.py").read_text(encoding="utf-8")
check('"cobertura", "coberturas"' in excel_ctx, "Falta guardia documental en follow-up de cartera")
check(r'\b(sus|su|ese|esa|eso|' not in excel_ctx, "Permanece el patrón amplio que secuestra cualquier 'sus'")

# ARCA no debe activar contexto sólo por preguntar la fuente.
commands = (ROOT / "chat_commands.py").read_text(encoding="utf-8")
check('if arca.get("pregunta_fuente"):\n            # Preguntar la fuente NO equivale a activar ARCA.' in commands, "Pregunta ARCA todavía activa contexto")
check('aliases_companias' in commands and 'bloqueadores' in commands, "Falta guardia compañía/documental de ARCA")

# Metadata: jamás fallback a todas las fichas si se pidió una compañía concreta.
svc = (ROOT / "servicios_ia.py").read_text(encoding="utf-8")
check('SIN_FICHAS_DE_LA_COMPANIA' in svc, "Falta aislamiento estricto de metadata")
check('universo = fichas' not in svc[svc.index('def buscar_en_metadatos'):svc.index('# V16:', svc.index('def buscar_en_metadatos'))], "Sigue activo fallback cruzado de metadata")
check('permitir_internet' in svc and 'permitidas.add("buscar_en_internet")' in svc, "Internet no está controlado por allowlist/intención explícita")

print("OK - regresiones críticas del router cubiertas")

# Estado operativo: TTL común y no reactivación por historial.
import chat_state
_s = {}
chat_state.guardar(_s, "arca_context", {"fuente": "ARCA"}, chat_id=7, ttl_seconds=60)
assert chat_state.obtener(_s, "arca_context", chat_id=7)["fuente"] == "ARCA"
assert chat_state.obtener(_s, "arca_context", chat_id=8) is None

commands = (ROOT / "chat_commands.py").read_text(encoding="utf-8")
check('return bool(isinstance(arca_context, dict) and arca_context.get("fuente") == "ARCA")' in commands, "ARCA todavía puede reactivarse por historial")

svc = (ROOT / "servicios_ia.py").read_text(encoding="utf-8")
check('modelo_fijado = None' in svc and 'models=modelos_llamada' in svc, "Gemini todavía puede cambiar de modelo dentro del mismo turno")
check('types.Content(role="user", parts=respuestas_tools)' in svc, "Function responses siguen fuera de Content(role=user)")
check('permitidas.update({"buscar_en_manuales", "guardar_metadato_relevante"})' in svc, "No quedó allowlist documental")
check('resolver_cuit_por_dni' not in svc[svc.index('def _tools_para_plan'):svc.index('def _mensaje_fuente_interna_no_disponible')], "ARCA sigue expuesto a Gemini")

# Selección de fuente: "ARCA" solo nunca intenta leer un archivo y una pregunta
# cartera explícita queda bloqueada del heurístico de persona. Validación estática
# para no importar integraciones Google en este script sin credenciales.
commands = (ROOT / "chat_commands.py").read_text(encoding="utf-8")
check('if n in {"arca", "padron arca", "padron", "cuit", "cuil", "padron arca cuit"}:' in commands, "Falta manejo explícito de ARCA solo")
check('"modo_arca": True' in commands and 'ARCA listo. Pasame un DNI' in commands, "ARCA solo todavía puede intentar leer un archivo")
check('"cartera", "asegurados", "buscar", "busca", "buscame"' in commands, "'mi cartera' sigue expuesta al heurístico de persona")
check('source_choice_pending' in commands, "Falta estado de selección de fuente pendiente")

# La elección pendiente queda bajo el mismo TTL común.
check("source_choice_pending" in chat_state.DEFAULT_TTLS, "Falta TTL para selección de fuente")
