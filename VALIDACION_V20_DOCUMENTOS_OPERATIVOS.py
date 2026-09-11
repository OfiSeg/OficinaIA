"""Validación offline del flujo documental operativo V20.

No llama Gemini ni servicios externos. Comprueba contratos determinísticos y
regresiones que deben mantenerse aunque la API real no esté disponible.
"""
from __future__ import annotations

import io
import tempfile

import fitz
from PIL import Image


# La validación es offline. Si el SDK de Google no está instalado en el entorno
# de CI, proveemos un stub mínimo sólo para poder importar los módulos y probar
# su lógica determinística. En producción requirements.txt instala google-genai.
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

import alta_ops
import cedula_ops
import chat_pdf
import document_classifier
import attachment_vision
from envios_ya_utils import normalizar_patente, normalizar_telefono_argentina, preparar_envios_ya


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_telefonos():
    casos = {
        "+54 9 11 4149-2756": "1141492756",
        "54 9 11 4149 2756": "1141492756",
        "011 4149-2756": "1141492756",
        "11 15 4149 2756": "1141492756",
        "011 15 4149 2756": "1141492756",
        "1141492756": "1141492756",
        # Secuencia 15 interna en un número ya válido: debe quedar intacta.
        "1134156789": "1134156789",
    }
    for entrada, esperado in casos.items():
        valor, error = normalizar_telefono_argentina(entrada)
        check(not error, f"{entrada}: error inesperado {error}")
        check(valor == esperado, f"{entrada}: {valor} != {esperado}")
    valor, error = normalizar_telefono_argentina("12345")
    check(valor == "" and error, "Teléfono inválido no debe truncarse ni rellenarse")
    valor, error = normalizar_telefono_argentina("1111111111")
    check(valor == "" and "sospechoso" in error.lower(), "Debe conservar control histórico de teléfonos basura")


def test_patente_envios():
    check(normalizar_patente("ab-123-cd") == "AB123CD", "Patente con guiones")
    check(normalizar_patente("AB 123 CD") == "AB123CD", "Patente con espacios")
    r = preparar_envios_ya({
        "ASEGURADO": "JUAN PEREZ",
        "POLIZA": "6509977",
        "NUMERO": "+54 9 11 4149-2756",
        "PATENTE": "ab-123-cd",
        "VEHICULO": "HONDA WAVE 110",
        "CIA": "ATM",
    })
    esperado = "JUAN PEREZ\t6509977\t1141492756\tAB123CD\tHONDA WAVE 110\tATM"
    check(r.texto == esperado, f"Fila Envíos Ya incorrecta: {r.texto!r}")
    check(r.texto.count("\t") == 5, "Envíos Ya debe usar 5 TAB reales")
    for etiqueta in ("Nombre:", "Teléfono:", "Patente:", "Compañía:"):
        check(etiqueta not in r.texto, f"No debe contener etiqueta {etiqueta}")
    check(r.telefono_valido, "El teléfono válido quedó marcado como inválido")


def test_clasificacion_textual():
    cedula = """
    REPUBLICA ARGENTINA DNRPA CEDULA DE IDENTIFICACION DEL AUTOMOTOR
    DOMINIO AB123CD TITULAR JUAN PEREZ MARCA VOLKSWAGEN MODELO GOL
    NRO MOTOR CFZ123456 NRO CHASIS 9BWZZZ377JT123456
    """
    c = document_classifier.clasificar_por_texto(cedula)
    check(c and c.tipo_documento == "cedula" and c.confianza == "alta", "No detectó cédula digital por texto")

    poliza = """
    POLIZA NRO 6509977 ASEGURADO JUAN PEREZ VIGENCIA 10/09/2026
    COBERTURA RESPONSABILIDAD CIVIL PREMIO 71073 PRIMA 50000 SUMA ASEGURADA
    """
    p = document_classifier.clasificar_por_texto(poliza)
    check(p and p.tipo_documento == "poliza" and p.confianza == "alta", "No detectó póliza por texto")


def ev(valor, legible=True, dudas=None, fuente="test"):
    return {"valor": valor, "legible": legible, "dudas": list(dudas or []), "fuente": fuente}


def test_consenso_cedula():
    valor = "8CHPC1230SP123456"
    r = cedula_ops._resolver_campo(ev(valor), ev(valor), ev(valor), [])
    check(r[0] == valor and r[1] == "verificado", "Tres lecturas idénticas deben verificar")

    r = cedula_ops._resolver_campo(ev(valor), ev(valor), ev("" , False), ["verificación incompleta"])
    check(r[0] == valor and r[1] == "revisar", "Dos de tres no deben quedar verificadas")

    otro = "BCHPC1230SP123456"
    r = cedula_ops._resolver_campo(ev(valor), ev(otro), ev(valor), [])
    check(r[1] == "revisar", "Una discrepancia debe marcar revisar")
    check("?" in r[0] or any("Posición 1" in x for x in r[2]), "Debe exponer la posición discrepante")

    r = cedula_ops._resolver_campo(ev("", False), ev("", False), ev("", False), [])
    check(r[0] == "" and r[1] == "no_legible", "Sin evidencia debe ser no_legible")


def test_texto_pdf_refuerza_identificadores():
    class A:
        tipo = "pdf"
        contexto = """
        ===== PDF ADJUNTADO EN EL CHAT =====
        PÁGINA 1
        CÉDULA DE IDENTIFICACIÓN DEL AUTOMOTOR
        DOMINIO AB123CD
        NRO. MOTOR CFZ123456
        NRO. CHASIS 9BWZZZ377JT123456
        ===== FIN PDF ADJUNTADO =====
        """
    ids = cedula_ops._extraer_identificadores_texto(A())
    check(ids["motor"] == "CFZ123456", f"Motor textual inesperado: {ids}")
    check(ids["chasis"] == "9BWZZZ377JT123456", f"Chasis textual inesperado: {ids}")

    # En PDF digital, texto + dos lecturas visuales iguales pueden completar las
    # tres evidencias independientes si una tercera lectura visual falló.
    valor = "9BWZZZ377JT123456"
    r = cedula_ops._resolver_campo(
        ev(valor, fuente="general"), ev(valor, fuente="focal"), ev("", False, fuente="verificacion"), [],
        cedula_ops._evidencia_textual(valor, "chasis"),
    )
    check(r[0] == valor and r[1] == "verificado", "Capa textual válida no reforzó PDF digital")

    # Pero un texto que contradice tres lecturas visuales impide ✓ Verificado.
    r = cedula_ops._resolver_campo(
        ev(valor), ev(valor), ev(valor), [],
        cedula_ops._evidencia_textual("9BWZZZ377JT12345B", "chasis"),
    )
    check(r[1] == "revisar", "Una evidencia textual conflictiva nunca debe ocultarse")


def test_rescate_cedula_no_depende_confianza_otro():
    import chat_special
    c_alta = document_classifier.ClasificacionAdjunto("otro", "alta", [], "gemini_visual", "")
    class Img:
        tipo = "imagen"
        contexto = ""
    check(chat_special._conviene_rescate_cedula(Img(), c_alta, "Analizá esta imagen según su contenido."),
          "Una foto de cédula no debe descartarse porque el clasificador dijo OTRO con confianza alta")

    class Scan:
        tipo = "pdf"
        contexto = ""
    check(chat_special._conviene_rescate_cedula(Scan(), c_alta, alta_ops.MENSAJE_PDF_POR_DEFECTO),
          "Un PDF escaneado debe tener rescate visual de cédula")

    class Manual:
        tipo = "pdf"
        contexto = "MANUAL GENERAL DE COBERTURAS " + ("texto " * 800)
    check(not chat_special._conviene_rescate_cedula(Manual(), c_alta, alta_ops.MENSAJE_PDF_POR_DEFECTO),
          "Un manual largo sin señales vehiculares no debe gastar el pipeline de cédula")


def test_pdf_escaneado_no_se_rechaza():
    # PDF con una imagen pero sin capa de texto.
    img = Image.new("RGB", (500, 300), "white")
    buf = io.BytesIO(); img.save(buf, format="PNG")
    doc = fitz.open(); page = doc.new_page(width=500, height=300)
    page.insert_image(page.rect, stream=buf.getvalue())
    pdf = doc.tobytes(); doc.close()
    contexto, paginas, chars = chat_pdf.extraer_contexto_pdf(
        pdf, "cedula_scan.pdf", max_paginas=8, max_chars=50000, max_bytes=20*1024*1024
    )
    check(contexto == "", "Scan sin texto debe seguir como contexto vacío para visión")
    check(paginas == 1 and chars == 0, "Metadatos incorrectos para PDF escaneado")



def test_orientacion_exif_se_aplica():
    # Simula una foto de celular guardada 120x60 pero marcada para rotar 90°.
    img = Image.new("RGB", (120, 60), "white")
    exif = Image.Exif(); exif[274] = 6
    buf = io.BytesIO(); img.save(buf, format="JPEG", exif=exif)
    class A:
        tipo = "imagen"
        datos_binarios = buf.getvalue()
        mime_type = "image/jpeg"
    media = attachment_vision.renderizar_para_vision(A(), max_paginas=1)
    check(len(media) == 1, "Foto EXIF no renderizada")
    with Image.open(io.BytesIO(media[0].data)) as out:
        check(out.size == (60, 120), f"La orientación EXIF no se aplicó: {out.size}")


def test_render_scan_para_vision():
    img = Image.new("RGB", (640, 400), "white")
    buf = io.BytesIO(); img.save(buf, format="PNG")
    doc = fitz.open(); page = doc.new_page(width=640, height=400)
    page.insert_image(page.rect, stream=buf.getvalue())
    pdf = doc.tobytes(); doc.close()
    class A:
        tipo = "pdf"
        datos_binarios = pdf
        mime_type = "application/pdf"
    media = attachment_vision.renderizar_para_vision(A(), max_paginas=2, escala_pdf=2.0)
    check(len(media) == 1, "PDF escaneado debe renderizarse para visión")
    check(media[0].mime_type == "image/png" and len(media[0].data) > 100, "Render visual inválido")


def test_rescate_clasificador_no_es_fatal():
    import chat_special
    original_clasificar = chat_special.clasificar_adjunto
    original_cedula = chat_special.cedula_ops.procesar_cedula
    original_flota = chat_special.flota_ops.procesar_turno
    try:
        chat_special.clasificar_adjunto = lambda _a: document_classifier.ClasificacionAdjunto(
            "otro", "baja", [], "gemini_error", "503 simulado"
        )
        chat_special.cedula_ops.procesar_cedula = lambda _a, clasificacion_confirmada=False: cedula_ops.CedulaResult(
            {"motor": "M123", "chasis": "C123", "estado_motor": "revisar", "estado_chasis": "revisar"}, []
        )
        chat_special.flota_ops.procesar_turno = lambda *args, **kwargs: (None, False, None)
        class A:
            tipo = "imagen"
            contexto = ""
        r = chat_special.procesar(
            chat_id=1, mensaje="Procesá este archivo.", contexto_pdf="", flota_store=None, adjunto=A()
        )
        check(r.atendido and r.handler == "cedula", "Fallo del clasificador debe permitir rescate de cédula")
        check("No pude clasificar" not in str(r.respuesta), "No debe devolver el fallo del clasificador como respuesta final")
    finally:
        chat_special.clasificar_adjunto = original_clasificar
        chat_special.cedula_ops.procesar_cedula = original_cedula
        chat_special.flota_ops.procesar_turno = original_flota

def test_semantica_excel_y_poliza():
    cols = alta_ops.propuesta_a_columnas({
        "asegurado": "JUAN PEREZ", "numero_poliza": "6509977",
        "vehiculo": "HONDA WAVE", "patente": "AB123CD", "compania": "ATM"
    })
    check(cols.get("POLIZA") == "6509977", "Debe conservar póliza efímera")
    check(cols.get("NUMERO") == "", "NUMERO histórico debe seguir siendo teléfono manual")
    check(cols.get("TELEFONO") == "", "No debe inventar teléfono desde la póliza")


def main():
    pruebas = [
        test_telefonos,
        test_patente_envios,
        test_clasificacion_textual,
        test_consenso_cedula,
        test_texto_pdf_refuerza_identificadores,
        test_rescate_cedula_no_depende_confianza_otro,
        test_pdf_escaneado_no_se_rechaza,
        test_orientacion_exif_se_aplica,
        test_render_scan_para_vision,
        test_rescate_clasificador_no_es_fatal,
        test_semantica_excel_y_poliza,
    ]
    for prueba in pruebas:
        prueba()
        print("OK", prueba.__name__)
    print(f"OK TOTAL: {len(pruebas)} grupos")


if __name__ == "__main__":
    main()
