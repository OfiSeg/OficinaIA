"""Tramo final de Sofia para /api/chat.

V20 Etapa 6: encapsula la llamada al núcleo IA y normaliza su contrato de salida.
No conoce Flask, DB ni session.
"""
from dataclasses import dataclass
import time


@dataclass
class AIResult:
    respuesta: str
    propuesta_excel: dict | None = None
    propuesta_metadato: dict | None = None
    elapsed: float = 0.0


def responder(mensaje, contexto, historial):
    from servicios_ia import consultar_gemini
    inicio = time.monotonic()
    resultado = consultar_gemini(mensaje, contexto, historial=historial)
    elapsed = time.monotonic() - inicio
    if isinstance(resultado, tuple):
        return AIResult(
            str(resultado[0]),
            resultado[1] if len(resultado) > 1 else None,
            resultado[2] if len(resultado) > 2 else None,
            elapsed,
        )
    return AIResult(str(resultado), elapsed=elapsed)
