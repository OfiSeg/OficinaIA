OficinaIA - actualización 2026-08-21 (favicon)

- Se incorporó `static/favicon.png` usando el logo proporcionado.
- Se agregó la referencia `<link rel="icon">` en `templates/base.html`.

OficinaIA - fixes 2026-08-19 (pasada metadatos + PDFs)

Archivos modificados:
- app.py:
  * Definida MANUALES_MAX_CANDIDATOS_CIA (default 0 = sin tope por compañía).
    Corrige NameError que vaciaba buscar_en_manuales al detectar compañía.
  * Endpoints /api/metadatos: leen/escriben en Neon cuando existe DATABASE_URL;
    fallback a SQLite en local.
- servicios_ia.py:
  * Tool buscar_en_metadatos marcada como FUENTE PRIORITARIA.
  * Tool buscar_en_manuales marcada como secundaria.
  * Prompt de Gemini: orden obligatorio metadatos → PDFs → resto.
  * _cargar_metadatos: intenta Neon primero, SQLite como fallback.
  * buscar_en_metadatos: manejo de errores consistente + log RETRIEVAL METADATOS.
  * _ejecutar_tool: también marca busqueda_vacia=True cuando hay error/excepción
    (antes solo con cantidad==0), para activar el segundo intento.
- database_pg.py:
  * Tabla metadatos en Neon + CRUD (listar/obtener/crear/actualizar/eliminar).
  * inicializar_postgres crea también la tabla metadatos.

Comportamiento esperado:
1. Consultas tipo "remolque Mercantil Andina" ya no revienten por NameError.
2. Gemini debe consultar primero metadatos; si hay ficha, responde con ella.
3. Si metadatos = 0, sigue con manuales/PDFs.
4. En producción (DATABASE_URL) las fichas persisten entre redeploys de Render.

Pendiente / notas:
- Fichas cargadas solo en SQLite local NO se migran automáticamente a Neon.
  Volvé a cargar las fichas importantes una vez en producción, o migrá manualmente.
- PDFs escaneados (sin texto seleccionable) siguen sin OCR: hay que subir
  versión con texto o copiar el contenido a una ficha de metadatos.
- Excel no se modificó a propósito.
