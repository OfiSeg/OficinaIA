# ETAPA 4 — Documentos múltiples, extractores ampliados y truncamiento seguro

Base: `OficinaIA_ETAPA3_FRONTEND_RESILIENCIA.zip`.

## Objetivo

Preservar el buen comportamiento actual de análisis de múltiples documentos, pero evitar inconsistencias cuando el lote contiene varias imágenes/PDFs y mejorar la información disponible para cédulas y licencias sin convertir el flujo en un refactor general.

## Cambios realizados

### 1. Truncamiento multimodal explícito

- Se agregó `RenderizacionMultiple` y `renderizar_varios_para_vision_con_reporte()` en `attachment_vision.py`.
- La función histórica `renderizar_varios_para_vision()` sigue existiendo y mantiene compatibilidad devolviendo sólo `list[MediaBlob]`.
- Cuando un lote supera los límites visuales internos, el sistema puede saber que hubo truncamiento y no queda obligado a fingir que revisó todo.
- `servicios_ia.py` ahora incorpora advertencias explícitas al prompt cuando parte del contenido visual no fue enviada a Gemini.
- Se registra evento `MULTIMODAL_TRUNCATED` en Salud/logs cuando corresponde, sin romper el chat si el logging falla.

### 2. Plan conservador de documentos múltiples

- Se agregó `DocumentoAgrupado`, `MultiDocumentPlan`, `planificar_coleccion()` y `resumen_coleccion_para_prompt()` en `document_grouping.py`.
- El plan no fusiona documentos por intuición.
- Frente/dorso se trata como candidato, no como certeza.
- El prompt general recibe instrucciones para:
  - separar por documento real detectado;
  - combinar frente/dorso sólo si el contenido lo confirma;
  - indicar `solo frente`, `solo dorso` o `cara no confirmada` cuando corresponda;
  - incluir estados `Verificado`, `Revisar` o `Lectura parcial` cuando aplique;
  - no decir que revisó todo si hubo truncamiento visual.

### 3. Extractor de cédulas ampliado

- `cedula_ops.py` ahora contempla también, cuando estén impresos:
  - uso;
  - vencimiento;
  - control;
  - número de cédula.
- No se inventan estos campos: sólo se muestran si el modelo los leyó.
- La UI de cédula puede mostrar esos datos como información operativa adicional.
- La copia de “todos los datos” también los incluye si existen y los campos críticos están listos.

### 4. Extractor de licencia/DNI ampliado

- `personal_document_ops.py` ahora contempla en la lectura general:
  - otorgamiento;
  - vencimiento;
  - clases;
  - observaciones/restricciones.
- DNI, fecha de nacimiento y CUIL mantienen la validación estricta de múltiples lecturas.
- Los nuevos campos de licencia son informativos: se copian sólo si están visibles, no se calculan ni se completan por conocimiento externo.
- La UI puede mostrar `OTORGAMIENTO`, `VENCIMIENTO`, `CLASES` y `OBSERVACIONES`.

### 5. Presentación actual preservada

- No se reemplazó la respuesta textual natural de documentos múltiples por una grilla obligatoria.
- No se forzó el flujo general de 3+ documentos a pasar por múltiples extractores especializados que podrían multiplicar llamadas Gemini y romper latencia.
- La idea es conservar el buen resultado actual y sumar reglas de seguridad/observabilidad.

## Validaciones ejecutadas

- `VALIDACION_ADJUNTOS_MULTIPLES.py` → 12/12 OK
- `VALIDACION_ETAPA1_CEDULA_PRODUCTOR.py` → 7/7 OK
- `VALIDACION_ETAPA2_CONTEXTO_CARTERA.py` → 8/8 OK
- `VALIDACION_ETAPA3_FRONTEND_RESILIENCIA.py` → 8/8 OK
- `VALIDACION_ETAPA4_DOCUMENTOS_MULTIPLES.py` → 7/7 OK
- `VALIDACION_RESILIENCIA_GLOBAL.py` → 12/12 OK
- `VALIDACION_SALUD_SERVICIOS.py` → 7/7 OK
- `VALIDACION_V20_DNI_LICENCIA.py` → 13/13 OK
- `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py` → 11/11 OK
- `python -m compileall -q .` → OK
- `node --check static/js/app.js` → OK

## Nota

No se implementó ARCA en esta etapa. Sigue quedando para una etapa propia.
