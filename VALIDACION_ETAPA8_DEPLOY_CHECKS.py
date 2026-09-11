from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_archivos_operativos_presentes() -> None:
    for rel in [
        "DIAGNOSTICO_OFICINAIA.py",
        "VALIDAR_TODO.py",
        "COMANDOS_GITHUB_RENDER.md",
        "ETAPA8_CAMBIOS.md",
    ]:
        assert_true((ROOT / rel).exists(), f"falta {rel}")


def test_validar_todo_lista_validadores_clave() -> None:
    text = read("VALIDAR_TODO.py")
    for nombre in [
        "VALIDACION_ETAPA1_CEDULA_PRODUCTOR.py",
        "VALIDACION_ETAPA2_CONTEXTO_CARTERA.py",
        "VALIDACION_ETAPA3_FRONTEND_RESILIENCIA.py",
        "VALIDACION_ETAPA4_DOCUMENTOS_MULTIPLES.py",
        "VALIDACION_ETAPA5_CAPABILITIES.py",
        "VALIDACION_ETAPA6_ARCA_CUIT.py",
        "VALIDACION_ETAPA7_INTEGRACION_FINAL.py",
        "VALIDACION_ETAPA8_DEPLOY_CHECKS.py",
        "VALIDACION_RESILIENCIA_GLOBAL.py",
        "VALIDACION_SALUD_SERVICIOS.py",
        "VALIDACION_V20_DNI_LICENCIA.py",
        "VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py",
    ]:
        assert_true(nombre in text, f"VALIDAR_TODO no incluye {nombre}")
    ast.parse(text)


def test_diagnostico_no_imprime_secretos_y_revisa_arca() -> None:
    text = read("DIAGNOSTICO_OFICINAIA.py")
    ast.parse(text)
    assert_true("No se muestran valores" in text, "el diagnóstico debe aclarar que no muestra secretos")
    assert_true("estado_padron" in text, "el diagnóstico debe revisar estado ARCA")
    assert_true("office_now" in text, "el diagnóstico debe probar hora de oficina")
    assert_true("apellidoNombreDenominacion.zip" in text, "el diagnóstico debe guiar importación ARCA")


def test_comandos_documentados() -> None:
    text = read("COMANDOS_GITHUB_RENDER.md")
    for snippet in [
        "python -m pip install -r requirements.txt",
        "python DIAGNOSTICO_OFICINAIA.py",
        "python app.py",
        "python importar_padron_arca.py apellidoNombreDenominacion.zip",
        "python VALIDAR_TODO.py",
        "git add .",
        "git push origin main",
        "gunicorn --workers 1 --threads 1 --timeout 180 app:app",
    ]:
        assert_true(snippet in text, f"falta comando/documentación: {snippet}")


def test_gitignore_sigue_excluyendo_padron() -> None:
    text = read(".gitignore")
    for patron in ["apellidoNombreDenominacion.zip", "apellidoNombreDenominacion*.zip", "padron_arca*.db", "padron_arca*.sqlite"]:
        assert_true(patron in text, f".gitignore no excluye {patron}")


def test_no_padron_pesado_en_paquete() -> None:
    prohibidos = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        lower = rel.lower()
        if lower.startswith(".git/"):
            continue
        if "apellidonombredenominacion" in lower and lower.endswith(".zip"):
            prohibidos.append(rel)
        if lower.startswith("padron_arca") and lower.endswith((".db", ".sqlite", ".zip")):
            prohibidos.append(rel)
    assert_true(not prohibidos, f"archivos pesados/prohibidos dentro del paquete: {prohibidos}")


def main() -> None:
    tests = [
        test_archivos_operativos_presentes,
        test_validar_todo_lista_validadores_clave,
        test_diagnostico_no_imprime_secretos_y_revisa_arca,
        test_comandos_documentados,
        test_gitignore_sigue_excluyendo_padron,
        test_no_padron_pesado_en_paquete,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"VALIDACION_ETAPA8_DEPLOY_CHECKS OK - {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
