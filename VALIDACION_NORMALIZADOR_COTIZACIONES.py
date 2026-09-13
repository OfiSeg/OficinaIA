# -*- coding: utf-8 -*-
"""Pruebas rápidas sin red para el normalizador universal de Cotizaciones."""
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
