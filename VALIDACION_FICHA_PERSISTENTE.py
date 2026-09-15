# -*- coding: utf-8 -*-
"""Regresiones de ficha persistente, fuentes, fechas y documentos institucionales."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ["INSURED_PROFILE_SQLITE_PATH"] = str(Path(_tmp.name) / "ficha_test.db")
os.environ.pop("DATABASE_URL", None)

import insured_profile_store as store
import insured_profile
from insurance_document_service import completar_fechas, preparar
from companias import catalogo_companias, normalizar_compania, texto_asistencia_compania


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# 1) Todos los conceptos económicos viven separados.
r = store.upsert({
    "ASEGURADO": "Juan Pérez", "PATENTE": "AA123BB", "CIA": "ATM", "POLIZA": "123",
    "PREMIO_TOTAL_PERIODO": "168000", "VALOR_CUOTA": "42000", "IMPORTE_PENDIENTE": "",
}, fuente="documento")
check(r["ok"], "No se creó la ficha persistente.")
data = r["ficha"]["datos"]
check(data["PREMIO_TOTAL_PERIODO"] == "168000", "Se perdió el premio total del período.")
check(data["VALOR_CUOTA"] == "42000", "Se perdió el valor de cuota.")
check(not data.get("IMPORTE_PENDIENTE"), "Se inventó una deuda a partir del premio/cuota.")

# 2) Manual confirmado gana y una lectura posterior no lo pisa.
r2 = store.upsert({"PATENTE":"AA123BB","CIA":"ATM","POLIZA":"123","COBERTURA":"Todo Riesgo"}, fuente="manual_confirmado")
check(r2["ok"], "No se guardó corrección manual.")
r3 = store.upsert({"PATENTE":"AA123BB","CIA":"ATM","POLIZA":"123","COBERTURA":"Terceros Completo"}, fuente="documento")
check(r3["ficha"]["datos"]["COBERTURA"] == "Todo Riesgo", "Un documento pisó una corrección manual confirmada.")

# 3) Fuentes fuertes contradictorias generan conflicto sin decidir solas.
r4 = store.upsert({"ASEGURADO":"Juan Pérez","PATENTE":"AA123BB","CIA":"ATM","POLIZA":"123","FORMA_PAGO":"CBU"}, fuente="alta_confirmada")
r5 = store.upsert({"PATENTE":"AA123BB","CIA":"ATM","POLIZA":"123","FORMA_PAGO":"Tarjeta"}, fuente="documento")
check(any(c.get("campo") == "FORMA_PAGO" for c in r5.get("conflictos") or []), "Dos fuentes fuertes contradictorias no generaron conflicto.")
check(r5["ficha"]["datos"]["FORMA_PAGO"] == "CBU", "El conflicto fuerte fue resuelto silenciosamente.")

# 4) Prioridad por campo: un dato calculado de la ficha NO pisa un dato explícito de Excel.
store.upsert({"PATENTE":"AA123BB","CIA":"ATM","POLIZA":"123","VENCIMIENTO":"21/10/2026"}, fuente="calculado")

def fake_excel(_libro):
    return {"filas":[
        ["ASEGURADO","PATENTE","CIA","VENCIMIENTO","COBERTURA"],
        ["Juan Pérez","AA123BB","ATM","15/10/2026","Responsabilidad Civil"],
    ]}

ficha = insured_profile.construir_ficha("AA123BB", fake_excel, buscar_persistente=store.buscar)
check(ficha["status"] == "found" and len(ficha["vehiculos"]) == 1, "Excel y ficha persistente del mismo vehículo no se fusionaron.")
veh = ficha["vehiculos"][0]
check(veh["vencimiento"] == "15/10/2026", "Un fallback calculado pisó el vencimiento explícito de Excel.")
check(veh["cobertura"] == "Todo Riesgo", "La corrección manual de cobertura no ganó por campo.")
check(veh["poliza"] == "123", "La póliza persistente no enriqueció al registro de Excel.")

# 5) Fechas: documento explícito manda; fallback general y ATM son distintos.
general, src_general = completar_fechas({"FECHA_EMISION":"14/09/2026","COMPANIA":"Allianz"}, {})
check(general["VIGENCIA_HASTA"] == "14/09/2027", "La vigencia fallback no es emisión + 1 año.")
check(general["VENCIMIENTO"] == "14/10/2026" and src_general["VENCIMIENTO"] == "calculado", "El vencimiento general fallback no es +1 mes.")
atm, _ = completar_fechas({"FECHA_EMISION":"14/09/2026","COMPANIA":"ATM"}, {})
check(atm["VENCIMIENTO"] == "19/10/2026", "ATM no aplica +1 mes +5 días como fallback operativo.")
explicit, _ = completar_fechas({"FECHA_EMISION":"14/09/2026","COMPANIA":"ATM","VENCIMIENTO":"30/09/2026","VIGENCIA_HASTA":"01/08/2027"}, {})
check(explicit["VENCIMIENTO"] == "30/09/2026" and explicit["VIGENCIA_HASTA"] == "01/08/2027", "Una fecha explícita fue pisada por fórmula.")
blank, _ = completar_fechas({"COMPANIA":"ATM"}, {})
check(not blank.get("VENCIMIENTO") and not blank.get("VIGENCIA_HASTA"), "Se inventaron fechas sin fecha de emisión.")
# Bordes de calendario: no fallar con fin de mes ni año bisiesto.
month_end, _ = completar_fechas({"FECHA_EMISION":"31/01/2026","COMPANIA":"Allianz"}, {})
check(month_end["VENCIMIENTO"] == "28/02/2026", "El +1 mes no recorta correctamente el fin de mes.")
atm_month_end, _ = completar_fechas({"FECHA_EMISION":"31/01/2026","COMPANIA":"ATM"}, {})
check(atm_month_end["VENCIMIENTO"] == "05/03/2026", "ATM no aplica +5 días después de recortar el mes correctamente.")
leap, _ = completar_fechas({"FECHA_EMISION":"29/02/2024","COMPANIA":"Allianz"}, {})
check(leap["VIGENCIA_HASTA"] == "28/02/2025", "La vigencia anual no resuelve correctamente el 29/02.")

# 6) Asistencia: estado de póliza decide; catálogo sólo dice cómo contactarla.
ficha_doc = {
    "status":"found", "asegurado":"Juan Pérez", "contacto":{},
    "registros":[{"asegurado":"Juan Pérez","vehiculo":"Auto","patente":"AA123BB","compania":"ATM","poliza":"123","cobertura":"RC","medio_pago":"CBU","emitido_dia":"14/09/2026"}]
}
inc = preparar("bienvenida", ficha=ficha_doc, campos={"PATENTE":"AA123BB","POLIZA":"123","ASISTENCIA_ESTADO":"INCLUYE"}, patente="AA123BB", poliza="123")
check("0800 345 1240" in inc["campos"]["ASISTENCIA_GRUA"], "ATM con asistencia confirmada no recibió canales.")
no = preparar("bienvenida", ficha=ficha_doc, campos={"PATENTE":"AA123BB","POLIZA":"123","ASISTENCIA_ESTADO":"NO_INCLUYE"}, patente="AA123BB", poliza="123")
check("0800 345 1240" not in no["campos"]["ASISTENCIA_GRUA"], "ATM sin asistencia recibió teléfono de grúa.")
unk = preparar("bienvenida", ficha=ficha_doc, campos={"PATENTE":"AA123BB","POLIZA":"123","ASISTENCIA_ESTADO":"DESCONOCIDO"}, patente="AA123BB", poliza="123")
check("0800 345 1240" not in unk["campos"]["ASISTENCIA_GRUA"], "Asistencia desconocida fue inventada.")
check(texto_asistencia_compania("EuroAmérica", solo_asistencia=True) == "", "Contacto general de EuroAmérica se usó como grúa.")


# 6b) Bienvenida: vencimiento recurrente automático; Pago pendiente: vencimiento concreto, no inferido.
welcome_atm = preparar(
    "bienvenida",
    ficha=ficha_doc,
    campos={"PATENTE":"AA123BB","POLIZA":"123","ASISTENCIA_ESTADO":"DESCONOCIDO"},
    extras={"FECHA_EMISION":"14/09/2026"},
    patente="AA123BB", poliza="123",
)
check(welcome_atm["campos"]["VENCIMIENTO"] == "Todos los 19 de cada mes", "Bienvenida ATM no usa emisión +5 como día recurrente.")
welcome_general = preparar(
    "bienvenida",
    ficha={"status":"found","asegurado":"Juan Pérez","contacto":{},"registros":[{"asegurado":"Juan Pérez","vehiculo":"Auto","patente":"BB123CC","compania":"Allianz","poliza":"A1","cobertura":"RC","medio_pago":"CBU"}]},
    campos={"PATENTE":"BB123CC","POLIZA":"A1"}, extras={"FECHA_EMISION":"14/09/2026"},
    patente="BB123CC", poliza="A1",
)
check(welcome_general["campos"]["VENCIMIENTO"] == "Todos los 14 de cada mes", "Bienvenida general no conserva el día de emisión.")
pending_without_due = preparar(
    "pago_pendiente",
    ficha=ficha_doc,
    campos={"PATENTE":"AA123BB","POLIZA":"123","IMPORTE_PENDIENTE":"85000","INSTRUCCION_PAGO":"Adjunto cupón"},
    patente="AA123BB", poliza="123",
)
check(not pending_without_due["campos"].get("VENCIMIENTO"), "Pago pendiente inventó un vencimiento a partir de la emisión.")
check("VENCIMIENTO" in pending_without_due["faltantes"], "Pago pendiente sin vencimiento no lo pidió como dato faltante.")

# 7) Registro central realmente completo respecto de las identidades ya presentes en OficinaIA.
cat = catalogo_companias()
keys = [x["key"] for x in cat]
check(len(cat) == 26 and len(keys) == len(set(keys)), "Registro central incompleto o con IDs duplicados.")
for raw, code in {"Sura":"SURA","Experta":"EXPERTA","Nación":"NACION","HDI":"HDI","Chubb":"CHUBB","SMG Seguros":"SMG","Galeno":"GALENO","Prevención ART":"PREVENCION"}.items():
    check(normalizar_compania(raw) == code, f"{raw} no resuelve al company_key/código central esperado.")

# 8) Misma patente con varias pólizas: una entrada sin póliza no debe
# sobreescribir arbitrariamente ninguna póliza histórica.
store.upsert({"ASEGURADO":"Ana Test","PATENTE":"ZZ999ZZ","CIA":"ATM","POLIZA":"POL-A","COBERTURA":"RC"}, fuente="documento")
store.upsert({"ASEGURADO":"Ana Test","PATENTE":"ZZ999ZZ","CIA":"ATM","POLIZA":"POL-B","COBERTURA":"Todo Riesgo"}, fuente="documento")
amb = store.upsert({"ASEGURADO":"Ana Test","PATENTE":"ZZ999ZZ","CIA":"ATM","TELEFONO":"11 5555-9999"}, fuente="alta_confirmada")
check(amb["ok"], "No se pudo guardar metadata ambigua de patente sin póliza.")
rows_amb = store.buscar("ZZ999ZZ")
polizas = {str((x.get("datos") or {}).get("POLIZA") or "") for x in rows_amb}
check({"POL-A", "POL-B"}.issubset(polizas), "Una actualización sin póliza pisó una póliza histórica existente.")
check("" in polizas, "La metadata sin póliza no quedó aislada como ficha de patente cuando había ambigüedad.")

# 9) Historial básico.
fid = r5["ficha"]["id"]
store.registrar_evento(fid, "documento_baja_generado", {"FECHA_BAJA":"14/09/2026"}, usuario="test")
events = store.eventos(fid)
check(events and events[0]["tipo"] == "documento_baja_generado", "La ficha no conserva historial de eventos.")

_tmp.cleanup()
print("OK - ficha persistente: fuentes por campo, importes, fechas, asistencia, compañías e historial")
