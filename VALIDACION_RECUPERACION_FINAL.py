"""Validación de integración de la recuperación final.

No llama a Gemini, Neon, R2 ni Google. Verifica contratos locales y que el
lector de cédulas congelado conserve exactamente el archivo de la base estable.
"""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parent

CEDULA_BASE_SHA256 = "0a05fabb46e078fdbe7bd4338d2b78538d4449774e55651aaa80ea923479f95e"
AI_GATEWAY_BASE_SHA256 = "07450cdd7756b2d04b664d95aaf89c5a85ca4fd03793c3ddeb95271818be17c7"


def ok(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("OK", msg)


def sha(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def main():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    html = (ROOT / "templates/documentos.html").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    commands = (ROOT / "chat_commands.py").read_text(encoding="utf-8")
    special = (ROOT / "chat_special.py").read_text(encoding="utf-8")

    # Congelados.
    ok(sha("cedula_ops.py") == CEDULA_BASE_SHA256, "cedula_ops.py sigue byte-identical a la base estable")
    ok(sha("ai_gateway.py") == AI_GATEWAY_BASE_SHA256, "ai_gateway.py no importó el Gemini roto del ZIP descartado")

    # UX general.
    ok("img/ui/brush.png" in html and "img/ui/trash.png" in html, "brocha/papelera recuperadas con iconos aprobados")
    ok('data-wallpaper="soft"' in html and 'data-wallpaper="clean"' in html, "brocha ofrece Suave/Liso")
    ok("agregarMensajeUsuarioConAdjuntos(t,archivos);" in js, "el chat no pinta prompts operativos como texto del usuario")
    ok("limpiarComposerDespuesDeEnvio(i,textoOriginal,editSeqAlEnviar)" in js, "composer se limpia por snapshot")
    send = js[js.index("async function enviarMensaje()") : js.index("async function initChat()")]
    ok(send.index("limpiarComposerDespuesDeEnvio") < send.index("const r=await fetch('/api/chat'"), "composer se limpia antes de esperar al backend")
    ok("archivosAdjuntosChat=[...archivos]" in send, "un fallo puede restaurar los adjuntos sin volver a buscarlos")
    ok("textoVisibleAsistente" in js and "tieneUiPrincipal" in js, "la prosa redundante se filtra en la capa general de presentación")

    # Voz/comandos/adjuntos.
    ok("SpeechRecognitionCtor" in js and "iniciarDictado" in js, "dictado por voz presente")
    ok("comando:'/cuit'" in js and "comando:'/cuil'" in js and "comando:'/ficha'" in js, "menú / contiene CUIT, CUIL y ficha")
    ok("MAX_CHAT_ATTACHMENTS=5" in js and "multiple accept=" in html, "adjuntos múltiples siguen habilitados")

    # ATM determinístico.
    ok((ROOT / "atm_cotizador.py").exists(), "módulo ATM determinístico presente")
    ok('/api/atm/cotizar' in app and "respuesta_chat_atm" in special, "ATM funciona por modal y por chat sin Gemini")
    ok("abrirCotizadorATM" in js and 'id="atmCotiModal"' in html, "modal ATM conectado al botón +")

    # Ficha operativa determinística.
    ok((ROOT / "insured_profile.py").exists(), "módulo de ficha operativa presente")
    ok("parsear_ficha_operativa" in commands and "ficha_operativa_asegurado" in commands, "ficha operativa conectada al chat")
    ok("mostrarFichaOperativaAsegurado" in js, "renderer de ficha operativa presente")

    # Rendimiento general sin alterar documentos.
    ok('GEMINI_CHAT_BUDGET_SECONDS' in app, "chat general tiene presupuesto propio")
    ok('GEMINI_DOCUMENT_BUDGET_SECONDS' in app, "documentos conservan su presupuesto separado")

    # Pruebas unitarias puras de las dos funcionalidades recuperadas.
    import atm_cotizador
    import insured_profile

    auto = atm_cotizador.cotizar_atm("158561", tipo="auto")
    manual = atm_cotizador.cotizar_atm("158561", tipo="auto", descuento="41")
    ok(auto["descuento_formateado"] == "50%", "ATM aplica preset Auto 50%")
    ok(manual["descuento_formateado"] == "41%", "ATM respeta descuento manual sobre preset")

    def leer_excel(libro):
        if str(libro) == "1":
            return {"filas": [
                ["ASEGURADO", "NUMERO", "VEHICULO", "PATENTE", "CIA", "POLIZA", "MAIL", "DNI", "COBERTURA"],
                ["JUAN PEREZ", "1122334455", "PEUGEOT 208", "AA123BB", "ATM", "123", "j@x.com", "12345678", "RC"],
            ]}
        return {"filas": [["ASEGURADO"]]}

    ficha = insured_profile.construir_ficha("AA123BB", leer_excel)
    ok(ficha.get("status") == "found" and ficha.get("asegurado") == "JUAN PEREZ", "ficha encuentra un asegurado por patente")

    print("VALIDACION_RECUPERACION_FINAL: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
