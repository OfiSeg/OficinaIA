from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote




# Identidad visual y aliases separados de la URL de acceso.
# Son valores iniciales editables: la UI nunca depende de que el portal de
# productores publique un favicon correcto.
DEFAULT_COMPANY_BRANDS = {
    "self": {
        "icon_url": "https://www.fedpat.com.ar/",
        "color": "#1976A8",
        "aliases": ["Self", "Federación Patronal", "Federacion Patronal", "FedPat"],
    },
    "atm": {
        "icon_url": "https://atmseguros.com.ar/",
        "color": "#D9363E",
        "aliases": ["ATM", "ATM Seguros"],
    },
    "triunfo": {
        "icon_url": "https://triunfoseguros.com/",
        "color": "#D9364A",
        "aliases": ["Triunfo", "Triunfo Seguros"],
    },
    "mercantil-andina": {
        "icon_url": "https://mercantilandina.com.ar/",
        "color": "#17879A",
        "aliases": ["Mercantil Andina", "La Mercantil Andina", "Mercantil", "MA"],
    },
    "rivadavia": {"aliases": ["Rivadavia", "Seguros Rivadavia"]},
    "prof": {"aliases": ["Prof", "PROF", "Prof Seguros"]},
    "ags": {
        "icon_url": "https://agrosaltaseguros.net/",
        "color": "#FF931E",
        "aliases": ["Ags", "AGS", "AgroSalta", "Agrosalta", "Agro Salta"],
    },
    "san-cristobal": {"aliases": ["San Cristobal", "San Cristóbal"]},
    "euroamerica": {"aliases": ["EuroAmerica", "Euro America"]},
    "allianz": {"aliases": ["Allianz"]},
}

DEFAULT_TOOL_BRANDS = {
    "gmail": {"icon_url": "/static/img/herramientas/gmail.png", "aliases": ["Gmail", "Google Mail"]},
    "whatsapp": {"icon_url": "/static/img/herramientas/whatsapp.png", "aliases": ["WhatsApp"]},
    "datacar": {"icon_url": "/static/img/herramientas/datacar.png", "aliases": ["Datacar"]},
    "nosis": {"icon_url": "/static/img/herramientas/nosis.png", "aliases": ["Nosis"]},
    "chatgpt": {"icon_url": "/static/img/herramientas/chatgpt.png", "aliases": ["ChatGPT"]},
    "drive": {"icon_url": "/static/img/herramientas/drive.png", "aliases": ["Drive", "Google Drive"]},
    "envios_ya": {"icon_url": "/static/img/herramientas/envios_ya.png", "aliases": ["Envíos Ya", "Envios Ya"]},
}


def _normalizar_aliases(value):
    if isinstance(value, str):
        value = re.split(r"[,;\n]+", value)
    if not isinstance(value, list):
        return []
    salida = []
    vistos = set()
    for raw in value[:30]:
        alias = str(raw or "").strip()
        if not alias:
            continue
        key = alias.casefold()
        if key in vistos:
            continue
        vistos.add(key)
        salida.append(alias[:100])
    return salida


def _brand_defaults(prefijo: str, ident: str, nombre: str = ""):
    tabla = DEFAULT_COMPANY_BRANDS if prefijo == "compania" else DEFAULT_TOOL_BRANDS
    ident_key = str(ident or "").lower()
    if ident_key in tabla:
        return dict(tabla[ident_key])
    nombre_key = str(nombre or "").casefold().strip()
    if nombre_key:
        for meta in tabla.values():
            aliases = _normalizar_aliases(meta.get("aliases", []))
            if any(nombre_key == alias.casefold().strip() for alias in aliases):
                return dict(meta)
    return {}


def _enriquecer_item_marca(item: dict, prefijo: str):
    item = dict(item or {})
    defaults = _brand_defaults(prefijo, item.get("id"), item.get("nombre", ""))
    icon_url = str(item.get("icon_url", item.get("favicon_url", defaults.get("icon_url", ""))) or "").strip()
    color = str(item.get("color", defaults.get("color", "")) or "").strip().upper()
    if color and not re.fullmatch(r"#[0-9A-F]{6}", color):
        color = ""
    aliases = _normalizar_aliases(item.get("aliases", defaults.get("aliases", [])))
    nombre = str(item.get("nombre", "") or "").strip()
    if nombre and nombre.casefold() not in {x.casefold() for x in aliases}:
        aliases.insert(0, nombre)
    item["icon_url"] = icon_url
    item["color"] = color
    item["aliases"] = aliases
    return item


def resolver_icono_marca(item: dict | None):
    """Devuelve un src estable para <img> sin mezclar acceso con branding.

    ``icon_url`` puede ser una imagen directa, un asset local o una web cuya
    identidad se resuelve mediante el servicio de favicons. Si no existe, se
    usa la URL de acceso como fallback.
    """
    item = item if isinstance(item, dict) else {}
    source = str(item.get("icon_url") or item.get("url") or "").strip()
    if not source:
        return ""
    if source.startswith(("/static/", "data:")):
        return source
    if re.search(r"\.(?:png|jpe?g|webp|gif|svg|ico)(?:[?#].*)?$", source, re.IGNORECASE):
        return source
    if re.match(r"^https?://", source, re.IGNORECASE):
        return "https://www.google.com/s2/favicons?sz=64&domain_url=" + quote(source, safe="")
    return ""


DEFAULT_CIAS_LINKS = [
    ("Self", "https://online.fedpat.com.ar/self/index.jsp"),
    ("ATM", "https://extranet.atmseguros.com.ar/ATM_COM_PROD/servlet/ar.com.glmsa.seguros.comercial.hlogin"),
    ("Rivadavia", "https://www.sistemas.segurosrivadavia.com/sistemas/login/login_intra_pas.php?u=P"),
    ("Triunfo", "https://www.triunfonet.com.ar/gauswebtriunfo/servlet/hlogon"),
    ("Prof", "https://pasnet.profseguros.seg.ar/Default.aspx"),
    ("Ags", "https://www.agsnet.com.ar/ingreprod.php"),
    ("San Cristobal", "https://productores.sancristobal.com.ar/"),
    ("Mercantil Andina", "https://servicios.mercantilandina.com.ar/sigmav3/"),
    ("EuroAmerica", "https://pas.euroamericaseguros.seg.ar/login"),
    ("Allianz", "https://auth.allianz.com.ar/login"),
]


SIDEBAR_ORDER_DEFAULT = [
    "chat", "companies", "excel", "pending", "estudio", "manuals", "salud"
]


CHAT_SHORTCUT_ACTIONS = {
    "patente": {"label": "Patente", "subtitle": "Consultar vehículo", "icon": "patente"},
    "cedula": {"label": "Cédula", "subtitle": "Adjuntá la cédula", "icon": "cedula"},
    "alta": {"label": "Alta asegurado", "subtitle": "Adjuntá la póliza", "icon": "policy"},
    "atm": {"label": "Cotización", "subtitle": "Comparar y generar propuesta", "icon": "cotizar"},
    "mail": {"label": "Mail", "subtitle": "Enviar correo", "icon": "mail"},
    "document": {"label": "Documentos", "subtitle": "PDF, Excel o archivo", "icon": "file-generic"},
    "photos": {"label": "Fotos", "subtitle": "Adjuntar imágenes", "icon": "image"},
    "portfolio": {"label": "Buscar cartera", "subtitle": "Asegurados y pólizas", "icon": "search"},
    "cuit": {"label": "CUIT / CUIL", "subtitle": "Buscar en ARCA", "icon": "cuit"},
}
CHAT_SHORTCUTS_DEFAULT = [
    "action:patente", "action:cedula", "action:alta", "action:atm"
]


def normalizar_chat_shortcuts(value, config: dict):
    """Valida accesos del welcome sin inferir claves externas inexistentes.

    Admite acciones internas conocidas y referencias explícitas a compañías o
    herramientas configuradas. Mantiene orden y elimina duplicados.
    """
    entrada = value if isinstance(value, list) else list(CHAT_SHORTCUTS_DEFAULT)
    company_ids = {str(x.get("id")) for x in (config.get("companias") or []) if isinstance(x, dict)}
    tool_ids = {str(x.get("id")) for x in (config.get("herramientas") or []) if isinstance(x, dict)}
    salida = []
    for raw in entrada[:24]:
        key = str(raw or "").strip()
        if not key or key in salida:
            continue
        if key.startswith("action:"):
            action = key.split(":", 1)[1]
            if action in CHAT_SHORTCUT_ACTIONS:
                salida.append(key)
        elif key.startswith("company:"):
            if key.split(":", 1)[1] in company_ids:
                salida.append(key)
        elif key.startswith("tool:"):
            if key.split(":", 1)[1] in tool_ids:
                salida.append(key)
    return salida


def resolver_chat_shortcuts(config: dict):
    """Devuelve tarjetas listas para renderizar desde el primer frame."""
    keys = normalizar_chat_shortcuts(config.get("chat_shortcuts"), config)
    companies = {str(x.get("id")): x for x in (config.get("companias") or []) if isinstance(x, dict)}
    tools = {str(x.get("id")): x for x in (config.get("herramientas") or []) if isinstance(x, dict)}
    out = []
    for key in keys:
        kind, ident = key.split(":", 1)
        if kind == "action":
            meta = CHAT_SHORTCUT_ACTIONS.get(ident)
            if meta:
                out.append({"key": key, "kind": kind, "action": ident, **meta})
        elif kind == "company":
            item = companies.get(ident)
            if item:
                out.append({"key": key, "kind": kind, "id": ident, "label": item.get("nombre") or "Compañía", "subtitle": "Abrir compañía", "url": item.get("url") or "", "icon_url": item.get("icon_url") or "", "color": item.get("color") or "", "aliases": item.get("aliases") or []})
        elif kind == "tool":
            item = tools.get(ident)
            if item:
                out.append({"key": key, "kind": kind, "id": ident, "label": item.get("nombre") or "Herramienta", "subtitle": "Abrir herramienta", "url": item.get("url") or "", "icon_url": item.get("icon_url") or "", "color": item.get("color") or "", "aliases": item.get("aliases") or []})
    return out


def _normalizar_sidebar_order(value):
    """Normaliza el orden visual de los módulos principales sin aceptar claves arbitrarias."""
    validos = list(SIDEBAR_ORDER_DEFAULT)
    entrada = value if isinstance(value, list) else []
    salida = []
    for item in entrada:
        clave = str(item or "").strip().lower()
        if clave in validos and clave not in salida:
            salida.append(clave)
    for clave in validos:
        if clave not in salida:
            salida.append(clave)
    return salida


def companias_sidebar_default():
    salida = []
    for i, (nombre, url) in enumerate(DEFAULT_CIAS_LINKS):
        ident = re.sub(r"[^a-z0-9_-]+", "-", str(nombre).lower()).strip("-") or f"compania-{i+1}"
        salida.append(_enriquecer_item_marca({"id": ident, "nombre": nombre, "url": url, "visible": True}, "compania"))
    return salida


def herramientas_legacy_a_lista(visibles=None, urls=None):
    visibles = visibles if isinstance(visibles, dict) else {}
    urls = urls if isinstance(urls, dict) else {}
    catalogo = [
        ("gmail", "Gmail", "https://mail.google.com/"),
        ("whatsapp", "WhatsApp", "https://web.whatsapp.com/"),
        ("datacar", "Datacar", "https://www.datacar.com.ar/"),
        ("nosis", "Nosis", "https://www.nosis.com/es"),
        ("chatgpt", "ChatGPT", "https://chatgpt.com/"),
        ("drive", "Drive", "https://drive.google.com/"),
        ("envios_ya", "Envíos Ya", ""),
    ]
    salida = []
    for clave, nombre, url_default in catalogo:
        url = str(urls.get(clave, url_default) or "").strip()
        if not url:
            continue
        salida.append(_enriquecer_item_marca({"id": clave, "nombre": nombre, "url": url, "visible": bool(visibles.get(clave, True))}, "herramienta"))
    return salida


def _normalizar_items(items, prefijo: str):
    if not isinstance(items, list):
        return []
    salida = []
    vistos = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("nombre", "") or "").strip()
        url = str(item.get("url", "") or "").strip()
        ident = re.sub(r"[^a-z0-9_-]+", "-", str(item.get("id", "") or "").lower()).strip("-")
        if not ident:
            ident = f"{prefijo}-{i+1}"
        base, n = ident, 2
        while ident in vistos:
            ident = f"{base}-{n}"
            n += 1
        vistos.add(ident)
        if nombre and url:
            enriched = _enriquecer_item_marca({**item, "id": ident, "nombre": nombre, "url": url, "visible": bool(item.get("visible", True))}, prefijo)
            salida.append(enriched)
    return salida


def default_config():
    return {
        "nombre_oficina": "Oficina Seguros",
        "notificaciones": True,
        "color_principal": "#122033",
        "color_acento": "#0d8b7c",
        "color_fondo": "#f7f9fb",
        "color_sidebar": "#ffffff",
        "color_botones": "#122033",
        "herramientas": [],
        "companias": companias_sidebar_default(),
        "sidebar_order": list(SIDEBAR_ORDER_DEFAULT),
        "chat_shortcuts": list(CHAT_SHORTCUTS_DEFAULT),
        "tips_visibles": True,
        "excel_visible": True,
    }


def cargar_configuracion(*, usar_pg: bool, pg_obtener: Callable[[], dict | None] | None, config_file: Path):
    config = default_config()
    try:
        datos = None
        if usar_pg and pg_obtener is not None:
            try:
                datos = pg_obtener()
            except Exception as error:
                print("ERROR cargar_configuracion PG:", error)
        elif config_file.exists():
            datos = json.loads(config_file.read_text(encoding="utf-8"))

        if isinstance(datos, dict):
            config.update(datos)
            herramientas = config.get("herramientas")
            if not isinstance(herramientas, list):
                herramientas = herramientas_legacy_a_lista(config.get("herramientas_visibles"), config.get("herramientas_urls"))
            config["herramientas"] = _normalizar_items(herramientas, "herramienta")

            companias_cfg = config.get("companias")
            if not isinstance(companias_cfg, list):
                companias_cfg = companias_sidebar_default()
            config["companias"] = _normalizar_items(companias_cfg, "compania")
            config["sidebar_order"] = _normalizar_sidebar_order(config.get("sidebar_order"))
            config["chat_shortcuts"] = normalizar_chat_shortcuts(config.get("chat_shortcuts"), config)
            config["excel_visible"] = bool(config.get("excel_visible", True))
            config["tips_visibles"] = bool(config.get("tips_visibles", True))
    except Exception:
        pass
    return config


def validar_y_construir_config(data: dict, config_actual: dict):
    data = data if isinstance(data, dict) else {}
    config = dict(config_actual)
    nombre = str(data.get("nombre_oficina", config["nombre_oficina"])).strip()
    if not nombre:
        return None, "El nombre de la oficina no puede estar vacío."

    colores = {
        "color_principal": data.get("color_principal", config["color_principal"]),
        "color_acento": data.get("color_acento", config["color_acento"]),
        "color_fondo": data.get("color_fondo", config["color_fondo"]),
        "color_sidebar": data.get("color_sidebar", config["color_sidebar"]),
        "color_botones": data.get("color_botones", config["color_botones"]),
    }
    for clave, valor in list(colores.items()):
        valor = str(valor).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", valor):
            return None, f"El color {clave} no es válido."
        colores[clave] = valor.upper()

    herramientas_recibidas = data.get("herramientas", config.get("herramientas", []))
    if not isinstance(herramientas_recibidas, list):
        return None, "La configuración de herramientas no es válida."
    herramientas, error = _validar_items_config(herramientas_recibidas, "herramienta", 60, "herramienta")
    if error:
        return None, error

    companias_recibidas = data.get("companias", config.get("companias", companias_sidebar_default()))
    if not isinstance(companias_recibidas, list):
        return None, "La configuración de compañías no es válida."
    companias, error = _validar_items_config(companias_recibidas, "compania", 80, "compañía")
    if error:
        return None, error

    config["nombre_oficina"] = nombre
    config["notificaciones"] = bool(data.get("notificaciones", config.get("notificaciones", True)))
    config["herramientas"] = herramientas
    config["companias"] = companias
    config["sidebar_order"] = _normalizar_sidebar_order(data.get("sidebar_order", config.get("sidebar_order")))
    config["chat_shortcuts"] = normalizar_chat_shortcuts(data.get("chat_shortcuts", config.get("chat_shortcuts")), config)
    config["tips_visibles"] = bool(data.get("tips_visibles", config.get("tips_visibles", True)))
    config["excel_visible"] = bool(data.get("excel_visible", config.get("excel_visible", True)))
    config.pop("herramientas_visibles", None)
    config.pop("herramientas_urls", None)
    config.update(colores)
    return config, None


def _validar_items_config(items, prefijo: str, max_nombre: int, etiqueta: str):
    salida, ids = [], set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return None, f"Hay una {etiqueta} inválida."
        nombre = str(item.get("nombre", "") or "").strip()
        url = str(item.get("url", "") or "").strip()
        if not nombre or not url:
            return None, f"Cada {etiqueta} necesita nombre y URL."
        if len(nombre) > max_nombre or len(url) > 1000:
            return None, f"Nombre o URL de {etiqueta} demasiado largo."
        if not re.match(r"^https?://", url, re.IGNORECASE):
            return None, f"La URL de {nombre} debe comenzar con http:// o https://"

        icon_url = str(item.get("icon_url", item.get("favicon_url", "")) or "").strip()
        if len(icon_url) > 1000:
            return None, f"El link de logo/favicon de {nombre} es demasiado largo."
        if icon_url and not (re.match(r"^https?://", icon_url, re.IGNORECASE) or icon_url.startswith("/static/")):
            return None, f"El link de logo/favicon de {nombre} debe ser http(s) o un asset /static/."

        color = str(item.get("color", "") or "").strip().upper()
        if color and not re.fullmatch(r"#[0-9A-F]{6}", color):
            return None, f"El color de {nombre} debe tener formato #RRGGBB."
        aliases = _normalizar_aliases(item.get("aliases", []))

        ident = re.sub(r"[^a-z0-9_-]+", "-", str(item.get("id", "") or "").lower()).strip("-") or f"{prefijo}-{i+1}"
        base, n = ident, 2
        while ident in ids:
            ident = f"{base}-{n}"
            n += 1
        ids.add(ident)
        salida.append(_enriquecer_item_marca({
            "id": ident, "nombre": nombre, "url": url,
            "visible": bool(item.get("visible", True)),
            "icon_url": icon_url, "color": color, "aliases": aliases,
        }, prefijo))
    return salida, None


def guardar_configuracion(config: dict, *, usar_pg: bool, pg_guardar: Callable[[dict], None] | None, config_file: Path):
    if usar_pg:
        if pg_guardar is None:
            raise RuntimeError("Persistencia PG de configuración no disponible")
        pg_guardar(config)
    else:
        config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
