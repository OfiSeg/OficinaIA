from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import types

# Validación ejecutable incluso en el sandbox de auditoría, que no instala las
# dependencias web completas del proyecto.
try:
    import werkzeug.utils  # type: ignore
except Exception:
    werkzeug_mod = types.ModuleType("werkzeug")
    utils_mod = types.ModuleType("werkzeug.utils")
    utils_mod.secure_filename = lambda x: Path(str(x or "")).name.replace(" ", "_")
    werkzeug_mod.utils = utils_mod
    sys.modules["werkzeug"] = werkzeug_mod
    sys.modules["werkzeug.utils"] = utils_mod

try:
    import chat_pdf  # type: ignore
except Exception:
    chat_pdf_mod = types.ModuleType("chat_pdf")
    class ChatPdfError(Exception):
        def __init__(self, message="error", status_code=422):
            super().__init__(message); self.status_code=status_code
    chat_pdf_mod.ChatPdfError = ChatPdfError
    chat_pdf_mod.extraer_contexto_pdf = lambda *a, **k: ("", 1, 0)
    sys.modules["chat_pdf"] = chat_pdf_mod

import chat_request
import document_grouping
import chat_ai


class C:
    def __init__(self, tipo):
        self.tipo_documento = tipo


class FakeFile:
    def __init__(self, nombre: str, contenido: bytes = b"hola"):
        self.filename = nombre
        self.stream = BytesIO(contenido)
        self.content_type = "text/plain"


class FakeFiles:
    def __init__(self, mapping): self.mapping = mapping
    def getlist(self, key): return list(self.mapping.get(key, []))


class FakeForm(dict):
    pass


class FakeRequest:
    is_json = False
    def __init__(self, archivos):
        self.form = FakeForm(mensaje="analiza", historial="[]", chat_id="1")
        self.files = FakeFiles({"archivo": archivos})


def _fs(nombre: str, contenido: bytes = b"hola"):
    return FakeFile(nombre, contenido)


def test_parse_incoming_recibe_tres_archivos_en_orden():
    req = FakeRequest([_fs("a.txt", b"A"), _fs("b.txt", b"B"), _fs("c.txt", b"C")])
    entrada = chat_request.parse_incoming(req)
    assert [x.filename for x in entrada.archivos] == ["a.txt", "b.txt", "c.txt"]


def test_extract_attachments_conserva_tres_y_orden():
    archivos = [_fs("a.txt", b"A"), _fs("b.txt", b"B"), _fs("c.txt", b"C")]
    out = chat_request.extract_attachments(
        archivos, max_pdf_bytes=20 * 1024 * 1024, max_pages=5, max_chars=10000,
    )
    assert [x.nombre for x in out] == ["a.txt", "b.txt", "c.txt"]
    assert [x.texto_plano for x in out] == ["A", "B", "C"]


def test_extract_attachments_limita_cantidad():
    archivos = [_fs(f"{i}.txt", b"x") for i in range(chat_request.MAX_CHAT_ATTACHMENTS + 1)]
    try:
        chat_request.extract_attachments(
            archivos, max_pdf_bytes=20 * 1024 * 1024, max_pages=5, max_chars=10000,
        )
    except chat_request.ChatRequestError as exc:
        assert "hasta 5" in str(exc)
    else:
        raise AssertionError("debió rechazar más de 5 archivos")


def test_extract_attachments_limita_total():
    archivos = [_fs("a.txt", b"12345"), _fs("b.txt", b"67890")]
    try:
        chat_request.extract_attachments(
            archivos, max_pdf_bytes=20 * 1024 * 1024, max_pages=5, max_chars=10000,
            max_total_bytes=9,
        )
    except chat_request.ChatRequestError as exc:
        assert exc.status_code == 413
    else:
        raise AssertionError("debió rechazar total excedido")


def test_grouping_frente_dorso_dni_sigue_funcionando():
    items = [object(), object()]
    plan = document_grouping.planificar(items, [C("dni"), C("otro")])
    assert plan.tipo == "dni" and plan.candidato_multicara
    assert plan.adjuntos == items


def test_grouping_tipos_distintos_no_se_fusionan_y_router_preserva_coleccion():
    items = [object(), object()]
    plan = document_grouping.planificar(items, [C("dni"), C("poliza")])
    assert not plan.candidato_multicara and len(plan.adjuntos) == 1
    # Compatibilidad histórica del planner; el router detecta este recorte y
    # evita activar un handler que descartaría el otro adjunto.
    text = Path(__file__).with_name("chat_special.py").read_text(encoding="utf-8")
    assert "len(plan.adjuntos) < len(adjuntos_actuales)" in text
    assert "plan = None" in text


def test_grouping_tres_no_descarta_archivos():
    items = [object(), object(), object()]
    plan = document_grouping.planificar(items, [C("otro"), C("otro"), C("otro")])
    assert plan.tipo == "otro" and plan.adjuntos == items


def test_chat_ai_reenvia_coleccion_a_servicios():
    capturado = {}
    fake = types.ModuleType("servicios_ia")
    def consultar_gemini(mensaje, contexto, historial=None, adjunto=None, adjuntos=None):
        capturado.update(mensaje=mensaje, contexto=contexto, adjunto=adjunto, adjuntos=adjuntos)
        return "ok"
    fake.consultar_gemini = consultar_gemini
    previo = sys.modules.get("servicios_ia")
    sys.modules["servicios_ia"] = fake
    try:
        a = object(); b = object()
        r = chat_ai.responder("x", "", [], adjunto=a, adjuntos=[a,b])
        assert r.respuesta == "ok" and capturado["adjuntos"] == [a,b] and capturado["adjunto"] is a
    finally:
        if previo is None: sys.modules.pop("servicios_ia", None)
        else: sys.modules["servicios_ia"] = previo


def test_frontend_acumula_elimina_y_no_limpia_antes_de_respuesta():
    text = Path(__file__).with_name("static").joinpath("js", "app.js").read_text(encoding="utf-8")
    assert "validarYAdjuntarArchivos(files,pdf,{reemplazar:false})" in text
    assert "validarYAdjuntarArchivos(archivos,pdf,{reemplazar:false})" in text
    assert "archivosAdjuntosChat.splice(indice,1)" in text
    assert "fd.append('archivo',a,a.name)" in text
    assert "MAX_CHAT_ATTACHMENTS=5" in text
    inicio = text.index("async function enviarMensaje()")
    fin = text.index("async function initChat()", inicio)
    bloque = text[inicio:fin]
    assert bloque.index("if(!r.ok||d.ok===false)") < bloque.index("if(archivos.length)quitarAdjuntosEnviados(archivos,attachmentSeqAlEnviar)")
    assert "quitarAdjunto();" not in bloque


def test_backend_pasa_coleccion_a_sofia():
    text = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    assert "adjuntos=adjuntos_actuales" in text
    assert "max_files=MAX_CHAT_ATTACHMENTS" in text
    assert "max_total_bytes=MAX_CHAT_ATTACHMENTS_TOTAL_BYTES" in text


def test_servicios_ia_construye_payload_multimedia_colectivo():
    text = Path(__file__).with_name("servicios_ia.py").read_text(encoding="utf-8")
    assert 'def consultar_gemini(pregunta, contexto="", historial=None, adjunto=None, adjuntos=None):' in text
    assert "for item in adjuntos_actuales:" in text
    assert "media_parts.append(types.Part.from_bytes" in text


def test_retries_conservan_contents_completo():
    text = Path(__file__).with_name("ai_gateway.py").read_text(encoding="utf-8")
    assert "contents=contents" in text and "AI_READ_ATTEMPTS = 3" in text


def main():
    tests=[v for k,v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t(); print("OK", t.__name__)
    print(f"OK TOTAL: {len(tests)} grupos")


if __name__ == "__main__": main()
