from __future__ import annotations

import importlib
import sys
import types as pytypes
from pathlib import Path

# Stubs mínimos para correr offline sin google-genai ni base de Salud real.
try:
    import google.genai  # type: ignore
except Exception:
    google_mod = sys.modules.get("google") or pytypes.ModuleType("google")
    genai_mod = pytypes.ModuleType("google.genai")
    types_mod = pytypes.ModuleType("google.genai.types")

    class HttpOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    types_mod.HttpOptions = HttpOptions
    genai_mod.types = types_mod
    genai_mod.Client = object
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod

EVENTOS = []
health = pytypes.ModuleType("system_health")

def registrar_evento(categoria, nivel, mensaje, detalle=None, codigo=None):
    EVENTOS.append({
        "categoria": categoria,
        "nivel": nivel,
        "mensaje": mensaje,
        "detalle": detalle,
        "codigo": codigo,
    })

health.registrar_evento = registrar_evento
sys.modules["system_health"] = health

import ai_gateway
from resilience import call_read_with_resilience


class FakeError(RuntimeError):
    def __init__(self, message, status_code=None, reason=None):
        super().__init__(message)
        self.status_code = status_code
        if reason:
            self.reason = reason


class Part:
    def __init__(self, text="x"):
        self.text = text


class Content:
    def __init__(self):
        self.parts = [Part()]


class Candidate:
    def __init__(self, finish_reason="STOP"):
        self.content = Content()
        self.finish_reason = finish_reason


class Response:
    def __init__(self, text="ok", finish_reason="STOP", parts=True):
        self.text = text
        self.candidates = [Candidate(finish_reason)] if parts else []


class FakeModels:
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        item = self.sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, sequence):
        self.models = FakeModels(sequence)


def reset_ai(request_id="req-test"):
    EVENTOS.clear()
    ai_gateway.begin_request(60, request_id=request_id)


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def codes():
    return [e.get("codigo") for e in EVENTOS]


def test_ai_gateway_retry_y_recuperacion_quedan_logueados():
    reset_ai("chat123")
    client = FakeClient([FakeError("503 UNAVAILABLE", 503, "UNAVAILABLE"), Response("bien")])
    resp, model = ai_gateway.generate_with_fallback(
        contents="x", config={}, client=client, models=("m1", "m2"), log_prefix="TEST_CHAT"
    )
    assert_true(resp.text == "bien", "La segunda llamada debe recuperar la respuesta")
    assert_true(len(client.models.calls) == 2, "Debe usar dos intentos")
    assert_true("AI_TRANSIENT_RETRY" in codes(), "Debe registrar el fallo temporal/reintento")
    assert_true("AI_RECOVERED" in codes(), "Debe registrar la recuperación explícita")
    detalle = "\n".join(str(e.get("detalle") or "") for e in EVENTOS)
    assert_true("status=503" in detalle, "El detalle debe conservar status cuando existe")
    assert_true("UNAVAILABLE" in detalle, "El detalle debe conservar motivo cuando existe")
    assert_true("chat123" in detalle, "El detalle debe conservar correlación de secuencia")


def test_ai_gateway_agotamiento_queda_logueado():
    reset_ai("chat456")
    client = FakeClient([
        FakeError("503", 503),
        FakeError("502", 502),
        FakeError("timeout TIMEOUT"),
    ])
    try:
        ai_gateway.generate_with_fallback(
            contents="x", config={}, client=client, models=("m1", "m2"), log_prefix="TEST_CHAT"
        )
    except Exception:
        pass
    else:
        raise AssertionError("Debió fallar luego de agotar intentos")
    assert_true(len(client.models.calls) == 3, "Debe realizar tres intentos")
    assert_true("AI_RETRIES_EXHAUSTED" in codes(), "Debe registrar agotamiento real 3/3")


def test_ai_gateway_auth_no_miente_agotamiento():
    reset_ai("chat789")
    client = FakeClient([FakeError("invalid api key", 401), Response("no")])
    try:
        ai_gateway.generate_with_fallback(
            contents="x", config={}, client=client, models=("m1", "m2"), log_prefix="TEST_CHAT"
        )
    except Exception:
        pass
    else:
        raise AssertionError("Debió fallar rápido")
    assert_true(len(client.models.calls) == 1, "401/API key debe fallar rápido")
    assert_true("AI_FINAL_FAILURE" in codes(), "Debe registrar fallo final no recuperable")
    assert_true("AI_RETRIES_EXHAUSTED" not in codes(), "No debe fingir 3/3 si no ocurrió")


def test_resilience_generica_registra_recuperacion_y_agotamiento():
    EVENTOS.clear()
    calls = {"n": 0}

    def ok_en_segundo():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeError("503", 503)
        return "ok"

    assert_true(
        call_read_with_resilience(ok_en_segundo, operation="read", provider="test", delays=(0, 0, 0)) == "ok",
        "Debe recuperar lectura genérica",
    )
    assert_true("AI_TRANSIENT_RETRY" in codes() and "AI_RECOVERED" in codes(), "Debe registrar retry y recuperación")

    EVENTOS.clear()
    def siempre_falla():
        raise FakeError("503", 503)

    try:
        call_read_with_resilience(siempre_falla, operation="read", provider="test", delays=(0, 0, 0))
    except Exception:
        pass
    else:
        raise AssertionError("Debió fallar")
    assert_true("AI_RETRIES_EXHAUSTED" in codes(), "Debe registrar agotamiento en capa genérica")


def test_frontend_limpia_solo_snapshot_enviado():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    assert_true("const textoOriginal=i.value" in js, "Debe capturar snapshot del texto enviado")
    assert_true("const editSeqAlEnviar=composerEditSeq" in js, "Debe capturar secuencia de edición")
    assert_true("limpiarComposerDespuesDeEnvio(i,textoOriginal,editSeqAlEnviar)" in js, "Debe limpiar mediante helper seguro")
    assert_true("if(composerEditSeq===seqAlEnviar && input.value===valorEnviado)" in js, "Debe evitar borrar borradores nuevos")
    enviar = js[js.index("async function enviarMensaje") : js.index("async function initChat")]
    assert_true("i.value='';size();" not in enviar, "Enviar no debe borrar el textarea de forma incondicional")


def test_frontend_no_borra_adjuntos_nuevos():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    assert_true("quitarAdjuntosEnviados(archivos,attachmentSeqAlEnviar)" in js, "Debe retirar sólo adjuntos enviados")
    assert_true("archivosAdjuntosChat=archivosAdjuntosChat.filter(f=>!enviadosSet.has(f))" in js, "Debe conservar adjuntos agregados luego")
    enviar = js[js.index("async function enviarMensaje") : js.index("async function initChat")]
    assert_true("quitarAdjunto();" not in enviar, "Enviar no debe vaciar todos los adjuntos")


def test_cache_busting_automatico():
    app = Path("app.py").read_text(encoding="utf-8")
    base = Path("templates/base.html").read_text(encoding="utf-8")
    estudio = Path("templates/estudio.html").read_text(encoding="utf-8")
    salud = Path("templates/salud.html").read_text(encoding="utf-8")
    envios = Path("templates/envios_masivos.html").read_text(encoding="utf-8")
    login = Path("templates/login.html").read_text(encoding="utf-8")
    assert_true("def static_asset" in app and "path.stat().st_mtime" in app, "Debe existir static_asset por mtime")
    assert_true("static_asset('js/app.js')" in base and "static_asset('css/estilo.css')" in base, "Base debe usar static_asset")
    assert_true("static_asset('js/estudio.js')" in estudio, "Estudio debe cache-bustear JS")
    assert_true("static_asset('js/salud.js')" in salud, "Salud debe cache-bustear JS")
    assert_true("static_asset('js/envios_masivos.js')" in envios, "Envíos masivos debe cache-bustear JS")
    assert_true("static_asset('css/login.css')" in login, "Login debe cache-bustear CSS")
    all_tpl = "\n".join(p.read_text(encoding="utf-8") for p in Path("templates").glob("*.html"))
    assert_true("20260911-etapa1" not in all_tpl and "20260905" not in all_tpl, "No deben quedar versiones manuales viejas en templates locales")


def test_error_visible_sin_nombre_sofia():
    app = Path("app.py").read_text(encoding="utf-8")
    assert_true('"Sofia no pudo responder"' not in app, "El evento visible no debe decir Sofia")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for test in tests:
        test()
        ok += 1
        print("OK", test.__name__)
    print(f"VALIDACION_ETAPA3_FRONTEND_RESILIENCIA: {ok}/{len(tests)} OK")
