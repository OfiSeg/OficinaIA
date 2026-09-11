from __future__ import annotations

import ast
import os
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_system_health_crea_eventos_sistema_sin_app() -> None:
    old_database_url = os.environ.pop("DATABASE_URL", None)
    try:
        import local_db
        import system_health

        original_db_file = local_db.DB_FILE
        with tempfile.TemporaryDirectory() as tmp:
            local_db.DB_FILE = Path(tmp) / "oficina_test.db"
            system_health.registrar_evento(
                "ia",
                "aviso",
                "No se pudo responder",
                detalle="api_key=secreto REFRESH_TOKEN=secreto postgres://usuario:clave@host/db",
                codigo="TEST_BOOTSTRAP",
            )
            rows = system_health.listar_eventos(dias=1)
            assert_true(rows, "registrar_evento debe crear la tabla y conservar el evento")
            row = rows[0]
            assert_true(row.get("codigo") == "TEST_BOOTSTRAP", "debe conservar codigo del evento")
            detalle = str(row.get("detalle_tecnico") or "")
            assert_true("secreto" not in detalle and "postgres://" not in detalle, "detalle debe sanear secretos")
            assert_true("Sofia" not in row.get("mensaje", ""), "mensaje visible no debe mostrar Sofia")
            with sqlite3.connect(local_db.DB_FILE) as db:
                cols = {r[1] for r in db.execute("PRAGMA table_info(eventos_sistema)").fetchall()}
            assert_true("codigo" in cols, "la migración perezosa debe agregar columna codigo")
        local_db.DB_FILE = original_db_file
    finally:
        if old_database_url is not None:
            os.environ["DATABASE_URL"] = old_database_url


def test_bat_windows_presentes_y_seguros() -> None:
    requeridos = [
        "INSTALAR_LOCAL.bat",
        "INICIAR_LOCAL.bat",
        "IMPORTAR_ARCA.bat",
        "VALIDAR_TODO.bat",
        "DIAGNOSTICO_LOCAL.bat",
    ]
    for rel in requeridos:
        path = ROOT / rel
        assert_true(path.exists(), f"falta {rel}")
        text = read(rel)
        assert_true("%~dp0" in text, f"{rel} debe ejecutarse desde su propia carpeta")
        assert_true("GEMINI_API_KEY" not in text and "GMAIL_OAUTH" not in text, f"{rel} no debe incluir secretos")


def test_importar_arca_bat_acepta_descargas_repetidas() -> None:
    text = read("IMPORTAR_ARCA.bat")
    assert_true("apellidoNombreDenominacion*.zip" in text, "debe detectar variantes descargadas como (1).zip")
    assert_true("importar_padron_arca.py" in text, "debe usar el importador real")
    assert_true("pause" in text.lower(), "debe pausar para que el productor pueda leer errores")


def test_documentacion_etapa9() -> None:
    text = read("ETAPA9_CAMBIOS.md")
    for snippet in [
        "Primer arranque local",
        "eventos_sistema",
        "INSTALAR_LOCAL.bat",
        "IMPORTAR_ARCA.bat",
        "apellidoNombreDenominacion*.zip",
    ]:
        assert_true(snippet in text, f"falta documentación: {snippet}")
    comandos = read("COMANDOS_GITHUB_RENDER.md")
    assert_true("Accesos rápidos de Windows" in comandos, "COMANDOS debe documentar los .bat")


def test_validar_todo_incluye_etapa9() -> None:
    text = read("VALIDAR_TODO.py")
    ast.parse(text)
    assert_true("VALIDACION_ETAPA9_PRIMER_ARRANQUE.py" in text, "VALIDAR_TODO debe incluir Etapa 9")


def main() -> None:
    tests = [
        test_system_health_crea_eventos_sistema_sin_app,
        test_bat_windows_presentes_y_seguros,
        test_importar_arca_bat_acepta_descargas_repetidas,
        test_documentacion_etapa9,
        test_validar_todo_incluye_etapa9,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"VALIDACION_ETAPA9_PRIMER_ARRANQUE OK - {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
