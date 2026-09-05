# OficinaIA — Correcciones de estabilidad y exactitud

Cambios aplicados sobre la versión entregada el 04/09/2026.

## Exactitud de la IA
- `contar_registros` pasa a ser la herramienta determinística para cantidades sobre el Excel completo.
- Soporta compañía, campo/valor, tipo de vehículo, rango de fechas y conteo por filas o asegurados únicos.
- Devuelve `cantidad`, `filtros_aplicados`, `dataset_total_filas` y trazabilidad del tipo de conteo.
- El prompt prohíbe contar previews, muestras parciales o filas visibles de `consultar_excel`.
- Se desambiguó “cuántos remolques tenemos” (Excel) de “cuántos remolques cubre la asistencia” (metadatos).
- `remolque` y `trailer` se tratan como sinónimos controlados para el filtro de vehículo.

## Excel y rendimiento
- Cache en memoria del Excel principal con TTL de 10 segundos.
- Invalidación explícita después de cada escritura confirmada mediante `guardar_matriz_excel`.
- Se mantiene 1 worker / 1 thread: no se habilitó concurrencia multiproceso mientras Excel/R2 siga siendo fuente viva.

## Gemini
- Modelos de fallback reducidos a dos IDs estables: `gemini-3.8-flash` y `gemini-3.5-flash-lite`.
- Timeout HTTP global del cliente: 30 segundos por llamada.
- La fecha actual del servidor se inyecta al prompt para resolver consultas temporales sin adivinar.

## Teléfono / Envíos Ya
- Nueva columna `TELEFONO` agregada al Excel sin mover las columnas existentes.
- Envíos Ya toma el teléfono únicamente de `TELEFONO`; deja de reutilizar `NUMERO`.
- `/guardar asegurado` mantiene el orden histórico y acepta `TELEFONO` como noveno campo opcional.
- `/alta` extrae teléfono sólo cuando aparece explícitamente en la póliza; nunca usa DNI o número de póliza como teléfono.

## Compañías
- Nueva fuente única de normalización: `companias.py`.
- Se unificaron aliases/códigos/nombres visibles para ATM, AGS, Mercantil, Federación, etc.
- La extracción de `/alta`, el guardado y las reglas de pago usan la misma normalización.

## Bug adicional encontrado y corregido
- El chat proponía `CIA` y `CP`, mientras el Excel real usa `COMPAÑIA` y `CODIGO POSTAL`.
- Se agregó el mapeo de alias correspondiente para evitar que esos valores se pierdan al guardar.

## Detección de póliza individual
- Se ampliaron señales válidas a COBERTURA, VIGENCIA y CERTIFICADO, conservando las barreras contra flotas.

## Validaciones realizadas
- Compilación Python de `app.py`, `servicios_ia.py` y `companias.py` sin errores de sintaxis.
- Pruebas determinísticas sobre el Excel entregado:
  - ATM: 88 registros.
  - AgroSalta/AGS: 55 registros.
  - `ATM + remolque`, `ATM + remolques` y `ATM + TRAILER` resuelven al mismo registro real.
  - Rango 22/08/2026–24/08/2026: 6 registros con fecha válida.
  - Cache reutiliza la misma carga durante el TTL.
  - El mapeo de `CIA -> COMPAÑIA`, `CP -> CODIGO POSTAL` y `TELEFONO` funciona con los encabezados reales.

## Pruebas recomendadas al desplegar
1. Preguntar: “¿Cuántos remolques tiene ATM?” y verificar que responda el conteo calculado por tool, no una muestra de asegurados.
2. Preguntar: “¿Cuántos servicios de remolque cubre ATM?” y verificar que consulte fichas/metadatos, no el Excel de asegurados.
3. Hacer dos preguntas seguidas que usen Excel y revisar logs: la carga del Excel debería aparecer una sola vez dentro del TTL.
4. Guardar un asegurado y consultarlo inmediatamente: debe aparecer sin esperar 10 segundos.
5. Guardar con CIA, CP y TELEFONO y verificar las columnas `COMPAÑIA`, `CODIGO POSTAL` y `TELEFONO`.
6. Ejecutar `/envios ya (patente)` sobre un registro con teléfono y otro sin teléfono.
7. Probar `/alta` con pólizas de AgroSalta escritas con variantes y verificar que guarde `AGS`.
8. Probar “¿cuántas pólizas emití entre 22/08/2026 y 24/08/2026?”.

No se modificó `render-start.txt`: continúa con `--workers 1 --threads 1 --timeout 180`.
