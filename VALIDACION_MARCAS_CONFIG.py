# -*- coding: utf-8 -*-
"""Pruebas offline de configuración de marcas y separación acceso/branding."""
from pathlib import Path
import config_service

cfg = config_service.default_config()
by_name = {x["nombre"]: x for x in cfg["companias"]}

atm = by_name["ATM"]
assert "extranet.atmseguros.com.ar" in atm["url"]
assert atm["icon_url"] == "https://atmseguros.com.ar/"
assert atm["color"].startswith("#")
assert "ATM Seguros" in atm["aliases"]

fed = by_name["Self"]
assert "online.fedpat.com.ar" in fed["url"]
assert "fedpat.com.ar" in fed["icon_url"]
assert any("Feder" in x for x in fed["aliases"])

tri = by_name["Triunfo"]
assert "triunfonet.com.ar" in tri["url"]
assert "triunfoseguros.com" in tri["icon_url"]

ma = by_name["Mercantil Andina"]
assert "servicios.mercantilandina.com.ar" in ma["url"]
assert "mercantilandina.com.ar" in ma["icon_url"]

custom, error = config_service.validar_y_construir_config({
    "nombre_oficina": "Oficina",
    "companias": [{
        "id": "atm",
        "nombre": "ATM",
        "url": "https://portal-productores.ejemplo/",
        "icon_url": "https://atmseguros.com.ar/",
        "color": "#CC3344",
        "aliases": ["ATM Seguros", "ATM Productores"],
        "visible": True,
    }],
    "herramientas": [{
        "id": "gmail",
        "nombre": "Gmail",
        "url": "https://mail.google.com/",
        "icon_url": "/static/img/herramientas/gmail.png",
        "color": "",
        "aliases": ["Mail"],
        "visible": True,
    }],
    "sidebar_order": cfg["sidebar_order"],
    "chat_shortcuts": ["company:atm", "tool:gmail"],
}, cfg)
assert error is None, error
assert custom["companias"][0]["url"] != custom["companias"][0]["icon_url"]
assert custom["companias"][0]["color"] == "#CC3344"
shortcuts = config_service.resolver_chat_shortcuts(custom)
assert shortcuts[0]["icon_url"] == "https://atmseguros.com.ar/"
assert shortcuts[1]["icon_url"].endswith("gmail.png")

js = Path("static/js/app.js").read_text(encoding="utf-8")
assert "marcaCompaniaPara" in js
assert "marcarFuenteVisualReciente('mercantil')" in js
assert "presentarFuenteCotizacion(section,item.id,companiaEfectivaFuente(item,'Federación Patronal'))" in js
assert "resolverCompaniaCotizacion" in js and "logo_url" in js
# En UI el favicon configurable debe tener prioridad sobre el PNG horizontal
# del manifiesto documental.
assert "item?.icon_url||item?.url||item?.favicon_url||item?.logo_url" in js
assert "icon_url:String(item.icon_url||item.url||'').trim()" in js
css = Path("static/css/design-system.css").read_text(encoding="utf-8")
assert "quote-source-branded" in css
assert "#federacionQuoteSources,#genericQuoteSources,#manualQuoteSources{display:contents" in css
assert ".atm-selected-summary" in css and "grid-template-columns:minmax(0,1fr)!important" in css
assert ".atm-selected-item.quote-selected-row" in css

print("OK - favicons UI, marcas configurables y presentación ATM uniforme")
