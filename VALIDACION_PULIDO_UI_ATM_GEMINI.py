from __future__ import annotations

from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_composer_sin_boton_slash_pero_comandos_siguen():
    html = (ROOT / "templates/documentos.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert 'id="slashBtn"' not in html
    assert "actualizarMenuComandos()" in js
    assert "COMANDOS_CHAT" in js


def test_menu_mas_sin_scrollbar_visible():
    css = (ROOT / "static/css/estilo.css").read_text(encoding="utf-8")
    assert ".chat-action-menu::-webkit-scrollbar" in css
    assert "scrollbar-width:none" in css
    assert "max-height:min(472px" in css
    assert "overflow-x:hidden" in css


def test_lightbox_sale_del_chat_window_y_cubre_viewport():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/estilo.css").read_text(encoding="utf-8")
    assert "document.body.appendChild(modal)" in js
    assert "body.chat-lightbox-open>.chat-image-lightbox" in css
    assert "height:100dvh" in css
    assert "backdrop-filter:blur(7px)" in css


def test_excel_es_entrada_principal_y_csv_salida():
    html = (ROOT / "templates/documentos.html").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "PDF, Excel o archivo" in html
    assert "Excel directo desde el chat (CSV secundario)" in app
    assert "generar el CSV final de Envíos Ya" in js
    assert "Descargar CSV para Envíos Ya" in js



def test_excel_real_xlsx_se_convierte_a_csv_envios_ya():
    from io import BytesIO
    import csv
    from openpyxl import Workbook
    from envios_masivos import procesar_bases, generar_exportacion_pendiente

    wb = Workbook()
    ws = wb.active
    ws.title = "Contactos"
    ws.append(["Nombre", "Apellido", "Celular", "Fecha"])
    ws.append(["Juan", "Pérez", "11 5555-1234", "2026-09-12"])
    ws.append(["Ana", "Gómez", "11-4444-9876", "2026-09-15"])
    bio = BytesIO()
    wb.save(bio)

    preparado = procesar_bases(
        [("contactos_prueba.xlsx", bio.getvalue())],
        generar_archivo=False,
    )
    assert preparado["requiere_mapeo"] is False
    assert preparado["resumen"]["exportables"] == 2
    assert preparado["archivo"] is None

    salida = generar_exportacion_pendiente(preparado["token"])
    try:
        with salida.open("r", encoding="utf-8", newline="") as fh:
            filas = list(csv.reader(fh))
        assert len(filas) == 2
        assert all(len(fila) == 10 for fila in filas)
        por_nombre = {(fila[0], fila[1]): fila for fila in filas}
        assert por_nombre[("Pérez", "Juan")][2:4] == ["1155551234", "2026-09-12"]
        assert por_nombre[("Gómez", "Ana")][2:4] == ["1144449876", "2026-09-15"]
        assert all(
            fila[4:7] == ["XXX", "XXX", "XXX"]
            and fila[7] == ""
            and fila[8] == "XXX"
            and fila[9] == ""
            for fila in filas
        )
    finally:
        salida.unlink(missing_ok=True)

def test_atm_no_selecciona_todo_por_defecto_y_preserva_eleccion():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "ofrecer:false" in js
    assert "seleccionadasATM()" in js
    assert "items.forEach(c=>c.ofrecer=false)" in js
    assert "item.ofrecer=true" in js or "preferida.ofrecer=true" in js
    assert "codigoSeleccionadoATM" in js


def test_propuesta_atm_corta_y_sin_descripciones_repetidas():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "¡Hola! Te paso algunas opciones de cobertura para tu vehículo" in js
    assert "Valores sujetos a las condiciones de contratación de ATM." not in js
    bloque = js[js.index("async function generarPropuestaATM"):js.index("async function copiarPropuestaATM")]
    assert "con cupones ·" in bloque and "con CBU o tarjeta adherida" in bloque
    assert "efectivo ·" not in bloque


def test_redondeo_comercial_y_formula_atm_intacta():
    import atm_cotizador
    assert atm_cotizador.redondear_comercial_miles(Decimal("94450")) == 94000
    assert atm_cotizador.redondear_comercial_miles(Decimal("94499")) == 94000
    assert atm_cotizador.redondear_comercial_miles(Decimal("94500")) == 95000
    assert atm_cotizador.redondear_comercial_miles(Decimal("94748")) == 95000
    assert atm_cotizador.redondear_comercial_miles(Decimal("119026")) == 119000
    assert atm_cotizador.redondear_comercial_miles(Decimal("377820")) == 378000
    assert atm_cotizador.ATM_FACTOR_ADHESION == Decimal(5) / Decimal(6)
    r = atm_cotizador.cotizar_atm("185000", descuento="50")
    assert Decimal(r["precio_adherido"]) == Decimal("185000") * Decimal(5) / Decimal(6)
    assert r["precio_base_descuento_comercial_formateado"] == "$93.000"
    assert r["precio_adherido_descuento_comercial_formateado"] == "$77.000"


def test_gemini_smalltalk_prioriza_lite_y_tiene_fallback_controlado():
    ia = (ROOT / "servicios_ia.py").read_text(encoding="utf-8")
    gateway = (ROOT / "ai_gateway.py").read_text(encoding="utf-8")
    assert 'SMALLTALK_MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash")' in ia
    assert 'GEMINI_CHAT_SMALLTALK_TIMEOUT_MS", 5500' in ia
    assert "max_attempts=2" in ia
    assert 'GEMINI_CHAT_THINKING_LEVEL", "low"' in ia
    assert '"gemini-3.8-flash"' in gateway
    assert '"gemini-3.5-flash-lite"' in gateway
    assert "IA_METRIC operation=" in gateway
    assert "categoria=" in (ROOT / "resilience.py").read_text(encoding="utf-8")


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print("OK", test.__name__)
    print(f"OK TOTAL: {len(tests)} grupos")


if __name__ == "__main__":
    main()
