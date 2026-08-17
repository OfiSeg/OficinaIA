# Corrección quirúrgica de estabilidad Render

## Causa encontrada
La ruta `/api/chat` ejecutaba `buscar_en_documentos()` en cada consulta. Antes,
`_manuales_r2_por_ruta()` descargaba TODOS los manuales de R2 antes de iniciar
la búsqueda y luego `buscar_en_documentos()` extraía texto de todos ellos.
Eso hacía que una sola petición pudiera realizar muchas descargas y extracciones
de PDF dentro del worker. Con `--threads 2`, dos consultas podían ejecutarse
simultáneamente en el mismo worker y multiplicar el pico de memoria/tiempo.
El traceback en `ssl.py` es compatible con un worker bloqueado en una operación
de red cuando Gunicorn aborta la petición; no se trató como un problema de SSL.

## Cambios
- `app.py`: los manuales R2 se seleccionan primero por relevancia del nombre/ruta
  y sólo se descargan/procesan hasta 12 candidatos por consulta.
- `servicios_ia.py`: se evita descargar Google Sheets dos veces en una misma
  consulta.
- `render-start.txt`: Gunicorn queda en 1 worker y 1 thread, manteniendo timeout 180.

No se eliminan manuales, registros, R2, PostgreSQL, Excel, usuarios ni interfaz.
