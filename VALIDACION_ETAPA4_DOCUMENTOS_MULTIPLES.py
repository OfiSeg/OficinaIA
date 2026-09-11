"""Regresiones ETAPA 4: documentos múltiples, no truncamiento silencioso y campos extra.

Validador offline. No llama Gemini ni servicios externos.
"""
from pathlib import Path
from io import BytesIO
import sys
import types

try:
    import google.genai  # type: ignore
except ModuleNotFoundError:
    google_mod = sys.modules.get("google") or types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    class _Part:
        @staticmethod
        def from_bytes(*, data=None, mime_type=None):
            return {"data": data, "mime_type": mime_type}
        @staticmethod
        def from_text(*, text=None):
            return {"text": text}
    class _Config:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs
    types_mod.Part = _Part
    types_mod.HttpOptions = _Config
    types_mod.GenerateContentConfig = _Config
    types_mod.AutomaticFunctionCallingConfig = _Config
    genai_mod.types = types_mod
    genai_mod.Client = _Config
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod

from PIL import Image
import document_grouping
import attachment_vision

class C:
    def __init__(self, tipo):
        self.tipo_documento = tipo

class A:
    def __init__(self, tipo="imagen", data=b"x", mime="image/jpeg"):
        self.tipo = tipo
        self.datos_binarios = data
        self.mime_type = mime
        self.contexto = ""
        self.nombre = "a.jpg"

def check(cond, msg):
    if not cond:
        raise AssertionError(msg)

def jpg():
    img = Image.new("RGB", (40, 30), "white")
    out = BytesIO(); img.save(out, format="JPEG")
    return out.getvalue()

def test_attachment_vision_reporte_truncamiento():
    items = [A(data=jpg()) for _ in range(5)]
    reporte = attachment_vision.renderizar_varios_para_vision_con_reporte(items, max_paginas_total=3)
    check(len(reporte.blobs) == 3, "Debe respetar límite visual")
    check(reporte.truncado is True, "Debe informar truncamiento")
    check(reporte.advertencias, "Debe dejar advertencia de truncamiento")

def test_funcion_historica_sigue_devolviendo_lista():
    out = attachment_vision.renderizar_varios_para_vision([A(data=jpg())], max_paginas_total=1)
    check(isinstance(out, list) and len(out) == 1, "Compatibilidad rota en renderizar_varios_para_vision")

def test_planificar_coleccion_no_fusiona_todo():
    items = [object(), object(), object(), object()]
    plan = document_grouping.planificar_coleccion(items, [C("cedula"), C("cedula"), C("licencia"), C("otro")])
    check(plan.cantidad_documentos == 2, f"Plan inesperado: {plan}")
    check(plan.documentos[0].indices == [0, 1] and plan.documentos[0].candidato_multicara, "Debe proponer sólo par compatible")
    check(plan.documentos[1].indices == [2, 3] and plan.documentos[1].candidato_multicara, "Licencia + otro puede ser frente/dorso candidato")

def test_resumen_coleccion_para_prompt_exige_estados_y_no_truncar():
    txt = document_grouping.resumen_coleccion_para_prompt([object(), object()], [C("cedula"), C("otro")], advertencias=["contenido omitido"])
    for frag in ("Verificado", "Revisar", "Lectura parcial", "No digas que revisaste todos", "ADVERTENCIA TÉCNICA"):
        check(frag in txt, f"Falta instrucción: {frag}")

def test_servicios_ia_incluye_advertencia_multimodal():
    text = Path("servicios_ia.py").read_text(encoding="utf-8")
    check("ADVERTENCIA TÉCNICA MULTIMODAL" in text, "Falta advertencia multimodal")
    check("MULTIMODAL_TRUNCATED" in text, "Falta evento de truncamiento")
    check("resumen_coleccion_para_prompt" in text, "Falta resumen conservador de documentos múltiples")

def test_extractores_ampliados_cedula_y_licencia():
    cedula = Path("cedula_ops.py").read_text(encoding="utf-8")
    personal = Path("personal_document_ops.py").read_text(encoding="utf-8")
    for frag in ('"uso"', '"vencimiento"', '"control"', '"numero_cedula"'):
        check(frag in cedula, f"Cédula no contempla {frag}")
    for frag in ('"otorgamiento"', '"vencimiento"', '"clases"', '"observaciones"'):
        check(frag in personal, f"Licencia no contempla {frag}")

def test_frontend_muestra_campos_extra():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    for frag in ("Control / N° cédula", "OTORGAMIENTO", "VENCIMIENTO", "CLASES", "OBSERVACIONES"):
        check(frag in js, f"Frontend no muestra {frag}")

def main():
    tests=[v for k,v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t(); print("OK", t.__name__)
    print(f"OK TOTAL: {len(tests)} grupos")

if __name__ == "__main__":
    main()
