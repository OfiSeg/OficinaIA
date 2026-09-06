"""Acciones contextuales del chat.

V20 Etapa 7: convierte referencias como "guardá metadato" en una propuesta
basada en el contenido conversacional inmediatamente anterior, sin reactivar
herramientas ni depender de un if para una frase exacta.

Este módulo NO persiste nada. Sólo construye propuestas que el frontend ya
sabe confirmar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any


@dataclass
class ContextActionResult:
    atendido: bool = False
    respuesta: str = ""
    propuesta_metadato: dict | None = None
    payload_extra: dict[str, Any] = field(default_factory=dict)


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _es_pedido_metadato_referencial(mensaje: str) -> bool:
    """Detecta intención, no una frase única.

    Se limita deliberadamente a pedidos de metadato para no confundir
    "guardá esto" con memoria, Excel u otra acción futura.
    """
    n = _norm(mensaje)
    if not n or len(n) > 220:
        return False
    menciona_destino = any(x in n for x in ("metadato", "metadata", "ficha interna", "ficha de conocimiento"))
    if not menciona_destino:
        return False
    verbos = (
        "guarda", "guardar", "guardalo", "guardala", "guardame", "guardate",
        "agrega", "agregar", "sumalo", "sumala", "anota", "anotalo", "anotala",
        "mete", "carga", "cargar", "registralo", "registrar",
    )
    referencias = ("esto", "eso", "lo anterior", "lo que dijiste", "esa info", "esa informacion")
    return any(v in n for v in verbos) or any(r in n for r in referencias)


def _mensajes_validos(historial):
    return [
        x for x in (historial or [])
        if isinstance(x, dict)
        and str(x.get("rol") or "") in {"user", "assistant"}
        and str(x.get("contenido") or "").strip()
    ]


def _ultimo_asistente(historial) -> str:
    for item in reversed(_mensajes_validos(historial)):
        if item.get("rol") == "assistant":
            return str(item.get("contenido") or "").strip()
    return ""


def _usuarios_recientes(historial, limite=3) -> list[str]:
    salida = []
    for item in reversed(_mensajes_validos(historial)):
        if item.get("rol") != "user":
            continue
        t = str(item.get("contenido") or "").strip()
        if t:
            salida.append(t)
        if len(salida) >= limite:
            break
    return list(reversed(salida))


def _quitar_markdown(texto: str) -> str:
    texto = re.sub(r"\*\*([^*]+)\*\*", r"\1", texto)
    texto = re.sub(r"__([^_]+)__", r"\1", texto)
    texto = re.sub(r"^\s{0,3}#{1,6}\s+", "", texto, flags=re.M)
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.M)
    return texto


def _tema_desde_contexto(asistente: str, usuarios: list[str]) -> str:
    # Primero priorizar una definición explícita: "Una franquicia es...".
    # Es más fiable que tomar cualquier frase en negrita del cuerpo.
    limpio_def = _quitar_markdown(asistente)
    m = re.search(r"\b(?:un|una|el|la)\s+([A-Za-zÁÉÍÓÚáéíóúÑñ0-9][^\n,.:;]{1,60}?)\s+(?:es|son|significa|consiste)\b", limpio_def, re.I)
    if m:
        candidato = " ".join(m.group(1).split()).strip(" .,:;¡!¿?")
        if candidato and not _norm(candidato).startswith(("si ", "cuando ")):
            return candidato[:120]

    # El texto enfatizado puede contener el concepto, pero no usamos condiciones
    # completas tipo "Si el daño es mayor..." como título.
    for patron in (r"\*\*([^*\n]{2,80})\*\*", r"__([^_\n]{2,80})__"):
        for m in re.finditer(patron, asistente):
            candidato = " ".join(m.group(1).split()).strip(" .,:;¡!¿?")
            n = _norm(candidato)
            if (
                candidato
                and len(candidato.split()) <= 7
                and not n.startswith(("si ", "cuando "))
                and not any(x in n for x in ("hola", "whatsapp", "mensaje", "version"))
            ):
                return candidato[:120]

    # Después, buscar construcciones definicionales en la respuesta.
    limpio = _quitar_markdown(asistente)
    m = re.search(r"\b(?:sobre|el|la|los|las)\s+([A-Za-zÁÉÍÓÚáéíóúÑñ0-9][^\n,.]{2,70})\s+(?:es|son|aplica|significa)\b", limpio, re.I)
    if m:
        candidato = " ".join(m.group(1).split()).strip(" .,:;¡!¿?")
        if 2 <= len(candidato) <= 100:
            return candidato

    # Último recurso: palabras significativas reiteradas por el usuario.
    stop = {
        "pero", "para", "esto", "eso", "como", "cual", "cualquier", "solo", "toda", "todo",
        "general", "reformula", "reformulado", "podria", "ser", "los", "las", "una", "uno",
        "del", "que", "con", "por", "mas", "bien", "caso", "actividad", "actividades",
    }
    cont = {}
    forma = {}
    for texto in usuarios:
        for token in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{4,}", texto):
            n = _norm(token)
            if n in stop:
                continue
            cont[n] = cont.get(n, 0) + 1
            forma.setdefault(n, token)
    if cont:
        top = sorted(cont, key=lambda k: (-cont[k], -len(k)))[:2]
        return " ".join(forma[k] for k in top).strip().capitalize()
    return "Ficha desde conversación"


def _es_parrafo_boilerplate(parrafo: str) -> bool:
    n = _norm(parrafo)
    patrones = (
        "aca tenes", "aca te dejo", "te dejo el mensaje", "listo para copiar",
        "tenes toda la razon", "claro, tenes razon", "version mas", "mensaje corregido",
        "cualquier duda", "cualquier cosa", "avisame", "un abrazo", "saludos",
    )
    if any(p in n for p in patrones) and len(n) < 260:
        return True
    return False


def _limpiar_contenido(asistente: str, tema: str) -> str:
    texto = _quitar_markdown(asistente).strip()
    parrafos = [" ".join(p.split()) for p in re.split(r"\n\s*\n+", texto) if p.strip()]
    utiles = [p for p in parrafos if not _es_parrafo_boilerplate(p)]
    if not utiles:
        utiles = parrafos[-2:] if parrafos else [texto]

    # Preferir párrafos con contenido explicativo y/o el concepto detectado.
    tema_n = _norm(tema)
    scored = []
    for i, p in enumerate(utiles):
        n = _norm(p)
        score = min(len(p), 500) / 500
        if tema_n and tema_n != "ficha desde conversacion" and tema_n in n:
            score += 3
        if any(x in n for x in (" es ", "significa", "se refiere", "aplica", "consiste", "incluye", "cubre", "no cubre")):
            score += 2
        if n.startswith("hola"):
            score -= 2
        scored.append((score, i, p))
    scored.sort(reverse=True)
    elegidos_idx = sorted(i for _, i, _ in scored[:3])
    contenido = " ".join(utiles[i] for i in elegidos_idx).strip()

    # Sacar saludos/preambulos típicos aunque estén en el mismo párrafo.
    contenido = re.sub(r"^Hola[^.!?]{0,80}[.!?]\s*", "", contenido, flags=re.I)
    contenido = re.sub(r"^(?:Te paso|Te dejo|Acá tenés|Acá te dejo)[^.]{0,180}\.\s*", "", contenido, flags=re.I)
    contenido = re.sub(r"\s*(?:Cualquier duda|Cualquier cosa)[^.?!]{0,140}[.!?]\s*(?:¡?Saludos!?|¡?Un abrazo!?)?\s*$", "", contenido, flags=re.I)
    contenido = re.sub(r"\s+", " ", contenido).strip(" -\n")

    if re.match(r"^(Es|Son)\b", contenido, flags=re.I) and tema and tema != "Ficha desde conversación":
        contenido = f"{tema}: {contenido[0].lower() + contenido[1:]}"

    return contenido[:1200].rstrip()


def _titulo_limpio(tema: str) -> str:
    tema = " ".join(str(tema or "").split()).strip(" .,:;¡!¿?")
    if not tema:
        return "Ficha desde conversación"
    if tema.isupper():
        return tema[:1] + tema[1:].lower()
    return tema[:1].upper() + tema[1:]


def procesar(mensaje: str, historial, proposer=None) -> ContextActionResult:
    if not _es_pedido_metadato_referencial(mensaje):
        return ContextActionResult()

    anterior = _ultimo_asistente(historial)
    if not anterior:
        return ContextActionResult()

    usuarios = _usuarios_recientes(historial)
    tema = _titulo_limpio(_tema_desde_contexto(anterior, usuarios))
    contenido = _limpiar_contenido(anterior, tema)
    if not contenido or len(contenido) < 20:
        return ContextActionResult()

    # Dependencia inyectable para test; en producción se resuelve tarde para
    # evitar convertir este módulo en dueño del retrieval/DB.
    if proposer is None:
        from servicios_ia import guardar_metadato_relevante as proposer
    resultado = proposer(tema, contenido)
    if resultado.get("duplicado"):
        existente = resultado.get("metadato_existente") or {}
        titulo_existente = str(existente.get("titulo") or tema)
        return ContextActionResult(
            atendido=True,
            respuesta=f"Ese contenido ya figura en metadatos como “{titulo_existente}”. No te propongo un duplicado.",
        )

    propuesta = resultado.get("propuesta") if resultado.get("valida") else None
    if not propuesta:
        # Si no pudo construir una propuesta segura, Sofia sigue el flujo normal.
        return ContextActionResult()

    return ContextActionResult(
        atendido=True,
        respuesta="Tomé lo que acabamos de definir y armé la ficha con ese contexto. Revisala y guardala si está bien.",
        propuesta_metadato=propuesta,
        payload_extra={"accion_contextual": "proponer_metadato_desde_contexto"},
    )
