"""Reglas pequeñas para agrupar caras de documentos operativos del chat.

No decide identidad por intuición: sólo propone qué adjuntos vale la pena leer
juntos. La confirmación de que pertenecen al mismo titular/documento queda en
el extractor especializado, que compara señales visibles.
"""
from __future__ import annotations

from dataclasses import dataclass, field


TIPOS_PERSONALES = {"dni", "licencia"}
TIPOS_DOCUMENTO = {"cedula", "dni", "licencia", "poliza", "cotizacion_atm", "otro"}


@dataclass
class GroupingPlan:
    tipo: str = "otro"
    adjuntos: list = field(default_factory=list)
    clasificaciones: list = field(default_factory=list)
    candidato_multicara: bool = False
    motivo: str = ""


@dataclass
class DocumentoAgrupado:
    tipo: str = "otro"
    indices: list[int] = field(default_factory=list)
    candidato_multicara: bool = False
    motivo: str = ""


@dataclass
class MultiDocumentPlan:
    documentos: list[DocumentoAgrupado] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def cantidad_documentos(self) -> int:
        return len(self.documentos)


def _tipo(clasificacion) -> str:
    t = str(getattr(clasificacion, "tipo_documento", "otro") or "otro").strip().lower()
    return t if t in TIPOS_DOCUMENTO else "otro"


def planificar(adjuntos: list, clasificaciones: list) -> GroupingPlan:
    """Elige un pipeline sin fusionar documentos de tipos distintos.

    Con dos imágenes, un lado poco reconocible puede quedar como ``otro``. Si
    la otra cara fue identificada con confianza como DNI/licencia/cédula, se
    permite probar ambas juntas; el extractor deberá confirmar compatibilidad.
    """
    items = [a for a in list(adjuntos or []) if a is not None]
    cls = list(clasificaciones or [])[: len(items)]
    if not items:
        return GroupingPlan()
    if not cls:
        return GroupingPlan("otro", items, [], False, "sin clasificación")

    tipos = [_tipo(c) for c in cls]
    reconocidos = [t for t in tipos if t != "otro"]
    if len(items) == 1:
        return GroupingPlan(tipos[0], items, cls, False, "un adjunto")

    # Los extractores operativos de frente/dorso están diseñados para dos caras.
    # Con más de dos adjuntos no descartamos ni recortamos silenciosamente la
    # colección: dejamos el conjunto completo al flujo general de Sofia, que sí
    # es multimodal N-archivos.
    if len(items) > 2:
        return GroupingPlan("otro", items, cls, False, "colección múltiple general")

    # No fusionar una póliza con documentación personal/vehicular.
    no_otro = set(reconocidos)
    if len(no_otro) > 1:
        return GroupingPlan(tipos[-1], [items[-1]], [cls[-1]], False, "tipos distintos")

    unico = reconocidos[0] if reconocidos else "otro"
    if unico in {"dni", "licencia", "cedula"} and all(t in {unico, "otro"} for t in tipos):
        return GroupingPlan(unico, items[:2], cls[:2], True, "posibles frente/dorso")

    if unico == "poliza":
        # El alta actual trabaja con una póliza por turno; no mezclar dos pólizas.
        idx = max(i for i, t in enumerate(tipos) if t == "poliza")
        return GroupingPlan("poliza", [items[idx]], [cls[idx]], False, "póliza individual")

    return GroupingPlan(tipos[-1], [items[-1]], [cls[-1]], False, "sin agrupamiento seguro")


def planificar_coleccion(adjuntos: list, clasificaciones: list) -> MultiDocumentPlan:
    """Plan N-documentos conservador.

    No ejecuta extractores ni fusiona por intuición. Sólo describe agrupamientos
    seguros/candidatos para que el router o el prompt general puedan preservar
    todo el lote y dejar claro que frente+dorso es una hipótesis a confirmar por
    la lectura especializada o por el productor.
    """
    items = [a for a in list(adjuntos or []) if a is not None]
    cls = list(clasificaciones or [])[:len(items)]
    tipos = [_tipo(c) for c in cls] if cls else ["otro"] * len(items)
    documentos: list[DocumentoAgrupado] = []
    i = 0
    while i < len(items):
        tipo = tipos[i] if i < len(tipos) else "otro"
        # Sólo proponemos multicara para pares adyacentes del mismo tipo operativo
        # o un ``otro`` junto a una cédula/DNI/licencia. No agrupamos pólizas.
        if i + 1 < len(items) and tipo in {"cedula", "dni", "licencia"}:
            sig = tipos[i + 1] if i + 1 < len(tipos) else "otro"
            if sig in {tipo, "otro"}:
                documentos.append(DocumentoAgrupado(tipo, [i, i + 1], True, "posible frente/dorso; requiere confirmación"))
                i += 2
                continue
        documentos.append(DocumentoAgrupado(tipo, [i], False, "documento individual"))
        i += 1
    return MultiDocumentPlan(documentos=documentos)

def resumen_coleccion_para_prompt(adjuntos: list, clasificaciones: list | None = None, *, advertencias: list[str] | None = None) -> str:
    plan = planificar_coleccion(adjuntos, clasificaciones or [])
    lineas = [
        "INSTRUCCIONES PARA COLECCIÓN DE DOCUMENTOS:",
        "- Respondé con una sección por documento real detectado.",
        "- Combiná frente/dorso sólo si el propio contenido confirma que pertenecen al mismo documento/titular/vehículo.",
        "- Si sólo recibiste frente o dorso, indicá 'solo frente', 'solo dorso' o 'cara no confirmada' según corresponda.",
        "- No digas que revisaste todos los documentos si el bloque técnico indica truncamiento visual.",
        "- Incluí estado por documento/campo cuando corresponda: Verificado, Revisar o Lectura parcial.",
        "- Para MOTOR, CHASIS, DOMINIO, DNI, CUIT/CUIL y póliza, no inventes caracteres ni completes por formato.",
        "- Si hay dudas visuales, explicá qué debe corroborar el productor.",
    ]
    if plan.documentos:
        lineas.append("Plan conservador de adjuntos recibido:")
        for n, doc in enumerate(plan.documentos, start=1):
            indices = ",".join(str(x + 1) for x in doc.indices)
            marca = "posible frente/dorso" if doc.candidato_multicara else "individual"
            lineas.append(f"  {n}. adjunto(s) {indices}: {doc.tipo} ({marca}; {doc.motivo})")
    for adv in list(advertencias or []):
        if str(adv).strip():
            lineas.append("ADVERTENCIA TÉCNICA: " + str(adv).strip())
    return "\n".join(lineas)
