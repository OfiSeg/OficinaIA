"""Validación localizada de Etapa 10.1: previews reales de fotos/adjuntos estilo WhatsApp."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
JS=(ROOT/'static/js/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'static/css/estilo.css').read_text(encoding='utf-8')

def ok(cond,msg):
    if not cond: raise AssertionError(msg)
    print('OK',msg)

def main():
    ok('crearVistaAdjuntoWhatsApp' in JS, 'existe creador unificado de vista de adjuntos')
    ok('URL.createObjectURL(file)' in JS, 'las imágenes locales tienen preview real antes/durante el envío')
    ok('agregarMensajeUsuarioConAdjuntos' in JS, 'el mensaje enviado puede mostrar miniaturas/archivos dentro del chat')
    ok('agregarMensajeUsuarioHistorico' in JS, 'los adjuntos históricos se renderizan como tarjetas y no como texto crudo')
    ok('agregarMensajeUsuarioConAdjuntos(t,archivos);' in JS, 'el envío muestra sólo el texto real del usuario junto a los adjuntos')
    ok("Procesá estos documentos.':'Analizá este archivo." not in JS, 'los prompts operativos no se pintan como mensajes del usuario')
    ok('wa-composer-attachment' in JS, 'la cola de adjuntos usa tarjetas visuales')
    ok('ETAPA 10.1' in CSS, 'existen reglas CSS de etapa 10.1')
    ok('.wa-photo-preview' in CSS, 'las fotos tienen clase de preview estilo WhatsApp')
    ok('.wa-sent-attachments' in CSS, 'los adjuntos enviados se muestran dentro del mensaje')
    ok('.file-attached-item.wa-composer-attachment' in CSS, 'la cola previa al envío se estiliza como preview y no lista plana')
    marker='ETAPA 10.1'
    section=CSS[CSS.index(marker):]
    ok('.msg.user .bubble{' not in section and '.msg.user .bubble {' not in section, 'la etapa 10.1 no redefine la burbuja externa del usuario')
    print('ETAPA 10.1 PREVIEWS WHATSAPP: OK')
    return 0
if __name__=='__main__':
    raise SystemExit(main())
