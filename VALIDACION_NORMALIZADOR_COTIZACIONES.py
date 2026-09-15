# -*- coding: utf-8 -*-
"""Pruebas rápidas sin red para el normalizador universal de Cotizaciones."""
import quote_normalizer as _qn
from quote_normalizer import normalizar_cobertura, normalizar_texto_cotizacion
from federacion_quote_service import _cobertura as cobertura_federacion

CASOS = [
    ("B", "RC.PERD TOTAL Accid. Inc. y Robo", "B"),
    ("B1", "RC.PERD TOTAL Inc. y Robo", "B1"),
    ("C", "RC.P.T ACC. Y P.TYP IN. Y ROBO", "C"),
    ("C1", "RC. PTOTAL y PARCIAL Inc. y Robo", "C1"),
    ("CF", "RC. PT Ac. y PTyP Inc. y Robo. Ruedas, vidrios, granizo y cerraduras", "C_PLUS"),
    ("LB", "RESP.CIVIL-PT Ac.-PTyP Inc. y Robo-RP Amp TOT.", "LB"),
    ("LB1", "RESP.CIVIL-PTyP Inc. y Robo-RP Amp TOT.", "LB1"),
    ("TD3", "TODO RIESGO CON FRANQUICIA FIJA", "TODO_RIESGO"),
]

for codigo, texto, esperado in CASOS:
    d = normalizar_cobertura(texto, codigo=codigo)
    assert d["perfil_normalizado"] == esperado, (codigo, d)

# La compañía desconocida NO autoriza inferir un perfil por un simple código.
d = normalizar_texto_cotizacion("COMPAÑÍA DESCONOCIDA\nCobertura C\nPrecio $100000")
assert not d["es_cotizacion_generica"], d

# Si el contenido explicita los riesgos, sí se normaliza aunque la compañía sea nueva.
d = normalizar_texto_cotizacion(
    "ASEGURADORA EJEMPLO S.A.\n"
    "Vehículo: Peugeot 208 2024\n"
    "Suma asegurada: $25.000.000\n"
    "PLAN XP4 - RC.P.T ACC. Y P.TYP IN. Y ROBO\n"
    "Cuota: $145.320,50\n"
    "CON SERV. DE GRUA\n"
)
assert d["es_cotizacion_generica"]
assert d["coberturas"][0]["perfil_normalizado"] == "C"
assert d["coberturas"][0]["servicio_grua"] is True
assert d["coberturas"][0]["precio_cuota_formateado"] == "$145.320,50"

# Federación: LB/LB1 ya tienen speech determinístico en el parser conocido.
assert "amparo" in cobertura_federacion("LB", "")[1].lower()
assert "destrucción total" in cobertura_federacion("LB", "")[1].lower()
assert "amparo" in cobertura_federacion("LB1", "")[1].lower()
assert "destrucción total" not in cobertura_federacion("LB1", "")[1].lower()

print("OK - normalizador universal de cotizaciones")

# Firma AgroSalta sin nombre impreso: debe reconocer la plantilla, leer TODAS
# las filas y normalizar por contenido visible, no quedarse sólo con RC.
tabla = """
Cotización de Automotores
Vehículo Cotizado
Marca: VOLKSWAGEN
Modelo: AMAROK 2,0L
Submodelo: VOLKSWAGEN AMAROK 2,0L 122 CV ST9
Año: 2024 Valor: $ 8.999.999
Cobertura Suma Prima Premio c/IVA 4 Cuotas
A - RESPONSABILIDAD CIVIL
$ 92.016,96
$ 167.999,28
$ 41.999,82
B - TOTALES CON DESTRUCCION TOTAL
$ 8.999.999
$ 156.528,96
$ 257.738,03
$ 64.434,51
B1 - TOTALES SIN DESTRUCCION TOTAL
$ 8.999.999
$ 152.496,96
$ 252.129,39
$ 63.032,35
C - TOTALES Y PARCIALES CON DESTRUCCION TOTAL
$ 8.999.999
$ 180.720,96
$ 291.390,08
$ 72.847,52
C1 - TOTALES Y PARCIALES SIN DESTRUCCION TOTAL
$ 8.999.999
$ 178.704,96
$ 288.585,77
$ 72.146,44
CF - TOT.Y PARC.C/DESTRUC.TOTAL.CRIST. Y PARABRIS
$ 8.999.999
$ 182.736,96
$ 294.194,42
$ 73.548,61
"""
d = normalizar_texto_cotizacion(tabla)
assert d["cantidad"] == 6, d
assert d["compania"] == "AgroSalta", d
assert d["anio"] == "2024" and d["suma_asegurada_formateada"] == "$8.999.999,00", d
assert [x["codigo_original"] for x in d["coberturas"]] == ["A", "B1", "B", "C1", "C", "CF"], d
assert [x["perfil_normalizado"] for x in d["coberturas"][:5]] == ["RC", "B1", "B", "C1", "C"], d
assert d["coberturas"][2]["precio_cuota_formateado"] == "$64.434,51", d
assert all(x["nombre_comercial"] and x["familia"] and "orden_comercial" in x for x in d["coberturas"]), d

# AgroSalta debe detectarse por alias y conservar compañía detectada separada
# de una futura confirmación manual del operador.
ags = normalizar_texto_cotizacion(
    "COMPAÑIA DE SEGUROS AGROSALTA\nA - RESPONSABILIDAD CIVIL\nCuota: $50.000"
)
assert ags["compania"] == "AgroSalta", ags
assert ags["compania_detectada"] == "AgroSalta" and ags["compania_confirmada"] == "", ags

# Variantes materiales: grúa sólo sube al título cuando existe el par y la
# franquicia TR siempre queda normalizada con un único signo.
variantes = _qn._normalizar_dato_vision({
    "es_cotizacion": True,
    "compania": "AgroSalta",
    "coberturas": [
        {"codigo":"A", "nombre":"Responsabilidad Civil", "descripcion":"Responsabilidad Civil", "precio":"50000", "grua":"si"},
        {"codigo":"A1", "nombre":"Responsabilidad Civil", "descripcion":"Responsabilidad Civil", "precio":"45000", "grua":"no"},
        {"codigo":"D", "nombre":"Todo Riesgo", "descripcion":"Todo Riesgo", "precio":"250000", "franquicia_pct":"3%%"},
    ],
})
assert variantes["coberturas"][0]["titulo_comercial"].endswith("CON GRÚA"), variantes
assert variantes["coberturas"][1]["titulo_comercial"].endswith("SIN GRÚA"), variantes
assert variantes["coberturas"][2]["titulo_comercial"] == "Todo Riesgo · FRANQUICIA 3%", variantes

# Todo Riesgo universal: mismo código fuente D, pero etiqueta visual por % de
# franquicia y orden ascendente, como ya se hace conceptualmente en Mercantil.
vision = _qn._normalizar_dato_vision({
    "es_cotizacion": True,
    "compania": "San Cristóbal Seguros",
    "coberturas": [
        {"codigo":"D", "nombre":"Todo riesgo con franquicia 2.5% SA", "descripcion":"Responsabilidad Civil. Robo total y parcial. Incendio total y parcial. Daños parciales por accidente.", "precio":"255643", "franquicia_pct":"2.5"},
        {"codigo":"D", "nombre":"Todo riesgo con franquicia 1.5% SA", "descripcion":"Responsabilidad Civil. Robo total y parcial. Incendio total y parcial. Daños parciales por accidente.", "precio":"271646", "franquicia_pct":"1.5"},
        {"codigo":"D", "nombre":"Todo riesgo con franquicia 2% SA", "descripcion":"Responsabilidad Civil. Robo total y parcial. Incendio total y parcial. Daños parciales por accidente.", "precio":"262045", "franquicia_pct":"2"},
    ],
})
assert vision["compania"] == "San Cristóbal", vision
assert [x["codigo_visual"] for x in vision["coberturas"]] == ["D1.5", "D2", "D2.5"], vision



# Allianz D4: granizo es un atributo del producto, también en fallback visual.
allianz_d4 = _qn._normalizar_dato_vision({
    "es_cotizacion": True,
    "compania": "Allianz",
    "coberturas": [
        {"codigo":"90", "nombre":"D4 Alta Gama Vip - 1% - C/granizo", "descripcion":"Responsabilidad Civil. Incendio total o parcial. Robo total o parcial. Daños parciales por accidente. C/granizo", "precio":"465452.86", "franquicia_pct":"1"},
        {"codigo":"91", "nombre":"D4 Alta Gama Vip - 2% - C/granizo", "descripcion":"Responsabilidad Civil. Incendio total o parcial. Robo total o parcial. Daños parciales por accidente. C/granizo", "precio":"417035.57", "franquicia_pct":"2"},
        {"codigo":"92", "nombre":"D4 Alta Gama Vip - 3% - C/granizo", "descripcion":"Responsabilidad Civil. Incendio total o parcial. Robo total o parcial. Daños parciales por accidente. C/granizo", "precio":"360146.75", "franquicia_pct":"3"},
    ],
})
assert [x["codigo_visual"] for x in allianz_d4["coberturas"]] == ["D1", "D2", "D3"], allianz_d4
assert all(x["nombre_comercial"] == "Alta Gama VIP" for x in allianz_d4["coberturas"]), allianz_d4
assert all(x.get("granizo_estado") == "INCLUYE" for x in allianz_d4["coberturas"]), allianz_d4

# ATM PDF oficial: una cabecera de plan + N prestaciones sigue siendo UNA
# cobertura. FCIA es franquicia; Premio/Cuota no puede confundirse con SA.
atm_d2 = normalizar_texto_cotizacion("""
ATM Seguros
AUTOMOTORES
66724000,00
VOLKSWAGEN-AMAROK 20TD 4X2 DC COMFORTL 2026
Valor a Asegurar: Equipo GNC:
Cobertura Premio Cuotas 1° Cuota
D2 - TODO RIESGO C/FCIA.VARIABLE 3% SUMA ASEGURADA
755.639,04
1
755.639,04
Ajus. Aut.: (SIN AJUSTE)
RESPONSABILIDAD CIVIL HASTA $ 208.000.000,00
ACCIDENTE TOTAL O PARCIAL $ 66.724.000,00
INCENDIO TOTAL O PARCIAL $ 66.724.000,00
ROBO TOTAL O PARCIAL $ 66.724.000,00
Daños a parabrisas y luneta, sin límite en la cantidad anual de eventos.
""")
assert atm_d2["compania"] == "ATM" and atm_d2["cantidad"] == 1, atm_d2
atm_d2_cov = atm_d2["coberturas"][0]
assert atm_d2_cov["codigo_original"] == "D2" and atm_d2_cov["perfil_normalizado"] == "TODO_RIESGO", atm_d2_cov
assert atm_d2_cov["franquicia_pct"] == "3", atm_d2_cov
assert atm_d2_cov["precio_cuota_formateado"] == "$755.639,04", atm_d2_cov
assert atm_d2["suma_asegurada_formateada"] == "$66.724.000,00", atm_d2

atm_c2 = normalizar_texto_cotizacion("""
ATM Seguros
AUTOMOTORES
66724000,00
VOLKSWAGEN-AMAROK 20TD 4X2 DC COMFORTL 2026
Valor a Asegurar: Equipo GNC:
Cobertura Premio Cuotas 1° Cuota
C2 - TERCEROS COMPLETOS PREMIUM
238.051,17
1
238.051,17
Ajus. Aut.: (SIN AJUSTE)
RESPONSABILIDAD CIVIL HASTA $ 208.000.000,00
DAÑO TOTAL POR ACCIDENTE $ 66.724.000,00
INCENDIO TOTAL O PARCIAL $ 66.724.000,00
ROBO TOTAL O PARCIAL $ 66.724.000,00
Daños a cristales y cerraduras, hasta 2 eventos acumulados por año.
""")
assert atm_c2["cantidad"] == 1, atm_c2
assert atm_c2["coberturas"][0]["codigo_original"] == "C2", atm_c2
assert atm_c2["coberturas"][0]["nombre_cliente"] == "Terceros Completo Premium", atm_c2
assert atm_c2["coberturas"][0]["precio_cuota_formateado"] == "$238.051,17", atm_c2

# Allianz: si existe una cobertura explícita, una segmentación anterior no
# gobierna el título comercial.
allianz = normalizar_texto_cotizacion("""
ALLIANZ
CLÁSICO SEGMENTADO
TERCEROS COMPLETOS C2
Responsabilidad Civil
Incendio total o parcial
Robo total o parcial
Destrucción total por accidente
Cuota: $205.000
""")
assert allianz["cantidad"] == 1, allianz
assert allianz["coberturas"][0]["nombre_cliente"] == "Terceros Completo C2", allianz
assert "CLÁSICO SEGMENTADO" not in allianz["coberturas"][0]["nombre_cliente"].upper(), allianz
