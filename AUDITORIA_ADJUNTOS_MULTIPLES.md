# Auditoría — Adjuntos múltiples end-to-end

Base: `OficinaIA_GITHUB_DEFINITIVA_RESILIENCIA_GLOBAL.zip`

## Causa raíz encontrada

El backend ya utilizaba `request.files.getlist("archivo")`, pero el compositor del chat no era realmente acumulativo:

1. El listener `change` del selector llamaba a `validarYAdjuntarArchivos(..., {reemplazar:true})`.
2. Drag & drop hacía lo mismo, por lo que cada nueva selección reemplazaba el estado previo.
3. La vista previa era una única pastilla con todos los nombres concatenados y sólo permitía borrar toda la colección.
4. `enviarMensaje()` limpiaba los adjuntos antes de conocer el resultado del request, de modo que un fallo previo al procesamiento obligaba a seleccionarlos otra vez.
5. Aunque Flask recibiera varios archivos, el fallback general de Sofia terminaba recibiendo sólo `adjunto_actual` (el primero) en `chat_ai -> servicios_ia`.
6. Los handlers especializados podían seleccionar un solo documento de una colección mixta. Ahora, cuando eso implicaría descartar archivos, el turno continúa por el análisis general multimodal con la colección completa.

Por eso el problema no era una sola línea visual: había discontinuidad entre estado de frontend, preview, ciclo de envío y payload multimodal.

## Cambios realizados

### `static/js/app.js`
- El estado `archivosAdjuntosChat` es acumulativo entre aperturas sucesivas del selector.
- Selector, drag & drop y Ctrl+V agregan archivos en vez de reemplazar los anteriores.
- Hasta 5 adjuntos por mensaje y 40 MB totales.
- Deduplicación prudente usando nombre + tamaño + fecha de modificación + MIME; no sólo nombre.
- Cada archivo tiene eliminación individual.
- Todos los archivos se agregan al mismo `FormData` conservando el orden.
- Los adjuntos no se limpian antes del `fetch`; se limpian sólo tras una respuesta HTTP válida de OficinaIA.
- Si el request falla, los archivos continúan en el compositor.
- El mensaje enviado representa todos los archivos y usa plural cuando corresponde.

### `templates/documentos.html`
- El preview único fue reemplazado por una lista interna de adjuntos dentro del componente visual existente.
- Se mantuvo `multiple` en el input.
- El overlay de drag & drop ahora usa texto plural.

### `static/css/estilo.css`
- Estilos mínimos para múltiples adjuntos reutilizando variables y estética actual.
- Soporte claro/oscuro y responsive.

### `chat_request.py`
- `parse_incoming()` ya preservaba `getlist("archivo")`; se conserva.
- `extract_attachments()` ahora admite hasta 5 archivos, conserva orden y valida 40 MB totales.
- Se mantiene la validación individual existente de extensión, firma y tamaño.

### `app.py`
- Límite HTTP global ajustado a 45 MB para permitir hasta 40 MB reales de adjuntos más overhead multipart.
- `/api/chat` procesa hasta 5 archivos y 40 MB totales.
- La colección completa se entrega al tramo general de Sofia.

### `chat_ai.py` / `servicios_ia.py`
- Se agregó soporte compatible para `adjuntos` sin romper callers históricos de `adjunto` único.
- Las imágenes del mismo mensaje se incluyen en un único payload multimodal.
- PDFs escaneados sin texto se renderizan y también se agregan al payload.
- PDFs digitales/TXT siguen aportando su contenido mediante el contexto textual existente.
- La colección `contents` completa es la misma que reutiliza `ai_gateway` en retries automáticos.

### `chat_special.py` / `document_grouping.py`
- Frente+dorso de DNI/licencia/cédula sigue usando el pipeline especializado de dos caras.
- Colecciones mayores a dos no se recortan a dos ni disparan una clasificación costosa por cada archivo: siguen al análisis general multimodal.
- Si dos archivos son de tipos distintos y un handler especializado consumiría sólo uno, se evita ese handler para no descartar el otro.
- El rescate de cédula individual sigue siendo individual y no secuestra colecciones múltiples.

## Invariantes resultantes

Para el chat:

`seleccionados = visibles = enviados = recibidos por Flask`

Para adjuntos visuales que llegan al flujo general:

`recibidos = incluidos en el payload multimodal`, dentro del límite seguro de medios configurado.

Frente+dorso compatible continúa analizándose como una única operación documental.

## Límites

- Máximo 5 archivos por mensaje.
- Máximo 40 MB acumulados por mensaje.
- Límites individuales existentes: PDF 20 MB, imagen 15 MB, TXT 2 MB.
- El análisis general limita los medios visuales renderizados a 8 partes para no exceder innecesariamente límites/latencia del proveedor. Cinco imágenes directas entran completas; PDFs escaneados multipágina comparten ese presupuesto visual.
- Los extractores especializados frente/dorso continúan diseñados para dos caras, que es su contrato funcional.

## Pruebas ejecutadas

- `VALIDACION_ADJUNTOS_MULTIPLES.py`: 12/12 grupos OK.
- `VALIDACION_RESILIENCIA_GLOBAL.py`: 12/12 grupos OK.
- `VALIDACION_SALUD_SERVICIOS.py`: 7/7 grupos OK.
- `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py`: 11/11 grupos OK.
- `VALIDACION_V20_DNI_LICENCIA.py`: 13/13 grupos OK.
- `python -m compileall -q .`: OK.
- `node --check static/js/app.js`: OK.

Total de grupos de validación funcional: 55/55.

## Prueba manual recomendada después del deploy

1. Adjuntar `dni_frente.jpg`.
2. Volver a abrir el clip y adjuntar `dni_dorso.jpg`.
3. Confirmar que ambos siguen visibles.
4. Eliminar sólo uno y verificar que el otro permanezca.
5. Volver a adjuntarlo y enviar una sola vez.
6. Confirmar que OficinaIA devuelve un único resultado DNI usando ambas caras.
7. Repetir con tres archivos genéricos y confirmar que los tres aparecen en el compositor y en el mensaje enviado.
8. Simular/observar un fallo transitorio: los retries de Gemini reutilizan el mismo conjunto y el usuario no debe volver a seleccionar archivos.

No se requieren variables nuevas de Render ni dependencias adicionales. Sí requiere deploy del código actualizado.
