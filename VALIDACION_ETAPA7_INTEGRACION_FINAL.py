# -*- coding: utf-8 -*-
"""Validación final de integración por etapas.

No reemplaza los validadores específicos de cada etapa; verifica que las piezas
quedaron integradas en una distribución segura para deploy.
"""
from __future__ import annotations

import importlib
import os
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"OK {msg}")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def html_visible_text(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<script.*?</script>", "", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def js_user_facing_strings(text: str) -> str:
    """Extrae strings JS probables de UI y descarta nombres técnicos/clases CSS."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(^|\s)//.*?$", "", text, flags=re.M)
    strings = re.findall(r"(['\"])(.*?)(?<!\\)\1", text, flags=re.S)
    visibles = []
    for _, value in strings:
        low = value.lower()
        if any(token in low for token in ["sofia-", "btn-sofia", "class=", "queryselector", "getelementbyid"]):
            continue
        visibles.append(value)
    return "\n".join(visibles)


def test_ui_visible_sin_sofia() -> None:
    targets = []
    for base in [ROOT / "templates", ROOT / "static" / "js"]:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".html", ".js"}:
                targets.append(path)

    offenders = []
    pattern = re.compile(r"sofia|sofía", re.I)
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".html":
            visible = html_visible_text(text)
        else:
            visible = js_user_facing_strings(text)
        if pattern.search(visible):
            offenders.append(str(path.relative_to(ROOT)))

    check(not offenders, "no hay referencias visibles a Sofia en templates/static js: " + ", ".join(offenders))


def test_timezone_blindado_windows_y_render() -> None:
    requirements = read("requirements.txt")
    code = read("office_time.py")
    check("tzdata" in requirements.lower(), "requirements incluye tzdata")
    check("ZoneInfoNotFoundError" in code and "timedelta(hours=-3)" in code, "office_time tiene fallback UTC-3")

    office_time = importlib.import_module("office_time")
    now = office_time.office_now()
    check(now.tzinfo is not None, "office_now devuelve datetime timezone-aware")
    check(hasattr(office_time, "office_today") and hasattr(office_time, "office_date_string"), "helpers de fecha comercial disponibles")


def test_capabilities_y_arca_integrados_sin_inventar() -> None:
    capabilities = importlib.import_module("capabilities")
    rendered = capabilities.capabilities_for_prompt()
    check("CAPABILITIES" not in rendered, "capabilities se inyecta en lenguaje natural, no como estructura técnica cruda")
    check("Consultar cartera" in rendered or "cartera" in rendered.lower(), "capabilities incluye cartera")
    check("cédula" in rendered.lower() or "cedula" in rendered.lower(), "capabilities incluye cédulas")

    arca = importlib.import_module("arca_service")
    check(hasattr(arca, "normalizar_dni"), "ARCA expone normalizador de DNI")
    check(arca.dni_indexado("3.456.789") == "03456789", "DNI bajo usa padding sólo interno")
    check(arca.formatear_cuit("20301234567") == "20-30123456-7", "CUIT se formatea para el productor")

    chat_commands_code = read("chat_commands.py")
    check("def parsear_cuit_arca" in chat_commands_code and "(?:cuit|cuil)" in chat_commands_code, "parser compartido /cuit y /cuil integrado")


def test_persisten_validadores_por_etapa() -> None:
    esperados = [
        "VALIDACION_ETAPA1_CEDULA_PRODUCTOR.py",
        "VALIDACION_ETAPA2_CONTEXTO_CARTERA.py",
        "VALIDACION_ETAPA3_FRONTEND_RESILIENCIA.py",
        "VALIDACION_ETAPA4_DOCUMENTOS_MULTIPLES.py",
        "VALIDACION_ETAPA5_CAPABILITIES.py",
        "VALIDACION_ETAPA6_ARCA_CUIT.py",
    ]
    faltantes = [name for name in esperados if not (ROOT / name).exists()]
    check(not faltantes, "todos los validadores por etapa siguen presentes")


def test_gitignore_y_distribucion_segura() -> None:
    gitignore = read(".gitignore")
    for token in ["apellidoNombreDenominacion.zip", "padron_arca*.db", "padron_arca*.sqlite"]:
        check(token in gitignore, f".gitignore excluye {token}")

    prohibidos = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        lower = rel.lower()
        if lower.endswith("apellidonombredenominacion.zip") or ("padron_arca" in lower and lower.endswith((".zip", ".db", ".sqlite"))):
            prohibidos.append(rel)
    check(not prohibidos, "no hay padrón pesado dentro del proyecto")


def main() -> None:
    test_ui_visible_sin_sofia()
    test_timezone_blindado_windows_y_render()
    test_capabilities_y_arca_integrados_sin_inventar()
    test_persisten_validadores_por_etapa()
    test_gitignore_y_distribucion_segura()
    print("VALIDACION_ETAPA7_INTEGRACION_FINAL OK")


if __name__ == "__main__":
    main()
