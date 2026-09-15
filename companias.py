"""Registro canónico de compañías de OficinaIA.

Una compañía se define una sola vez acá. El resto del sistema consume esta
identidad para aliases, nombre visible, accesos, favicon y contactos. Que una
compañía exista en el registro NO implica que tenga parser, cotizador, manual o
servicio de grúa confirmado.
"""
from __future__ import annotations

import re
import unicodedata
from copy import deepcopy


# ``key`` es estable para UI/assets; ``codigo`` conserva el valor histórico que
# OficinaIA guarda/usa en sus planillas y reglas ya existentes.
_REGISTRY = {
    "federacion_patronal": {
        "codigo": "FEDERACION", "nombre": "Federación Patronal",
        "aliases": ["Self", "Federación", "Federacion", "Federación Patronal", "Federacion Patronal", "Fed", "FedPat", "federacionpatronal"],
        "portal_id": "self", "portal_nombre": "Self",
        "portal_url": "https://online.fedpat.com.ar/self/index.jsp",
        "icon_url": "https://www.fedpat.com.ar/", "color": "#1976A8", "sidebar_default": True,
        "envios_filename": "FEDERACION PATRONAL", "coti_enabled": True, "coti_nombre": "Federación Patronal", "manuales_enabled": True,
    },
    "atm": {
        "codigo": "ATM", "nombre": "ATM", "aliases": ["ATM", "ATM Seguros"],
        "portal_id": "atm", "portal_nombre": "ATM",
        "portal_url": "https://extranet.atmseguros.com.ar/ATM_COM_PROD/servlet/ar.com.glmsa.seguros.comercial.hlogin",
        "icon_url": "https://atmseguros.com.ar/", "color": "#D9363E", "sidebar_default": True,
        "envios_filename": "ATM SEGUROS", "coti_enabled": True, "coti_nombre": "ATM", "manuales_enabled": True,
    },
    "rivadavia": {
        "codigo": "RIVADAVIA", "nombre": "Rivadavia", "aliases": ["Rivadavia", "Rivadavia Seguros", "Seguros Rivadavia"],
        "portal_id": "rivadavia", "portal_nombre": "Rivadavia",
        "portal_url": "https://www.sistemas.segurosrivadavia.com/sistemas/login/login_intra_pas.php?u=P", "sidebar_default": True,
        "envios_filename": "RIVADAVIA", "coti_enabled": True, "coti_nombre": "Rivadavia", "manuales_enabled": True,
    },
    "triunfo": {
        "codigo": "TRIUNFO", "nombre": "Triunfo", "aliases": ["Triunfo", "Triunfo Seguros"],
        "portal_id": "triunfo", "portal_nombre": "Triunfo",
        "portal_url": "https://www.triunfonet.com.ar/gauswebtriunfo/servlet/hlogon",
        "icon_url": "https://triunfoseguros.com/", "color": "#D9364A", "sidebar_default": True,
        "envios_filename": "TRIUNFO SEGUROS", "coti_enabled": True, "coti_nombre": "Triunfo", "manuales_enabled": True,
    },
    "prof": {
        "codigo": "PROF", "nombre": "PROF",
        "aliases": ["Prof", "PROF", "Prof Seguros", "Productores de Frutas Argentinas", "Productores de Frutas"],
        "portal_id": "prof", "portal_nombre": "Prof",
        "portal_url": "https://pasnet.profseguros.seg.ar/Default.aspx", "sidebar_default": True,
        "envios_filename": "PROF SEGUROS", "coti_enabled": True, "coti_nombre": "Prof", "manuales_enabled": True,
    },
    "agrosalta": {
        "codigo": "AGS", "nombre": "AgroSalta",
        "aliases": ["Ags", "AGS", "AgroSalta", "Agrosalta", "Agro Salta", "Compañía de Seguros AgroSalta", "Compania de Seguros Agrosalta"],
        "portal_id": "ags", "portal_nombre": "Ags",
        "portal_url": "https://www.agsnet.com.ar/ingreprod.php",
        "icon_url": "https://agrosaltaseguros.net/", "color": "#FF931E", "sidebar_default": True,
        "envios_filename": "AGROSALTA SEGUROS", "coti_enabled": True, "coti_nombre": "AGS", "manuales_enabled": True,
    },
    "san_cristobal": {
        "codigo": "SAN CRISTOBAL", "nombre": "San Cristóbal",
        "aliases": ["San Cristobal", "San Cristóbal", "San Cristobal Seguros", "San Cristóbal Seguros", "Grupo San Cristobal", "Grupo San Cristóbal", "sancristobal"],
        "portal_id": "san-cristobal", "portal_nombre": "San Cristobal",
        "portal_url": "https://productores.sancristobal.com.ar/", "sidebar_default": True,
        "envios_filename": "SAN CRISTOBAL", "coti_enabled": True, "coti_nombre": "San Cristóbal", "manuales_enabled": True,
    },
    "mercantil_andina": {
        "codigo": "MERCANTIL", "nombre": "Mercantil Andina",
        "aliases": ["Mercantil Andina", "La Mercantil Andina", "Mercantil", "MA", "mercantilandina"],
        "portal_id": "mercantil-andina", "portal_nombre": "Mercantil Andina",
        "portal_url": "https://servicios.mercantilandina.com.ar/sigmav3/",
        "icon_url": "https://mercantilandina.com.ar/", "color": "#17879A", "sidebar_default": True,
        "envios_filename": "MERCANTIL ANDINA", "coti_enabled": True, "coti_nombre": "Mercantil Andina", "manuales_enabled": True,
    },
    "euroamerica": {
        "codigo": "EUROAMERICA", "nombre": "EuroAmérica", "aliases": ["EuroAmerica", "Euro América", "Euro America", "EuroAmérica"],
        "portal_id": "euroamerica", "portal_nombre": "EuroAmerica",
        "portal_url": "https://pas.euroamericaseguros.seg.ar/login", "sidebar_default": True,
        "envios_filename": "EUROAMERICA", "coti_enabled": True, "coti_nombre": "Euroamerica", "manuales_enabled": True,
    },
    "allianz": {
        "codigo": "ALLIANZ", "nombre": "Allianz", "aliases": ["Allianz", "Allianz Seguros"],
        "portal_id": "allianz", "portal_nombre": "Allianz",
        "portal_url": "https://auth.allianz.com.ar/login", "sidebar_default": True,
        "envios_filename": "ALLIANZ", "coti_enabled": True, "coti_nombre": "Allianz",
    },
    # Compañías que OficinaIA ya reconoce aunque hoy no tengan acceso directo
    # preconfigurado. Permanecen en el mismo registro para que cotizaciones,
    # documentos, búsqueda y futuros módulos no creen listas paralelas.
    "la_segunda": {"codigo": "LA SEGUNDA", "nombre": "La Segunda", "aliases": ["La Segunda", "La Segunda Seguros", "lasegunda"]},
    "rio_uruguay": {"codigo": "RIO URUGUAY", "nombre": "Río Uruguay", "aliases": ["Río Uruguay", "Rio Uruguay", "Río Uruguay Seguros", "Rio Uruguay Seguros", "riouruguay"]},
    "sancor": {"codigo": "SANCOR SEGUROS", "nombre": "Sancor Seguros", "aliases": ["Sancor", "San Cor", "Sancor Seguros", "sancorseguros"]},
    "provincia": {"codigo": "PROVINCIA", "nombre": "Provincia Seguros", "aliases": ["Provincia", "Provincia Seguros"]},
    "mapfre": {"codigo": "MAPFRE", "nombre": "Mapfre", "aliases": ["Mapfre", "Mapfre Seguros", "Mapfre Argentina"]},
    "parana": {"codigo": "PARANA", "nombre": "Paraná Seguros", "aliases": ["Paraná", "Parana", "Paraná Seguros", "Parana Seguros"]},
    "zurich": {"codigo": "ZURICH", "nombre": "Zurich", "aliases": ["Zurich", "Zurich Seguros", "Zurich Retiro"]},
    "toval": {"codigo": "TOVAL", "nombre": "Toval", "aliases": ["Toval"]},
    # Identidades documentales/operativas que ya aparecían en OficinaIA en
    # títulos, metadatos o búsquedas. Quedan centralizadas aunque hoy no tengan
    # cotizador, acceso directo o manual cargado.
    "sura": {"codigo": "SURA", "nombre": "Sura", "aliases": ["Sura", "Sura Seguros"]},
    "experta": {"codigo": "EXPERTA", "nombre": "Experta", "aliases": ["Experta", "Experta Seguros", "Experta ART"]},
    "nacion": {"codigo": "NACION", "nombre": "Nación Seguros", "aliases": ["Nación", "Nacion", "Nación Seguros", "Nacion Seguros"]},
    "hdi": {"codigo": "HDI", "nombre": "HDI", "aliases": ["HDI", "HDI Seguros"]},
    "chubb": {"codigo": "CHUBB", "nombre": "Chubb", "aliases": ["Chubb", "Chubb Seguros"]},
    "smg": {"codigo": "SMG", "nombre": "SMG", "aliases": ["SMG", "SMG Seguros", "Swiss Medical Seguros"]},
    "galeno": {"codigo": "GALENO", "nombre": "Galeno", "aliases": ["Galeno", "Galeno Seguros", "Galeno ART"]},
    "prevencion": {"codigo": "PREVENCION", "nombre": "Prevención", "aliases": ["Prevención", "Prevencion", "Prevención ART", "Prevencion ART"]},
}


# Contactos operativos. ``tipo=contacto_general`` sirve para conservar un
# número sin presentarlo como grúa. La póliza concreta decide si la asistencia
# está incluida; este catálogo sólo responde cómo contactarla cuando corresponda.
_ASISTENCIAS = {
    "AGS": {
        "tipo": "asistencia", "etiqueta": "Asistencia y grúa",
        "whatsapp": ["+54 9 11 2468-5636"],
        "telefonos": ["0387-4210891", "0387-4219671"],
    },
    "ATM": {
        "tipo": "asistencia", "etiqueta": "Remolque",
        "telefonos": ["0800 345 1240"], "sms": ["SOS + PATENTE al 70703"],
    },
    "ALLIANZ": {
        "tipo": "asistencia", "etiqueta": "Asistencia",
        "telefonos": ["0800-888-24324"], "whatsapp": ["11-2808-0012"],
    },
    "SAN CRISTOBAL": {
        "tipo": "asistencia", "etiqueta": "Asistencia", "horario": "24 h",
        "telefonos": ["0810-222-8887", "0810-444-0100"],
    },
    "FEDERACION": {
        "tipo": "asistencia", "etiqueta": "Grúa y asistencia",
        "telefonos": ["0800-800-0022", "0800-222-0022"],
    },
    "MERCANTIL": {
        "tipo": "asistencia", "etiqueta": "Grúa y auxilio mecánico", "horario": "24 h",
        "telefonos": ["0800-777-2634", "011-4335-5792 (opción 1)"],
    },
    "RIVADAVIA": {
        "tipo": "asistencia", "etiqueta": "Grúa y asistencia", "horario": "24 h",
        "telefonos": ["0800-666-6789", "+54 11 2808-0012"],
    },
    "EUROAMERICA": {
        "tipo": "contacto_general", "etiqueta": "Contacto general",
        "telefonos": ["011 4312-8398"],
    },
    "PROF": {
        "tipo": "asistencia", "etiqueta": "Prof Assist", "horario": "24 h",
        "telefonos": ["0800-333-3512"],
    },
}


def _clave(texto):
    texto = str(texto or "").strip().lower().replace("_", " ")
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _alias_index():
    out = {}
    for key, item in _REGISTRY.items():
        values = [key, item.get("codigo"), item.get("nombre"), item.get("portal_nombre"), *(item.get("aliases") or [])]
        for alias in values:
            norm = _clave(alias)
            if norm:
                out[norm] = key
    return out


_ALIAS_TO_KEY = _alias_index()


def datos_compania(nombre_crudo):
    """Devuelve una copia del registro canónico o ``{}`` si no se conoce."""
    clave = _clave(nombre_crudo)
    key = _ALIAS_TO_KEY.get(clave)
    if not key:
        # Fallback conservador para expresiones como "Allianz Seguros SA".
        candidatos = []
        for alias, alias_key in _ALIAS_TO_KEY.items():
            if len(alias) >= 5 and re.search(rf"\b{re.escape(alias)}\b", clave):
                candidatos.append((len(alias), alias_key))
        if candidatos:
            candidatos.sort(reverse=True)
            key = candidatos[0][1]
    if not key:
        return {}
    item = deepcopy(_REGISTRY[key])
    item["key"] = key
    item["asistencia"] = deepcopy(_ASISTENCIAS.get(item.get("codigo")) or {})
    return item


def normalizar_compania(nombre_crudo):
    """Código canónico/histórico que OficinaIA usa internamente."""
    item = datos_compania(nombre_crudo)
    return item.get("codigo") if item else str(nombre_crudo or "").strip().upper()


def nombre_compania(nombre_crudo):
    """Nombre visible canónico sin inventar una marca desconocida."""
    item = datos_compania(nombre_crudo)
    return item.get("nombre") if item else str(nombre_crudo or "").replace("_", " ").strip().title()


def company_key(nombre_crudo):
    item = datos_compania(nombre_crudo)
    return item.get("key", "") if item else ""


def aliases_companias():
    """Compatibilidad: alias -> (código, nombre visible)."""
    out = {}
    for alias, key in _ALIAS_TO_KEY.items():
        item = _REGISTRY[key]
        out[alias] = (item["codigo"], item["nombre"])
    # Mantener además las grafías originales para UIs/tests que las muestran.
    for key, item in _REGISTRY.items():
        for alias in [item.get("nombre"), item.get("portal_nombre"), *(item.get("aliases") or [])]:
            if alias:
                out[str(alias)] = (item["codigo"], item["nombre"])
    return out


def catalogo_companias():
    salida = []
    for key, raw in _REGISTRY.items():
        item = deepcopy(raw)
        item["key"] = key
        item["asistencia"] = deepcopy(_ASISTENCIAS.get(item.get("codigo")) or {})
        salida.append(item)
    return salida


def nombres_companias(capacidad: str | None = None):
    items = catalogo_companias()
    if capacidad:
        items = [item for item in items if item.get(capacidad)]
    return [item["nombre"] for item in items]


def slug_compania(nombre_crudo):
    item = datos_compania(nombre_crudo)
    if item:
        return item["key"]
    return re.sub(r"[^a-z0-9]+", "_", _clave(nombre_crudo)).strip("_")


def companias_sidebar_default():
    """Items de accesos que vienen visibles de fábrica, derivados del registro."""
    out = []
    for item in catalogo_companias():
        if not item.get("sidebar_default") or not item.get("portal_url"):
            continue
        out.append({
            "id": item.get("portal_id") or item["key"].replace("_", "-"),
            "nombre": item.get("portal_nombre") or item["nombre"],
            "url": item.get("portal_url") or "",
            "icon_url": item.get("icon_url") or "",
            "color": item.get("color") or "",
            "aliases": list(dict.fromkeys([item["nombre"], *(item.get("aliases") or [])])),
            "visible": True,
        })
    return out


def detectar_compania_en_texto(texto):
    """Detecta identidad usando aliases distintivos del registro único."""
    clave_texto = _clave(texto)
    if not clave_texto:
        return ""
    excluidos = {"self", "federacion", "mercantil", "provincia", "parana", "prof", "ma"}
    especiales = {"atm", "ags"}
    candidatos = []
    for alias, key in _ALIAS_TO_KEY.items():
        if alias in excluidos:
            continue
        if len(alias) < 5 and alias not in especiales:
            continue
        patron = r"(?:^|\b)" + re.escape(alias).replace(r"\ ", r"\s+") + r"(?:\b|$)"
        if re.search(patron, clave_texto):
            candidatos.append((len(alias), _REGISTRY[key]["nombre"]))
    if not candidatos:
        return ""
    candidatos.sort(reverse=True)
    return candidatos[0][1]


def asistencia_compania(nombre_crudo):
    """Canales conocidos, sin afirmar que una póliza concreta los incluya."""
    clave = _clave(nombre_crudo)
    key = _ALIAS_TO_KEY.get(clave)
    codigo = _REGISTRY[key]["codigo"] if key else str(nombre_crudo or "").strip().upper()
    raw = _ASISTENCIAS.get(codigo)
    return deepcopy(raw) if isinstance(raw, dict) else {}


def texto_asistencia_compania(nombre_crudo, *, solo_asistencia: bool = False):
    """Texto humano derivado del registro estructurado de contactos.

    ``solo_asistencia=True`` evita usar un mero contacto general (EuroAmérica)
    como si fuera un teléfono confirmado de grúa.
    """
    info = asistencia_compania(nombre_crudo)
    if not info or (solo_asistencia and info.get("tipo") != "asistencia"):
        return ""
    etiqueta = str(info.get("etiqueta") or "Asistencia").strip()
    horario = str(info.get("horario") or "").strip()
    encabezado = f"{etiqueta}{(' ' + horario) if horario else ''}"
    canales = []
    telefonos = [str(x).strip() for x in (info.get("telefonos") or []) if str(x).strip()]
    whatsapp = [str(x).strip() for x in (info.get("whatsapp") or []) if str(x).strip()]
    sms = [str(x).strip() for x in (info.get("sms") or []) if str(x).strip()]
    if telefonos:
        canales.append("Tel.: " + " / ".join(telefonos))
    if whatsapp:
        canales.append("WhatsApp: " + " / ".join(whatsapp))
    if sms:
        canales.append("SMS: " + " / ".join(sms))
    return (encabezado + ": " + " · ".join(canales) + ".") if canales else encabezado


__all__ = [
    "normalizar_compania", "nombre_compania", "company_key", "aliases_companias",
    "catalogo_companias", "nombres_companias", "slug_compania", "companias_sidebar_default",
    "datos_compania", "detectar_compania_en_texto", "asistencia_compania",
    "texto_asistencia_compania",
]
