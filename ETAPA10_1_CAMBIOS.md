# Etapa 10.1 — Previews reales de fotos y adjuntos

Corrección sobre Etapa 10.

La Etapa 10 había aplicado el fondo y la forma general del chat, pero faltaba convertir la visualización real de fotos/adjuntos a un comportamiento visual tipo WhatsApp.

## Cambios

- La cola de adjuntos antes de enviar ya no muestra sólo nombre + clip.
- Las imágenes adjuntas muestran miniatura real usando `URL.createObjectURL`.
- PDFs, TXT, planillas y archivos genéricos se muestran como tarjetas compactas.
- Al enviar archivos, el mensaje del usuario muestra los previews dentro de la burbuja existente.
- Al reabrir historial, los adjuntos guardados como `[Adjunto: ...]` se reconstruyen como tarjetas genéricas, sin inventar miniaturas inexistentes.
- Se preserva la burbuja externa del usuario: no se cambia color, forma ni padding global; sólo se agregan previews internos.
- Fotos/recortes generados dentro de respuestas también quedan integrados con estética de conversación.

## Archivos modificados

- `static/js/app.js`
- `static/css/estilo.css`
- `VALIDAR_TODO.py`
- `VALIDACION_ETAPA10_1_PREVIEWS_WHATSAPP.py`
