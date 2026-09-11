"""Validaciones determinísticas de DNI/licencia/frente+dorso.

No consume Gemini real. Mockea las respuestas estructuradas del extractor y
valida contratos, agrupamiento y la UI estática.
"""
from pathlib import Path
from types import SimpleNamespace

# Validación offline: el ZIP declara google-genai en requirements.txt, pero el
# entorno de prueba puede no tener el SDK. Stub mínimo para importar módulos.
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

import document_classifier
import document_grouping
import personal_document_ops as pdo
import cedula_ops

ROOT = Path(__file__).resolve().parent


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def cls(tipo, confianza="alta"):
    return document_classifier.ClasificacionAdjunto(tipo, confianza, [], "test")


def test_clasificador_textual():
    d = document_classifier.clasificar_por_texto(
        "REPÚBLICA ARGENTINA DOCUMENTO NACIONAL DE IDENTIDAD RENAPER DNI 40123456 FECHA DE NACIMIENTO"
    )
    check(d and d.tipo_documento == "dni", "No clasificó DNI por texto")
    l = document_classifier.clasificar_por_texto(
        "REPÚBLICA ARGENTINA LICENCIA NACIONAL DE CONDUCIR DNI 40123456 CLASE B1 VENCIMIENTO"
    )
    check(l and l.tipo_documento == "licencia", "No clasificó licencia por texto")
    p = document_classifier.clasificar_por_texto(
        "POLIZA 6509977 ASEGURADO JUAN PEREZ VIGENCIA COBERTURA PREMIO"
    )
    check(p and p.tipo_documento == "poliza", "Rompió clasificación de póliza")


def test_grouping():
    a, b = object(), object()
    plan = document_grouping.planificar([a, b], [cls("dni"), cls("otro", "baja")])
    check(plan.tipo == "dni" and plan.candidato_multicara and len(plan.adjuntos) == 2,
          "No agrupó DNI + dorso ambiguo")
    plan2 = document_grouping.planificar([a, b], [cls("dni"), cls("licencia")])
    check(not plan2.candidato_multicara and len(plan2.adjuntos) == 1,
          "Fusionó DNI y licencia")


def test_normalizadores():
    check(pdo._safe_digits("40.123.456") == "40123456", "DNI normalizado incorrecto")
    check(pdo.mostrar_dni("40123456") == "40.123.456", "DNI visible incorrecto")
    check(pdo.normalizar_fecha("12/03/2001") == "2001-03-12", "Fecha normalizada incorrecta")
    check(pdo.mostrar_fecha("2001-03-12") == "12/03/2001", "Fecha visible incorrecta")
    check(pdo.mostrar_cuil("20401234560") == "20-40123456-0", "CUIL visible incorrecto")
    check(pdo._cuil_checksum_valido("20401234560"), "CUIL válido rechazado")


def ev(valor, legible=True, dudas=None):
    return {"valor": valor, "legible": legible, "dudas": list(dudas or [])}


def test_confianza_criticos():
    v, estado, n, dudas = pdo._resolver_critico([ev("40123456"), ev("40123456"), ev("40123456")], campo="dni")
    check((v, estado, n, dudas) == ("40123456", "alta", 3, []), "3/3 DNI no quedó alta")
    v, estado, n, _ = pdo._resolver_critico([ev("40123456"), ev("40123456"), ev("40123458")], campo="dni")
    check(v == "40123456" and estado == "media" and n == 2, "2/3 DNI no quedó media")
    v, estado, n, _ = pdo._resolver_critico([ev("", False), ev("", False), ev("", False)], campo="cuil")
    check(v == "" and estado == "no_disponible" and n == 0, "CUIL ausente debería ser no disponible")
    _, estado, _, dudas = pdo._resolver_critico([ev("31/02/2001")]*3, campo="fecha_nacimiento")
    check(estado != "alta" and dudas, "Fecha imposible quedó alta")


def _general_dni(*, caras=2, fecha2="2001-03-12", dni2="40123456", cuil="20401234560"):
    lista = [
        {"cara":"frente", "nombre":"JUAN", "apellido":"PEREZ", "dni":"40123456", "fecha_nacimiento":"2001-03-12", "cuil":"", "domicilio":"", "localidad":""},
    ]
    if caras > 1:
        lista.append({"cara":"dorso", "nombre":"JUAN", "apellido":"PEREZ", "dni":dni2, "fecha_nacimiento":fecha2, "cuil":cuil, "domicilio":"AV ESPORA 1234", "localidad":"BURZACO"})
    return {
        "tipo_documento":"dni", "mismo_titular":True, "compatibilidad":"alta",
        "nombre":"JUAN", "apellido":"PEREZ", "dni":"40123456", "fecha_nacimiento":"2001-03-12",
        "cuil":cuil, "domicilio":"AV ESPORA 1234" if caras>1 else "", "localidad":"BURZACO" if caras>1 else "",
        "caras":lista, "dni_legible":True, "fecha_nacimiento_legible":True,
        "cuil_legible":bool(cuil), "dni_dudas":[], "fecha_nacimiento_dudas":[], "cuil_dudas":[], "advertencias":[]
    }


def _verify(dni="40123456", fecha="2001-03-12", cuil="20401234560"):
    return {
        "dni":{"valor":dni,"legible":bool(dni),"dudas":[]},
        "fecha_nacimiento":{"valor":fecha,"legible":bool(fecha),"dudas":[]},
        "cuil":{"valor":cuil,"legible":bool(cuil),"dudas":[]},
    }


def _run_personal_with(responses, items, tipo="dni"):
    orig_parts = pdo._media_parts
    orig_call = pdo._call_json
    seq = iter(responses)
    try:
        pdo._media_parts = lambda _items: ["media-simulada"]
        pdo._call_json = lambda *args, **kwargs: next(seq)
        return pdo.procesar_documento_personal(items, tipo_hint=tipo)
    finally:
        pdo._media_parts = orig_parts
        pdo._call_json = orig_call


def test_dni_frente_dorso_mismo_turno():
    general = _general_dni()
    r = _run_personal_with([general, _verify(), _verify()], [object(), object()])
    d = r.datos
    check(d["caras_combinadas"] is True, "No marcó frente+dorso")
    check(d["dni"] == "40123456" and d["estado_dni"] == "alta", "DNI combinado incorrecto")
    check(d["cuil"] == "20401234560" and d["estado_cuil"] == "alta", "No incorporó CUIL del dorso")
    check(d["domicilio"] == "AV ESPORA 1234" and d["localidad"] == "BURZACO", "No combinó domicilio/localidad")


def test_dni_frente_solo_no_inventa_cuil():
    general = _general_dni(caras=1, cuil="")
    general["cuil"] = ""
    r = _run_personal_with([general, _verify(cuil=""), _verify(cuil="")], [object()])
    check(r.datos["cuil"] == "" and r.datos["estado_cuil"] == "no_disponible",
          "Calculó/inventó CUIL ausente")


def test_pdf_multicara_se_combina():
    # Un único Adjunto puede renderizar dos páginas. Si Gemini reporta dos caras,
    # el resultado debe considerarse combinado igual que dos archivos.
    general = _general_dni()
    r = _run_personal_with([general, _verify(), _verify()], [object()])
    check(r.datos["caras_combinadas"] is True, "PDF multipágina no quedó como frente+dorso")


def test_personas_distintas_no_combinan():
    general = _general_dni(dni2="30111222")
    try:
        _run_personal_with([general, _verify(), _verify()], [object(), object()])
    except pdo.DocumentosIncompatiblesError:
        return
    raise AssertionError("Fusionó dos DNI distintos")


def test_contradiccion_fecha_no_se_elije():
    general = _general_dni(fecha2="1999-01-02")
    # DNI coincide: sabemos que probablemente es el mismo titular, pero la fecha
    # contradicha no puede resolverse silenciosamente.
    r = _run_personal_with([general, _verify(), _verify()], [object(), object()])
    check(r.datos["fecha_nacimiento"] == "" and r.datos["estado_fecha_nacimiento"] == "revisar",
          "Eligió arbitrariamente una fecha contradictoria")


def test_licencia_sin_cuil():
    general = _general_dni(caras=1, cuil="")
    general.update({"tipo_documento":"licencia", "cuil":""})
    r = _run_personal_with([general, _verify(cuil=""), _verify(cuil="")], [object()], tipo="licencia")
    check(r.datos["tipo_documento"] == "licencia" and not r.datos["cuil"], "Inventó CUIL en licencia")


def test_patente_ambigua_no_se_mutila():
    e = cedula_ops._evidencia_general({"patente":"AB?23CD", "patente_legible":False, "patente_dudas":["B/8"]}, "patente")
    check(e["valor"] == "AB?23CD" and not e["legible"], "La normalización ocultó '?' de patente")


def test_ui_y_multiarchivo():
    js = (ROOT/"static/js/app.js").read_text(encoding="utf-8")
    html = (ROOT/"templates/documentos.html").read_text(encoding="utf-8")
    app = (ROOT/"app.py").read_text(encoding="utf-8")
    check('type="file" multiple' in html, "Input no admite frente+dorso")
    check("crearCampo('patente','PATENTE')" in js and "Copiar '+etiqueta.toLowerCase()" in js, "Falta botón Copiar patente")
    check("mostrarDocumentoPersonalDetectado" in js, "Falta tarjeta DNI/licencia")
    check("Copiar datos principales" in js, "Falta copiar datos principales")
    check("Alta confianza — 3/3 lecturas coincidentes" in js, "Falta etiqueta 3/3")
    check("✓ Verificado" not in js, "La UI sigue diciendo Verificado")
    check("extract_attachments" in app and "adjuntos=adjuntos_actuales" in app, "Backend no recibe dos adjuntos")


def test_poliza_no_se_redefine():
    grouping = (ROOT/"document_grouping.py").read_text(encoding="utf-8")
    special = (ROOT/"chat_special.py").read_text(encoding="utf-8")
    check('if unico == "poliza"' in grouping, "Agrupamiento no preserva póliza individual")
    check("alta_ops.procesar(" in special and "alta_automatica" in special, "Se perdió flujo de alta/póliza")


def main():
    tests = [
        test_clasificador_textual,
        test_grouping,
        test_normalizadores,
        test_confianza_criticos,
        test_dni_frente_dorso_mismo_turno,
        test_dni_frente_solo_no_inventa_cuil,
        test_pdf_multicara_se_combina,
        test_personas_distintas_no_combinan,
        test_contradiccion_fecha_no_se_elije,
        test_licencia_sin_cuil,
        test_patente_ambigua_no_se_mutila,
        test_ui_y_multiarchivo,
        test_poliza_no_se_redefine,
    ]
    for t in tests:
        t()
        print("OK", t.__name__)
    print(f"OK TOTAL: {len(tests)} grupos")


if __name__ == "__main__":
    main()
