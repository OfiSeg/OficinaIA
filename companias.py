import re
import unicodedata

# Una sola fuente de verdad para alias, código guardado y nombre visible.
_COMPANIAS = {
    "atm": ("ATM", "ATM"),
    "agrosalta": ("AGS", "AgroSalta"),
    "agro salta": ("AGS", "AgroSalta"),
    "ags": ("AGS", "AgroSalta"),
    "compania de seguros agrosalta": ("AGS", "AgroSalta"),
    "prof": ("PROF", "PROF"),
    "productores de frutas argentinas": ("PROF", "PROF"),
    "productores de frutas": ("PROF", "PROF"),
    "federacion": ("FEDERACION", "Federación Patronal"),
    "federacion patronal": ("FEDERACION", "Federación Patronal"),
    "federacionpatronal": ("FEDERACION", "Federación Patronal"),
    "rivadavia": ("RIVADAVIA", "Rivadavia"),
    "euroamerica": ("EUROAMERICA", "EuroAmérica"),
    "euro america": ("EUROAMERICA", "EuroAmérica"),
    "triunfo": ("TRIUNFO", "Triunfo"),
    "mercantil": ("MERCANTIL", "Mercantil Andina"),
    "mercantil andina": ("MERCANTIL", "Mercantil Andina"),
    "mercantilandina": ("MERCANTIL", "Mercantil Andina"),
    "san cristobal": ("SAN CRISTOBAL", "San Cristóbal"),
    "sancristobal": ("SAN CRISTOBAL", "San Cristóbal"),
    "la segunda": ("LA SEGUNDA", "La Segunda"),
    "lasegunda": ("LA SEGUNDA", "La Segunda"),
    "rio uruguay": ("RIO URUGUAY", "Río Uruguay"),
    "riouruguay": ("RIO URUGUAY", "Río Uruguay"),
    "sancor seguros": ("SANCOR SEGUROS", "Sancor Seguros"),
    "sancorseguros": ("SANCOR SEGUROS", "Sancor Seguros"),
    "provincia": ("PROVINCIA", "Provincia Seguros"),
    "provincia seguros": ("PROVINCIA", "Provincia Seguros"),
}

def _clave(texto):
    texto = str(texto or '').strip().lower().replace('_', ' ')
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    texto = re.sub(r'[^a-z0-9 ]', ' ', texto)
    return re.sub(r'\s+', ' ', texto).strip()

def normalizar_compania(nombre_crudo):
    """Devuelve el código canónico que OficinaIA guarda en el Excel."""
    clave = _clave(nombre_crudo)
    if not clave:
        return ''
    if clave in _COMPANIAS:
        return _COMPANIAS[clave][0]
    # Sólo coincidencias parciales razonables; evitamos aliases de 3 letras
    # dentro de palabras largas para no producir falsos positivos.
    for alias, (codigo, _display) in sorted(_COMPANIAS.items(), key=lambda x: len(x[0]), reverse=True):
        if len(alias) >= 5 and re.search(rf'\b{re.escape(alias)}\b', clave):
            return codigo
    return str(nombre_crudo or '').strip().upper()

def nombre_compania(nombre_crudo):
    """Nombre visible, usando la misma tabla que la normalización de datos."""
    clave = _clave(nombre_crudo)
    if clave in _COMPANIAS:
        return _COMPANIAS[clave][1]
    codigo = normalizar_compania(nombre_crudo)
    for _alias, (cod, display) in _COMPANIAS.items():
        if cod == codigo:
            return display
    return str(nombre_crudo or '').replace('_', ' ').strip().title()

def aliases_companias():
    return dict(_COMPANIAS)
