# -*- coding: utf-8 -*-
"""Regresiones de la pasada de normalización/estandarización 2026-09-14.

Estas pruebas validan contratos universales, no layouts particulares por compañía.
"""
from pathlib import Path
from io import BytesIO
import tempfile

from docx import Document

from config_service import default_config
from companias import asistencia_compania, texto_asistencia_compania, catalogo_companias as catalogo_companias_canonico
from coti import COMPANIAS_COTI
from envios_masivos import COMPANIAS_FILENAME, _detectar_compania_filename
from cotizacion_document_service import catalogo_companias, normalizar_cobertura_para_carta
from insurance_document_service import preparar, generar_docx
from mercantil_coberturas import entrada as entrada_mercantil
from quote_normalizer import (
    PERFIL_C_PLUS,
    PERFIL_TR,
    evaluar_calidad_lectura,
    normalizar_texto_cotizacion,
)

BASE = Path(__file__).resolve().parent


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# 1) Mercantil M Plus: prestación confirmada de grúa + normalización canónica.
mplus = entrada_mercantil("M PLUS")
check(mplus and mplus.get("servicio_grua") is True, "M Plus perdió la grúa confirmada.")
merc = normalizar_texto_cotizacion(
    "M PLUS - TERCEROS COMPLETO M PLUS\n"
    + mplus["descripcion_cliente"]
    + "\nPrecio por cuota $ 100.000",
    compania="Mercantil Andina",
)
check(merc["coberturas"], "No se normalizó el ejemplo Mercantil.")
check(merc["coberturas"][0]["perfil_normalizado"] == PERFIL_C_PLUS, "M Plus no quedó en C_PLUS.")

# 2) AgroSalta CF: una prestación extra explícita no puede perderse.
agro = normalizar_texto_cotizacion(
    """Cotización de Automotores
Vehículo Cotizado
Marca: VOLKSWAGEN
Modelo: AMAROK
Año: 2024 Valor: $ 8.999.999
Cobertura Suma Prima Premio c/IVA 4 Cuotas
A - RESPONSABILIDAD CIVIL $ 92.016,96 $ 167.999,28 $ 41.999,82
CF - TOT.Y PARC.C/DESTRUC.TOTAL.CRIST. Y PARABRIS $ 8.999.999 $ 182.736,96 $ 294.194,42 $ 73.548,61
"""
)
check(agro["compania"] == "AgroSalta", "La firma de plantilla AgroSalta no se reconoció.")
cf = next((x for x in agro["coberturas"] if str(x.get("codigo_original") or "").upper() == "CF"), None)
check(cf is not None, "El CF sintético desapareció de la cotización.")
check(cf["perfil_normalizado"] == PERFIL_C_PLUS, "CF con cristales/parabrisas no quedó como cobertura mejorada.")
check("VIDRIOS" in cf["riesgos_detectados"], "CF perdió cristales/parabrisas.")

# 3) Franquicia: el renderer documental debe agregar nota universal para cualquier porcentaje.
tr = normalizar_cobertura_para_carta({
    "compania": "Compañía de prueba",
    "nombre": "Todo Riesgo",
    "nombre_comercial": "Todo Riesgo",
    "familia": PERFIL_TR,
    "franquicia_pct": "7,5",
    "contenidos": [{"tipo": "beneficio", "texto": "Daños parciales por accidente."}],
})
notas = [x["texto"] for x in tr["contenidos"] if x["tipo"] == "nota"]
check(len(notas) == 1 and "7,5% de la suma asegurada" in notas[0], "La nota de franquicia debe ser universal y única para porcentajes variables.")
tr2 = normalizar_cobertura_para_carta(tr)
check(tr2 == tr, "Normalizar dos veces una cobertura cambió el resultado.")

# 4) Catálogo: identidad común + compañías configuradas, aunque no tengan logo.
cat = catalogo_companias(BASE / "static" / "img" / "companias", default_config().get("companias"))
nombres = [x["nombre"] for x in cat]
for nombre in ("ATM", "Federación Patronal", "Mercantil Andina", "San Cristóbal", "AgroSalta", "Allianz", "PROF"):
    check(nombre in nombres, f"Falta {nombre} en el catálogo universal.")
check(nombres.count("Federación Patronal") == 1, "Self duplicó la identidad de Federación Patronal.")
for nombre in ("Rivadavia", "Triunfo", "EuroAmérica", "La Segunda", "Río Uruguay", "Sancor Seguros", "Provincia Seguros", "Mapfre", "Paraná Seguros", "Zurich", "Toval", "Sura", "Experta", "Nación Seguros", "HDI", "Chubb", "SMG", "Galeno", "Prevención"):
    check(nombre in nombres, f"Falta {nombre} en el registro central completo.")

# Las capacidades también salen del registro central, pero centralizar identidad
# NO habilita funciones que antes no existían. /coti, Manuales y Envíos deben
# conservar exactamente su alcance histórico hasta que se configure una nueva
# capacidad de forma explícita.
cat_canon = catalogo_companias_canonico()
coti_esperadas = {str(x.get("coti_nombre") or x["nombre"]) for x in cat_canon if x.get("coti_enabled")}
check(set(COMPANIAS_COTI.values()) == coti_esperadas, "/coti dejó de respetar las capacidades declaradas en el registro central.")
check("Zurich" not in set(COMPANIAS_COTI.values()), "Registrar Zurich habilitó /coti sin configuración comercial.")
check(set(COMPANIAS_FILENAME.values()) >= {"ATM SEGUROS", "FEDERACION PATRONAL", "MERCANTIL ANDINA"}, "Envíos perdió etiquetas históricas de compañía.")
check(_detectar_compania_filename("cartera_zurich_septiembre.xlsx") == "", "Registrar Zurich habilitó Envíos sin configuración explícita.")


# 4b) Asistencia: un solo registro canónico alimenta documentos sin inferir cobertura.
ags_help = asistencia_compania("Ags")
check(ags_help.get("whatsapp") == ["+54 9 11 2468-5636"], "AgroSalta perdió su WhatsApp de asistencia.")
check("0800 345 1240" in texto_asistencia_compania("ATM"), "ATM perdió el contacto canónico de remolque.")
for cia, dato in {
    "Allianz": "0800-888-24324",
    "San Cristóbal": "0810-222-8887",
    "Federación Patronal": "0800-800-0022",
    "Mercantil Andina": "0800-777-2634",
    "Rivadavia": "0800-666-6789",
    "EuroAmerica": "011 4312-8398",
    "PROF": "0800-333-3512",
}.items():
    check(dato in texto_asistencia_compania(cia), f"{cia} perdió su contacto canónico de asistencia.")
cat_atm = next((x for x in cat if x.get("nombre") == "ATM"), None)
check(cat_atm and cat_atm.get("asistencia", {}).get("telefonos") == ["0800 345 1240"], "El catálogo universal no expone asistencia de ATM.")
check(texto_asistencia_compania("EuroAmerica", solo_asistencia=True) == "", "EuroAmérica fue presentado como grúa aunque sólo tiene contacto general.")

# 5) Calidad: una prestación convertida en plan y precios perdidos debe disparar revisión.
bad = {
    "texto_fuente": "Cobertura Premio Cuotas\nC2 - TERCEROS COMPLETOS\nINCENDIO TOTAL O PARCIAL $ 50.000.000\nROBO TOTAL O PARCIAL $ 50.000.000",
    "suma_asegurada": "50000000",
    "coberturas": [
        {"nombre_original": "INCENDIO TOTAL O PARCIAL", "perfil_normalizado": "SIN_CLASIFICAR", "precio_cuota": None},
        {"nombre_original": "ROBO TOTAL O PARCIAL", "perfil_normalizado": "SIN_CLASIFICAR", "precio_cuota": None},
    ],
}
quality = evaluar_calidad_lectura(bad)
check(quality["confiable"] is False and quality["score"] < 65, "Un parseo incoherente fue aceptado como confiable.")

# 6) Ficha documental: no mezcla dos vehículos/pólizas y una confirmación explícita gana.
ficha_multi = {
    "status": "found",
    "asegurado": "Jorge Carrizo",
    "contacto": {"telefono": "1111111111"},
    "registros": [
        {"asegurado": "Jorge Carrizo", "patente": "AA111AA", "poliza": "100", "vehiculo": "Auto A", "compania": "ATM"},
        {"asegurado": "Jorge Carrizo", "patente": "BB222BB", "poliza": "200", "vehiculo": "Auto B", "compania": "Allianz"},
    ],
}
amb = preparar("baja", ficha=ficha_multi)
check(len(amb["registros_ambiguos"]) == 2, "La ficha mezcló vehículos/pólizas distintos en silencio.")

ficha_one = {
    "status": "found",
    "asegurado": "Jorge Carrizo",
    "contacto": {"telefono": "1111111111"},
    "registros": [{
        "asegurado": "Jorge Carrizo", "patente": "AA111AA", "poliza": "100",
        "vehiculo": "Auto A", "compania": "ATM", "cobertura": "Responsabilidad Civil",
        "medio_pago": "CBU", "emitido_dia": "14/09/2026", "vencimiento": "14/10/2026",
    }],
}
prep = preparar(
    "bienvenida",
    ficha=ficha_one,
    campos={"PATENTE": "AA111AA", "POLIZA": "100", "COMPANIA": "ATM"},
    extras={"COMPANIA": "Allianz"},
    patente="AA111AA",
    poliza="100",
)
check(prep["campos"]["COMPANIA"] == "Allianz", "La confirmación explícita del usuario no tuvo prioridad.")
check(prep["fuentes"]["COMPANIA"] == "manual_confirmado", "No quedó trazada la autoridad del usuario.")

# Una evidencia positiva de grúa recibe el canal de la compañía; una negativa no.
prep_grua = preparar(
    "bienvenida", ficha=ficha_one,
    campos={"PATENTE":"AA111AA","POLIZA":"100","COMPANIA":"ATM","ASISTENCIA_GRUA":"Incluye grúa."},
    patente="AA111AA", poliza="100",
)
check("0800 345 1240" in prep_grua["campos"].get("ASISTENCIA_GRUA", ""), "Bienvenida no completó el contacto ATM con grúa confirmada.")
prep_sin_grua = preparar(
    "bienvenida", ficha=ficha_one,
    campos={"PATENTE":"AA111AA","POLIZA":"100","COMPANIA":"ATM","ASISTENCIA_GRUA":"Sin grúa."},
    patente="AA111AA", poliza="100",
)
check("0800 345 1240" not in prep_sin_grua["campos"].get("ASISTENCIA_GRUA", ""), "Se agregó asistencia a una cobertura explícitamente sin grúa.")

# 7) Importe pendiente no puede heredarse desde premio/importe aproximado.
ficha_importe = {
    "status": "found", "asegurado": "Jorge Carrizo", "contacto": {},
    "registros": [{"asegurado":"Jorge Carrizo","patente":"AA111AA","poliza":"100","vehiculo":"Auto A","compania":"ATM","importe_aprox":"50000","importe":"50000"}],
}
pend = preparar("pago_pendiente", ficha=ficha_importe, patente="AA111AA", poliza="100")
check(not pend["campos"].get("IMPORTE_PENDIENTE"), "Un premio/importe aproximado se usó como deuda pendiente.")

# 8) Las tres plantillas institucionales generan Word sin variables residuales.
samples = {
    "bienvenida": {"NOMBRE":"Jorge Carrizo","VEHICULO":"Auto A","PATENTE":"AA111AA","COMPANIA":"ATM","COBERTURA":"Responsabilidad Civil","POLIZA":"100","FECHA_EMISION":"14/09/2026","FORMA_PAGO":"CBU","VENCIMIENTO":"14/10/2026","ASISTENCIA_GRUA":"Incluye grúa."},
    "pago_pendiente": {"NOMBRE":"Jorge Carrizo","VEHICULO":"Auto A","PATENTE":"AA111AA","COMPANIA":"ATM","POLIZA":"100","IMPORTE_PENDIENTE":"$50.000","VENCIMIENTO":"14/10/2026","FORMA_PAGO":"CBU","INSTRUCCION_PAGO":"Solicitá el link de pago."},
    "baja": {"NOMBRE":"Jorge Carrizo","VEHICULO":"Auto A","PATENTE":"AA111AA","COMPANIA":"ATM","POLIZA":"100","FECHA_BAJA":"14/09/2026","MOTIVO_BAJA":"Solicitud del asegurado."},
}
with tempfile.TemporaryDirectory() as td:
    for tipo, fields in samples.items():
        bio, filename = generar_docx(tipo, fields, templates_dir=BASE / "plantillas" / "seguros")
        payload = bio.getvalue()
        check(len(payload) > 5000 and filename.endswith(".docx"), f"No se generó correctamente {tipo}.")
        doc = Document(BytesIO(payload))
        visible = "\n".join(p.text for p in doc.paragraphs)
        check("{{" not in visible, f"{tipo} contiene un placeholder sin resolver.")

print("OK - normalización integral: prestaciones, franquicia, catálogo, calidad de lectura y documentos")
