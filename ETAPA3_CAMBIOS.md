# ETAPA 3 — Frontend, cache y observabilidad de IA

Base utilizada: `OficinaIA_ETAPA2_CONTEXTO_CARTERA_FECHA.zip`.

## Objetivo

Corregir los problemas de frontend y observabilidad acordados para la Etapa 3 sin tocar la lógica funcional de Gemini/reintentos que ya estaba funcionando.

## Cambios implementados

### Frontend del chat

- El textarea del chat se limpia sólo después de una respuesta aceptada/procesada.
- Se captura un snapshot del texto enviado.
- Si el usuario escribe un mensaje nuevo mientras el asistente está respondiendo, ese borrador nuevo no se borra cuando termina la respuesta anterior.
- Los adjuntos enviados se retiran de la bandeja pendiente sólo cuando la operación fue exitosa.
- Si el usuario agrega adjuntos nuevos mientras el request anterior está en curso, esos adjuntos nuevos no se eliminan al finalizar la respuesta anterior.
- Se reemplazó el borrado global de adjuntos por eliminación de los objetos enviados en ese request.
- Se mantuvo la conservación de texto/adjuntos ante errores de red o servidor.

### Cache busting automático

- Se agregó `static_asset(filename)` en Flask.
- Los assets locales críticos usan una versión automática basada en `mtime` del archivo.
- Se eliminaron versiones manuales olvidables en templates para CSS/JS locales.
- Si se modifica `static/js/app.js`, `static/css/estilo.css`, `static/js/estudio.js`, `static/js/salud.js`, `static/js/envios_masivos.js` o `static/css/login.css`, el navegador recibe una URL versionada nueva.

### Observabilidad de IA

- No se modificó el número de intentos.
- No se modificó el backoff actual.
- No se eliminaron fallbacks de modelos.
- No se aplicaron reintentos a escrituras ni acciones con efectos secundarios.
- Se agregó correlación conceptual por `request_id` y `sequence_id` para distinguir secuencias de IA dentro de un mismo request.
- Los retries recuperados registran explícitamente `AI_RECOVERED`.
- Los agotamientos reales registran explícitamente `AI_RETRIES_EXHAUSTED`.
- Los fallos no recuperables registran `AI_FINAL_FAILURE` sin mentir que agotaron 3/3.
- Los cortes por presupuesto/deadline registran `AI_BUDGET_EXHAUSTED`.
- Los modelos no disponibles registran `AI_MODEL_UNAVAILABLE` cuando corresponde.
- El detalle técnico intenta incluir `status`, `motivo`, `modelo`, `intento`, `duración` y `secuencia` sólo cuando esos datos están disponibles.
- No se loguean prompts completos, documentos completos, respuestas completas ni credenciales.
- El logging de Salud sigue siendo defensivo: si falla, no rompe el flujo principal.

### Limpieza textual visible

- Se reemplazó el evento visible “Sofia no pudo responder” por “No se pudo responder”.
- Se actualizaron comentarios visibles del JS para no arrastrar el nombre del asistente en textos servidos innecesariamente.

## Archivos modificados

- `app.py`
- `ai_gateway.py`
- `resilience.py`
- `static/js/app.js`
- `templates/base.html`
- `templates/estudio.html`
- `templates/salud.html`
- `templates/envios_masivos.html`
- `templates/login.html`
- `VALIDACION_ADJUNTOS_MULTIPLES.py`
- `VALIDACION_ETAPA2_CONTEXTO_CARTERA.py`

## Archivos creados

- `VALIDACION_ETAPA3_FRONTEND_RESILIENCIA.py`
- `ETAPA3_CAMBIOS.md`

## Validaciones ejecutadas

- `VALIDACION_ADJUNTOS_MULTIPLES.py` → 12/12 OK
- `VALIDACION_ETAPA1_CEDULA_PRODUCTOR.py` → 7/7 OK
- `VALIDACION_ETAPA2_CONTEXTO_CARTERA.py` → 8/8 OK
- `VALIDACION_ETAPA3_FRONTEND_RESILIENCIA.py` → 8/8 OK
- `VALIDACION_RESILIENCIA_GLOBAL.py` → 12/12 OK
- `VALIDACION_SALUD_SERVICIOS.py` → 7/7 OK
- `VALIDACION_V20_DNI_LICENCIA.py` → 13/13 OK
- `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py` → 11/11 OK
- `python -m compileall -q .` → OK
- `node --check static/js/app.js` → OK

## Qué NO se tocó

- No se incorporó ARCA.
- No se modificó la lógica funcional de lectura documental.
- No se modificó la cantidad de reintentos de Gemini.
- No se cambiaron tiempos de espera ni backoff.
- No se agregaron reintentos sobre mails, guardados, Excel, altas ni otras escrituras.
- No se cambió la UI general del chat fuera del comportamiento de composer/cache.
