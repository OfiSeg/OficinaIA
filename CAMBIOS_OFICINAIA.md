# OficinaIA — retoque conservador

Cambios aplicados sobre la base existente:

- Se conserva la arquitectura Flask, rutas, base SQLite, PDFs, pólizas, Excel, Word, usuarios y Gemini.
- Las filas nuevas vacías del Excel ya no se eliminan durante el guardado automático.
- La eliminación de filas vacías queda como acción explícita.
- Se incorpora eliminación explícita de columnas completamente vacías.
- Se agregan colores personalizables en Configuración y persistencia en `configuracion.json`.
- Se pulieron sidebar, tipografía, espaciados, chat, botones y responsive mediante overrides CSS.
- Se eliminaron frases de marketing de la navegación/chat.
- Gemini busca también en todo el Excel interno, además de Google Sheets y PDFs.
- Las búsquedas por patente/número se restringen a los registros que contienen ese identificador para evitar mezclar pólizas.
- Se mantienen búsquedas completas por cliente cuando la consulta identifica inequívocamente al cliente.
- Gemini recibe instrucciones reforzadas para diferenciar fuentes, no inventar y citar documentos/páginas.
- Se agregó grounding con Google Search para consultas que piden o requieren información pública/actual; Internet complementa los datos internos.
- No se reemplazaron componentes funcionales ni se reconstruyó la aplicación desde cero.

## Mejora de Gemini — recuperación y respuestas (2026-08-17)

- La recuperación de PDFs prioriza los fragmentos con mayor relevancia y limita a un máximo de 2 documentos distintos por consulta.
- Un mismo documento puede aportar varios fragmentos cuando la consulta necesita contexto distribuido.
- Las consultas complejas pueden recuperar más fragmentos del mismo documento; las simples recuperan menos.
- La selección final de contexto compite entre Excel interno, Excel externo y documentos, buscando 1 fuente cuando alcanza y 2 sólo cuando aportan valor real.
- El prompt de Gemini ahora exige cubrir todos los puntos de una pregunta compleja, evitar registros ajenos, no inventar y citar sólo las fuentes realmente utilizadas.
- `max_output_tokens` aumentó de 1400 a 4096 para evitar cortes prematuros de respuestas válidas, sin pedir respuestas largas por defecto.


## Corrección adicional 2026-08-18 — consultas documentales sin Gemini
- Se corrigió `consultar_gemini()` para que la ausencia de `GEMINI_API_KEY` no transforme una consulta de remolque/asistencia en un resultado de Excel/Google Sheets.
- Las consultas clasificadas como `DOCUMENTO` siguen excluyendo Excel y Sheets del routing estructurado.
- Si Gemini no está configurado, se muestran únicamente fragmentos PDF recuperados como evidencia, sin inventar cantidades/coberturas.
- Se agregó logging explícito `INTENCION=DOCUMENTO`, `SERVICIO=REMOLQUE`, `FUENTE=PDF`, `GEMINI=NO_CONFIGURADO`.
