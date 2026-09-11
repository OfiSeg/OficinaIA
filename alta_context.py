"""Correcciones contextuales sobre el alta activa del chat."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from companias import normalizar_compania, aliases_companias
from envios_ya_utils import normalizar_patente


@dataclass
class AltaContextResult:
    actualizado: bool = False
    campos: dict = field(default_factory=dict)
    cambios: list[str] = field(default_factory=list)


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


ALIASES = {
    "TELEFONO": ("telefono", "tel", "celular", "numero de telefono"),
    "PATENTE": ("patente", "dominio", "chapa"),
    "POLIZA": ("numero de poliza", "nro de poliza", "nro poliza", "poliza", "numero"),
    "VEHICULO": ("vehiculo", "auto", "moto", "marca modelo", "marca/modelo"),
    "CIA": ("compania", "aseguradora", "cia"),
    "MEDIO DE PAGO": ("medio de pago", "forma de pago", "pago"),
    "CP": ("codigo postal", "cp"),
    "MAIL": ("mail", "email", "correo"),
}


def _buscar_actualizacion_etiquetada(mensaje: str):
    original = str(mensaje or "").strip()
    normal = _norm(original)
    for campo, aliases in ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            patron = rf"^(?:el|la|mi|su)?\s*{re.escape(alias)}\s*(?:es|son|queda|:|=)\s*(.+)$"
            m = re.match(patron, normal, flags=re.I)
            if not m:
                continue
            mo = re.search(r"(?:\s(?:es|son|queda)\s|[:=])(.+)$", original, flags=re.I)
            valor = (mo.group(1) if mo else m.group(1)).strip(" .")
            return campo, valor
    return None, None


def aplicar_actualizacion(campos_actuales: dict, mensaje: str) -> AltaContextResult:
    campos = dict(campos_actuales or {})
    campo, valor = _buscar_actualizacion_etiquetada(mensaje)

    if not campo:
        m = re.match(r"^\s*(?:es|la compania es|la compañía es)\s+(.+?)\s*[.!]?$", str(mensaje or ""), re.I)
        if m:
            crudo = m.group(1).strip()
            posible = normalizar_compania(crudo)
            codigos = {codigo for codigo, _display in aliases_companias().values()}
            if posible in codigos:
                campo, valor = "CIA", posible

    if not campo:
        m = re.match(r"^\s*es\s+un(?:a)?\s+(.+?)\s*[.!]?$", str(mensaje or ""), re.I)
        if m:
            candidato = m.group(1).strip()
            if 2 < len(candidato) <= 100:
                campo, valor = "VEHICULO", candidato

    if not campo or not str(valor or "").strip():
        return AltaContextResult(False, campos, [])

    valor = str(valor).strip()
    if campo == "PATENTE":
        valor = normalizar_patente(valor)
    elif campo == "CIA":
        valor = normalizar_compania(valor)

    campos[campo] = valor
    return AltaContextResult(True, campos, [campo])
