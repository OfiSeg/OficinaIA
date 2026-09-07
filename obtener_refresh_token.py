"""Ejecutar UNA vez en una PC con navegador para obtener el refresh token Gmail.

Requiere GMAIL_OAUTH_CLIENT_ID y GMAIL_OAUTH_CLIENT_SECRET en el entorno.
No se usa ni se ejecuta en producción.
"""
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

client_id = (os.getenv("GMAIL_OAUTH_CLIENT_ID") or "").strip()
client_secret = (os.getenv("GMAIL_OAUTH_CLIENT_SECRET") or "").strip()
if not client_id or not client_secret:
    raise SystemExit("Definí GMAIL_OAUTH_CLIENT_ID y GMAIL_OAUTH_CLIENT_SECRET antes de ejecutar este script.")

config = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}
flow = InstalledAppFlow.from_client_config(config, SCOPES)
credenciales = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nGMAIL_OAUTH_REFRESH_TOKEN=" + str(credenciales.refresh_token or ""))
