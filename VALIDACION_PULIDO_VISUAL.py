from pathlib import Path

ROOT = Path(__file__).resolve().parent
css = (ROOT / 'static/css/design-system.css').read_text(encoding='utf-8')
legacy = (ROOT / 'static/css/estilo.css').read_text(encoding='utf-8')
app = (ROOT / 'static/js/app.js').read_text(encoding='utf-8')
pend = (ROOT / 'templates/pendientes.html').read_text(encoding='utf-8')

checks = {
    'semantic info surface': '--oi-surface-info:' in css and '--oi-border-info:' in css,
    'semantic pending surface': '--oi-surface-pending:' in css and '--oi-border-pending:' in css,
    'semantic document surface': '--oi-surface-document:' in css and '--oi-border-document:' in css,
    'profile uses info surface': '.insured-profile-card{' in css and 'background:var(--oi-surface-info)!important' in css,
    'document uses document surface': '.insurance-doc-panel{' in css and 'background:var(--oi-surface-document)!important' in css,
    'pending state classes emitted': 'class="pend-card is-${esc(estadoActual)}"' in pend,
    'pending pending style': '.pend-card.is-pendiente' in css,
    'pending done style': '.pend-card.is-hecho' in css,
    'pending discarded style': '.pend-card.is-descartado' in css,
    'slash anchored left': '.chat-command-menu{left:16px;right:auto;bottom:68px' in legacy,
    'slash ltr': 'direction:ltr!important' in legacy,
    'document loading feedback': "gen.textContent='Generando…'" in app and "gen.setAttribute('aria-busy','true')" in app,
    'modal blur removed': 'backdrop-filter:none!important' in css,
    'plus menu neutral icons': '.chat-action-icon{' in css and 'background:var(--oi-surface-muted)!important' in css,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit('FALLÓ PULIDO VISUAL: ' + ', '.join(failed))
print('OK - pulido visual: jerarquía semántica, ficha, documentos, pendientes, slash y feedback')
