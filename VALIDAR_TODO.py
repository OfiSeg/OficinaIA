"""Ejecuta todas las validaciones locales de OficinaIA en orden.

Uso:
    python VALIDAR_TODO.py

No sube archivos, no modifica GitHub y no importa el padrón ARCA pesado.
Si algún validador falla, termina con exit code 1.
"""
from __future__ import annotations

import compileall
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

VALIDADORES = [
    "VALIDACION_ADJUNTOS_MULTIPLES.py",
    "VALIDACION_ETAPA1_CEDULA_PRODUCTOR.py",
    "VALIDACION_ETAPA2_CONTEXTO_CARTERA.py",
    "VALIDACION_ETAPA3_FRONTEND_RESILIENCIA.py",
    "VALIDACION_ETAPA4_DOCUMENTOS_MULTIPLES.py",
    "VALIDACION_ETAPA5_CAPABILITIES.py",
    "VALIDACION_ETAPA6_ARCA_CUIT.py",
    "VALIDACION_ETAPA7_INTEGRACION_FINAL.py",
    "VALIDACION_ETAPA8_DEPLOY_CHECKS.py",
    "VALIDACION_ETAPA9_PRIMER_ARRANQUE.py",
    "VALIDACION_ETAPA10_WHATSAPP_VISUAL.py",
    "VALIDACION_ETAPA10_1_PREVIEWS_WHATSAPP.py",
    "VALIDACION_RESILIENCIA_GLOBAL.py",
    "VALIDACION_SALUD_SERVICIOS.py",
    "VALIDACION_V20_DNI_LICENCIA.py",
    "VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py",
]


def _run_python_file(path: Path, timeout: int = 240) -> tuple[bool, float]:
    inicio = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(path.name)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    duracion = time.monotonic() - inicio
    if proc.stdout:
        print(proc.stdout.rstrip())
    return proc.returncode == 0, duracion


def _node_check() -> bool:
    app_js = ROOT / "static" / "js" / "app.js"
    if not app_js.exists():
        print("AVISO node --check omitido: no existe static/js/app.js")
        return True
    node = shutil.which("node")
    if not node:
        print("AVISO node --check omitido: Node no está instalado. No afecta el uso normal de Flask.")
        return True
    proc = subprocess.run(
        [node, "--check", str(app_js)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.returncode == 0:
        print("OK node --check static/js/app.js")
        return True
    print("ERROR node --check static/js/app.js")
    return False


def main() -> int:
    print("========================================")
    print("VALIDACIÓN GENERAL OFICINAIA")
    print("========================================")
    print(f"Carpeta: {ROOT}")
    print(f"Python: {sys.version.split()[0]}")
    print("")

    resultados: list[tuple[str, bool, float]] = []
    for nombre in VALIDADORES:
        path = ROOT / nombre
        print("----------------------------------------")
        print(nombre)
        print("----------------------------------------")
        if not path.exists():
            print(f"ERROR: no existe {nombre}")
            resultados.append((nombre, False, 0.0))
            continue
        try:
            ok, duracion = _run_python_file(path)
        except subprocess.TimeoutExpired:
            print(f"ERROR: {nombre} excedió el tiempo máximo")
            ok, duracion = False, 240.0
        resultados.append((nombre, ok, duracion))
        print(f"Resultado: {'OK' if ok else 'ERROR'} ({duracion:.1f}s)")

    print("----------------------------------------")
    print("compileall")
    print("----------------------------------------")
    compile_ok = compileall.compile_dir(str(ROOT), quiet=1)
    print("OK compileall" if compile_ok else "ERROR compileall")

    print("----------------------------------------")
    print("JavaScript")
    print("----------------------------------------")
    js_ok = _node_check()

    print("========================================")
    print("RESUMEN")
    print("========================================")
    for nombre, ok, duracion in resultados:
        print(f"{'OK' if ok else 'ERROR'} {nombre} ({duracion:.1f}s)")
    print(f"{'OK' if compile_ok else 'ERROR'} compileall")
    print(f"{'OK' if js_ok else 'ERROR'} node check")

    todo_ok = all(ok for _, ok, _ in resultados) and compile_ok and js_ok
    print("========================================")
    print("TODO OK" if todo_ok else "HAY ERRORES")
    print("========================================")
    return 0 if todo_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
