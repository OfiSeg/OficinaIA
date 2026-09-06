"""Handlers especiales previos a Sofia.

V20 Etapa 5: unifica el contrato de /coti, /flota y /alta. Estos handlers son
mutuamente excluyentes y se evalúan en orden antes del chat general. La capa HTTP
sólo persiste la respuesta y serializa ``payload_extra``.
"""

from dataclasses import dataclass, field
import re

import alta_ops
import flota_ops
from coti import procesar_comando_coti


@dataclass
class SpecialResult:
    atendido: bool = False
    respuesta: str | None = None
    payload_extra: dict = field(default_factory=dict)
    handler: str | None = None


def procesar(
    *,
    chat_id,
    mensaje,
    contexto_pdf,
    flota_store,
    on_stage=None,
):
    # /coti es totalmente determinístico y tiene prioridad histórica.
    respuesta_coti = procesar_comando_coti(mensaje)
    if respuesta_coti is not None:
        return SpecialResult(
            atendido=True,
            respuesta=str(respuesta_coti),
            payload_extra={},
            handler="coti",
        )

    if on_stage:
        on_stage("flota_router")
    respuesta_flota, atendido_flota, tabulado_flota = flota_ops.procesar_turno(
        chat_id, mensaje, contexto_pdf, flota_store
    )
    if atendido_flota:
        return SpecialResult(
            atendido=True,
            respuesta=str(respuesta_flota),
            payload_extra={"tabulado_flota": tabulado_flota},
            handler="flota",
        )

    # Alta individual: explícita o detección conservadora desde PDF.
    es_alta_explicito = bool(re.match(r"^/alta\b", mensaje, re.IGNORECASE))
    mensaje_para_alta = mensaje
    alta_automatica = False
    if (
        not es_alta_explicito
        and contexto_pdf
        and alta_ops.pdf_parece_poliza_individual(contexto_pdf)
    ):
        texto_extra = "" if mensaje.strip() == alta_ops.MENSAJE_PDF_POR_DEFECTO else mensaje.strip()
        mensaje_para_alta = ("/alta " + texto_extra).strip()
        alta_automatica = True

    if on_stage:
        on_stage("alta_router")
    respuesta_alta, atendido_alta, propuesta_alta = alta_ops.procesar(
        mensaje_para_alta, contexto_pdf, automatico=alta_automatica
    )
    if atendido_alta:
        payload = {
            "propuesta_alta_asegurado": propuesta_alta,
            "tabulado_alta_asegurado": alta_ops.armar_tabulado(propuesta_alta) if propuesta_alta else None,
            "campos_guardar_alta_asegurado": alta_ops.a_campos_guardar_asegurado(propuesta_alta) if propuesta_alta else None,
        }
        return SpecialResult(
            atendido=True,
            respuesta=str(respuesta_alta),
            payload_extra=payload,
            handler="alta",
        )

    return SpecialResult()
