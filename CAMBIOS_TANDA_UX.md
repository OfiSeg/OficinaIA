# OficinaIA — Tandas UX 1–5

## Tanda 1 — Apariencia
- Modo claro/oscuro (localStorage + prefers-color-scheme, prioridad manual)
- Tamaño de fuente A− / A+ (sm–xl, localStorage)
- Toasts de feedback (`showToast`)
- Variables CSS coherentes

## Tanda 2 — Chat
- Scroll al **inicio** de la respuesta de Sofia (no al último renglón)
- No secuestra el scroll si el usuario lee mensajes anteriores
- Renderer más natural (•, negrita, limpia ### *** >>>)
- Botón Copiar en respuestas
- Prompt: tono San José Seguros + reglas de formato

## Tanda 3 — Historial
- Título automático determinístico (compañía — tema)
- Fecha · hora en cada chat
- Búsqueda, renombrar (PATCH), eliminar con toast
- Chat activo destacado

## Tanda 4 — Fetch / sin F5
- Manuales y pólizas: actualizar DOM sin reload
- Usuarios en configuración sin recarga completa
- Persistencia real → luego UI

## Tanda 5 — Auditoría
- Dark mode en Excel, Word, metadatos, biblioteca
- Focus visible, botones disabled
- alert de PDF → toast
- Corrección handler legacy de manuales.html
- Sticky headers en tablas de settings

## Archivos principales
- templates/base.html
- templates/biblioteca.html
- templates/configuracion.html
- templates/notas.html
- templates/manuales.html
- static/css/estilo.css
- static/js/app.js
- app.py
- database_pg.py
- servicios_ia.py (solo reglas de formato/tono)
