"""Regresiones de ETAPA 1: cédulas ambiguas + decisión final del productor.

No llama servicios externos. Valida la lógica determinística y el contrato UI.
"""
from io import BytesIO
from pathlib import Path

from PIL import Image

# Validación offline: stub mínimo del SDK de Google si no está instalado.
try:
    import google.genai  # type: ignore
except ModuleNotFoundError:
    import sys
    import types as _pytypes
    google_mod = sys.modules.get("google") or _pytypes.ModuleType("google")
    genai_mod = _pytypes.ModuleType("google.genai")
    types_mod = _pytypes.ModuleType("google.genai.types")
    class _Part:
        @staticmethod
        def from_bytes(*, data=None, mime_type=None):
            return {"data": data, "mime_type": mime_type}
    class _Config:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs
    types_mod.Part = _Part
    types_mod.HttpOptions = _Config
    types_mod.GenerateContentConfig = _Config
    genai_mod.types = types_mod
    genai_mod.Client = _Config
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod

import cedula_ops
from attachment_vision import MediaBlob


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def ev(valor, *, legible=True, dudas=None, calidad="buena"):
    return {
        "valor": valor,
        "legible": legible,
        "dudas": list(dudas or []),
        "calidad": calidad,
    }


def test_3_de_3_buena_calidad_verifica():
    valor = "10FDB31987010"
    r = cedula_ops._resolver_campo(
        ev(valor), ev(valor), ev(valor), [],
        calidad_documento="buena", problemas_imagen=[]
    )
    check(r[0] == valor, "Cambió el valor consensuado")
    check(r[1] == "verificado", "3/3 nítido debe poder verificarse")


def test_3_de_3_mala_calidad_no_es_certeza():
    valor = "10FDB31987010"
    r = cedula_ops._resolver_campo(
        ev(valor), ev(valor), ev(valor), [],
        calidad_documento="mala", problemas_imagen=["imagen borrosa"]
    )
    check(r[1] == "revisar", "3/3 borroso no debe quedar verificado")
    check(any("calidad visual" in x.lower() for x in r[2]), "Debe explicar por qué requiere revisión")


def test_discrepancia_muestra_posicion_y_variantes_reales():
    a = "10FDB31987010"
    b = "10FDB31907010"
    r = cedula_ops._resolver_campo(ev(a), ev(b), ev(a), [])
    check(r[1] == "revisar", "Lecturas distintas deben requerir revisión")
    check(any("Posición 9: 8 / 0" in x or "Posición 9: 0 / 8" in x for x in r[2]), f"No detectó posición exacta: {r[2]}")
    check(set(r[3]) == {a, b}, f"Las opciones deben ser sólo lecturas completas observadas: {r[3]}")


def test_parcial_no_genera_candidato_ficticio():
    a = "10FDB31987010"
    parcial = "10FDB319?7010"
    r = cedula_ops._resolver_campo(ev(a), ev(parcial, legible=False, dudas=["carácter dudoso"]), ev(a), [])
    check(a in r[3], "Debe conservar la lectura completa real")
    check(parcial not in r[3], "No debe ofrecer una lectura con ? como candidato completo")


def test_rotacion_adaptativa_no_toca_original():
    img = Image.new("RGB", (120, 60), "white")
    out = BytesIO(); img.save(out, format="JPEG")
    blob = MediaBlob("image/jpeg", out.getvalue(), 1)
    media = [blob]
    primera = {"orientaciones": [{"pagina": 1, "rotacion_para_leer": 90}]}
    rotada, cambio = cedula_ops._aplicar_rotaciones_detectadas(media, primera)
    check(cambio is True, "Debe aplicar la rotación detectada")
    check(rotada[0] is not blob, "La normalización debe trabajar sobre copia temporal")
    with Image.open(BytesIO(rotada[0].data)) as got:
        check(got.width < got.height, "Un giro 90° debe intercambiar orientación")
    with Image.open(BytesIO(blob.data)) as original:
        check(original.width > original.height, "No debe modificar el original")


def test_ui_decision_productor_y_header():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    html = Path("templates/documentos.html").read_text(encoding="utf-8")
    check("Copiar igualmente" not in js, "No debe quedar la acción genérica Copiar igualmente")
    for texto in ("Seleccionar lectura", "Confirmar dato", "Ingresar manualmente", "Confirmado por productor"):
        check(texto in js, f"Falta UI de decisión humana: {texto}")
    check("estadoCriticoConfiable" in js, "Falta bloquear acciones hasta confirmación")
    check("<b>Sofia</b>" not in html, "Sofia sigue visible en el encabezado central del chat")
    check("sofia-logo-shell" in html and "favicon.png" in html, "Debe conservarse el ícono de carpeta")


def test_prompt_calidad_y_orientacion():
    prompt = cedula_ops.CEDULA_SYSTEM_INSTRUCTION
    check("patente_calidad" in prompt and "motor_calidad" in prompt and "chasis_calidad" in prompt, "Falta calidad por dato crítico")
    check("rotacion_para_leer" in prompt, "Falta detección de orientación")
    check("No completes por formato esperado" in prompt, "No debe inferir caracteres")


def main():
    tests = [
        test_3_de_3_buena_calidad_verifica,
        test_3_de_3_mala_calidad_no_es_certeza,
        test_discrepancia_muestra_posicion_y_variantes_reales,
        test_parcial_no_genera_candidato_ficticio,
        test_rotacion_adaptativa_no_toca_original,
        test_ui_decision_productor_y_header,
        test_prompt_calidad_y_orientacion,
    ]
    for t in tests:
        t(); print("OK", t.__name__)
    print("OK TOTAL:", len(tests), "grupos")


if __name__ == "__main__":
    main()
