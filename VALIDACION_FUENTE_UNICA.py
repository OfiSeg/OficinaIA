from pathlib import Path

BASE = Path(__file__).resolve().parent
js = (BASE / 'static/js/app.js').read_text(encoding='utf-8')
doc = (BASE / 'cotizacion_document_service.py').read_text(encoding='utf-8')
css = (BASE / 'static/css/design-system.css').read_text(encoding='utf-8')
agents = (BASE / 'AGENTS.md').read_text(encoding='utf-8')

def check(cond, msg):
    if not cond:
        raise AssertionError(msg)

check('una sola fuente de verdad ejecutable' in agents.lower(), 'AGENTS.md perdió el principio de fuente única.')
check('QUOTE_CORE_BENEFIT' not in js, 'El frontend volvió a duplicar la tabla canónica de prestaciones.')
check('QUOTE_PROFILE_COMMERCIAL_NAMES' not in js, 'El frontend volvió a duplicar nombres comerciales por perfil.')
check('PERFIL_BENEFICIO_BASE' not in doc, 'El renderer documental volvió a decidir prestaciones por perfil.')
check('_contenido_canonico_por_familia' not in doc, 'El renderer documental volvió a reconstruir coberturas.')
check('PERFIL_NOMBRE_COMERCIAL' not in doc, 'El renderer documental volvió a decidir nombres comerciales.')
check('OFICINAIA · VISUAL CONSOLIDATION V1 · 2026-09-15' not in css, 'Volvió la capa visual superpuesta retirada.')
check('no vuelve a decidir jerarquía comercial' in doc, 'El renderer perdió el contrato de orden canónico recibido.')
print('OK - fuente única: frontend sin tablas semánticas paralelas, renderer sin reinterpretación y sin capa visual superpuesta')
