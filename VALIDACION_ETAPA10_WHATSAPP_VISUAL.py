"""Validación localizada de la Etapa 10: visual tipo WhatsApp Web.

No prueba backend ni IA. Sólo asegura que la prueba visual quedó cableada
sin tocar el envío de mensajes ni la burbuja del usuario.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = (ROOT / "templates" / "documentos.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "estilo.css").read_text(encoding="utf-8")


def ok(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print("OK", msg)


def main() -> int:
    ok('id="chatWallpaperBtn"' in HTML, "existe botón brocha para cambiar fondo")
    ok('id="chatWallpaperMenu"' in HTML and 'data-wallpaper="classic"' in HTML, "existe selector simple de fondos")
    ok('chat-header-actions' in HTML, "la brocha queda agrupada junto al eliminar chat")
    ok('chat-clear-danger' in HTML and 'aria-label="Eliminar chat"' in HTML, "eliminar chat queda como acción destructiva con ícono")
    ok('>Eliminar chat<' not in HTML, "no queda texto visible 'Eliminar chat' en el header")

    ok('CHAT_WALLPAPER_KEY' in JS and 'oficinaia_chat_wallpaper' in JS, "el fondo se persiste localmente")
    ok('inicializarVisualChatWhatsApp' in JS, "se inicializa la prueba visual del chat")
    ok('aplicarFondoChat' in JS and 'dataset.wallpaper' in JS, "el fondo se aplica mediante data-wallpaper")
    ok('limpiarMetadataVisualMensajes' in JS, "hay limpieza defensiva de horas/vistos/checks si existieran")

    ok('ETAPA 10' in CSS and 'WhatsApp Web' in CSS, "existen reglas CSS de etapa 10")
    ok('body.chat-layout .chat[data-wallpaper="classic"] .history' in CSS, "fondo clásico tipo WhatsApp aplicado al historial")
    ok('body.chat-layout .history .msg.assistant .bubble' in CSS, "burbuja del asistente adaptada visualmente")
    ok('body.chat-layout .file-attached-item' in CSS, "adjuntos/previews tienen estilo compacto tipo WhatsApp")
    ok('body.chat-layout .chat>header .chat-clear-danger.clear-chat' in CSS, "basura roja en el header")
    ok('body.chat-layout .msg-time' in CSS and '.wa-checks' in CSS, "hora/visto/checks quedan ocultos si alguna plantilla los trae")

    marker = '/* Burbujas del asistente/sistema: estilo entrante de WhatsApp Web.'
    section = CSS[CSS.index(marker):]
    ok('.user .bubble{' not in section and '.user .bubble {' not in section, "la sección nueva no redefine la burbuja del usuario")
    print("ETAPA 10 WHATSAPP VISUAL: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
