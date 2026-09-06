from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterable


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


def companias_sidebar_default():
    salida = []
    for i, (nombre, url) in enumerate(DEFAULT_CIAS_LINKS):
        ident = re.sub(r"[^a-z0-9_-]+", "-", str(nombre).lower()).strip("-") or f"compania-{i+1}"
        salida.append({"id": ident, "nombre": nombre, "url": url, "visible": True})
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
        salida.append({"id": clave, "nombre": nombre, "url": url, "visible": bool(visibles.get(clave, True))})
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
            salida.append({"id": ident, "nombre": nombre, "url": url, "visible": bool(item.get("visible", True))})
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
        ident = re.sub(r"[^a-z0-9_-]+", "-", str(item.get("id", "") or "").lower()).strip("-") or f"{prefijo}-{i+1}"
        base, n = ident, 2
        while ident in ids:
            ident = f"{base}-{n}"
            n += 1
        ids.add(ident)
        salida.append({"id": ident, "nombre": nombre, "url": url, "visible": bool(item.get("visible", True))})
    return salida, None


def guardar_configuracion(config: dict, *, usar_pg: bool, pg_guardar: Callable[[dict], None] | None, config_file: Path):
    if usar_pg:
        if pg_guardar is None:
            raise RuntimeError("Persistencia PG de configuración no disponible")
        pg_guardar(config)
    else:
        config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
