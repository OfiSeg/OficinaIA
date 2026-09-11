# Auditoría — Salud → Servicios / robustez de dependencias

## Base

Implementación realizada sobre `OficinaIA_GITHUB_DEFINITIVA_CEDULA_ENVIOSYA.zip`, preservando cédulas, pólizas, Envíos Ya, Estudio, login, Pendientes y navegación principal.

## Causa raíz investigada

Se encontraron dos hechos distintos que conviene separar:

1. **Render entrega las variables de entorno al proceso al arrancar.** Un proceso que ya está ejecutándose no puede descubrir por sí solo un cambio posterior realizado en el panel de Environment. Por eso un restart/deploy hace visible la configuración al nuevo proceso. La aplicación no puede “recargar” secretos del panel de Render sin reiniciar el proceso.
2. En la base original, `load_dotenv()` se ejecutaba dentro de `app.py` **después de importar numerosos módulos locales**. Eso hacía que el comentario “cargar dotenv antes de leer env” no fuera realmente cierto para desarrollo local y dejaba abierta la posibilidad de que módulos con lecturas al importar vieran un entorno distinto.

No se encontró evidencia de que `SHEET_ID_ASEGURADOS` estuviera cacheado como valor fijo en la ruta normal: `excel_books.py` ya lo leía en tiempo de ejecución. El problema no se corrigió con un segundo `os.getenv()` ni con un fallback inventado.

## Corrección estructural

- Se agregó `runtime_config.py` como punto mínimo y común para interpretar el entorno.
- En Render no se carga `.env`; en local se usa `override=False`.
- `app.py` importa esta capa antes de módulos locales, haciendo determinista el orden de carga.
- Google Sheets, Gemini, Gmail, R2 y PostgreSQL consumen la misma interpretación de configuración en las piezas modificadas.
- Los IDs de Sheets se siguen leyendo en tiempo de ejecución; no se guardan secretos ni IDs en frontend.
- Google Sheets ahora diferencia missing / empty / credenciales inválidas / 401 / 403 / 404 / 429 / timeout / 5xx.
- Las lecturas de Sheets pueden reintentarse hasta 3 veces ante fallos transitorios. Las escrituras no se reintentan automáticamente para evitar duplicar filas tras un timeout ambiguo.
- Sofia conserva la causa de una caída de Sheets y no transforma una fuente interna indisponible en un conjunto vacío que pueda terminar en un conteo falso.

## Salud → Servicios

Se mantuvo la sección principal `Salud` y se agregó **Servicios como vista interna**, junto a Eventos. No se agregó una entrada nueva al sidebar.

Servicios diagnostica únicamente dependencias reales encontradas en el proyecto:

- Google Sheets
- Gemini
- Correo Gmail
- Excel local de referencia
- Base de datos (PostgreSQL o SQLite local)
- Cloudflare R2

El endpoint `/api/system/health` está protegido con `@requiere_admin`.

Los checks son de sólo lectura. No envían correos, no escriben Sheets, no modifican Excel y no ejecutan prompts de Gemini. El chequeo de Gemini consulta metadata del modelo y no genera contenido.

Los resultados se cachean brevemente para evitar comprobaciones constantes y el botón **Comprobar servicios** fuerza una actualización.

## Logging

`eventos_sistema` admite un `codigo` opcional para conservar causa raíz. La migración es compatible con PostgreSQL y SQLite. El registrador mantiene fallback para bases todavía no migradas y aplica redacción defensiva de secretos conocidos.

## Archivos nuevos

- `runtime_config.py`
- `service_diagnostics.py`
- `static/js/salud.js`
- `ENVIRONMENT_VARIABLES.md`
- `VALIDACION_SALUD_SERVICIOS.py`
- `AUDITORIA_SALUD_SERVICIOS.md`

## Archivos modificados

- `app.py`
- `excel_books.py`
- `google_sheets_service.py`
- `ai_gateway.py`
- `mail_service.py`
- `database_pg.py`
- `storage_r2.py`
- `system_health.py`
- `servicios_ia.py`
- `templates/salud.html`
- `static/css/estilo.css`

## Pendientes

No se cambió su almacenamiento. El código real usa PostgreSQL cuando existe `DATABASE_URL` y SQLite local cuando no; por lo tanto su dependencia operativa queda cubierta por el diagnóstico de Base de datos.

## Render

No existe `render.yaml` en esta base, por lo que no había Blueprint/config declarativa que corregir.

Después de subir esta versión hace falta **un deploy/restart normal** para que el proceso nuevo reciba las variables actuales de Render. No hace falta volver a copiar variables que ya estén correctamente guardadas.

Si una variable se modifica en Render en el futuro, seguirá siendo necesario que Render reinicie/recree el proceso: eso es parte del modelo de entorno de procesos, no un fallo que Flask pueda evitar desde dentro.
