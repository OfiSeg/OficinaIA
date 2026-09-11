"""Formato operativo compartido para Envíos Ya.

Esta capa es deliberadamente determinística: no usa Gemini, Flask ni Excel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any


CAMPOS_ENVIOS_YA = (
    "ASEGURADO",
    "POLIZA",
    "TELEFONO",
    "PATENTE",
    "VEHICULO",
    "COMPAÑIA",
)


def _texto_limpio(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return re.sub(r"\s+", " ", str(valor).strip())


def _digits(valor: Any) -> str:
    texto = _texto_limpio(valor)
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    return re.sub(r"\D", "", texto)


def _norm_key(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", texto.lower())


def normalizar_patente(valor: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def normalizar_telefono_argentina(valor: Any) -> tuple[str, str]:
    """Devuelve ``(telefono_10_digitos, motivo_error)``.

    Quita +54/54, 9 internacional, 0 interurbano y 15 histórico sólo cuando
    su posición/longitud es compatible. Nunca mutila un teléfono ya válido de
    10 dígitos que contenga ``15`` internamente.
    """
    original = _digits(valor)
    if not original:
        return "", "Sin teléfono"

    d = original
    if d.startswith("0054"):
        d = d[4:]
    elif d.startswith("54") and len(d) >= 12:
        d = d[2:]

    # +54 9 AA... -> AA...
    if len(d) == 11 and d.startswith("9"):
        d = d[1:]

    # 0AA... -> AA...
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]

    # Si ya quedó con diez dígitos, no tocar secuencias 15 internas. La
    # validación de plausibilidad se hace al final para conservar el control
    # histórico de Envíos Masivos.
    if len(d) == 10 and not d.startswith("0"):
        if len(set(d)) <= 2:
            return "", "Número sospechoso"
        return d, ""

    # Formato histórico: 0AA 15 XXXXXXXX / AA 15 XXXXXXXX.
    sin_cero = d[1:] if d.startswith("0") else d
    candidatos: list[str] = []
    for largo_area in (2, 3, 4):
        if len(sin_cero) >= largo_area + 2 and sin_cero[largo_area:largo_area + 2] == "15":
            candidato = sin_cero[:largo_area] + sin_cero[largo_area + 2:]
            if len(candidato) == 10 and not candidato.startswith("0"):
                candidatos.append(candidato)
    candidatos = list(dict.fromkeys(candidatos))
    if len(candidatos) == 1:
        d = candidatos[0]

    if len(d) != 10:
        return "", f"No se pudo normalizar a 10 dígitos ({len(d)} dígitos)"
    if d.startswith("0"):
        return "", "El número normalizado no puede comenzar con 0"
    # Conserva la validación histórica de Envíos Masivos: una cadena de diez
    # dígitos casi uniforme suele ser un dato basura/placeholder.
    if len(set(d)) <= 2:
        return "", "Número sospechoso"
    return d, ""


def _obtener(datos: dict[str, Any], *claves: str) -> str:
    if not isinstance(datos, dict):
        return ""
    normalizados = {_norm_key(k): v for k, v in datos.items()}
    for clave in claves:
        valor = normalizados.get(_norm_key(clave))
        if _texto_limpio(valor):
            return _texto_limpio(valor)
    return ""


@dataclass
class EnviosYaResult:
    texto: str
    campos: dict[str, str]
    advertencias: list[str] = field(default_factory=list)
    telefono_valido: bool = True


def preparar_envios_ya(datos: dict[str, Any]) -> EnviosYaResult:
    """Construye una fila con TAB reales y sin etiquetas.

    ``NUMERO`` del Excel histórico se considera teléfono. El número de póliza
    vive de forma efímera como ``POLIZA``/``NUMERO_POLIZA`` y no cambia la
    semántica de la planilla.
    """
    asegurado = _obtener(datos, "ASEGURADO", "NOMBRE ASEGURADO", "NOMBRE Y APELLIDO")
    poliza = _obtener(datos, "POLIZA", "PÓLIZA", "NUMERO_POLIZA", "NÚMERO DE PÓLIZA", "NRO POLIZA")
    telefono_original = _obtener(datos, "TELEFONO", "TELÉFONO", "CELULAR") or _obtener(datos, "NUMERO")
    telefono, error_telefono = normalizar_telefono_argentina(telefono_original)
    patente = normalizar_patente(_obtener(datos, "PATENTE", "DOMINIO", "CHAPA"))
    vehiculo = _obtener(datos, "VEHICULO", "VEHÍCULO", "MARCA_MODELO", "MARCA/MODELO")
    compania = _obtener(datos, "CIA", "COMPAÑIA", "COMPAÑÍA", "ASEGURADORA")

    campos = {
        "ASEGURADO": asegurado,
        "POLIZA": poliza,
        "TELEFONO": telefono,
        "PATENTE": patente,
        "VEHICULO": vehiculo,
        "COMPAÑIA": compania,
    }
    advertencias: list[str] = []
    if error_telefono:
        advertencias.append(f"Revisá TELEFONO: {error_telefono}.")
    if not asegurado:
        advertencias.append("Falta ASEGURADO.")
    if not poliza:
        advertencias.append("Falta NÚMERO DE PÓLIZA.")
    if not patente:
        advertencias.append("Falta PATENTE.")
    if not vehiculo:
        advertencias.append("Falta VEHICULO.")
    if not compania:
        advertencias.append("Falta COMPAÑIA.")

    texto = "\t".join(campos[c] for c in CAMPOS_ENVIOS_YA)
    return EnviosYaResult(texto, campos, advertencias, not bool(error_telefono))


def armar_fila_envios_ya(datos: dict[str, Any]) -> str:
    return preparar_envios_ya(datos).texto
