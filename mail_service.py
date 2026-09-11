"""Canal de envío por Gmail API usando OAuth 2.0 de una cuenta Gmail común."""
from __future__ import annotations

import base64
import re

import runtime_config
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import system_health

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SCOPES = ("https://www.googleapis.com/auth/gmail.send",)


class MailChannel:
    nombre = "mail"

    @staticmethod
    def destinatario_valido(destinatario: str) -> bool:
        return bool(EMAIL_RE.fullmatch(str(destinatario or "").strip()))

    @staticmethod
    def _credentials():
        sender = (runtime_config.get_text("GMAIL_SENDER_EMAIL") or "").strip()
        client_id = (runtime_config.get_text("GMAIL_OAUTH_CLIENT_ID") or "").strip()
        client_secret = (runtime_config.get_text("GMAIL_OAUTH_CLIENT_SECRET") or "").strip()
        refresh_token = (runtime_config.get_text("GMAIL_OAUTH_REFRESH_TOKEN") or "").strip()
        faltan = [
            nombre for nombre, valor in (
                ("GMAIL_SENDER_EMAIL", sender),
                ("GMAIL_OAUTH_CLIENT_ID", client_id),
                ("GMAIL_OAUTH_CLIENT_SECRET", client_secret),
                ("GMAIL_OAUTH_REFRESH_TOKEN", refresh_token),
            ) if not valor
        ]
        if faltan:
            raise RuntimeError("Falta configurar Gmail: " + ", ".join(faltan))
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        return sender, creds

    def enviar(self, destinatario: str, texto: str, adjuntos: list, asunto: str = "") -> bool:
        destinatario = str(destinatario or "").strip()
        if not self.destinatario_valido(destinatario):
            system_health.registrar_evento("mail", "aviso", "Destinatario de mail inválido", destinatario)
            return False
        try:
            sender, creds = self._credentials()
            mensaje = MIMEMultipart()
            mensaje["To"] = destinatario
            mensaje["From"] = sender
            mensaje["Subject"] = str(asunto or "").strip() or "San José Seguros"
            mensaje.attach(MIMEText(str(texto or ""), "plain", "utf-8"))

            for adjunto in adjuntos or []:
                datos = getattr(adjunto, "datos_binarios", None)
                nombre = str(getattr(adjunto, "nombre", "adjunto") or "adjunto")
                mime = str(getattr(adjunto, "mime_type", "application/octet-stream") or "application/octet-stream")
                if not datos:
                    continue
                if mime.startswith("image/"):
                    subtype = mime.split("/", 1)[1]
                    parte = MIMEImage(datos, _subtype=subtype, name=nombre)
                else:
                    subtype = mime.split("/", 1)[1] if "/" in mime else "octet-stream"
                    parte = MIMEApplication(datos, _subtype=subtype, Name=nombre)
                parte.add_header("Content-Disposition", "attachment", filename=nombre)
                mensaje.attach(parte)

            raw = base64.urlsafe_b64encode(mensaje.as_bytes()).decode("ascii")
            servicio = build("gmail", "v1", credentials=creds, cache_discovery=False)
            servicio.users().messages().send(userId="me", body={"raw": raw}).execute()
            system_health.registrar_evento("mail", "aviso", f"Mail enviado a {destinatario}")
            return True
        except Exception as error:
            system_health.registrar_evento("mail", "error", "No se pudo enviar un mail", str(error))
            return False
