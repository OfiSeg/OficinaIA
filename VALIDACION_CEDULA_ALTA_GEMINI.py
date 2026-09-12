from __future__ import annotations

import sys
import types as pytypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Stubs mínimos para validar módulos puros aun sin google-genai instalado.
try:
    import google.genai  # type: ignore
except Exception:
    google_mod = sys.modules.get("google") or pytypes.ModuleType("google")
    genai_mod = pytypes.ModuleType("google.genai")
    types_mod = pytypes.ModuleType("google.genai.types")

    class _Dummy:
        def __init__(self, *args, **kwargs): self.args=args; self.kwargs=kwargs
        @classmethod
        def from_text(cls, *args, **kwargs): return cls(*args, **kwargs)
        @classmethod
        def from_bytes(cls, *args, **kwargs): return cls(*args, **kwargs)

    def _types_getattr(_name):
        return _Dummy

    types_mod.__getattr__ = _types_getattr  # type: ignore[attr-defined]
    types_mod.HttpOptions = _Dummy
    types_mod.GenerateContentConfig = _Dummy
    types_mod.ThinkingConfig = _Dummy
    types_mod.AutomaticFunctionCallingConfig = _Dummy
    types_mod.Part = _Dummy
    types_mod.Content = _Dummy
    types_mod.Tool = _Dummy
    genai_mod.types = types_mod
    genai_mod.Client = _Dummy
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod

import alta_ops
import ai_gateway
from resilience import clasificar_error_ia


def test_cedula_prefill_usa_mismo_contrato_alta():
    datos = {
        "titular": "BAO GABRIEL ROBERTO",
        "marca": "MERCEDES BENZ",
        "modelo": "C 200 KOMPRESSOR AVANTGARDE",
        "anio": "2009",
        "patente": "idf853",
        "estado_patente": "verificado",
        "motor": "27195031104628",
        "chasis": "WDDGF41X59F208438",
    }
    campos = alta_ops.campos_alta_desde_cedula(datos)
    assert campos["ASEGURADO"] == "BAO GABRIEL ROBERTO"
    assert campos["PATENTE"] == "IDF853"
    assert "MERCEDES BENZ" in campos["VEHICULO"]
    assert "2009" in campos["VEHICULO"]
    # La cédula no debe inventar datos que no contiene.
    for clave in ("POLIZA", "NUMERO", "CIA", "MEDIO DE PAGO", "CP", "EMITIDO DÍA:", "IMPORTE APROX"):
        assert campos[clave] == "", clave


def test_cedula_dudosa_llega_marcada():
    datos = {"patente": "IDF853", "estado_patente": "revisar"}
    rev = alta_ops.revisiones_alta_desde_cedula(datos)
    assert "PATENTE" in rev and "confirmar" in rev["PATENTE"].lower()
    datos["estado_patente"] = "confirmado_productor"
    assert "PATENTE" not in alta_ops.revisiones_alta_desde_cedula(datos)


def test_merge_misma_patente_confirma_sin_duplicar_alta():
    poliza = {"ASEGURADO":"BAO GABRIEL ROBERTO", "VEHICULO":"MERCEDES BENZ C 200", "PATENTE":"IDF853", "CIA":"ATM"}
    cedula = {"titular":"BAO GABRIEL ROBERTO", "marca":"MERCEDES BENZ", "modelo":"C 200", "patente":"IDF853", "estado_patente":"revisar"}
    campos, revisiones, avisos = alta_ops.fusionar_alta_con_cedula(poliza, cedula)
    assert campos["PATENTE"] == "IDF853"
    assert "PATENTE" not in revisiones
    assert not avisos
    assert campos["CIA"] == "ATM"


def test_merge_conflicto_no_elige_silenciosamente():
    poliza = {"ASEGURADO":"BAO GABRIEL ROBERTO", "VEHICULO":"MERCEDES BENZ C 200", "PATENTE":"IDF853"}
    cedula = {"titular":"BAO GABRIEL ROBERTO", "patente":"IDF858", "estado_patente":"verificado"}
    campos, revisiones, avisos = alta_ops.fusionar_alta_con_cedula(poliza, cedula)
    assert campos["PATENTE"] == ""
    assert "PATENTE" in revisiones
    assert avisos and "Conflicto" in avisos[0]


def test_frontend_reutiliza_formulario_existente():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "Preparar alta" in js
    assert "mostrarOpcionesAltaAsegurado(null,campos,{origen:'cedula',revisiones})" in js
    assert "Guardar en Excel" in js
    assert "alta-prefill-warning" in js
    assert "Lectura para confirmar" in js


def test_chat_mixto_tiene_un_solo_formulario_alta():
    src = (ROOT / "chat_special.py").read_text(encoding="utf-8")
    assert "_resultado_cedula_y_poliza" in src
    assert '"alta_origen": "cedula+poliza"' in src
    assert "fusionar_alta_con_cedula" in src
    assert 'handler="cedula"' in src  # cédula sola sigue siendo cédula hasta que el usuario pulsa Preparar alta


def test_gemini_chat_quedo_separado_del_documental():
    ia = (ROOT / "servicios_ia.py").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    gateway = (ROOT / "ai_gateway.py").read_text(encoding="utf-8")
    assert 'GEMINI_CHAT_THINKING_LEVEL", "low"' in ia
    assert 'GEMINI_CHAT_HTTP_TIMEOUT_MS", 10000' in ia
    assert 'GEMINI_CHAT_SMALLTALK_TIMEOUT_MS", 5500' in ia
    assert "SMALLTALK_MODELS" in ia
    assert '("gemini-3.5-flash-lite", "gemini-3.8-flash")' in ia
    assert "max_attempts=2" in ia
    assert 'GEMINI_CHAT_BUDGET_SECONDS", 35.0' in app
    assert 'GEMINI_DOCUMENT_BUDGET_SECONDS' in app
    assert "IA_METRIC operation=" in gateway
    assert "input_chars=" in gateway and "media_bytes=" in gateway



def test_gateway_permite_smalltalk_con_dos_intentos_controlados():
    class FakeError(RuntimeError):
        status_code = 503
    class Models:
        def __init__(self): self.calls = 0
        def generate_content(self, **_kwargs):
            self.calls += 1
            raise FakeError("503 unavailable")
    class Client:
        def __init__(self): self.models = Models()
    ai_gateway.begin_request(30, request_id="test-smalltalk")
    cliente = Client()
    try:
        ai_gateway.generate_with_fallback(
            contents="hola", config={}, client=cliente, models=("m1","m2"),
            log_prefix="TEST SMALLTALK", max_attempts=2,
        )
    except FakeError:
        pass
    else:
        raise AssertionError("debió propagar el fallo tras dos intentos")
    assert cliente.models.calls == 2

def test_clasificacion_errores_gemini():
    class E(RuntimeError):
        def __init__(self, msg, status_code=None):
            super().__init__(msg); self.status_code=status_code
    assert clasificar_error_ia(TimeoutError("x")) == "TIMEOUT"
    assert clasificar_error_ia(E("rate limit", 429)) == "RATE_LIMIT"
    assert clasificar_error_ia(E("unavailable", 503)) == "SERVICE_UNAVAILABLE"
    assert clasificar_error_ia(E("invalid api key", 401)) == "AUTH_ERROR"


def main():
    tests=[v for k,v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t(); print("OK", t.__name__)
    print(f"OK TOTAL: {len(tests)} grupos")


if __name__ == "__main__":
    main()
