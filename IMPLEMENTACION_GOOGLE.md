# OficinaIA — activación de Sheets, Gmail y mantenimiento

El código ya queda preparado para usar Google Sheets como fuente viva. Para que funcione en producción faltan únicamente credenciales/recursos externos, que no deben guardarse en Git.


## Orden recomendado para pasar a producción

1. Crear las dos planillas, compartirlas con la cuenta de servicio y cargar en el entorno local `GOOGLE_SHEETS_CREDENTIALS_JSON`, `SHEET_ID_ASEGURADOS` y `SHEET_ID_FLOTAS`.
2. Ejecutar **una sola vez** `python migrar_excel_a_sheets.py` y revisar visualmente que Asegurados y Flotas tengan encabezados/datos correctos.
3. Cargar esas mismas variables de Sheets en Render y desplegar esta versión. No desplegar primero y migrar después: desde esta versión Sheets es la única fuente activa.
4. Crear/configurar el Cron Job `python daily_maintenance.py` con las variables de Sheets y R2.
5. Configurar Gmail OAuth, generar el refresh token definitivo y cargar las variables `GMAIL_*` en Render. Gmail puede habilitarse después del deploy sin afectar Sheets ni Sofia.
6. Probar en producción, en este orden: `/notas` → alta de un asegurado → consulta inmediata a Sofia sobre ese alta → `/salud` → mail de prueba → respaldo diario manual con `python daily_maintenance.py`.

## 1. Google Sheets

1. En Google Cloud habilitar **Google Sheets API**.
2. Crear una **cuenta de servicio** y copiar su JSON completo en `GOOGLE_SHEETS_CREDENTIALS_JSON`.
3. Crear dos planillas y compartirlas como **Editor** con el mail de la cuenta de servicio.
4. Guardar sus IDs en `SHEET_ID_ASEGURADOS` y `SHEET_ID_FLOTAS`.
5. Para llevar el Excel actual a Sheets una única vez: `python migrar_excel_a_sheets.py`.
   - Migra `excel_interno.xlsx` al libro Asegurados.
   - Si `excel_flotas.xlsx` no existe (no viene en el ZIP limpio actual), inicializa el libro Flotas con sus encabezados compatibles con `/flota`.

Después de esto, `/notas`, las altas y Sofia leen la misma fuente. El `.xlsx` del repositorio deja de ser fuente activa.

## 2. Gmail

1. Habilitar **Gmail API** en Google Cloud.
2. Configurar la pantalla OAuth para la cuenta que va a enviar y crear un OAuth Client ID de tipo **Desktop app**.
3. Antes de generar el token definitivo de producción, pasar el proyecto OAuth a **In production**. En estado **Testing**, Google limita los refresh tokens a 7 días. Google puede solicitar pasos adicionales de verificación según los scopes/configuración del proyecto.
4. En una PC con navegador, definir `GMAIL_OAUTH_CLIENT_ID` y `GMAIL_OAUTH_CLIENT_SECRET` y ejecutar `python obtener_refresh_token.py`.
5. Guardar el token resultante como `GMAIL_OAUTH_REFRESH_TOKEN` y configurar `GMAIL_SENDER_EMAIL`.

El servidor no necesita abrir un navegador para enviar luego mientras el refresh token siga vigente y no sea revocado.

## 3. Respaldo diario y limpieza

Crear en Render un **Cron Job** con el mismo repositorio y variables de entorno:

- Comando: `python daily_maintenance.py`
- Horario recomendado: 03:00 de Argentina (06:00 UTC).

Ese job genera un XLSX por libro bajo `respaldo/`, conserva los últimos 30 y limpia eventos del panel Salud con más de 30 días.

## 4. Variables

Usar `.env.example` como lista. `.env` sigue ignorado por Git. Nunca subir JSON de cuenta de servicio, client secret ni refresh token al repositorio.
