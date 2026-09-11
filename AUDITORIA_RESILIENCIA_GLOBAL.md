# Auditoría — Resiliencia global de lecturas

Base: `OficinaIA_GITHUB_DEFINITIVA_DNI_LICENCIA.zip`.

## Diagnóstico previo

- Las llamadas reales a Gemini ya convergían en `ai_gateway.generate_with_fallback`, pero esa capa hacía fallback de modelo y no una política uniforme de hasta 3 intentos transitorios.
- `cedula_ops.py` y `personal_document_ops.py` tenían retries propios de 2 intentos, lo que duplicaba política y podía multiplicar llamadas al combinarse con el gateway.
- `estudio_ops.py` utilizaba el gateway pero una salida JSON defectuosa terminaba el caso como incompleto sin una recuperación global.
- Los parsers JSON estaban repetidos entre alta, cédula, DNI/licencia, Estudio y otros lectores.
- Google Sheets ya tenía retry seguro para lecturas, pero con una implementación separada.
- Las descargas de R2 usadas por búsquedas/manuales/Estudio no reintentaban una caída temporal.
- Los adjuntos del chat ya se convierten a `bytes` (`Adjunto.datos_binarios`) antes del análisis. Por eso pueden reutilizarse internamente en un retry sin volver a pedir el archivo ni depender del stream HTTP original.
- Mail, escrituras de Sheets/Excel, guardados y demás acciones con efectos reales no pasan por la nueva política global.

## Implementación

### `resilience.py` (nuevo)
Capa reutilizable para operaciones idempotentes de lectura:

- máximo 3 intentos;
- backoff corto;
- clasificación de 408/429/5xx/timeouts/conexiones como transitorios;
- errores permanentes fallan rápido;
- logging sanitizado de intento/proveedor/resultado;
- `parse_json_object()` recupera JSON con markdown, texto alrededor, trailing commas o comillas simples sin inventar campos;
- no existe API de retry global para escrituras/acciones.

### `ai_gateway.py`
Gemini ahora absorbe fallos transitorios de manera central:

- máximo 3 llamadas totales por operación;
- alterna modelos configurados sin exceder ese máximo;
- reutiliza exactamente `contents` en cada intento;
- 401/403/API key inválida fallan rápido;
- 404/modelo no disponible permite fallback al modelo restante;
- 429/500/502/503/504/timeouts se reintentan con espera corta;
- respuesta vacía y salida truncada se consideran recuperables;
- `response_validator` permite que JSON estructuralmente inválido consuma el mismo presupuesto de retries en vez de crear loops locales adicionales;
- se mantiene el presupuesto por request para no competir con el timeout de Gunicorn/Render.

### Lectores estructurados
`alta_ops.py`, `cedula_ops.py`, `personal_document_ops.py`, `document_classifier.py`, `estudio_ops.py`, `flota_ops.py` y el fallback de mapeo de `envios_masivos.py` validan la salida estructurada dentro del gateway. Cédula y documentos personales ya no mantienen un segundo loop propio de fallos transitorios.

### Google Sheets
`google_sheets_service.py` reutiliza la capa común para `read` y conserva sus códigos específicos. Las escrituras siguen ejecutándose una sola vez por defecto para evitar append/clear duplicados.

### R2
`storage_r2.py` aplica retry únicamente a GET/descarga de objetos. Subir, borrar y escribir respaldos mantienen su comportamiento separado.

### PostgreSQL
`database_pg.conectar_pg()` reintenta únicamente el establecimiento de conexión cuando el fallo parece transitorio. No reintenta transacciones ni sentencias de escritura.

## Operaciones deliberadamente excluidas

No se agregó retry global a:

- mail;
- WhatsApp/envíos;
- Guardar en Excel;
- append/clear/update de Google Sheets;
- altas/guardados persistentes;
- bajas;
- eliminaciones;
- emisiones;
- cambios de estado;
- subidas o borrados de R2.

Esto evita duplicados cuando el proveedor hubiera procesado la acción pero la respuesta se perdiera por timeout.

## Archivos nuevos

- `resilience.py`
- `VALIDACION_RESILIENCIA_GLOBAL.py`
- `AUDITORIA_RESILIENCIA_GLOBAL.md`

## Archivos modificados

- `ai_gateway.py`
- `alta_ops.py`
- `cedula_ops.py`
- `database_pg.py`
- `document_classifier.py`
- `envios_masivos.py`
- `estudio_ops.py`
- `flota_ops.py`
- `google_sheets_service.py`
- `personal_document_ops.py`
- `storage_r2.py`

No se modificó `app.py`, templates, CSS ni JavaScript: esta etapa no rediseña OficinaIA.

## Validaciones ejecutadas

- `VALIDACION_SALUD_SERVICIOS.py`: 7 grupos OK.
- `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py`: 11 grupos OK.
- `VALIDACION_V20_DNI_LICENCIA.py`: 13 grupos OK.
- `VALIDACION_RESILIENCIA_GLOBAL.py`: 12 grupos OK.
- Total: 43 grupos OK.
- `python -m py_compile *.py`: OK.
- `python -m compileall`: OK.
- sintaxis JavaScript principal: OK.

La nueva validación comprueba, entre otros casos:

- primer Gemini 503 y segundo intento exitoso;
- reutilización del mismo objeto `contents`;
- tres fallos -> un error final;
- API key/401 -> fail-fast;
- respuesta vacía -> retry;
- respuesta truncada -> retry;
- JSON menor reparable localmente;
- JSON irrecuperable -> retry controlado;
- lectura genérica transitoria -> recuperación;
- error permanente -> sin intentos inútiles;
- inexistencia de un retry global de escritura;
- mail fuera de la política;
- lectores estructurados conectados al validador central.

## Prueba real pendiente

Este entorno no dispone de las credenciales productivas de Gemini/Sheets/R2/Neon. Después del deploy conviene provocar o esperar un fallo transitorio real y confirmar en Render Logs que aparece `attempt=...` y que el usuario recibe sólo el resultado final si alguno de los tres intentos funciona.

No hace falta cambiar variables de Render para esta etapa. Sí hace falta un deploy normal para ejecutar el código nuevo.
