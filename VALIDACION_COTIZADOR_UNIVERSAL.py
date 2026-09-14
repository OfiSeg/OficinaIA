# -*- coding: utf-8 -*-
"""Regresiones offline del cotizador universal y sus contratos de interfaz."""
from pathlib import Path
from decimal import Decimal

from cotizacion_document_service import catalogo_companias
from mercantil_cotizador import calcular_descuento
from quote_normalizer import PROFILE_LABELS, PERFIL_LB, PERFIL_LB1


BASE = Path(__file__).resolve().parent
JS = (BASE / "static" / "js" / "app.js").read_text(encoding="utf-8")
HTML = (BASE / "templates" / "documentos.html").read_text(encoding="utf-8")
APP = (BASE / "app.py").read_text(encoding="utf-8")
BASE_HTML = (BASE / "templates" / "base.html").read_text(encoding="utf-8")
ESTILO = (BASE / "static" / "css" / "estilo.css").read_text(encoding="utf-8")
DESIGN = (BASE / "static" / "css" / "design-system.css").read_text(encoding="utf-8")


def check(condicion, mensaje):
    if not condicion:
        raise AssertionError(mensaje)


# ATM nunca muestra ambos catálogos a la vez; desconocido cae conservadoramente
# en auto, por lo que MOTOS tampoco aparece por defecto.
check("matrix.hidden=esMoto" in JS, "ATM auto no oculta la matriz de motos correctamente.")
check("motoRow.hidden=!esMoto" in JS, "ATM moto/auto perdió visibilidad condicional.")
check("==='moto'?'moto':'auto'" in JS, "El tipo ATM desconocido dejó de caer en auto.")

# Mercantil tiene un solo control global y ninguna fila seleccionada crea un
# input por cobertura. La fórmula sigue siendo la misma; 40% debe recalcular.
check(HTML.count('id="mercantilBonificacion"') == 1, "Mercantil no tiene una única bonificación global.")
check("const discount=document.createElement('span')" in JS, "La bonificación volvió a ser editable por fila.")
check("recalcularMercantilTodas" in JS, "La bonificación global no recalcula todas las alternativas.")
for precio in (100000, 179666, 250000):
    resultado = calcular_descuento(precio, 40, 50)
    check(Decimal(resultado["precio_final"]) == Decimal(precio) * Decimal("0.60"), "Mercantil 35→40 no recalculó correctamente.")

# La identidad se edita por source id, no mediante una variable global de
# compañía. Elegir una conocida toma el logo del manifiesto; otra queda textual.
check("fuenteCotizacionPorId" in JS and "confirmarCompaniaFuente" in JS, "Falta identidad de compañía por fuente.")
check("compania_confirmada" in JS and "compania_detectada" in JS, "No se separó compañía detectada de confirmada.")
check("/api/cotizaciones/companias" in APP, "Falta catálogo de logos para Cotizaciones.")
catalogo = catalogo_companias(BASE / "static" / "img" / "companias")
check(len(catalogo) == 7, "El manifiesto no ofrece las siete compañías normalizadas.")
for item in catalogo:
    check((BASE / "static" / "img" / "companias" / item["file"]).is_file(), f"Falta logo de {item['nombre']}.")

# UI, WhatsApp y carta parten del mismo objeto comercial de salida.
check("modeloComercialOpcion" in JS, "Falta el adaptador comercial único.")
check("nombre_comercial" in JS and "variante_comercial" in JS and "variante_grua" in JS, "El modelo comercial está incompleto.")
check("modelo.titulo_comercial" in JS, "Las filas seleccionadas no consumen el título comercial.")
check("gruaTokenExplicito" in JS, "Una variante de grúa explícita puede perderse al reconstruir el título.")

# Los perfiles LB/LB1 no pueden volver a exponerse como códigos técnicos.
check(not PROFILE_LABELS[PERFIL_LB].lower().startswith("cobertura lb"), "LB conserva un nombre técnico en vez de comercial.")
check(not PROFILE_LABELS[PERFIL_LB1].lower().startswith("cobertura lb"), "LB1 conserva un nombre técnico en vez de comercial.")
check("LB:'Robo e Incendio + Robo Parcial al Amparo + Accidente Total'" in JS, "Frontend y normalizador no comparten el nombre comercial de LB.")
check("LB1:'Robo e Incendio + Robo Parcial al Amparo'" in JS, "Frontend y normalizador no comparten el nombre comercial de LB1.")

# design-system.css se carga después de estilo.css: la uniformidad definitiva debe
# vivir en la hoja que realmente gana la cascada, no en una regla inefectiva.
check(BASE_HTML.index("css/estilo.css") < BASE_HTML.index("css/design-system.css"), "Cambió el orden esperado de hojas de estilo.")
check("COTIZADOR UNIVERSAL · UNIFORMIDAD FINAL 2026-09-13" in DESIGN, "La capa visual final del cotizador no está en design-system.css.")
check("COTIZADOR UNIVERSAL · UNIFORMIDAD VISUAL / MARCAS 2026-09-13" not in ESTILO, "Quedó una capa duplicada e inefectiva en estilo.css.")
check(".quote-selected-row" in DESIGN and ".quote-source-brand-mark img" in DESIGN, "Faltan reglas comunes para seleccionadas o favicons de compañía.")

print("OK - cotizador universal: UI común, bonificación global, compañía editable, nombres comerciales y cascada visual")
