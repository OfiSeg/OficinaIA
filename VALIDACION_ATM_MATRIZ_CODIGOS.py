from __future__ import annotations
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_catalogo_codigo_fijo_y_orden():
    from atm_coberturas import catalogo_publico
    cat = catalogo_publico()
    assert [x['codigo'] for x in cat] == ['A','A1','B','B1','B2','B3','B4','B5','C','CPr','CB','TR']
    por = {x['codigo']: x for x in cat}
    assert por['C']['titulo_atm'] == 'TERCEROS COMPLETOS PLUS'
    assert por['CPr']['titulo_atm'] == 'TERCEROS COMPLETOS PREMIUM'
    assert por['CB']['titulo_atm'] == 'TERCEROS COMPLETOS BLACK'
    assert por['A']['grua'] is True and por['A1']['grua'] is False
    assert por['B']['grua'] is True and por['B3']['grua'] is True
    assert por['B4']['grua'] is False and por['B5']['grua'] is False
    assert por['C']['descripcion_cliente'] == por['CPr']['descripcion_cliente'] == por['CB']['descripcion_cliente']
    assert all(x in por['C']['descripcion_cliente'].lower() for x in ('ruedas','vidrios','granizo','cerraduras','grúa'))


def test_titulos_reales_resuelven_siempre_igual():
    from atm_coberturas import resolver_codigo_atm
    casos = {
        'RESPONSABILIDAD CIVIL': 'A',
        'RESPONSABILIDAD CIVIL SIN ASISTENCIA': 'A1',
        'ROBO E INCENDIO TOTAL Y/O PARCIAL + ACCIDENTE TOTAL': 'B',
        'ROBO E INCENDIO TOTAL Y/O PARCIAL': 'B1',
        'ROBO, INCENDIO Y ACCIDENTE TOTAL': 'B2',
        'ROBO E INCENDIO TOTAL': 'B3',
        'ROBO, INCENDIO Y ACCIDENTE TOTAL SIN ASISTENCIA': 'B4',
        'ROBO E INCENDIO TOTAL SIN ASISTENCIA': 'B5',
        'TERCEROS COMPLETOS PLUS': 'C',
        'TERCEROS COMPLETOS PREMIUM': 'CPr',
        'TERCEROS COMPLETOS BLACK': 'CB',
        'TODO RIESGO C/FCIA.VARIABLE 3% SUMA ASEGURADA': 'TR',
        'TODO RIESGO C/FCIA.VARIABLE 6% SUMA ASEGURADA': 'TR',
    }
    for titulo, codigo in casos.items():
        assert resolver_codigo_atm(titulo) == codigo, (titulo, resolver_codigo_atm(titulo))


def test_ui_final_una_fila_sin_auto_moto_y_ctrl_v():
    html = (ROOT/'templates/documentos.html').read_text(encoding='utf-8')
    js = (ROOT/'static/js/app.js').read_text(encoding='utf-8')
    css = (ROOT/'static/css/design-system.css').read_text(encoding='utf-8')
    assert 'data-atm-tab="capture"' in html
    assert 'Pegá con Ctrl+V o elegí una imagen' in html
    assert 'data-atm-tipo=' not in html
    assert 'Tipo de vehículo' not in html
    assert "atmTabActual='capture'" in js
    assert "modal.addEventListener('paste'" in js
    assert "ATM_CODIGOS_ORDEN=['A','A1','B','B1','B2','B3','B4','B5','C','CPr','CB','TR']" in js
    assert "['3','6'].forEach" in js
    assert 'atmTipoSeleccionado' not in js
    assert 'setTipoATM' not in js
    assert 'grid-template-columns:repeat(14,minmax(0,1fr))' in css
    assert 'readonly' not in html[html.index('atmProposalText')-80:html.index('atmProposalText')+120]


def test_propuesta_cliente_clara_sin_codigos_internos():
    js = (ROOT/'static/js/app.js').read_text(encoding='utf-8')
    bloque = js[js.index('function nombreClientePropuestaATM'):js.index('async function copiarPropuestaATM')]
    assert '¡Hola! Te paso algunas opciones de cobertura para tu vehículo para que puedas compararlas y elegir la que mejor te sirva:' in bloque
    assert 'con cupones · ${adherido} con CBU o tarjeta adherida' in bloque
    assert 'Valores sujetos a las condiciones de contratación de ATM.' not in bloque
    assert 'Todo Riesgo – Franquicia ${pct}%' in bloque
    assert 'Todo gasto que supere ese importe queda a cargo de la compañía.' in bloque
    assert 'grúa/remolque' not in bloque and 'remolque/grúa' not in bloque


def test_formula_adherido_no_se_toco():
    import atm_cotizador
    assert atm_cotizador.ATM_FACTOR_ADHESION == Decimal(5)/Decimal(6)
    r = atm_cotizador.cotizar_atm('185000', descuento='50')
    assert Decimal(r['precio_adherido']) == Decimal('185000') * Decimal(5) / Decimal(6)


def main():
    tests=[v for k,v in globals().items() if k.startswith('test_') and callable(v)]
    for t in tests:
        t();print('OK',t.__name__)
    print(f'OK TOTAL: {len(tests)} grupos')

if __name__=='__main__':
    main()
