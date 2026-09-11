# Variables de entorno de OficinaIA

Este archivo documenta **nombres reales usados por el proyecto**. No debe contener valores, secretos ni credenciales.

## Obligatorias / principales en producción

- `FLASK_SECRET_KEY` — clave de sesión de Flask. En Render debe existir y no usar el valor de desarrollo.
- `DATABASE_URL` — conexión PostgreSQL/Neon usada por la persistencia de producción.
- `GEMINI_API_KEY` — acceso a Gemini para el asistente y análisis multimodal.
- `SHEET_ID_ASEGURADOS` — ID de la planilla Google Sheets de Asegurados.
- `GOOGLE_SHEETS_CREDENTIALS_JSON` — credencial JSON de cuenta de servicio para Google Sheets.

## Flotas / Google Sheets

- `SHEET_ID_FLOTAS` — ID de la planilla de Flotas.

## Correo Gmail OAuth

- `GMAIL_SENDER_EMAIL`
- `GMAIL_OAUTH_CLIENT_ID`
- `GMAIL_OAUTH_CLIENT_SECRET`
- `GMAIL_OAUTH_REFRESH_TOKEN`

## Cloudflare R2

- `R2_ENDPOINT_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`

## Administración / arranque

- `ADMIN_INITIAL_PASSWORD` — contraseña inicial usada únicamente para crear el administrador cuando corresponde.
- `RENDER` — indicador provisto por el entorno de Render; OficinaIA no lo define manualmente.

## Ajustes de Gemini ya soportados

- `GEMINI_HTTP_TIMEOUT_MS`
- `GEMINI_REQUEST_BUDGET_SECONDS`
- `GEMINI_MIN_REMAINING_SECONDS`
- `GEMINI_DOCUMENT_BUDGET_SECONDS`

## Ajustes de búsqueda documental ya soportados

- `MANUALES_MAX_CANDIDATOS_GENERAL`
- `MANUALES_MAX_CANDIDATOS_CIA`
- `MANUALES_MAX_ARCHIVOS_CON_CIA`
- `MANUALES_MAX_ARCHIVOS_GENERAL`

### Regla de seguridad

Los valores se cargan desde el entorno del proceso. En Render, `runtime_config.py` **no carga `.env`** y usa exclusivamente el entorno que recibió el proceso al arrancar. En desarrollo local puede completar variables desde `.env`, siempre con `override=False`.
