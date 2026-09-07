# OficinaIA — validación de esta implementación

## Estado

Esta versión implementa la arquitectura del plan maestro sobre el ZIP limpio de GitHub.

### Bloque 1 — UI
- `base.html` carga un solo CSS global (`static/css/estilo.css`) y un solo JS global (`static/js/app.js`).
- `ui-clean.css` y `oficina_plus.js` fueron absorbidos/eliminados.
- Se eliminó el control numérico `-/+` de fuente y su `localStorage`; el tamaño base queda fijo en 16 px.
- Se eliminaron reglas muertas de `.font-controls` y SVG inline fuera de `_icons.html`.
- El chat usa layout de historial + conversación y compositor fijo.
- **Pendiente de comprobación visual en navegador real:** el CSS conserva la cascada efectiva del proyecto. No se hizo una deduplicación automática agresiva de selectores contradictorios porque podría alterar pantallas sin una prueba visual completa.

### Bloque 2 — Google Sheets
- Google Sheets es la fuente viva para Asegurados y Flotas.
- `/notas`, altas y Sofia usan la misma fuente.
- Las altas agregan filas con `append`; las ediciones completas usan `batchUpdate`.
- El XLSX local queda únicamente como fuente para la migración inicial, no para ejecución normal.
- Script `migrar_excel_a_sheets.py` incluido. Si `excel_flotas.xlsx` no existe, inicializa los encabezados de Flotas.
- Respaldo diario Sheets -> XLSX -> R2 con retención de 30 copias.

### Bloque 3 — adjuntos y canales
- Chat: PDF, TXT, PNG, JPG/JPEG y WEBP bajo un modelo común `Adjunto`.
- Imágenes se entregan a Gemini como contenido multimodal, sin OCR previo.
- Comandos `/mail` y `/whatsapp` usan una interfaz común de canal.
- Lenguaje natural puede invocar `enviar_por_canal` mediante function calling.
- El adjunto del turno actual puede enviarse normalmente. El del turno anterior sólo se reutiliza ante una referencia explícita del usuario; nunca se hereda automáticamente en un mail nuevo.
- WhatsApp queda deliberadamente como canal no configurado hasta resolver Meta Cloud API.

### Bloque 4 — Salud del sistema
- Tabla `eventos_sistema` en PostgreSQL y SQLite local.
- Ruta `/salud` restringida a admin, filtros por categoría/nivel y contador de errores IA de 24 h.
- Errores relevantes de IA, Sheets y mail se registran sin exponer detalle técnico al usuario.
- Limpieza automática de eventos de más de 30 días en el mantenimiento diario.

### Bloque 5 — Gmail
- `MailChannel` usa Gmail API + OAuth 2.0 con refresh token.
- Script `obtener_refresh_token.py` incluido.
- Credenciales sólo por variables de entorno.
- Fallos de envío no rompen el chat y quedan registrados en Salud.

## Correcciones adicionales detectadas durante la integración
- Se corrigió una llamada inexistente de `app.py` al armar el texto de Envíos Ya después de un alta.
- Se corrigió una referencia huérfana `buscar_cliente_exactamente` en `servicios_ia.py`.
- Se agregó el import faltante de `unicodedata` en `flota_ops.py`.
- Un PDF adjunto para reenviar por mail/WhatsApp ya no es secuestrado por la detección automática de `/alta`.
- Una caída de Google Sheets ya no se transforma en un dataset vacío que pueda hacer que Sofia responda falsamente “0 resultados”.

## Validaciones ejecutadas en este entorno
- `python -m compileall -q .` -> OK.
- `node --check static/js/app.js` -> OK.
- Parseo Jinja -> 15 templates OK.
- Parseo CSS con `tinycss2` -> OK.
- Validación de imports locales `from ... import ...` -> OK.
- Escaneo de referencias eliminadas (`ui-clean.css`, `oficina_plus.js`, font +/- y antiguo camino XLSX/R2 de Sofia) -> OK.
- Prueba aislada de `ExcelRecordService` con persistencia simulada -> Asegurados y Flotas hacen append correctamente.
- Prueba simulada del servicio Google Sheets -> lectura/escritura/append OK durante el desarrollo.
- Prueba simulada del despacho -> búsqueda de destinatario + envío por canal OK durante el desarrollo.
- Prueba simulada de enrutado de PDF -> envío no activa `/alta`; análisis normal sí puede hacerlo.
- Prueba simulada del respaldo -> genera ambos XLSX y poda a 30 copias.

## Ajuste visual posterior — ventana de Chat IA

- Se corrigió el desborde vertical que nacía de combinar `main{padding-top:48px}` con un `chat-shell` de casi `100dvh`.
- El sidebar sigue siendo independiente; no se unió al chat ni se convirtió la interfaz en una superficie de borde a borde.
- Chat + conversaciones ahora viven dentro de una única ventana flotante con margen visible arriba, abajo y a los costados.
- Se recuperó una barra superior propia de esa ventana; fecha, tema, configuración y cierre de sesión quedan alineados visualmente dentro de ella.
- El historial de conversaciones se puede ocultar/mostrar en escritorio. Al ocultarlo, Sofia ocupa el espacio liberado sin mover la ventana.
- La preferencia queda guardada en `localStorage` (`oficinaia_chat_list`) y se aplica antes del render para evitar parpadeos.
- En móvil se conserva el sheet de conversaciones existente; el plegado de escritorio no reemplaza ese comportamiento.

## Límite de la validación local

Este entorno no tiene instalados Flask, `google-api-python-client`, `google-auth`, `google-genai` ni `psycopg2`, y no tiene salida a PyPI. Por eso **no se pudo levantar el servidor completo ni conectar realmente con Google/R2 desde acá**. Las dependencias necesarias ya están declaradas en `requirements.txt` para Render.

Antes de reemplazar producción, seguir `IMPLEMENTACION_GOOGLE.md` y probar con credenciales reales en este orden: `/notas` -> alta -> consulta inmediata a Sofia -> `/salud` -> mail de prueba -> mantenimiento diario.

- El menú de comandos del chat expone `/mail` con la plantilla `/mail destinatario@correo.com asunto Asunto mensaje Mensaje`; las conversaciones de correo se identifican como `Mail` en el historial.

- `/mail` permite indicar asunto explícito con separadores `|`; el formato anterior sin asunto sigue usando `San José Seguros` como valor predeterminado.


## Ajuste visual — icono Chat IA

- `Chat IA` usa ahora un icono propio de burbuja de conversación + spark mediante `_icons.html`.
- El favicon queda reservado para la marca Oficina/Sofia y ya no se reutiliza en la entrada de navegación `Chat IA`.

## Corrección /mail y conteos exactos

- `/mail` acepta `asunto` o `titulo/título` como delimitador de asunto, seguido por `mensaje`: `/mail correo asunto Mi asunto mensaje Mi texto`.
- Se mantiene compatibilidad con `/mail correo | Asunto | Mensaje` y con el formato viejo sin asunto explícito, que usa `San José Seguros`.
- La analítica vehicular calcula y expone `autos_motos_total` en Python.
- Las consultas simples de autos/motos/vehículos se responden directamente desde el resultado determinístico, sin volver a delegar sumas a Gemini.

## Remodelación alta individual desde póliza

Última pasada:

- El número de póliza fue eliminado del contrato de extracción de `/alta`.
- `NUMERO` (teléfono histórico de la planilla) y `TELEFONO` quedan vacíos al leer un PDF; el teléfono se completa manualmente en la ficha.
- Medio de pago se normaliza exclusivamente a `CUPONERA`, `CBU` o `CREDITO`.
- Se agregaron fallbacks determinísticos para etiquetas claras de forma de pago, fecha de emisión y premio/precio.
- `EMITIDO DÍA:` e `IMPORTE APROX` viajan en el guardado real al Excel/Sheets.
- La confirmación de alta se reemplazó por una ficha compacta con datos principales, teléfono manual y acciones `Guardar en Excel`, `Editar` y `Tabulado`.
- El tabulado se abre al final de la misma ficha y se genera con los valores actuales, incluidas correcciones manuales.
- Después de guardar no se agrega automáticamente otro bloque largo de Envíos Ya; queda disponible como acción dentro de la misma ficha.
- `Envíos Ya` acepta como teléfono tanto `TELEFONO` como el histórico `NUMERO` para conservar compatibilidad con registros existentes.

Validaciones ejecutadas:

- `python -m py_compile` sobre todos los módulos Python: OK.
- `node --check static/js/app.js`: OK.
- Parseo Jinja de 15 templates: OK.
- Balance de llaves CSS: OK.
- Pruebas de normalización de medios de pago: CUPONERA / CBU / CREDITO: OK.
- Prueba de fallback de PDF: tarjeta de crédito + fecha de emisión + premio argentino: OK.
- Prueba de mapeo de fila Excel: teléfono manual en NUMERO, medio de pago, emisión y precio en sus columnas reales: OK.
