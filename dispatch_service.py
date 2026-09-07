"""Despacho genérico de mensajes desde el chat por canales registrados."""
from __future__ import annotations

import contextvars
import re
from typing import Protocol

import google_sheets_service
from excel_records import normalizar_encabezado
from mail_service import MailChannel
import system_health


class CanalEnvio(Protocol):
    nombre: str
    def enviar(self, destinatario: str, texto: str, adjuntos: list) -> bool: ...


class WhatsAppChannel:
    nombre = "whatsapp"
    def enviar(self, destinatario: str, texto: str, adjuntos: list) -> bool:
        system_health.registrar_evento(
            "whatsapp", "aviso", "Se intentó usar WhatsApp antes de configurar Meta Cloud API"
        )
        return False


CANALES: dict[str, CanalEnvio] = {
    "mail": MailChannel(),
    "whatsapp": WhatsAppChannel(),
}

_turn_attachments: contextvars.ContextVar[list] = contextvars.ContextVar(
    "oficinaia_turn_attachments", default=[]
)
_previous_attachments: contextvars.ContextVar[list] = contextvars.ContextVar(
    "oficinaia_previous_attachments", default=[]
)


def set_turn_attachments(adjuntos: list | None) -> None:
    """Adjuntos cargados explícitamente en el request actual."""
    _turn_attachments.set(list(adjuntos or []))


def set_previous_attachments(adjuntos: list | None) -> None:
    """Adjunto del turno inmediatamente anterior, sólo para reutilización explícita."""
    _previous_attachments.set(list(adjuntos or []))


def _buscar_destinatario_en_sheets(canal: str, identificador: str) -> str:
    identificador = str(identificador or "").strip()
    if not identificador:
        return ""
    data = google_sheets_service.leer_excel("1")
    filas = data.get("filas") or []
    if len(filas) < 2:
        return ""
    headers = [normalizar_encabezado(x) for x in filas[0]]
    idx = {h: i for i, h in enumerate(headers) if h}
    campos_id = ["asegurado", "cliente", "patente", "dominio", "numero"]
    objetivo = normalizar_encabezado(identificador)
    destino_header = "mail" if canal == "mail" else "telefono"
    destino_idx = idx.get(destino_header)
    if destino_idx is None:
        return ""
    for row in filas[1:]:
        coincide = False
        for campo in campos_id:
            pos = idx.get(campo)
            if pos is None or pos >= len(row):
                continue
            valor = normalizar_encabezado(row[pos])
            if valor and (objetivo == valor or objetivo in valor or valor in objetivo):
                coincide = True
                break
        if coincide and destino_idx < len(row):
            return str(row[destino_idx] or "").strip()
    return ""


def enviar_por_canal(canal: str, destinatario: str = "", texto: str = "",
                      asegurado: str = "", usar_adjunto_del_turno: bool = True,
                      usar_adjunto_anterior: bool = False, asunto: str = "") -> dict:
    canal = str(canal or "").strip().lower()
    implementacion = CANALES.get(canal)
    if not implementacion:
        return {"ok": False, "error": f"Canal no disponible: {canal or 'sin indicar'}."}
    destinatario = str(destinatario or "").strip()
    if not destinatario and asegurado:
        try:
            destinatario = _buscar_destinatario_en_sheets(canal, asegurado)
        except Exception as error:
            system_health.registrar_evento(canal, "error", "No se pudo resolver destinatario en Sheets", str(error))
    if not destinatario:
        return {"ok": False, "error": "Falta identificar el destinatario."}
    if canal == "mail" and hasattr(implementacion, "destinatario_valido") and not implementacion.destinatario_valido(destinatario):
        return {"ok": False, "error": "El correo del destinatario no parece válido. Confirmame la dirección antes de enviarlo."}
    # Seguridad: un envío nuevo sólo toma adjuntos del request actual. El adjunto
    # anterior jamás se hereda por defecto; sólo se usa cuando el usuario lo pide
    # explícitamente y la herramienta marca usar_adjunto_anterior=True.
    adjuntos = list(_turn_attachments.get() or []) if usar_adjunto_del_turno else []
    if usar_adjunto_anterior and not adjuntos:
        adjuntos = list(_previous_attachments.get() or [])
    if canal == "mail":
        ok = bool(implementacion.enviar(
            destinatario, str(texto or ""), adjuntos, asunto=str(asunto or "").strip()
        ))
    else:
        ok = bool(implementacion.enviar(destinatario, str(texto or ""), adjuntos))
    if ok:
        return {"ok": True, "canal": canal, "destinatario": destinatario, "adjuntos": len(adjuntos)}
    if canal == "whatsapp":
        return {"ok": False, "error": "WhatsApp todavía no está configurado en OficinaIA."}
    return {"ok": False, "error": f"No pude mandarlo por {canal}."}


def parsear_comando_explicito(mensaje: str):
    texto = str(mensaje or "").strip()
    m = re.match(r"^/(mail|whatsapp)\b\s*(.*)$", texto, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    canal = m.group(1).lower()
    resto = m.group(2).strip()
    if not resto:
        if canal == "mail":
            return {"error": "Usá /mail destinatario@correo.com asunto Asunto mensaje Mensaje."}
        return {"error": f"Usá /{canal} destinatario texto."}

    if canal == "mail" and "|" in resto:
        partes_mail = [parte.strip() for parte in resto.split("|", 2)]
        if len(partes_mail) != 3:
            return {"error": "Usá /mail destinatario@correo.com asunto Asunto mensaje Mensaje."}
        destinatario, asunto, cuerpo = partes_mail
        if not destinatario:
            return {"error": "Falta el destinatario del mail."}
        if not asunto:
            return {"error": "Falta el asunto del mail."}
        if not cuerpo:
            return {"error": "Falta el mensaje del mail."}
        return {
            "canal": canal,
            "destinatario": destinatario,
            "asunto": asunto,
            "texto": cuerpo,
        }

    # Forma natural y determinística del comando, sin intervención de Gemini:
    # /mail correo asunto Mi título mensaje Hola mundo
    # /mail correo titulo Mi título mensaje Hola mundo
    if canal == "mail":
        m_mail = re.match(
            r"^(?P<destinatario>\S+)\s+(?:asunto|t[ií]tulo)\s+(?P<asunto>.+?)\s+mensaje\s+(?P<cuerpo>.+)$",
            resto,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m_mail:
            destinatario = m_mail.group("destinatario").strip()
            asunto = m_mail.group("asunto").strip()
            cuerpo = m_mail.group("cuerpo").strip()
            if not asunto:
                return {"error": "Falta el asunto del mail."}
            if not cuerpo:
                return {"error": "Falta el mensaje del mail."}
            return {
                "canal": canal,
                "destinatario": destinatario,
                "asunto": asunto,
                "texto": cuerpo,
            }

    partes = resto.split(None, 1)
    destinatario = partes[0].strip()
    cuerpo = partes[1].strip() if len(partes) > 1 else ""
    if not cuerpo:
        return {"error": "Falta el texto que querés enviar."}
    resultado = {"canal": canal, "destinatario": destinatario, "texto": cuerpo}
    if canal == "mail":
        resultado["asunto"] = "San José Seguros"
    return resultado


def procesar_comando_explicito(mensaje: str):
    parsed = parsear_comando_explicito(mensaje)
    if parsed is None:
        return None
    if parsed.get("error"):
        return {"ok": False, "respuesta": parsed["error"]}
    resultado = enviar_por_canal(**parsed, usar_adjunto_del_turno=True)
    if resultado.get("ok"):
        if parsed["canal"] == "mail":
            asunto = str(parsed.get("asunto") or "San José Seguros").strip()
            return {
                "ok": True,
                "respuesta": f"Listo, mandé el mail a {resultado['destinatario']} con asunto «{asunto}».",
            }
        return {"ok": True, "respuesta": f"Listo, lo mandé por {parsed['canal']} a {resultado['destinatario']}."}
    return {
        "ok": False,
        "respuesta": resultado.get("error") or f"No pude mandarlo por {parsed['canal']}, pero el chat sigue disponible para intentarlo de nuevo.",
    }
