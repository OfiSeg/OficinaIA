"""Comando para un Cron Job diario (recomendado: 03:00 America/Argentina/Buenos_Aires)."""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent / ".env")

from sheets_backup import ejecutar_respaldo_diario
import system_health

if __name__ == "__main__":
    resultado = ejecutar_respaldo_diario()
    eliminados = system_health.limpiar_eventos_antiguos(30)
    print("RESPALDO:", resultado)
    print("EVENTOS ANTIGUOS ELIMINADOS:", eliminados)
    if not resultado.get("ok"):
        raise SystemExit(1)
