from __future__ import annotations

import sys
import time
from pathlib import Path

from arca_service import importar_padron_arca, estado_padron


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("Uso: python importar_padron_arca.py apellidoNombreDenominacion.zip")
        return 2
    path = Path(argv[0])
    inicio = time.time()
    try:
        resultado = importar_padron_arca(path)
    except Exception as exc:
        print("========================================")
        print("NO SE PUDO IMPORTAR EL PADRÓN ARCA")
        print("========================================")
        print(str(exc))
        print("El padrón anterior, si existía, se conserva.")
        return 1
    duracion = time.time() - inicio
    print("========================================")
    print("PADRÓN ARCA IMPORTADO CORRECTAMENTE")
    print("========================================")
    print(f"Backend: {resultado.get('backend')}")
    print(f"Archivo interno: {resultado.get('archivo_origen') or '-'}")
    print(f"Registros procesados: {resultado.get('procesados')}")
    print(f"Personas importadas: {resultado.get('importados')}")
    print(f"Registros descartados: {resultado.get('descartados')}")
    print(f"Fecha del padrón: {resultado.get('fecha_padron') or '-'}")
    print(f"Duración: {duracion:.1f} segundos")
    print("========================================")
    estado = estado_padron()
    print(f"Estado actual: cargado={estado.get('cargado')} registros={estado.get('registros')} backend={estado.get('backend')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
