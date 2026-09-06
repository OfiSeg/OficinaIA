"""Router liviano de intención/alcance para Sofia.

V20 Etapa 2: este módulo NO ejecuta herramientas ni llama a Gemini.
Sólo transforma una pregunta en un plan explícito y auditable.

Principio: estado conversacional persistente; estado de ejecución efímero.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Iterable


def normalizar_texto(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    valor = valor.encode("ascii", "ignore").decode("ascii").lower()
    valor = re.sub(r"\s+", " ", valor).strip()
    return valor


@dataclass(frozen=True)
class ExecutionPlan:
    intencion: str = "general"
    alcance: str = "puntual"
    fuentes: tuple[str, ...] = ()
    requiere_completitud: bool = False
    requiere_metadatos: bool = False
    motivo: str = "consulta general"

    def to_dict(self) -> dict:
        salida = asdict(self)
        salida["fuentes"] = list(self.fuentes)
        return salida


_TERMINOS_ESTRUCTURADOS = (
    "asegurado", "asegurados", "patente", "patentes", "poliza", "polizas",
    "planilla", "excel", "dni", "numero de poliza", "cuantos registros",
    "cantidad de vehiculos", "cantidad de vehiculo",
)

_ENTIDADES_EXCEL = (
    "asegurado", "asegurados", "poliza", "polizas", "vehiculo", "vehiculos",
    "remolque", "remolques", "trailer", "trailers", "acoplado", "acoplados",
    "grua", "gruas", "moto", "motos", "auto", "autos", "camion", "camiones",
    "hogar", "hogares", "combinado familiar", "combinados familiares", "seguro de hogar", "seguros de hogar",
)

_TERMINOS_DOCUMENTALES = (
    "cobertura", "coberturas", "cubre", "cubrir", "asistencia", "asistencias",
    "grua", "gruas", "remolque", "remolques", "auxilio", "traslado",
    "limite", "limites", "condicion", "condiciones", "procedimiento",
    "procedimientos", "compania", "companias", "prestacion", "prestaciones",
    "servicio", "servicios", "evento", "eventos", "kilometro", "kilometros",
    "cerradura", "cerraduras", "granizo", "vidrio", "vidrios", "rueda",
    "ruedas", "robo", "incendio", "destruccion", "responsabilidad civil", "rc",
    "adicional", "adicionales", "beneficio", "beneficios", "franquicia",
    "franquicias", "exclusion", "exclusiones", "plan", "planes",
)

_PATRONES_EXHAUSTIVOS = (
    r"\btod[oa]s?\b",
    r"\bcada\b",
    r"\bcomplet[oa]s?\b",
    r"\bdetalle(?:me|ame)?\b",
    r"\bdetalla(?:me)?\b",
    r"\blista(?:me)?\b",
    r"\ben todas?\b",
    r"\bde cada\b",
    r"\btodo lo que\b",
    r"\bdisponibles?\b",
)

_PATRONES_COMPARATIVOS = (
    r"\ben que compania\b",
    r"\ben cuales companias\b",
    r"\bque compania (?:toma|acepta|asegura|emite|cotiza)\b",
    r"\bque companias (?:toman|aceptan|aseguran|emiten|cotizan)\b",
    r"\bdonde (?:puedo )?(?:emitir|asegurar|cotizar|colocar)\b",
    r"\bquien (?:toma|acepta|asegura|emite|cotiza)\b",
    r"\bquienes (?:toman|aceptan|aseguran|emiten|cotizan)\b",
    r"\bcompar(?:a|ame|ar)\b.*\bcompan",
    r"\bcual compania me sirve\b",
    r"\bque compania me sirve\b",
)


def es_consulta_comparativa(texto: str) -> bool:
    t = normalizar_texto(texto)
    return bool(t and any(re.search(p, t) for p in _PATRONES_COMPARATIVOS))


def _parece_conteo_excel(texto_norm: str) -> bool:
    es_conteo = bool(re.search(r"\b(cuantos|cuantas|cantidad|total)\b", texto_norm))
    if not es_conteo:
        return False
    # Si el usuario habla de servicio/cobertura, no es inventario aunque diga remolque/grúa.
    if any(x in texto_norm for x in ("cubre", "cobertura", "asistencia", "servicio", "prestacion", "kilomet")):
        return False
    return any(t in texto_norm for t in _ENTIDADES_EXCEL)




def _parece_analisis_excel(texto_norm: str) -> bool:
    """Detecta operaciones analíticas estructuradas, no simples búsquedas."""
    if not texto_norm:
        return False
    # "vehículos" no equivale a filas: el Excel también puede contener hogar/combinados.
    if any(x in texto_norm for x in ("vehiculo", "vehiculos")) and any(x in texto_norm for x in ("cuanto", "cantidad", "total", "tengo")):
        return True
    señales = (
        "porcentaje", "representa", "ranking", "ordena", "ordenar",
        "segundo", "segunda", "mayor", "menor", "promedio", "media",
        "duplicad", "repetid", "sin patente", "patente vacia",
        "no tienen patente", "no tiene patente",
    )
    if any(x in texto_norm for x in ("hogar", "combinado familiar", "combinados familiares", "seguro de hogar", "seguros de hogar")):
        if any(x in texto_norm for x in ("cuanto", "cantidad", "tengo", "hay", "excel", "cartera")):
            return True
    if any(x in texto_norm for x in señales):
        return any(x in texto_norm for x in (
            "cartera", "compania", "asegur", "vehiculo", "patente", "registro",
            "moto", "auto", "excel", "poliza"
        ))
    if "moto" in texto_norm and "auto" in texto_norm and any(x in texto_norm for x in ("cuanto", "cantidad", "mas", "menos", "diferencia")):
        return True
    # Una sola clase también requiere el clasificador determinístico: por ejemplo
    # "cuántos autos de ATM" o "qué compañía tiene más motos".
    if any(x in texto_norm for x in ("auto", "automotor", "moto", "motocicleta", "motovehiculo")):
        if any(x in texto_norm for x in ("cuanto", "cantidad", "porcentaje", "compania", "cartera", "mas", "menos")):
            return True
    return False

def requiere_metadatos(texto: str) -> bool:
    t = normalizar_texto(texto)
    if not t or t.startswith("/"):
        return False
    if _parece_conteo_excel(t):
        return False
    if any(term in t for term in _TERMINOS_ESTRUCTURADOS):
        # Una póliza/Excel explícitos pertenecen al dominio estructurado salvo que además
        # exista una pregunta documental clara (p. ej. "qué cobertura tiene la póliza").
        return any(term in t for term in ("cobertura", "cubre", "limite", "asistencia", "granizo", "grua"))
    return any(term in t for term in _TERMINOS_DOCUMENTALES)


def detectar_alcance(texto: str) -> tuple[str, bool]:
    t = normalizar_texto(texto)
    if not t:
        return "puntual", False
    if es_consulta_comparativa(t):
        return "comparativo", True
    exhaustivo = any(re.search(p, t) for p in _PATRONES_EXHAUSTIVOS)
    return ("exhaustivo", True) if exhaustivo else ("puntual", False)


def construir_plan_base(pregunta: str) -> ExecutionPlan:
    t = normalizar_texto(pregunta)
    if not t:
        return ExecutionPlan()

    alcance, completitud = detectar_alcance(t)

    if es_consulta_comparativa(t):
        return ExecutionPlan(
            intencion="comparacion_companias",
            alcance="comparativo",
            fuentes=("comparar_companias",),
            requiere_completitud=True,
            requiere_metadatos=False,
            motivo="consulta transversal de colocación/comparación",
        )

    if _parece_analisis_excel(t):
        return ExecutionPlan(
            intencion="analisis_excel",
            alcance="puntual",
            fuentes=("analizar_excel",),
            requiere_completitud=False,
            requiere_metadatos=False,
            motivo="analítica determinística sobre el Excel interno",
        )

    if _parece_conteo_excel(t):
        return ExecutionPlan(
            intencion="conteo_excel",
            alcance="puntual",
            fuentes=("contar_registros",),
            requiere_completitud=False,
            requiere_metadatos=False,
            motivo="conteo de registros/inventario interno",
        )

    if requiere_metadatos(t):
        return ExecutionPlan(
            intencion="consulta_documental",
            alcance=alcance,
            fuentes=("buscar_en_metadatos",),
            requiere_completitud=completitud,
            requiere_metadatos=True,
            motivo="consulta sobre coberturas/condiciones/servicios internos",
        )

    return ExecutionPlan(
        intencion="general",
        alcance=alcance,
        fuentes=(),
        requiere_completitud=False,
        requiere_metadatos=False,
        motivo="no requiere fuente documental precargada",
    )
