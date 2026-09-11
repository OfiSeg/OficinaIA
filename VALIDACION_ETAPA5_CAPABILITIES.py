"""Regresiones ETAPA 5: manifiesto de capacidades y hotfix de timezone.

Validador offline: no llama Gemini, Google Sheets, Gmail ni servicios externos.
"""
from __future__ import annotations

import os
from pathlib import Path


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_manifesto_central_existe_y_tiene_capacidades_reales():
    import capabilities
    caps = capabilities.get_capabilities(include_unavailable=True)
    for key in (
        "consulta_cartera",
        "conteos_y_fechas",
        "estadisticas",
        "analisis_archivos",
        "documentos_multiples",
        "lectura_cedulas",
        "ambiguedad_cedulas",
        "lectura_dni_licencia",
        "lectura_polizas",
        "alta_desde_poliza",
        "guardar_excel",
        "envios_ya",
        "manuales_metadatos",
        "comparar_companias",
        "estudio",
        "redaccion_mail",
        "envio_mail",
        "salud",
    ):
        check(key in caps, f"Falta capacidad {key}")
        check(caps[key].get("description"), f"{key} no tiene descripción humana")
    # Desde Etapa 6 ARCA existe en el manifiesto, pero sólo debe aparecer disponible
    # cuando el padrón interno fue cargado.
    if "resolver_cuit_arca" in caps:
        check(caps["resolver_cuit_arca"].get("description"), "ARCA debe tener descripción humana")
        check("requires_padron_arca" in caps["resolver_cuit_arca"], "ARCA debe depender del padrón cargado")


def test_capabilities_se_inyecta_en_prompt_sin_autodenominarse_sofia():
    import sofia_prompt
    prompt = sofia_prompt.build_sofia_prompt(
        fecha_hoy="11/09/2026",
        plan_texto="INTENCIÓN: general",
        historial_texto="",
        contexto_comparativo="",
        contexto_documental="",
        contexto_estructurado="",
        pregunta="qué podés hacer",
    )
    check("CAPACIDADES ACTUALES DE OFICINAIA" in prompt, "El prompt no recibe capacidades")
    check("Leer cédulas" in prompt, "El prompt no explica cédulas")
    check("Analizar pólizas" in prompt, "El prompt no explica pólizas")
    check("Redactar comunicaciones" in prompt, "El prompt no explica redacción")
    check("Sos Sofia" not in prompt and "Sos Sofía" not in prompt, "El prompt fuerza autodenominación Sofia")
    check("No uses un nombre propio" in prompt, "Falta regla de no nombre propio visible")
    check("CAPABILITIES[" not in prompt, "No debe exponer formato técnico al modelo como respuesta")


def test_disponibilidad_runtime_no_inventa_integraciones():
    import capabilities
    names = (
        "GMAIL_SENDER_EMAIL",
        "GMAIL_OAUTH_CLIENT_ID",
        "GMAIL_OAUTH_CLIENT_SECRET",
        "GMAIL_OAUTH_REFRESH_TOKEN",
    )
    old = {n: os.environ.pop(n, None) for n in names}
    try:
        check(capabilities.capability_is_available("envio_mail") is False, "Mail no debe aparecer disponible sin configuración")
        for n in names:
            os.environ[n] = "x"
        check(capabilities.capability_is_available("envio_mail") is True, "Mail debe quedar disponible con configuración completa")
    finally:
        for n in names:
            if old[n] is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = old[n]


def test_timezone_tiene_tzdata_y_fallback_windows():
    req = Path("requirements.txt").read_text(encoding="utf-8").lower()
    office_time = Path("office_time.py").read_text(encoding="utf-8")
    check("tzdata" in req, "requirements.txt debe incluir tzdata para Windows/local")
    check("timezone(timedelta(hours=-3)" in office_time, "office_time debe tener fallback UTC-3 fijo")
    check("nombre != DEFAULT_OFFICE_TIMEZONE" in office_time, "Debe intentar la zona default sólo como fallback controlado")
    check(office_time.count("except ZoneInfoNotFoundError") >= 2, "El fallback default debe estar protegido por su propio except")


def test_salud_y_templates_no_muestran_sofia_visible():
    estudio = Path("templates/estudio.html").read_text(encoding="utf-8")
    biblioteca = Path("templates/biblioteca.html").read_text(encoding="utf-8")
    servicios = Path("servicios_ia.py").read_text(encoding="utf-8")
    check("Cómo aprende Sofía" not in estudio, "Estudio no debe mostrar Sofía")
    check("para que Sofia las use" not in biblioteca, "Biblioteca no debe mostrar Sofia")
    check('"Sofia no pudo leer Google Sheets"' not in servicios, "Eventos nuevos no deben guardar Sofia visible")
    import system_health
    rows = [{"mensaje": "Sofia no pudo responder"}, {"mensaje": "Sofia no pudo leer Google Sheets"}]
    fixed = system_health._normalizar_eventos_visibles(rows)
    joined = "\n".join(r["mensaje"] for r in fixed)
    check("Sofia" not in joined and "Sofía" not in joined, "Salud debe sanitizar eventos históricos visibles")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for test in tests:
        test()
        ok += 1
        print("OK", test.__name__)
    print(f"VALIDACION_ETAPA5_CAPABILITIES: {ok}/{len(tests)} OK")


if __name__ == "__main__":
    main()
