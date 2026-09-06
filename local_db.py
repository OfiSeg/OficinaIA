from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "oficina.db"

def conectar_db():
    """Conexión SQLite local compartida para desarrollo/fallback."""
    conexion = sqlite3.connect(DB_FILE)
    conexion.row_factory = sqlite3.Row
    return conexion
