"""Diagnóstico rápido local para OficinaIA.

Uso:
    python DIAGNOSTICO_OFICINAIA.py

Este script no muestra secretos. Sólo informa si las piezas mínimas están
presentes para ejecutar la app, validar etapas e importar el padrón ARCA.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PAQUETES = [
    ("flask", "Flask"),
    ("google.genai", "google-genai / Gemini"),
    ("openpyxl", "Excel local"),
    ("PIL", "Pillow / imágenes"),
    ("fitz", "PyMuPDF / PDF"),
    ("dotenv", "python-dotenv / .env local"),
    ("psycopg2", "PostgreSQL producción"),
    ("tzdata", "tzdata Windows/local"),
]

ARCHIVOS_CLAVE = [
    "app.py",
    "requirements.txt",
    "runtime.txt",
    "render-start.txt",
    "office_time.py",
    "capabilities.py",
    "arca_service.py",
    "importar_padron_arca.py",
    "static/js/app.js",
]

ENV_CLAVE = [
    "FLASK_SECRET_KEY",
    "GEMINI_API_KEY",
    "DATABASE_URL",
    "GOOGLE_SHEET_ID",
    "GMAIL_SENDER_EMAIL",
    "GMAIL_OAUTH_CLIENT_ID",
    "GMAIL_OAUTH_CLIENT_SECRET",
    "GMAIL_OAUTH_REFRESH_TOKEN",
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "OFFICE_TIMEZONE",
]


def _ok(label: str) -> None:
    print(f"OK    {label}")


def _warn(label: str) -> None:
    print(f"AVISO {label}")


def _err(label: str) -> None:
    print(f"ERROR {label}")


def _package_available(modulo: str) -> bool:
    try:
        spec = importlib.util.find_spec(modulo)
    except Exception:
        return False
    return spec is not None


def _check_archivos() -> bool:
    print("\nARCHIVOS CLAVE")
    ok_total = True
    for rel in ARCHIVOS_CLAVE:
        path = ROOT / rel
        if path.exists():
            _ok(rel)
        else:
            _err(f"falta {rel}")
            ok_total = False
    return ok_total


def _check_paquetes() -> bool:
    print("\nPAQUETES PYTHON")
    ok_total = True
    for modulo, descripcion in PAQUETES:
        disponible = _package_available(modulo)
        if disponible:
            _ok(descripcion)
        elif modulo in {"psycopg2", "tzdata"}:
            _warn(f"{descripcion} no detectable. Instalá con: python -m pip install -r requirements.txt")
        else:
            _err(f"falta {descripcion}. Ejecutá: python -m pip install -r requirements.txt")
            ok_total = False
    return ok_total


def _check_timezone() -> bool:
    print("\nHORA DE OFICINA")
    try:
        office_time = importlib.import_module("office_time")
        ahora = office_time.office_now()
        _ok(f"office_now funciona: {ahora.isoformat()}")
        if ahora.tzinfo is None:
            _err("office_now devolvió datetime sin timezone")
            return False
        return True
    except Exception as exc:
        _err(f"office_time falló: {exc}")
        _warn("Probá: python -m pip install tzdata")
        return False


def _check_env() -> None:
    print("\nVARIABLES DE ENTORNO / .ENV")
    for name in ENV_CLAVE:
        value = os.environ.get(name)
        if value and str(value).strip():
            _ok(f"{name}=configurada")
        else:
            _warn(f"{name}=no configurada")
    print("No se muestran valores para evitar filtrar secretos.")


def _check_arca() -> None:
    print("\nPADRÓN ARCA")
    zip_path = ROOT / "apellidoNombreDenominacion.zip"
    if zip_path.exists():
        _ok("apellidoNombreDenominacion.zip está en la carpeta del proyecto")
    else:
        _warn("apellidoNombreDenominacion.zip no está en la carpeta. Para importar, copialo a C:\\OficinaIA.")
    try:
        arca_service = importlib.import_module("arca_service")
        estado = arca_service.estado_padron()
        if estado.get("cargado"):
            _ok(f"padrón cargado: {estado.get('registros')} registros | backend={estado.get('backend')}")
            if estado.get("fecha_padron"):
                _ok(f"fecha padrón: {estado.get('fecha_padron')}")
        else:
            _warn("padrón no cargado todavía")
            _warn("comando: python importar_padron_arca.py apellidoNombreDenominacion.zip")
            if estado.get("error"):
                _warn(f"detalle ARCA: {estado.get('error')}")
    except Exception as exc:
        _warn(f"no se pudo consultar estado ARCA: {exc}")


def _check_no_padron_git() -> bool:
    print("\nSEGURIDAD DE PAQUETE")
    gitignore = ROOT / ".gitignore"
    ok_total = True
    if gitignore.exists():
        text = gitignore.read_text(encoding="utf-8", errors="ignore")
        for patron in ["apellidoNombreDenominacion*.zip", "padron_arca*.db", "padron_arca*.sqlite"]:
            if patron in text:
                _ok(f".gitignore excluye {patron}")
            else:
                _err(f".gitignore no excluye {patron}")
                ok_total = False
    else:
        _err("no existe .gitignore")
        ok_total = False
    return ok_total


def main() -> int:
    print("========================================")
    print("DIAGNÓSTICO OFICINAIA")
    print("========================================")
    print(f"Carpeta: {ROOT}")
    print(f"Python: {sys.version.split()[0]}")

    ok_archivos = _check_archivos()
    ok_paquetes = _check_paquetes()
    ok_timezone = _check_timezone()
    _check_env()
    _check_arca()
    ok_seguridad = _check_no_padron_git()

    print("\nCOMANDOS ÚTILES")
    print("python -m pip install -r requirements.txt")
    print("python app.py")
    print("python importar_padron_arca.py apellidoNombreDenominacion.zip")
    print("python VALIDAR_TODO.py")

    hard_ok = ok_archivos and ok_paquetes and ok_timezone and ok_seguridad
    print("\n========================================")
    print("DIAGNÓSTICO OK" if hard_ok else "DIAGNÓSTICO CON ERRORES")
    print("========================================")
    return 0 if hard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
