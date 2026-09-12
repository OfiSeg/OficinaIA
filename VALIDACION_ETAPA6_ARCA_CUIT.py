from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

import local_db
import arca_service
import sys
import types
sys.modules.setdefault("dispatch_service", types.SimpleNamespace(procesar_comando_explicito=lambda mensaje: None))
import chat_commands


def _linea(cuit: str, nombre: str) -> str:
    return f"{cuit}{nombre[:30]:<30}RESTO"


def _crear_zip(path: Path) -> None:
    lineas = [
        _linea("20433848567", "HERRERA RAMIRO ALEJANDRO"),
        _linea("20376822665", "RODRIGUEZ NICOLAS HUMBERTO"),
        _linea("20034567895", "PEREZ DNI BAJO"),
        _linea("27034567894", "PEREZ DNI BAJO HOMONIMO"),
        _linea("30999999991", "EMPRESA NO PERSONA"),
        "linea corrupta",
    ]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("utlfile/padr/SELE-SAL-CONSTA.p20out1.20260905.tmp", "\n".join(lineas))


def _dummy_excel(*args, **kwargs):
    return {"filas": [["ASEGURADO", "PATENTE"]]}


def _norm(x):
    return str(x or "").strip().upper()


def _procesar(mensaje, historial=None, arca_context=None):
    return chat_commands.procesar(
        mensaje,
        leer_excel=_dummy_excel,
        normalizar_encabezado=_norm,
        libros_excel={"1": {"nombre": "Asegurados"}},
        historial=historial or [],
        arca_context=arca_context,
        adjuntos=[],
    )


def main():
    assert not os.getenv("DATABASE_URL"), "Esta validación offline debe correr con SQLite local."
    with tempfile.TemporaryDirectory() as td:
        local_db.DB_FILE = Path(td) / "oficina_test.db"
        zip_path = Path(td) / "apellidoNombreDenominacion.zip"
        _crear_zip(zip_path)

        r = arca_service.importar_padron_arca(zip_path, batch_size=2)
        assert r["ok"] and r["importados"] == 4, r
        assert r["fecha_padron"] == "05/09/2026", r

        estado = arca_service.estado_padron()
        assert estado["cargado"] and estado["registros"] == 4, estado

        dni = arca_service.resolver_cuit_por_dni("43.384.856")
        assert dni["status"] == "found", dni
        assert dni["cuit_formateado"] == "20-43384856-7", dni
        assert dni["dni_mostrar"] == "43.384.856", dni

        bajo = arca_service.resolver_cuit_por_dni("3.456.789")
        assert bajo["status"] == "multiple", bajo
        assert all(c["dni_mostrar"] == "3.456.789" for c in bajo["candidates"]), bajo

        nombre = arca_service.buscar_personas_arca("Ramiro Alejandro Herrera")
        assert nombre["status"] in {"found", "multiple"}, nombre
        assert nombre["candidates"][0]["nombre"] == "HERRERA RAMIRO ALEJANDRO", nombre

        cmd = _procesar("/cuit 43384856")
        assert cmd.atendido and "20-43384856-7" in cmd.respuesta, cmd
        assert "asegurado" in cmd.respuesta.lower(), cmd.respuesta

        cmd2 = _procesar("3456789")
        assert cmd2.atendido and "CUIT/CUIL" in cmd2.respuesta, cmd2.respuesta

        cmd3 = _procesar("Ramiro Alejandro Herrera")
        assert cmd3.atendido and "cartera" in cmd3.respuesta and "ARCA" in cmd3.respuesta, cmd3.respuesta

        ctx = {"fuente": "ARCA", "candidates": [
            {"nombre": "UNO", "cuit": "20111111110", "cuit_formateado": "20-11111111-0", "dni_mostrar": "11.111.111"},
            {"nombre": "DOS", "cuit": "20222222220", "cuit_formateado": "20-22222222-0", "dni_mostrar": "22.222.222"},
        ]}
        cmd4 = _procesar("el segundo", arca_context=ctx)
        assert cmd4.atendido and "DOS" in cmd4.respuesta and "20-22222222-0" in cmd4.respuesta, cmd4.respuesta

        cmd4b = _procesar("el último", arca_context=ctx)
        assert cmd4b.atendido and "DOS" in cmd4b.respuesta, cmd4b.respuesta

        # Una mención ARCA vieja no debe ganar si la fuente relevante más reciente es cartera.
        hist_fuentes = [
            {"rol": "user", "contenido": "/cuit 43384856"},
            {"rol": "assistant", "contenido": "Resultado ARCA CUIT/CUIL"},
            {"rol": "user", "contenido": "Buscá en mi cartera cuantos asegurados tuve hoy"},
            {"rol": "assistant", "contenido": "Hoy encontré 4 asegurados únicos en la cartera."},
        ]
        assert chat_commands._contexto_es_cartera(hist_fuentes), "La última fuente relevante debe ser CARTERA"
        assert not chat_commands._contexto_es_arca(hist_fuentes, None), "ARCA viejo no debe quedar pegado por historial"
        cmd_nombre_cartera = _procesar("Bao Gabriel Roberto", historial=hist_fuentes)
        assert not cmd_nombre_cartera.atendido, "Un nombre tras contexto cartera no debe ser secuestrado por ARCA"

        # Contexto de cartera gana: número compatible con póliza no debe ir a ARCA.
        hist = [{"rol": "user", "contenido": "buscame la póliza"}]
        cmd5 = _procesar("1764648", historial=hist)
        assert not cmd5.atendido, cmd5

    print("VALIDACION_ETAPA6_ARCA_CUIT OK - contexto ARCA/cartera validado")


if __name__ == "__main__":
    main()
