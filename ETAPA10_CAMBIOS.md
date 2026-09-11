# ETAPA 10 — Prueba visual estilo WhatsApp Web

Base utilizada: `OficinaIA_ETAPA9_PRIMER_ARRANQUE_WINDOWS.zip`.

## Objetivo

Aplicar una prueba visual para que el área de conversación, burbujas no-usuario, adjuntos, fotos/previews y fondo del chat se vean lo más idénticos posible a WhatsApp Web, sin modificar lógica funcional.

## Cambios realizados

- `templates/documentos.html`
  - Se agregó botón de brocha para cambiar fondo.
  - Se agregó selector simple de fondos.
  - El botón de eliminar chat pasó a ser un ícono de basura rojo.
  - Se quitó el texto visible `Eliminar chat` del header.

- `static/js/app.js`
  - Se agregó `inicializarVisualChatWhatsApp()`.
  - Se agregó `aplicarFondoChat()` con persistencia en `localStorage`.
  - Se agregó selector de fondos con valores `classic`, `soft` y `clean`.
  - Se agregó limpieza defensiva de metadata visual (`hora`, `visto`, `checks`) si alguna plantilla antigua la inyecta.

- `static/css/estilo.css`
  - Se agregó fondo tipo WhatsApp al historial del chat.
  - Se aplicó estilo de burbuja entrante tipo WhatsApp a mensajes del asistente/sistema.
  - Se adaptaron adjuntos y previews al look compacto tipo WhatsApp.
  - Se ocultaron clases típicas de hora/visto/checks si existieran.
  - Se preservó la burbuja del usuario: la sección nueva no redefine `.user .bubble`.

- `VALIDACION_ETAPA10_WHATSAPP_VISUAL.py`
  - Valida brocha, selector de fondo, basura roja, ocultamiento de metadata, estilo de burbujas no-usuario y preservación de burbuja del usuario.

- `VALIDAR_TODO.py`
  - Incluye la validación de Etapa 10.

## Alcance preservado

No se modificó:

- backend;
- IA;
- rutas;
- APIs;
- envío de mensajes;
- lógica de adjuntos;
- historial;
- retries;
- ARCA;
- Excel;
- procesamiento documental.

## Nota

El fondo se implementa mediante CSS, sin agregar imágenes pesadas ni assets externos. Esto mantiene el ZIP liviano y reversible.
