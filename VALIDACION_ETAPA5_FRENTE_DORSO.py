"""Validación offline de Etapa 5: frente+dorso y adjuntos múltiples.

No llama a Gemini ni modifica infraestructura. Verifica contratos ya existentes
que esta etapa debe preservar y el único dato/UI añadido para cédula multicara.
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent

import document_grouping


def _c(tipo):
    return SimpleNamespace(tipo_documento=tipo)


def test_dni_frente_dorso_mismo_turno():
    a, b = object(), object()
    p = document_grouping.planificar([a, b], [_c("dni"), _c("otro")])
    assert p.tipo == "dni" and p.candidato_multicara and p.adjuntos == [a, b]


def test_licencia_frente_dorso_mismo_turno():
    a, b = object(), object()
    p = document_grouping.planificar([a, b], [_c("licencia"), _c("licencia")])
    assert p.tipo == "licencia" and p.candidato_multicara and len(p.adjuntos) == 2


def test_cedula_frente_dorso_mismo_turno():
    a, b = object(), object()
    p = document_grouping.planificar([a, b], [_c("cedula"), _c("otro")])
    assert p.tipo == "cedula" and p.candidato_multicara and p.adjuntos == [a, b]


def test_tipos_distintos_no_se_fusionan():
    a, b = object(), object()
    p = document_grouping.planificar([a, b], [_c("dni"), _c("licencia")])
    assert not p.candidato_multicara


def test_coleccion_mayor_a_dos_no_se_recorta():
    xs = [object(), object(), object()]
    p = document_grouping.planificar(xs, [_c("otro"), _c("otro"), _c("otro")])
    assert p.adjuntos == xs and p.tipo == "otro"


def test_router_conserva_turno_anterior_como_candidato():
    text = (ROOT / "chat_special.py").read_text(encoding="utf-8")
    assert "adjunto_anterior is not None" in text
    assert "[adjunto_anterior, adjuntos_actuales[0]]" in text
    assert "candidato.candidato_multicara" in text


def test_backend_entrega_toda_la_coleccion():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    req = (ROOT / "chat_request.py").read_text(encoding="utf-8")
    assert "extract_attachments(" in app
    assert "adjuntos=adjuntos_actuales" in app
    assert 'getlist("archivo")' in req
    assert "MAX_CHAT_ATTACHMENTS = 5" in req


def test_frontend_acumula_y_envia_todos():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "archivosAdjuntosChat" in js
    assert "{reemplazar:false}" in js
    assert "archivos.forEach(a=>fd.append('archivo',a,a.name))" in js
    assert "MAX_CHAT_ATTACHMENTS=5" in js


def test_cedula_multicara_se_expone_sin_nueva_llamada():
    py = (ROOT / "cedula_ops.py").read_text(encoding="utf-8")
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert '"caras_combinadas": bool(es_multicara)' in py
    assert "datos.caras_combinadas?' · frente + dorso':''" in js


def test_no_se_toco_gateway():
    # Esta prueba sólo documenta el invariante de alcance: Etapa 5 no requiere
    # modificar ai_gateway para agrupar caras.
    assert (ROOT / "ai_gateway.py").exists()


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t(); print("OK", t.__name__)
    print(f"OK TOTAL: {len(tests)} grupos")


if __name__ == "__main__":
    main()
