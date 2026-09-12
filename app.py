from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory,
    send_file,
    Response,
    stream_with_context,
    g,
)

from pathlib import Path
from io import BytesIO
from functools import wraps
import re
import os
import json
import logging
import traceback
import time
from contextlib import closing
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

import runtime_config

import pendientes_ops
from pending_store import PendingStore
from database_pg import (
    inicializar_postgres,
    listar_manuales,
    registrar_manual,
    actualizar_manual,
    eliminar_manual as eliminar_manual_pg,
    obtener_manual_por_r2_key,
    listar_polizas as pg_listar_polizas,
    obtener_poliza_por_r2_key,
    registrar_poliza,
    eliminar_poliza as eliminar_poliza_pg,
    listar_usuarios as pg_listar_usuarios,
    obtener_usuario as pg_obtener_usuario,
    obtener_usuario_por_id as pg_obtener_usuario_por_id,
    usuario_existe as pg_usuario_existe,
    crear_usuario as pg_crear_usuario,
    actualizar_usuario as pg_actualizar_usuario,
    eliminar_usuario as pg_eliminar_usuario,
    crear_conversacion as pg_crear_conversacion,
    listar_chats as pg_listar_chats,
    validar_chat as pg_validar_chat,
    obtener_chat_con_mensajes as pg_obtener_chat_con_mensajes,
    eliminar_chat as pg_eliminar_chat,
    agregar_mensaje as pg_agregar_mensaje,
    actualizar_metadata_mensaje as pg_actualizar_metadata_mensaje,
    listar_mensajes_historial as pg_listar_mensajes_historial,
    actualizar_tipo_chat as pg_actualizar_tipo_chat,
    obtener_titulo_chat as pg_obtener_titulo_chat,
    actualizar_titulo_chat as pg_actualizar_titulo_chat,
    obtener_configuracion as pg_obtener_configuracion,
    guardar_configuracion as pg_guardar_configuracion,
    obtener_documento_interno as pg_obtener_documento_interno,
    guardar_documento_interno as pg_guardar_documento_interno,
    obtener_flota_activa as pg_obtener_flota_activa,
    guardar_flota_activa as pg_guardar_flota_activa,
    borrar_flota_activa as pg_borrar_flota_activa,
    listar_pendientes as pg_listar_pendientes,
    contar_pendientes as pg_contar_pendientes,
    crear_pendiente as pg_crear_pendiente,
    editar_pendiente as pg_editar_pendiente,
    eliminar_pendiente as pg_eliminar_pendiente,
)
from storage_r2 import (
    subir_pdf as r2_subir_pdf,
    eliminar_pdf as r2_eliminar_pdf,
    obtener_objeto_stream,
)
from companias import normalizar_compania, nombre_compania as _nombre_compania_canonico
from local_db import conectar_db
from metadata_store import (
    listar_metadatos as metadata_listar,
    obtener_metadato as metadata_obtener,
    crear_metadato as metadata_crear,
    actualizar_metadato as metadata_actualizar,
    eliminar_metadato as metadata_eliminar,
)
from document_search import (
    MANUALES_COMPANIAS,
    MAX_PDF_FILE_SIZE_BYTES,
    MAX_PDF_PAGES_CHAT,
    MAX_PDF_TEXT_CHARS_CHAT,
    slug_manual_compania,
    extraer_texto_pdf_bytes,
    _proponer_ficha_desde_manual,
    buscar_en_documentos,
)
import estudio_ops
import envios_masivos
import atm_cotizador
import atm_quote_service
import atm_coberturas
import alta_ops
from flota_store import FlotaStore
from chat_store import ChatStore
import chat_special
import chat_commands
import chat_ai
import chat_context_actions
import alta_context
from payment_rules import calcular_regla_pago
from ai_gateway import begin_request
from chat_request import (
    parse_incoming, extract_attachment, extract_attachments, ChatRequestError,
    MAX_CHAT_ATTACHMENTS, MAX_CHAT_ATTACHMENTS_TOTAL_BYTES,
)
import config_service
import library_service
from user_store import UserStore, validar_email
from office_docs_service import OfficeDocumentsService, limpiar_filas_excel, limpiar_columnas_excel
import google_sheets_service
import system_health
import service_diagnostics
import dispatch_service
import chat_attachments
import chat_media_store
import excel_conversation_context
from excel_records import ExcelRecordService, normalizar_encabezado
from envios_ya_utils import preparar_envios_ya
from excel_books import obtener_catalogo_libros
from office_time import office_today

# ==========================================================
# CONFIGURACIÓN
# ==========================================================

# runtime_config se importa ANTES de los módulos locales y carga .env sólo en
# desarrollo, con override=False. En Render siempre manda el entorno del proceso.
BASE_DIR = runtime_config.BASE_DIR

app = Flask(__name__)

# P0.1 — Secret de sesión: en producción (Neon/Render) es obligatorio.
# El default solo se tolera en desarrollo local sin DATABASE_URL.
_secret = runtime_config.get_text("FLASK_SECRET_KEY")
_es_produccion = bool(runtime_config.get_text("DATABASE_URL") or runtime_config.get_text("RENDER"))
if _es_produccion:
    if not _secret or _secret == "OFICINA_SEGUROS_CAMBIAR_CLAVE":
        raise RuntimeError(
            "FLASK_SECRET_KEY debe estar definida en producción y no puede "
            "ser el valor por defecto. Configurala en el panel de Render."
        )
    app.secret_key = _secret
else:
    app.secret_key = _secret or "OFICINA_SEGUROS_CAMBIAR_CLAVE"

# Cookies de sesión endurecidas (P0.1 / P1.1).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_es_produccion,  # solo HTTPS en prod
    MAX_CONTENT_LENGTH=45 * 1024 * 1024,
)

# P-FIX500 — Logger técnico para excepciones no controladas. Va a stdout,
# que es lo que Render captura como logs del servicio.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("oficinaia")

# Validación local y segura de configuración. Las integraciones secundarias no
# impiden arrancar OficinaIA; sólo se informa qué servicio quedará degradado.
_STARTUP_ENV = runtime_config.validate_environment(production=_es_produccion)
for _svc, _state in _STARTUP_ENV["services"].items():
    if not _state["configured"]:
        logger.warning(
            "CONFIG servicio=%s faltantes=%s vacias=%s",
            _svc,
            ",".join(_state["missing"]) or "-",
            ",".join(_state["empty"]) or "-",
        )


# P-FIX500 — Red de seguridad global: ninguna excepción no controlada debe
# terminar en el HTML genérico de Flask/Werkzeug ("Internal Server Error").
# Esto NO reemplaza el manejo específico que ya tienen /api/chat y otras
# rutas (que arman mensajes más precisos): es la última línea de defensa
# para cualquier endpoint que no tenga su propio try/except, para que el
# frontend (leerJsonSeguro) siempre reciba JSON parseable.
@app.errorhandler(Exception)
def _manejar_excepcion_no_controlada(error):
    from werkzeug.exceptions import HTTPException

    if isinstance(error, HTTPException):
        # Errores HTTP legítimos (404, 405, etc.) mantienen su status,
        # pero devolvemos JSON en vez del HTML por defecto de Werkzeug.
        logger.warning(
            "HTTPException en %s %s: %s", request.method, request.path, error
        )
        return jsonify({
            "ok": False,
            "error": error.description or "No se pudo completar la operación.",
        }), error.code

    # Excepción real no controlada: log técnico completo (sin credenciales)
    # y respuesta JSON genérica y amigable para el usuario.
    logger.error(
        "EXCEPCIÓN NO CONTROLADA en %s %s: %s\n%s",
        request.method,
        request.path,
        error,
        traceback.format_exc(),
    )
    return jsonify({
        "ok": False,
        "error": "Ocurrió un problema al procesar la solicitud. Intentá nuevamente. "
                 "Si el problema continúa, avisá al administrador.",
    }), 500


# Request demasiado grande (ej. PDF > MAX_CONTENT_LENGTH): Werkzeug corta la
# petición en el parsing, antes de que el código de /api/chat pueda dar su
# propio mensaje. Sin este handler, esto también devuelve HTML.
@app.errorhandler(413)
def _manejar_request_demasiado_grande(error):
    return jsonify({
        "ok": False,
        "error": "El conjunto de adjuntos es demasiado grande. El máximo permitido por mensaje es 40 MB.",
    }), 413


DOCUMENTOS_DIR = BASE_DIR / "documentos"

NOTAS_FILE = BASE_DIR / "notas.json"
WORD_FILE = BASE_DIR / "documento_interno.docx"


LIBROS_EXCEL = obtener_catalogo_libros()

DOCUMENTOS_DIR.mkdir(
    exist_ok=True
)

CONFIG_FILE = BASE_DIR / "configuracion.json"
DB_FILE = BASE_DIR / "oficina.db"
ROLES_VALIDOS = {"admin", "usuario"}
USUARIO_ADMIN_PRINCIPAL = "admin"

# Accesos directos a plataformas de compañías. Se muestran solo los nombres.
CIAS_LINKS = [
    ("Self", "https://online.fedpat.com.ar/self/index.jsp"),
    ("ATM", "https://extranet.atmseguros.com.ar/ATM_COM_PROD/servlet/ar.com.glmsa.seguros.comercial.hlogin"),
    ("Rivadavia", "https://www.sistemas.segurosrivadavia.com/sistemas/login/login_intra_pas.php?u=P"),
    ("Triunfo", "https://www.triunfonet.com.ar/gauswebtriunfo/servlet/hlogon"),
    ("Prof", "https://pasnet.profseguros.seg.ar/Default.aspx"),
    ("Ags", "https://www.agsnet.com.ar/ingreprod.php"),
    ("San Cristobal", "https://productores.sancristobal.com.ar/"),
    ("Mercantil Andina", "https://servicios.mercantilandina.com.ar/sigmav3/"),
    ("EuroAmerica", "https://pas.euroamericaseguros.seg.ar/login"),
    ("Allianz", "https://auth.allianz.com.ar/login"),
]

def _companias_sidebar_default():
    return config_service.companias_sidebar_default()

MANUALES_DIR = BASE_DIR / "manuales_companias"
POLIZAS_DIR = BASE_DIR / "polizas"
MANUALES_DIR.mkdir(exist_ok=True)
POLIZAS_DIR.mkdir(exist_ok=True)

def manuales_companias():
    """Adaptador compatible para la estructura que espera la interfaz."""
    return library_service.agrupar_manuales(
        listar_manuales(), MANUALES_COMPANIAS, slug_manual_compania
    )


# ==========================================================
# USUARIOS Y AUTENTICACIÓN
# ==========================================================


def _usuarios_usar_pg():
    """True si hay DATABASE_URL (Neon): los usuarios se guardan ahí y
    sobreviven a los redeploys/reinicios de Render. Si no hay Neon
    configurada, se usa SQLite local como respaldo (solo para desarrollo)."""
    return bool(runtime_config.get_text("DATABASE_URL"))


# Los chats (conversaciones + mensajes) usan la misma regla que los usuarios:
# con Neon configurada viven en Postgres y sobreviven a los redeploys de
# Render; sin Neon, caen a SQLite local (solo development).
_chats_usar_pg = _usuarios_usar_pg

# La configuración global (nombre de oficina, colores, herramientas
# visibles) sigue la misma regla: Neon si está configurada, archivo JSON
# local como respaldo de desarrollo.
_config_usar_pg = _usuarios_usar_pg

# El documento interno (Word / "Notas") es texto plano: con Neon vive en
# Postgres; sin Neon cae al .docx local como respaldo de desarrollo.
_documento_interno_usar_pg = _usuarios_usar_pg


def inicializar_base_datos():
    with closing(conectar_db()) as db:
        db.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE NOT NULL, password TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS conversaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL,
            titulo TEXT NOT NULL DEFAULT 'Nueva conversación',
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversacion_id INTEGER NOT NULL,
            rol TEXT NOT NULL,
            contenido TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(conversacion_id) REFERENCES conversaciones(id) ON DELETE CASCADE
        )""")
        cols_msg = {fila[1] for fila in db.execute("PRAGMA table_info(mensajes)").fetchall()}
        if "metadata" not in cols_msg:
            db.execute("ALTER TABLE mensajes ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}' ")
        db.execute("""CREATE TABLE IF NOT EXISTS flotas_activas (
            conversacion_id INTEGER PRIMARY KEY,
            estado TEXT NOT NULL DEFAULT 'nueva',
            libro_id TEXT NOT NULL DEFAULT '2',
            datos_generales TEXT NOT NULL DEFAULT '{}',
            vehiculos TEXT NOT NULL DEFAULT '[]',
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(conversacion_id) REFERENCES conversaciones(id) ON DELETE CASCADE
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS eventos_sistema (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            categoria TEXT NOT NULL,
            nivel TEXT NOT NULL,
            mensaje TEXT NOT NULL,
            detalle_tecnico TEXT
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_eventos_sistema_fecha ON eventos_sistema(timestamp DESC)")
        cols_eventos = {fila[1] for fila in db.execute("PRAGMA table_info(eventos_sistema)").fetchall()}
        if "codigo" not in cols_eventos:
            db.execute("ALTER TABLE eventos_sistema ADD COLUMN codigo TEXT")
        db.execute("""CREATE TABLE IF NOT EXISTS metadatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL,
            titulo TEXT NOT NULL,
            contenido TEXT NOT NULL,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        columnas = {fila[1] for fila in db.execute("PRAGMA table_info(usuarios)").fetchall()}
        if "email" not in columnas: db.execute("ALTER TABLE usuarios ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        if "rol" not in columnas: db.execute("ALTER TABLE usuarios ADD COLUMN rol TEXT NOT NULL DEFAULT 'usuario'")
        if "protegido" not in columnas: db.execute("ALTER TABLE usuarios ADD COLUMN protegido INTEGER NOT NULL DEFAULT 0")
        # P2.6 / Tanda C — tipo de chat (flota|coti|alta|envios)
        cols_conv = {fila[1] for fila in db.execute("PRAGMA table_info(conversaciones)").fetchall()}
        if "tipo" not in cols_conv:
            db.execute("ALTER TABLE conversaciones ADD COLUMN tipo TEXT NOT NULL DEFAULT ''")
        # El bootstrap del admin en SQLite sólo importa cuando NO hay Neon
        # (desarrollo local). Con Neon configurada, el admin se crea/mantiene
        # en Postgres desde inicializar_postgres(), para no pisar contraseñas
        # cambiadas en la nube con el valor por defecto de este archivo local.
        if not _usuarios_usar_pg():
            admin = db.execute("SELECT id FROM usuarios WHERE usuario = ?", (USUARIO_ADMIN_PRINCIPAL,)).fetchone()
            if admin is None:
                db.execute("INSERT INTO usuarios (usuario,password,email,rol,protegido) VALUES (?,?,?,?,1)", ("admin", generate_password_hash("1234"), "", "admin"))
            else:
                db.execute("UPDATE usuarios SET rol='admin', protegido=1 WHERE usuario=?", (USUARIO_ADMIN_PRINCIPAL,))
        db.commit()
        pendientes_ops.asegurar_tabla(db)


def _user_store():
    return UserStore(
        usar_pg=_usuarios_usar_pg(),
        conectar_db=conectar_db,
        pg={
            "obtener_usuario": pg_obtener_usuario,
            "obtener_usuario_por_id": pg_obtener_usuario_por_id,
            "listar_usuarios": pg_listar_usuarios,
            "usuario_existe": pg_usuario_existe,
            "crear_usuario": pg_crear_usuario,
            "actualizar_usuario": pg_actualizar_usuario,
            "eliminar_usuario": pg_eliminar_usuario,
        },
        hash_password=generate_password_hash,
    )

def obtener_usuario(usuario):
    return _user_store().obtener_por_usuario(usuario)

def obtener_usuario_por_id(usuario_id):
    return _user_store().obtener_por_id(usuario_id)

def usuario_es_admin():
    u = obtener_usuario(session.get("usuario", "")) if session.get("usuario") else None
    return bool(u and u["rol"] == "admin")

def requiere_admin(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "usuario" not in session: return redirect(url_for("login"))
        if not usuario_es_admin(): return ("Acceso no autorizado", 403)
        return func(*args, **kwargs)
    return wrapper



def static_asset(filename: str) -> str:
    """URL de assets locales con cache-busting automático por mtime.

    Evita versionados manuales olvidables como 20260911-fix-1: si cambia el
    archivo, cambia la query string servida por Flask y el navegador pide la
    versión nueva.
    """
    nombre = str(filename or "").lstrip("/")
    kwargs = {"filename": nombre}
    try:
        path = BASE_DIR / "static" / nombre
        kwargs["v"] = str(int(path.stat().st_mtime))
    except Exception:
        kwargs["v"] = "dev"
    return url_for("static", **kwargs)

def _herramientas_legacy_a_lista(visibles=None, urls=None):
    # Compatibilidad de migración: la implementación vive fuera de Flask.
    return config_service.herramientas_legacy_a_lista(visibles, urls)

def cargar_configuracion():
    return config_service.cargar_configuracion(
        usar_pg=_config_usar_pg(),
        pg_obtener=pg_obtener_configuracion,
        config_file=CONFIG_FILE,
    )

def contexto_usuario():
    u=obtener_usuario(session.get("usuario", "")) if session.get("usuario") else None
    config = cargar_configuracion()
    return {
        "usuario_rol": u["rol"] if u else None,
        "usuario_es_admin": bool(u and u["rol"] == "admin"),
        "config_global": config,
        "cias_links": [(c["nombre"], c["url"]) for c in config.get("companias", []) if c.get("visible", True)],
        "static_asset": static_asset,
    }

app.context_processor(contexto_usuario)


# ==========================================================
# LOGIN
# ==========================================================

def requiere_login(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "usuario" not in session:

            return redirect(
                url_for("login")
            )

        return func(
            *args,
            **kwargs
        )

    return wrapper


# ==========================================================
# NOMBRES DE COMPAÑÍAS
# ==========================================================

def nombre_compania(nombre):
    return _nombre_compania_canonico(nombre)


app.jinja_env.globals["nombre_compania"] = nombre_compania


# ==========================================================
# OBTENER COMPAÑÍAS
# ==========================================================

def obtener_companias():
    """Devuelve únicamente las compañías que forman parte de la biblioteca de Manuales."""
    DOCUMENTOS_DIR.mkdir(parents=True, exist_ok=True)

    companias = [
        "atm",
        "mercantil_andina",
        "federacion_patronal",
        "san_cristobal",
        "rivadavia",
        "euroamerica",
        "agrosalta",
        "triunfo",
        "prof",
    ]

    for compania in companias:
        (DOCUMENTOS_DIR / compania).mkdir(parents=True, exist_ok=True)

    return sorted(
        companias,
        key=lambda x: nombre_compania(x).lower()
    )


# ==========================================================
# LOGIN
# ==========================================================

@app.route(
    "/",
    methods=["GET", "POST"]
)
def login():

    if "usuario" in session:

        return redirect(
            url_for("documentos")
        )

    error = None

    if request.method == "POST":

        usuario = request.form.get(
            "usuario",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        registro = obtener_usuario(usuario)
        if registro:
            try: valido = check_password_hash(registro["password"], password)
            except (ValueError, TypeError): valido = False
            if valido:
                session.clear()
                session["usuario"] = registro["usuario"]
                session["rol"] = registro["rol"]
                session["forzar_chat_nuevo"] = True
                return redirect(url_for("documentos"))
        error = "Usuario o contraseña incorrectos."

    return render_template(
        "login.html",
        error=error
    )


# ==========================================================
# INICIO
# ==========================================================

@app.route("/documentos")
@requiere_login
def documentos():
    # Consumir el flag una sola vez: solo fuerza un chat nuevo al iniciar sesión.
    forzar_chat_nuevo = session.pop("forzar_chat_nuevo", False)

    return render_template(
        "documentos.html",
        carpetas=obtener_companias(),
        usuario=session["usuario"],
        usuario_rol=session.get("rol", "usuario"),
        forzar_chat_nuevo=forzar_chat_nuevo
    )


# ==========================================================
# VER CARPETA
# ==========================================================

@app.route(
    "/carpeta/<path:carpeta>"
)
@requiere_login
def ver_carpeta(carpeta):
    # P0.5 — Anti path-traversal: el path resuelto debe quedar bajo DOCUMENTOS_DIR.
    try:
        carpeta_path = (DOCUMENTOS_DIR / carpeta).resolve()
        if not carpeta_path.is_relative_to(DOCUMENTOS_DIR.resolve()):
            return ("Acceso denegado", 403)
    except (OSError, ValueError):
        return ("Compañía no encontrada", 404)

    if not carpeta_path.exists() or not carpeta_path.is_dir():
        return ("Compañía no encontrada", 404)

    archivos = []
    for archivo in carpeta_path.rglob("*"):
        if archivo.is_file():
            try:
                rel = archivo.relative_to(carpeta_path)
            except ValueError:
                continue
            archivos.append({
                "nombre": archivo.name,
                "ruta": str(rel),
                "extension": archivo.suffix.lower(),
                "tamaño": round(archivo.stat().st_size / 1024, 1),
            })

    return render_template(
        "carpeta.html",
        carpeta=carpeta,
        nombre=nombre_compania(carpeta),
        archivos=archivos,
        usuario=session["usuario"],
        carpetas=obtener_companias()
    )


# ==========================================================
# ARCHIVO
# ==========================================================

@app.route(
    "/archivo/<path:carpeta>/<path:archivo>"
)
@requiere_login
def archivo(carpeta, archivo):
    # P0.5 — Anti path-traversal.
    try:
        carpeta_path = (DOCUMENTOS_DIR / carpeta).resolve()
        archivo_path = (carpeta_path / archivo).resolve()
        base = DOCUMENTOS_DIR.resolve()
        if not carpeta_path.is_relative_to(base) or not archivo_path.is_relative_to(base):
            return ("Acceso denegado", 403)
    except (OSError, ValueError):
        return ("Archivo no encontrado", 404)

    if not archivo_path.exists() or not archivo_path.is_file():
        return ("Archivo no encontrado", 404)

    # send_from_directory necesita el directorio base y el nombre relativo.
    rel = archivo_path.relative_to(carpeta_path)
    return send_from_directory(str(carpeta_path), str(rel))


# ==========================================================
# BUSCADOR
# ==========================================================

@app.route("/buscar")
@requiere_login
def buscar():

    return render_template(
        "buscar.html",
        usuario=session["usuario"],
        carpetas=obtener_companias()
    )


# ==========================================================
# BUSCADOR DE ARCHIVOS
# ==========================================================

@app.route(
    "/api/buscar"
)
@requiere_login
def api_buscar():

    consulta = request.args.get(
        "q",
        ""
    ).strip().lower()

    resultados = []

    if not consulta:

        return jsonify(
            resultados
        )

    for archivo in DOCUMENTOS_DIR.rglob("*"):

        if not archivo.is_file():

            continue

        if consulta not in archivo.name.lower():

            continue

        try:

            relativa = archivo.relative_to(
                DOCUMENTOS_DIR
            )

            partes = relativa.parts

            compania = (
                partes[0]
                if partes
                else ""
            )

            resultados.append({

                "nombre":
                    archivo.name,

                "compania":
                    nombre_compania(
                        compania
                    ),

                "ruta":
                    str(
                        relativa
                    ),

                "extension":
                    archivo.suffix.lower(),

                "tamaño":
                    round(
                        archivo.stat().st_size / 1024,
                        1
                    )

            })

        except Exception:

            pass

    return jsonify(
        resultados[:200]
    )


# ==========================================================
# BÚSQUEDA REAL EN CONTENIDO
# ==========================================================

@app.route(
    "/api/consultar_documentos",
    methods=["POST"]
)
@requiere_login
def consultar_documentos():

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "ok": False,
            "resultados": []
        })

    consulta = data.get(
        "consulta",
        ""
    ).strip()

    resultados = buscar_en_documentos(
        consulta
    )

    respuesta = []

    for resultado in resultados[:5]:

        texto = resultado["texto"]

        palabras = re.findall(
            r"\w+",
            consulta.lower()
        )

        posiciones = []

        for palabra in palabras:

            posicion = texto.lower().find(
                palabra
            )

            if posicion >= 0:

                posiciones.append(
                    posicion
                )

        if posiciones:

            posicion = min(
                posiciones
            )

        else:

            posicion = 0

        inicio = max(
            0,
            posicion - 250
        )

        fin = min(
            len(texto),
            posicion + 750
        )

        fragmento = (
            texto[inicio:fin]
            .replace(
                "\n",
                " "
            )
        )

        respuesta.append({

            "archivo":
                resultado["archivo"],

            "compania":
                resultado["compania"],

            "coincidencias":
                resultado["coincidencias"],

            "fragmento":
                fragmento

        })

    return jsonify({

        "ok": True,

        "resultados":
            respuesta

    })


# ==========================================================
# ==========================================================
# EXCEL Y WORD INTERNOS
# ==========================================================

def _invalidar_cache_excel_ia():
    from servicios_ia import invalidar_cache_excel_interno
    invalidar_cache_excel_interno()


_office_docs = OfficeDocumentsService(
    word_file=WORD_FILE,
    usar_pg_documento=_documento_interno_usar_pg,
    pg_obtener_documento=pg_obtener_documento_interno,
    pg_guardar_documento=pg_guardar_documento_interno,
)

# Wrappers de compatibilidad: el contrato externo no cambia, pero la fuente
# activa de Asegurados/Flotas es exclusivamente Google Sheets.
def leer_excel_interno(libro_id="1"):
    return google_sheets_service.leer_excel(libro_id)

def guardar_matriz_excel(filas, nombre_hoja="Datos", libro_id="1"):
    google_sheets_service.guardar_excel(filas, nombre_hoja, libro_id)
    if str(libro_id) == "1":
        _invalidar_cache_excel_ia()
    return None

def agregar_filas_excel(filas, libro_id="1", nombre_hoja=None):
    cantidad = google_sheets_service.agregar_filas(filas, libro_id, nombre_hoja)
    if str(libro_id) == "1":
        _invalidar_cache_excel_ia()
    return cantidad

def _limpiar_filas_excel(filas, conservar_vacias=False):
    return limpiar_filas_excel(filas, conservar_vacias)

def _limpiar_columnas_excel(filas):
    return limpiar_columnas_excel(filas)

def leer_word_interno():
    return _office_docs.leer_word()

def guardar_word_interno(contenido):
    return _office_docs.guardar_word(contenido)

def _generar_docx_documento_interno():
    return _office_docs.generar_docx()


@app.route("/notas")
@requiere_login
def notas():
    # Se conserva la URL para no romper marcadores antiguos; ahora muestra Excel + Word.
    return render_template("notas.html", usuario=session["usuario"], carpetas=obtener_companias())


@app.route("/api/atm/catalogo", methods=["GET"])
@requiere_login
def api_atm_catalogo():
    return jsonify({"ok": True, "coberturas": atm_coberturas.catalogo_publico()})


@app.route("/api/atm/cotizar", methods=["POST"])
@requiere_login
def api_atm_cotizar():
    data = request.get_json(silent=True) or {}
    try:
        resultado = atm_cotizador.cotizar_atm(
            data.get("precio_base"),
            tipo=data.get("tipo"),
            descuento=data.get("descuento"),
        )
        return jsonify({"ok": True, **resultado})
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        logger.exception("Error calculando cotización ATM: %s", error)
        return jsonify({"ok": False, "error": "No se pudo calcular la cotización ATM."}), 500


@app.route("/api/atm/leer-captura", methods=["POST"])
@requiere_login
def api_atm_leer_captura():
    archivo = request.files.get("captura")
    if not archivo or not getattr(archivo, "filename", ""):
        return jsonify({"ok": False, "error": "Adjuntá una captura de la cotización ATM."}), 400
    try:
        adjunto = extract_attachment(
            archivo,
            max_pdf_bytes=MAX_PDF_FILE_SIZE_BYTES,
            max_pages=1,
            max_chars=4000,
        )
        if adjunto is None or adjunto.tipo != "imagen":
            return jsonify({"ok": False, "error": "Usá una captura PNG, JPG, JPEG o WEBP."}), 400
        begin_request(
            runtime_config.get_float("GEMINI_ATM_CAPTURE_BUDGET_SECONDS", 45.0),
            request_id=getattr(g, "chat_request_id", None),
        )
        resultado = atm_quote_service.extraer_cotizacion_atm(adjunto)
        if not resultado.get("es_cotizacion_atm"):
            return jsonify({"ok": False, "error": "La imagen no parece ser una pantalla de cotización ATM."}), 422
        return jsonify({"ok": True, **resultado})
    except ChatRequestError as error:
        return jsonify({"ok": False, "error": str(error)}), error.status_code
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        logger.exception("Error leyendo captura ATM: %s", error)
        return jsonify({"ok": False, "error": "No pude leer la captura ATM en este intento. Reintentá o cargá el precio manualmente."}), 500


@app.route("/api/excel", methods=["GET"])
@requiere_login
def api_excel():
    libro_id = request.args.get("libro_id", "1")
    try:
        return jsonify({"ok": True, **leer_excel_interno(libro_id)})
    except Exception as error:
        system_health.registrar_evento("excel", "error", "No se pudo leer la planilla", str(error))
        print("ERROR LEYENDO EXCEL INTERNO:", error)
        return jsonify({"ok": False, "error": "No se pudo leer la planilla."}), 500


@app.route("/api/excel", methods=["POST"])
@requiere_login
def api_excel_guardar():
    data = request.get_json(silent=True) or {}
    libro_id = data.get("libro_id", request.args.get("libro_id", "1"))
    try:
        guardar_matriz_excel(data.get("filas", []), data.get("hoja", "Datos"), libro_id)
        return jsonify({"ok": True, **leer_excel_interno(libro_id)})
    except Exception as error:
        system_health.registrar_evento("excel", "error", "No se pudo guardar la planilla", str(error))
        print("ERROR GUARDANDO EXCEL INTERNO:", error)
        return jsonify({"ok": False, "error": "No se pudo guardar la planilla."}), 500


@app.route("/api/excel/limpiar", methods=["POST"])
@requiere_login
def api_excel_limpiar():
    data = request.get_json(silent=True) or {}
    libro_id = data.get("libro_id", request.args.get("libro_id", "1"))
    try:
        datos = leer_excel_interno(libro_id)
        filas_limpias = _limpiar_filas_excel(datos["filas"], conservar_vacias=False)
        guardar_matriz_excel(filas_limpias, datos["hoja"], libro_id)
        return jsonify({"ok": True, **leer_excel_interno(libro_id)})
    except Exception as error:
        system_health.registrar_evento("excel", "error", "No se pudieron eliminar filas vacías", str(error))
        print("ERROR LIMPIANDO EXCEL:", error)
        return jsonify({"ok": False, "error": "No se pudieron eliminar las filas vacías."}), 500


@app.route("/api/excel/limpiar-columnas", methods=["POST"])
@requiere_login
def api_excel_limpiar_columnas():
    data = request.get_json(silent=True) or {}
    libro_id = data.get("libro_id", request.args.get("libro_id", "1"))
    try:
        datos = leer_excel_interno(libro_id)
        filas_limpias = _limpiar_columnas_excel(datos["filas"])
        guardar_matriz_excel(filas_limpias, datos["hoja"], libro_id)
        return jsonify({"ok": True, **leer_excel_interno(libro_id)})
    except Exception as error:
        system_health.registrar_evento("excel", "error", "No se pudieron eliminar columnas vacías", str(error))
        return jsonify({"ok": False, "error": "No se pudieron eliminar las columnas vacías."}), 500


@app.route("/api/excel/importar", methods=["POST"])
@requiere_login
def api_excel_importar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return jsonify({"ok": False, "error": "No se recibió ningún archivo."}), 400
    nombre = secure_filename(archivo.filename)
    if not nombre.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"ok": False, "error": "Usá un archivo Excel .xlsx o .xlsm."}), 400
    libro_id = request.form.get("libro_id", request.args.get("libro_id", "1"))
    if str(libro_id) not in LIBROS_EXCEL:
        return jsonify({"ok": False, "error": "Libro de Excel no válido."}), 400
    try:
        wb = load_workbook(archivo.stream, data_only=False)
        if not wb.sheetnames:
            raise ValueError("El Excel no contiene hojas.")
        ws = wb[wb.sheetnames[0]]
        filas = [["" if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)]
        guardar_matriz_excel(filas, ws.title, libro_id)
        return jsonify({"ok": True, **leer_excel_interno(libro_id)})
    except Exception as error:
        system_health.registrar_evento("excel", "error", "No se pudo importar un Excel a Sheets", str(error))
        print("ERROR IMPORTANDO EXCEL:", error)
        return jsonify({"ok": False, "error": "No se pudo importar el Excel."}), 400


@app.route("/excel/exportar")
@requiere_login
def excel_exportar():
    libro_id = request.args.get("libro_id", "1")
    if str(libro_id) not in LIBROS_EXCEL:
        return jsonify({"ok": False, "error": "Libro de Excel no válido."}), 400
    try:
        datos = leer_excel_interno(libro_id)
        wb = Workbook()
        ws = wb.active
        ws.title = str(datos.get("hoja") or "Datos")[:31]
        filas = datos.get("filas") or []
        for fila in filas:
            ws.append(["" if v is None else str(v) for v in fila])
        for c in range(1, max(1, int(datos.get("columnas") or 1)) + 1):
            letra = get_column_letter(c)
            valores = [str(ws.cell(r, c).value or "") for r in range(1, min(ws.max_row, 30) + 1)]
            ws.column_dimensions[letra].width = min(max([len(v) for v in valores] + [10]) + 2, 32)
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        nombre = "OficinaIA_Asegurados.xlsx" if str(libro_id) == "1" else "OficinaIA_Flotas.xlsx"
        return send_file(buffer, as_attachment=True, download_name=nombre, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as error:
        system_health.registrar_evento("excel", "error", "No se pudo exportar Sheets a XLSX", str(error))
        return jsonify({"ok": False, "error": "No se pudo exportar la planilla."}), 500


@app.route("/api/word", methods=["GET"])
@requiere_login
def api_word():
    try:
        return jsonify({"ok": True, "contenido": leer_word_interno()})
    except Exception as error:
        print("ERROR LEYENDO WORD:", error)
        return jsonify({"ok": False, "error": "No se pudo leer el documento."}), 500


@app.route("/api/word", methods=["POST"])
@requiere_login
def api_word_guardar():
    data = request.get_json(silent=True) or {}
    try:
        guardar_word_interno(data.get("contenido", ""))
        return jsonify({"ok": True})
    except Exception as error:
        print("ERROR GUARDANDO WORD:", error)
        return jsonify({"ok": False, "error": "No se pudo guardar el documento."}), 500


@app.route("/word/exportar")
@requiere_login
def word_exportar():
    _generar_docx_documento_interno()
    return send_from_directory(WORD_FILE.parent, WORD_FILE.name, as_attachment=True, download_name="OficinaIA.docx")




# ==========================================================
# METADATOS — FICHAS DE TEXTO LIBRE
# Persistencia aislada en metadata_store.py. Flask sólo traduce HTTP/JSON.
# ==========================================================

@app.route("/api/metadatos", methods=["GET"])
@requiere_login
def listar_metadatos():
    try:
        filas = metadata_listar()
        resumen = [
            {
                "id": f["id"],
                "titulo": f.get("titulo"),
                "actualizado_en": f.get("actualizado_en"),
            }
            for f in filas
        ]
        return jsonify({"ok": True, "metadatos": resumen})
    except Exception as error:
        print("ERROR listar_metadatos:", error)
        return jsonify({"ok": False, "error": "No se pudieron listar los metadatos."}), 500


@app.route("/api/metadatos/<int:metadato_id>", methods=["GET"])
@requiere_login
def obtener_metadato(metadato_id):
    try:
        fila = metadata_obtener(metadato_id)
        if not fila:
            return jsonify({"ok": False, "error": "Ficha no encontrada."}), 404
        return jsonify({"ok": True, "metadato": fila})
    except Exception as error:
        print("ERROR obtener_metadato:", error)
        return jsonify({"ok": False, "error": "No se pudo leer la ficha."}), 500


@app.route("/api/metadatos", methods=["POST"])
@requiere_login
def crear_metadato():
    data = request.get_json(silent=True) or {}
    titulo = str(data.get("titulo", "")).strip()
    contenido = str(data.get("contenido", "") or "")
    if not titulo:
        return jsonify({"ok": False, "error": "El título es obligatorio."}), 400
    titulo = titulo[:200]

    try:
        fila = metadata_crear(session["usuario"], titulo, contenido)
        return jsonify({"ok": True, "metadato": fila})
    except Exception as error:
        print("ERROR crear_metadato:", error)
        return jsonify({"ok": False, "error": "No se pudo guardar la ficha."}), 500


@app.route("/api/metadatos/<int:metadato_id>", methods=["PUT"])
@requiere_login
def editar_metadato(metadato_id):
    data = request.get_json(silent=True) or {}
    titulo = str(data.get("titulo", "")).strip()
    contenido = str(data.get("contenido", "") or "")
    if not titulo:
        return jsonify({"ok": False, "error": "El título es obligatorio."}), 400
    titulo = titulo[:200]

    try:
        fila = metadata_actualizar(metadato_id, titulo, contenido)
        if not fila:
            return jsonify({"ok": False, "error": "Ficha no encontrada."}), 404
        return jsonify({"ok": True, "metadato": fila})
    except Exception as error:
        print("ERROR editar_metadato:", error)
        return jsonify({"ok": False, "error": "No se pudo actualizar la ficha."}), 500


@app.route("/api/metadatos/<int:metadato_id>", methods=["DELETE"])
@requiere_login
def eliminar_metadato(metadato_id):
    try:
        ok = metadata_eliminar(metadato_id)
        if not ok:
            return jsonify({"ok": False, "error": "Ficha no encontrada."}), 404
        return jsonify({"ok": True})
    except Exception as error:
        print("ERROR eliminar_metadato:", error)
        return jsonify({"ok": False, "error": "No se pudo eliminar la ficha."}), 500

# ==========================================================
# CONVERSACIONES PERSISTENTES
# ==========================================================

def _crear_conversacion(usuario, titulo="Nueva conversación"):
    return _chat_store.crear(usuario, titulo)


def _validar_chat(chat_id, usuario):
    return _chat_store.validar(chat_id, usuario)


def _guardar_mensaje(chat_id, rol, contenido, metadata=None):
    # Los errores de persistencia se propagan: un turno no debe fingir que
    # quedó guardado cuando PostgreSQL falló.
    return _chat_store.guardar_mensaje(chat_id, rol, contenido, metadata=metadata)


def _historial_desde_db(chat_id, usuario, limite=10):
    return _chat_store.historial(chat_id, usuario, limite=limite)


def _detectar_tipo_chat(mensaje):
    """Tipo operativo a partir del mensaje (comandos slash y señales claras)."""
    t = (mensaje or "").strip().lower()
    if t.startswith("/flota") or t.startswith("flota "):
        return "flota"
    if t.startswith("/coti"):
        return "coti"
    if t.startswith("/guardar") or t.startswith("/alta"):
        return "alta"
    if t.startswith("/envios") or t.startswith("/envíos"):
        return "envios"
    if "whatsapp" in t[:80]:
        return "whatsapp"
    return ""


def _asignar_tipo_chat(chat_id, usuario, mensaje):
    tipo = _detectar_tipo_chat(mensaje)
    if not tipo or not chat_id:
        return
    try:
        _chat_store.asignar_tipo_si_vacio(chat_id, usuario, tipo)
    except Exception as error:
        print("ERROR _asignar_tipo_chat:", error)


def _generar_titulo_chat(mensaje):
    """Título corto y útil a partir de la primera consulta. Determinístico, sin IA."""
    texto = " ".join(str(mensaje or "").split())
    if not texto:
        return "Nueva conversación"

    if texto.startswith("/"):
        partes = texto.split(None, 1)
        cmd = partes[0]
        resto = partes[1].strip() if len(partes) > 1 else ""
        if resto:
            corto = resto[:42] + ("…" if len(resto) > 42 else "")
            return f"{cmd} — {corto}"[:90]
        return cmd[:90]

    t = texto
    t = re.sub(r"^[¿?¡!\s]+", "", t)
    t = re.sub(r"[¿?¡!]+$", "", t).strip()
    # Quitar muletillas de pregunta frecuentes
    t = re.sub(
        r"^(?:cu[aá]ntos?|cu[aá]ntas?|qu[eé]|c[oó]mo|cu[aá]ndo|d[oó]nde|por\s+qu[eé]|para\s+qu[eé]|"
        r"me\s+pod[eé]s|pod[eé]s|necesit[oa]|quiero|haceme|armame|decime|mostrame|"
        r"busc[aá]|listame|ten[eé]s|dame|pasame|informame)\b[\s,:]*",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    t = re.sub(r"^(?:de\s+la|de\s+los|de\s+las|del|de|el|la|los|las|un|una)\s+", "", t, flags=re.IGNORECASE).strip()

    if not t:
        t = texto

    # Si aparece una compañía conocida, priorizarla al frente
    companias = (
        "ATM", "Sancor", "San Cor", "Mercantil Andina", "Mercantil", "Rivadavia",
        "Federación Patronal", "Federacion Patronal", "La Segunda", "Sura", "Allianz",
        "Mapfre", "Zurich", "Experta", "Provincia", "Triunfo", "Nación", "Nacion",
        "HDI", "Chubb", "SMG", "Galeno", "Prevención", "Prevencion",
    )
    encontrada = None
    lower = t.lower()
    for cia in sorted(companias, key=len, reverse=True):
        if cia.lower() in lower:
            encontrada = cia
            break
    if encontrada:
        resto = re.sub(re.escape(encontrada), " ", t, count=1, flags=re.IGNORECASE)
        # Limpiar verbos/conectores sobrantes del enunciado interrogativo
        resto = re.sub(
            r"\b(tiene|tienen|hay|son|es|para|sobre|con|del|de\s+la|de\s+los|de\s+las|de)\b",
            " ",
            resto,
            flags=re.IGNORECASE,
        )
        resto = re.sub(r"\s+", " ", resto).strip(" -—,.:;")
        if resto:
            if resto and resto[0].islower():
                resto = resto[0].upper() + resto[1:]
            if len(resto) > 40:
                corte = resto[:40].rsplit(" ", 1)[0] or resto[:40]
                resto = corte + "…"
            t = f"{encontrada} — {resto}"
        else:
            t = encontrada
    else:
        if t and t[0].islower():
            t = t[0].upper() + t[1:]
        if len(t) > 56:
            corte = t[:53].rsplit(" ", 1)[0] or t[:53]
            t = corte + "…"

    return (t or "Nueva conversación")[:90]


def _obtener_titulo_chat(chat_id, usuario):
    try:
        return _chat_store.obtener_titulo(chat_id, usuario)
    except Exception as error:
        print("ERROR _obtener_titulo_chat:", error)
        return None


def _actualizar_titulo_chat(chat_id, usuario, titulo):
    try:
        return _chat_store.actualizar_titulo(chat_id, usuario, titulo)
    except Exception as error:
        print("ERROR _actualizar_titulo_chat:", error)
        return False


def _auto_titulo_si_corresponde(chat_id, usuario, mensaje):
    """Si el chat sigue con el título por defecto, lo reemplaza con uno derivado del mensaje."""
    actual = _obtener_titulo_chat(chat_id, usuario)
    if actual is None:
        return None
    if str(actual).strip().lower() not in {"nueva conversación", "nueva conversacion", ""}:
        return actual
    nuevo = _generar_titulo_chat(mensaje)
    if nuevo and nuevo != actual:
        _actualizar_titulo_chat(chat_id, usuario, nuevo)
        return nuevo
    return actual


_chat_store = ChatStore(
    usar_pg=_chats_usar_pg,
    conectar_db=conectar_db,
    pg={
        "crear": pg_crear_conversacion,
        "listar": pg_listar_chats,
        "validar": pg_validar_chat,
        "obtener": pg_obtener_chat_con_mensajes,
        "eliminar": pg_eliminar_chat,
        "agregar_mensaje": pg_agregar_mensaje,
        "actualizar_metadata_mensaje": pg_actualizar_metadata_mensaje,
        "historial": pg_listar_mensajes_historial,
        "actualizar_tipo": pg_actualizar_tipo_chat,
        "obtener_titulo": pg_obtener_titulo_chat,
        "actualizar_titulo": pg_actualizar_titulo_chat,
    },
)

_flota_usar_pg = _usuarios_usar_pg

# V20 Etapa 4 — persistencia de /flota aislada de app.py. El dominio sigue
# usando estas tres funciones como contrato estable, pero la implementación
# PG/SQLite vive en flota_store.py y no conoce Flask ni el router del chat.
_flota_store = FlotaStore(
    usar_pg=_flota_usar_pg,
    conectar_db=conectar_db,
    pg_obtener=pg_obtener_flota_activa,
    pg_guardar=pg_guardar_flota_activa,
    pg_borrar=pg_borrar_flota_activa,
)



@app.route("/api/chats", methods=["GET"])
@requiere_login
def listar_chats():
    try:
        return jsonify({"ok": True, "chats": _chat_store.listar(session["usuario"])})
    except Exception as error:
        print("ERROR listar_chats:", error)
        return jsonify({"ok": False, "error": "No se pudieron cargar las conversaciones."}), 500

@app.route("/api/chats", methods=["POST"])
@requiere_login
def crear_chat():
    data = request.get_json(silent=True) or {}
    titulo = str(data.get("titulo", "Nueva conversación")).strip()[:100] or "Nueva conversación"
    try:
        cid = _chat_store.crear(session["usuario"], titulo)
    except Exception as error:
        print("ERROR crear_chat:", error)
        return jsonify({"ok": False, "error": "No se pudo crear la conversación."}), 500
    return jsonify({"ok": True, "id": cid, "titulo": titulo})

@app.route("/api/chats/<int:chat_id>", methods=["GET"])
@requiere_login
def obtener_chat(chat_id):
    try:
        chat, mensajes = _chat_store.obtener(chat_id, session["usuario"])
    except Exception as error:
        print("ERROR obtener_chat:", error)
        return jsonify({"ok": False, "error": "No se pudo cargar la conversación."}), 500
    if not chat:
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    return jsonify({"ok": True, "chat": chat, "mensajes": mensajes})

@app.route("/api/chats/<int:chat_id>/assets/<asset_id>", methods=["GET"])
@requiere_login
def obtener_chat_asset(chat_id, asset_id):
    if not _validar_chat(chat_id, session["usuario"]):
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    try:
        _chat, mensajes = _chat_store.obtener(chat_id, session["usuario"])
        asset = None
        for msg in mensajes or []:
            md = msg.get("metadata") if isinstance(msg, dict) else {}
            for item in (md or {}).get("attachments", []) if isinstance(md, dict) else []:
                if str(item.get("id") or "") == str(asset_id):
                    asset = item
                    break
            if asset:
                break
        if not asset:
            return jsonify({"ok": False, "error": "Adjunto no disponible."}), 404
        abierto = chat_media_store.abrir_asset(asset)
        if not abierto:
            return jsonify({"ok": False, "error": "Adjunto no disponible."}), 404
        backend, objeto = abierto
        mime = str(asset.get("mime") or "application/octet-stream")
        nombre = secure_filename(str(asset.get("name") or "adjunto")) or "adjunto"
        if backend == "local":
            return send_file(objeto, mimetype=mime, download_name=nombre, as_attachment=False)
        body = objeto.get("Body")
        def generar():
            try:
                for bloque in iter(lambda: body.read(1024 * 256), b""):
                    yield bloque
            finally:
                try:
                    body.close()
                except Exception:
                    pass
        resp = Response(stream_with_context(generar()), mimetype=mime)
        resp.headers["Content-Disposition"] = f'inline; filename="{nombre}"'
        return resp
    except Exception as error:
        logger.warning("No se pudo abrir adjunto persistente chat=%s asset=%s: %s", chat_id, asset_id, error)
        return jsonify({"ok": False, "error": "Adjunto no disponible."}), 404


@app.route("/api/chats/<int:chat_id>/messages/<int:message_id>/ui-state", methods=["PATCH"])
@requiere_login
def actualizar_estado_ui_mensaje(chat_id, message_id):
    data = request.get_json(silent=True) or {}
    ui_state = data.get("ui_state")
    if not isinstance(ui_state, dict):
        return jsonify({"ok": False, "error": "Estado visual inválido."}), 400
    permitido = {}
    for clave in ("saved_excel", "confirmed", "selected_variant", "cedula_confirmaciones"):
        if clave in ui_state:
            permitido[clave] = ui_state[clave]
    if not permitido:
        return jsonify({"ok": False, "error": "No hay estado permitido para guardar."}), 400
    ok = _chat_store.actualizar_metadata_mensaje(
        message_id, chat_id, session["usuario"], {"ui_state": permitido}
    )
    return jsonify({"ok": bool(ok)}) if ok else (jsonify({"ok": False, "error": "Mensaje no encontrado."}), 404)


@app.route("/api/chats/<int:chat_id>", methods=["DELETE"])
@requiere_login
def eliminar_chat(chat_id):
    try:
        borrado = _chat_store.eliminar(chat_id, session["usuario"])
    except Exception as error:
        print("ERROR eliminar_chat:", error)
        return jsonify({"ok": False, "error": "No se pudo eliminar la conversación."}), 500
    if not borrado:
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    return jsonify({"ok": True})

@app.route("/api/chats/<int:chat_id>", methods=["PATCH", "PUT"])
@requiere_login
def renombrar_chat(chat_id):
    data = request.get_json(silent=True) or {}
    titulo = str(data.get("titulo", "")).strip()[:100]
    if not titulo:
        return jsonify({"ok": False, "error": "El título no puede estar vacío."}), 400
    try:
        ok = _chat_store.actualizar_titulo(chat_id, session["usuario"], titulo)
    except Exception as error:
        print("ERROR renombrar_chat:", error)
        return jsonify({"ok": False, "error": "No se pudo renombrar la conversación."}), 500
    if not ok:
        return jsonify({"ok": False, "error": "Conversación no encontrada."}), 404
    return jsonify({"ok": True, "id": chat_id, "titulo": titulo})


# CHAT
# ==========================================================

_excel_records = ExcelRecordService(
    libros_excel=LIBROS_EXCEL,
    leer_excel=leer_excel_interno,
    guardar_excel=guardar_matriz_excel,
    agregar_filas=agregar_filas_excel,
)


@app.route("/api/excel/agregar-fila", methods=["POST"])
@requiere_login
def api_excel_agregar_fila():
    data = request.get_json(silent=True) or {}
    tipo_propuesta = str(data.get("tipo_propuesta") or "").strip().lower()
    filas_propuesta = data.get("filas")
    campos = data.get("campos")
    libro_id = str(data.get("libro_id") or session.get("guardar_asegurado_libro_id") or "1")

    try:
        # POLIZA es un dato efímero del alta para Envíos Ya. No debe cambiar
        # silenciosamente la estructura/semántica del Excel histórico.
        campos_excel = dict(campos or {}) if isinstance(campos, dict) else campos
        if isinstance(campos_excel, dict):
            campos_excel.pop("POLIZA", None)
            campos_excel.pop("NUMERO_POLIZA", None)
        resultado = _excel_records.agregar(
            libro_id=libro_id,
            campos=campos_excel,
            filas=filas_propuesta,
            tipo_propuesta=tipo_propuesta,
        )
        session.pop("guardar_asegurado_libro_id", None)
        session.pop("alta_activa", None)
        texto_envios_ya = None
        envios_advertencias = []
        envios_telefono_valido = True
        if tipo_propuesta != "flota" and resultado["libro_id"] == "1" and isinstance(campos, dict):
            try:
                preparado = preparar_envios_ya(campos)
                texto_envios_ya = preparado.texto
                envios_advertencias = preparado.advertencias
                envios_telefono_valido = preparado.telefono_valido
            except Exception as error:
                print("ERROR ARMANDO TEXTO ENVIOS YA:", error)
        return jsonify({
            "ok": True,
            "libro_id": resultado["libro_id"],
            "filas_agregadas": resultado["filas_agregadas"],
            "texto_envios_ya": texto_envios_ya,
            "envios_ya_advertencias": envios_advertencias,
            "envios_ya_telefono_valido": envios_telefono_valido,
            **resultado["datos"],
        })
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        system_health.registrar_evento("excel", "error", "No se pudo agregar una fila desde el chat", str(error))
        print("ERROR AGREGANDO FILA DESDE CHAT:", error)
        return jsonify({"ok": False, "error": "No se pudo agregar el registro a la planilla."}), 500


@app.route("/api/alta/preparar-salidas", methods=["POST"])
@requiere_login
def api_alta_preparar_salidas():
    """Tabulado + Envíos Ya desde los inputs ACTUALES, sin guardar primero."""
    data = request.get_json(silent=True) or {}
    campos = data.get("campos")
    if not isinstance(campos, dict):
        return jsonify({"ok": False, "error": "No se recibieron campos del alta."}), 400

    tabulado = alta_ops.armar_tabulado_desde_campos(campos)
    envios = preparar_envios_ya(campos)

    chat_id = data.get("chat_id")
    try:
        chat_id = int(chat_id) if chat_id else None
    except (TypeError, ValueError):
        chat_id = None
    if chat_id and _validar_chat(chat_id, session["usuario"]):
        session["alta_activa"] = {"chat_id": chat_id, "campos": dict(campos)}

    return jsonify({
        "ok": True,
        "tabulado_alta_asegurado": tabulado,
        "texto_envios_ya": envios.texto,
        "envios_ya_advertencias": envios.advertencias,
        "envios_ya_telefono_valido": envios.telefono_valido,
        "envios_ya_campos": envios.campos,
    })


# V20 Etapa 5 — dominio /flota movido a flota_ops.py.

# ==========================================================
# TANDA 4 — PÓLIZA → ASEGURADO (flujo nuevo, separado de /flota)
# ==========================================================
#
# Este flujo NO toca /flota: no comparte estado (flotas_activas), no
# reutiliza su deduplicación ni sus mensajes. Lo que se reutiliza de
# /flota es el aprendizaje de cómo interpretar un frente de póliza
# (mismo patrón de "Gemini con instrucción estricta, salida JSON, sin
# inventar campos vacíos") — no su código de flota en sí.
#
# El comando es "/alta" y procesa UNA póliza individual (no una flota)
# para dejar lista la propuesta de alta de asegurado. Es de un solo turno:
# no arrastra estado entre mensajes como sí hace /flota.

# V20 Etapa 5 — /alta se consume mediante chat_special.py.
_MENSAJE_PDF_POR_DEFECTO = alta_ops.MENSAJE_PDF_POR_DEFECTO

def _mensaje_error_chat(error):
    """Clasifica errores escapados del chat sin modificar su causa ni el logging."""
    texto = f"{type(error).__module__} {type(error).__name__} {error}".lower()

    indicadores_ia = (
        "gemini", "google.genai", "genai", "resource_exhausted",
        "quota", "api key", "apikey", "model", "generate_content",
    )
    if any(indicador in texto for indicador in indicadores_ia):
        return (
            "No pude procesar la consulta con el servicio de IA en este momento. "
            "Intentá nuevamente en unos segundos."
        )

    indicadores_metadatos = (
        "metadato", "metadata", "buscar_en_metadatos", "_cargar_metadatos",
    )
    if any(indicador in texto for indicador in indicadores_metadatos):
        return (
            "No pude completar la búsqueda de información en este momento. "
            "Intentá nuevamente."
        )

    return (
        "Ocurrió un problema al procesar la consulta. Intentá nuevamente. "
        "Si el problema continúa, avisá al administrador."
    )


def _envolver_chat_con_manejo_de_errores(func):
    """Red defensiva del chat sin alterar los flujos que ya funcionan.

    Cada request recibe un id corto y tiempos en logs. Si algo escapa de los
    manejos específicos, se registra el traceback completo pero al navegador
    vuelve JSON controlado con HTTP 200: una frase mal formulada nunca debe
    convertirse en una pantalla 500. No crea threads, colas ni reintentos.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        request_id = os.urandom(4).hex()
        inicio = time.monotonic()
        g.chat_request_id = request_id
        try:
            logger.info("CHAT[%s] inicio", request_id)
            respuesta = func(*args, **kwargs)
            logger.info("CHAT[%s] fin %.2fs", request_id, time.monotonic() - inicio)
            return respuesta
        except Exception as error:
            system_health.registrar_evento("ia", "error", "No se pudo responder", str(error))
            logger.exception(
                "CHAT[%s] excepción no controlada tras %.2fs: %s",
                request_id,
                time.monotonic() - inicio,
                error,
            )
            # El frontend lo muestra dentro de la burbuja del asistente, sin una
            # página/estado HTTP 500. El detalle técnico queda sólo en Render.
            return jsonify({
                "ok": False,
                "error": _mensaje_error_chat(error),
                "request_id": request_id,
            }), 200
    return wrapper


@app.route(
    "/api/chat",
    methods=["POST"]
)
@requiere_login
@_envolver_chat_con_manejo_de_errores
def chat():

    # V20: cada turno recibe estado efímero propio para timeout/circuit breaker.
    # El historial conversacional sigue persistiendo por separado.
    # Chat interactivo: presupuesto corto. Si hay adjuntos/documentos, el bloque
    # de abajo reemplaza este presupuesto por el presupuesto documental existente.
    # Así aceleramos el chat general SIN alterar el flujo actual de cédulas.
    begin_request(
        runtime_config.get_float("GEMINI_CHAT_BUDGET_SECONDS", 35.0),
        request_id=getattr(g, "chat_request_id", None),
    )

    # El chat acepta JSON para consultas normales y multipart/form-data con
    # un adjunto efímero (PDF, TXT o imagen). El archivo no se incorpora a la
    # biblioteca ni se persiste como documento permanente.
    logger.info("CHAT[%s] etapa=request_parse", getattr(g, "chat_request_id", "-"))
    entrada = parse_incoming(request)
    mensaje = entrada.mensaje
    mensaje_usuario_original = str(mensaje or "")
    chat_id = entrada.chat_id
    historial = entrada.historial
    archivos = list(getattr(entrada, "archivos", None) or ([entrada.archivo] if entrada.archivo else []))
    archivo = archivos[0] if archivos else None

    # Los adjuntos operativos pueden requerir clasificación + varias lecturas
    # visuales independientes (especialmente una cédula). El presupuesto normal
    # de 75s era demasiado justo y podía cortar la verificación después de haber
    # reconocido correctamente el documento. Seguimos muy por debajo del timeout
    # de Gunicorn (180s) y el valor puede ajustarse por entorno.
    if archivos:
        try:
            # Frente+dorso suma lecturas visuales; damos un poco más de margen
            # sin acercarnos al timeout de Gunicorn.
            presupuesto_docs = 145.0 if len(archivos) > 1 else 125.0
            begin_request(runtime_config.get_float("GEMINI_DOCUMENT_BUDGET_SECONDS", presupuesto_docs), request_id=getattr(g, "chat_request_id", None))
        except Exception:
            begin_request(125, request_id=getattr(g, "chat_request_id", None))

    if not entrada.tiene_data and not archivos:
        return jsonify({"respuesta": "No recibí ningún mensaje."})

    # El libro de un /guardar asegurado queda pendiente sólo para su confirmación
    # inmediata; cualquier nuevo mensaje invalida ese destino.
    session.pop("guardar_asegurado_libro_id", None)

    try:
        chat_id = int(chat_id) if chat_id else None
    except (TypeError, ValueError):
        chat_id = None

    if chat_id and not _validar_chat(chat_id, session["usuario"]):
        chat_id = None
    if not chat_id:
        titulo = _generar_titulo_chat(mensaje)
        chat_id = _crear_conversacion(session["usuario"], titulo)
    else:
        _auto_titulo_si_corresponde(chat_id, session["usuario"], mensaje)

    logger.info("CHAT[%s] etapa=historial_inicio chat_id=%s", getattr(g, "chat_request_id", "-"), chat_id)
    historial_db = _historial_desde_db(chat_id, session["usuario"], limite=10)
    if historial_db:
        historial = historial_db
    else:
        if not isinstance(historial, list):
            historial = []
        historial = [
            x for x in historial
            if isinstance(x, dict)
            and x.get("rol") in {"user", "assistant"}
            and str(x.get("contenido", "")).strip()
        ][-10:]
    logger.info("CHAT[%s] etapa=historial_fin mensajes=%s", getattr(g, "chat_request_id", "-"), len(historial))

    _asignar_tipo_chat(chat_id, session["usuario"], mensaje)

    adjuntos_actuales = []
    # Guardamos una referencia al adjunto inmediatamente anterior ANTES de
    # reemplazar el cache. Sólo se usa como candidato frente/dorso; el extractor
    # debe confirmar que pertenece al mismo documento/titular.
    adjunto_anterior_candidato = chat_attachments.obtener(chat_id) if archivos else None
    if archivos:
        logger.info("CHAT[%s] etapa=adjunto_inicio cantidad=%s", getattr(g, "chat_request_id", "-"), len(archivos))
        try:
            adjuntos_actuales = extract_attachments(
                archivos,
                max_pdf_bytes=MAX_PDF_FILE_SIZE_BYTES,
                max_pages=MAX_PDF_PAGES_CHAT,
                max_chars=MAX_PDF_TEXT_CHARS_CHAT,
                max_files=MAX_CHAT_ATTACHMENTS,
                max_total_bytes=MAX_CHAT_ATTACHMENTS_TOTAL_BYTES,
            )
        except ChatRequestError as exc:
            return jsonify({"ok": False, "error": str(exc)}), exc.status_code
        # Compatibilidad: el primer adjunto sigue siendo ``adjunto_actual`` para
        # flujos históricos que sólo esperan un archivo. Los lectores nuevos
        # reciben la lista completa.
        adjunto_actual = adjuntos_actuales[0] if adjuntos_actuales else None
        if adjuntos_actuales:
            chat_attachments.guardar(chat_id, adjuntos_actuales[-1])
        logger.info(
            "CHAT[%s] etapa=adjunto_extraido tipos=%s",
            getattr(g, "chat_request_id", "-"),
            ",".join(a.tipo for a in adjuntos_actuales),
        )
    else:
        adjunto_actual = None

    # Para envío por mail/WhatsApp sólo cuentan los adjuntos explícitos del turno.
    # El anterior se expone al dispatcher únicamente cuando NO llegó uno nuevo,
    # preservando la política de seguridad existente.
    adjunto_anterior = None
    if not adjuntos_actuales:
        adjunto_anterior = chat_attachments.obtener(chat_id)
        if adjunto_anterior is not None:
            chat_attachments.limpiar(chat_id)
    dispatch_service.set_turn_attachments(adjuntos_actuales)
    dispatch_service.set_previous_attachments([adjunto_anterior] if adjunto_anterior else [])

    contextos = [a.contexto for a in adjuntos_actuales if getattr(a, "contexto", "")]
    contexto_adjunto = "\n\n".join(contextos)
    nombres_adjuntos = [a.nombre for a in adjuntos_actuales if getattr(a, "nombre", "")]
    nombre_adjunto = ", ".join(nombres_adjuntos)

    if not mensaje and adjunto_actual:
        if len(adjuntos_actuales) > 1:
            mensaje = "Procesá estos documentos y combiná frente/dorso sólo si corresponden al mismo documento."
        elif adjunto_actual.tipo == "pdf":
            mensaje = _MENSAJE_PDF_POR_DEFECTO
        elif adjunto_actual.tipo == "imagen":
            mensaje = "Analizá esta imagen según su contenido."
        elif adjunto_actual.tipo == "tabla":
            mensaje = "Prepará esta base de contactos para Envíos Ya."
        else:
            mensaje = "Analizá este archivo de texto según su contenido."

    if not mensaje:

        return jsonify({
            "respuesta":
                "Escribime una consulta."
        })

    mensaje_guardado = mensaje
    if nombre_adjunto:
        etiqueta = "Adjuntos" if len(nombres_adjuntos) > 1 else "Adjunto"
        mensaje_guardado = f"[{etiqueta}: {nombre_adjunto}]\n{mensaje}"
    assets_persistidos = []
    if adjuntos_actuales:
        try:
            assets_persistidos = chat_media_store.persistir_adjuntos(session["usuario"], chat_id, adjuntos_actuales)
        except Exception as error:
            logger.warning("CHAT[%s] persistencia_visual_adjuntos_fallo: %s", getattr(g, "chat_request_id", "-"), error)
    user_metadata = {
        "attachments": assets_persistidos,
        "display_text": mensaje_usuario_original.strip(),
        "auto_prompt": bool(adjuntos_actuales and not mensaje_usuario_original.strip()),
    }
    _guardar_mensaje(chat_id, "user", mensaje_guardado, metadata=user_metadata)
    logger.info("CHAT[%s] mensaje usuario guardado chat_id=%s", getattr(g, "chat_request_id", "-"), chat_id)

    # ======================================================
    # PLANILLAS DE CONTACTOS — Excel directo desde el chat (CSV secundario)
    # ======================================================
    adjuntos_tabla = [a for a in adjuntos_actuales if getattr(a, "tipo", "") == "tabla"]
    if adjuntos_tabla:
        if len(adjuntos_tabla) != len(adjuntos_actuales):
            respuesta_tabla = "Para preparar contactos de Envíos Ya, adjuntá las planillas sin mezclarlas con PDFs o imágenes en el mismo mensaje."
            assistant_message_id = _guardar_mensaje(chat_id, "assistant", respuesta_tabla)
            return jsonify({
                "respuesta": respuesta_tabla, "chat_id": chat_id,
                "assistant_message_id": assistant_message_id,
                "archivo_adjunto": nombre_adjunto or None,
            })
        payload_tabla = [(a.nombre, bytes(a.datos_binarios or b"")) for a in adjuntos_tabla]
        try:
            token_fuente = envios_masivos.guardar_fuentes_pendientes(payload_tabla)
            resultado_tabla = envios_masivos.procesar_bases(
                payload_tabla,
                generar_archivo=False,
                token_pendiente=token_fuente,
            )
            if resultado_tabla.get("requiere_mapeo"):
                envios_payload = {
                    "estado": "mapeo",
                    "token": token_fuente,
                    "mapeos": resultado_tabla.get("mapeos") or [],
                    "resumen": resultado_tabla.get("resumen") or {},
                }
                respuesta_tabla = "Necesito confirmar algunas columnas antes de preparar los contactos."
            else:
                envios_masivos.eliminar_fuentes_pendientes(token_fuente)
                resumen_tabla = resultado_tabla.get("resumen") or {}
                envios_payload = {
                    "estado": "confirmar",
                    "token": resultado_tabla.get("token"),
                    "resumen": resumen_tabla,
                    "preview": resultado_tabla.get("preview") or [],
                }
                respuesta_tabla = (
                    f"Encontré {int(resumen_tabla.get('exportables') or 0)} contacto(s) válido(s)"
                    f" y {int(resumen_tabla.get('revisar') or 0)} para revisar. "
                    "Confirmá y genero el CSV para Envíos Ya."
                )
            ui_payload = {"envios_chat": envios_payload}
            assistant_message_id = _guardar_mensaje(chat_id, "assistant", respuesta_tabla, metadata={"ui": ui_payload})
            return jsonify({
                "respuesta": respuesta_tabla, "chat_id": chat_id,
                "assistant_message_id": assistant_message_id,
                "archivo_adjunto": nombre_adjunto or None,
                "envios_chat": envios_payload,
            })
        except ValueError as error:
            respuesta_tabla = str(error)
            assistant_message_id = _guardar_mensaje(chat_id, "assistant", respuesta_tabla)
            return jsonify({"respuesta": respuesta_tabla, "chat_id": chat_id, "assistant_message_id": assistant_message_id}), 400
        except Exception as error:
            logger.exception("CHAT planilla Envíos Ya falló: %s", error)
            respuesta_tabla = "No pude preparar esa base en este intento. El archivo original no se modificó."
            assistant_message_id = _guardar_mensaje(chat_id, "assistant", respuesta_tabla)
            return jsonify({"respuesta": respuesta_tabla, "chat_id": chat_id, "assistant_message_id": assistant_message_id}), 500

    # ======================================================
    # CONTEXTO DETERMINÍSTICO DE CARTERA — referencias y fechas
    # ======================================================
    # Antes de delegar en Gemini, resolvemos consultas donde los datos
    # estructurados mandan: "hoy", "ayer", "este mes" y follow-ups como
    # "decime sus detalles". Esto evita que un registro real pero sin fecha
    # sea presentado como "el de hoy" por una búsqueda aproximada.
    if not adjuntos_actuales:
        try:
            respuesta_contexto = excel_conversation_context.responder_followup_registro(
                mensaje, session_obj=session, chat_id=chat_id
            )
            if respuesta_contexto is None:
                respuesta_contexto = excel_conversation_context.responder_conteo_temporal(
                    mensaje, session_obj=session, chat_id=chat_id
                )
            if respuesta_contexto is not None:
                _guardar_mensaje(chat_id, "assistant", str(respuesta_contexto))
                return jsonify({
                    "respuesta": respuesta_contexto,
                    "chat_id": chat_id,
                    "archivo_adjunto": nombre_adjunto or None,
                    "propuesta_excel": None,
                    "propuesta_metadato": None,
                })
        except Exception as error:
            logger.warning(
                "CHAT[%s] contexto_cartera_no_resuelto: %s",
                getattr(g, "chat_request_id", "-"),
                error,
            )
            mensaje_fuente = None
            try:
                import servicios_ia as _servicios_ia
                mensaje_fuente = _servicios_ia._mensaje_fuente_interna_no_disponible(error)
            except Exception:
                mensaje_fuente = None
            if mensaje_fuente:
                _guardar_mensaje(chat_id, "assistant", mensaje_fuente)
                return jsonify({
                    "respuesta": mensaje_fuente,
                    "chat_id": chat_id,
                    "archivo_adjunto": nombre_adjunto or None,
                    "propuesta_excel": None,
                    "propuesta_metadato": None,
                })

    # ======================================================
    # HANDLERS ESPECIALES — /coti, /flota, /alta
    # ======================================================
    def _log_stage(stage):
        logger.info("CHAT[%s] etapa=%s", getattr(g, "chat_request_id", "-"), stage)

    # Un adjunto nuevo invalida el alta conversacional previa. Si el nuevo
    # archivo es póliza, el handler establece inmediatamente la nueva.
    if adjunto_actual is not None:
        session.pop("alta_activa", None)

    especial = chat_special.procesar(
        chat_id=chat_id,
        mensaje=mensaje,
        contexto_pdf=contexto_adjunto if any(a.tipo == "pdf" for a in adjuntos_actuales) else "",
        flota_store=_flota_store,
        adjunto=adjunto_actual,
        adjuntos=adjuntos_actuales,
        adjunto_anterior=adjunto_anterior_candidato,
        on_stage=_log_stage,
    )
    if especial.atendido:
        if especial.handler == "alta":
            logger.info("CHAT[%s] etapa=alta_resuelta", getattr(g, "chat_request_id", "-"))
            campos_alta = especial.payload_extra.get("campos_guardar_alta_asegurado")
            if isinstance(campos_alta, dict):
                session["alta_activa"] = {"chat_id": chat_id, "campos": dict(campos_alta)}
        ui_payload = {
            "propuesta_excel": None,
            "propuesta_metadato": None,
            **(especial.payload_extra or {}),
        }
        assistant_message_id = _guardar_mensaje(chat_id, "assistant", str(especial.respuesta), metadata={"ui": ui_payload})
        return jsonify({
            "respuesta": especial.respuesta,
            "chat_id": chat_id,
            "assistant_message_id": assistant_message_id,
            "archivo_adjunto": nombre_adjunto or None,
            "propuesta_excel": None,
            "propuesta_metadato": None,
            **especial.payload_extra,
        })

    # ======================================================
    # COMANDOS DETERMINÍSTICOS — /envios ya, /guardar asegurado
    # ======================================================
    arca_context_activo = session.get("arca_context")
    if isinstance(arca_context_activo, dict):
        # ARCA también es contexto conversacional: no debe filtrarse entre chats.
        if str(arca_context_activo.get("chat_id") or "") != str(chat_id or ""):
            arca_context_activo = None
            session.pop("arca_context", None)

    comando = chat_commands.procesar(
        mensaje,
        leer_excel=leer_excel_interno,
        normalizar_encabezado=normalizar_encabezado,
        libros_excel=LIBROS_EXCEL,
        historial=historial,
        arca_context=arca_context_activo,
        adjuntos=adjuntos_actuales,
    )
    if comando.atendido:
        if comando.libro_id:
            # Compatibilidad con el endpoint de confirmación existente.
            # El destino vive sólo hasta el próximo turno.
            session["guardar_asegurado_libro_id"] = comando.libro_id
        if isinstance(comando.payload_extra, dict) and comando.payload_extra.get("arca_context"):
            # Si ARCA fue la fuente realmente usada, pasa a ser el contexto activo
            # de ESTE chat y se invalida el conjunto conversacional de cartera.
            nuevo_arca_context = dict(comando.payload_extra.get("arca_context") or {})
            nuevo_arca_context["chat_id"] = str(chat_id or "")
            session["arca_context"] = nuevo_arca_context
            excel_conversation_context.limpiar_contexto(session)
        ui_payload = {
            "propuesta_excel": comando.propuesta_excel,
            "propuesta_metadato": None,
            "texto_envios_ya": comando.texto_envios_ya,
            **(comando.payload_extra or {}),
        }
        assistant_message_id = _guardar_mensaje(chat_id, "assistant", str(comando.respuesta), metadata={"ui": ui_payload})
        return jsonify({
            "respuesta": comando.respuesta,
            "chat_id": chat_id,
            "assistant_message_id": assistant_message_id,
            "archivo_adjunto": nombre_adjunto or None,
            "propuesta_excel": comando.propuesta_excel,
            "propuesta_metadato": None,
            "texto_envios_ya": comando.texto_envios_ya,
            **comando.payload_extra,
        })

    # ======================================================
    # ALTA ACTIVA — correcciones contextuales del mismo registro
    # ======================================================
    alta_activa = session.get("alta_activa") or {}
    if (
        adjunto_actual is None
        and int(alta_activa.get("chat_id") or 0) == int(chat_id or 0)
        and isinstance(alta_activa.get("campos"), dict)
    ):
        actualizacion_alta = alta_context.aplicar_actualizacion(alta_activa["campos"], mensaje)
        if actualizacion_alta.actualizado:
            session["alta_activa"] = {"chat_id": chat_id, "campos": actualizacion_alta.campos}
            tabulado_actual = alta_ops.armar_tabulado_desde_campos(actualizacion_alta.campos)
            preparado_envios = preparar_envios_ya(actualizacion_alta.campos)
            respuesta_actualizacion = "Actualicé " + ", ".join(actualizacion_alta.cambios) + " en el alta actual."
            ui_payload = {
                "actualizacion_alta_asegurado": actualizacion_alta.campos,
                "tabulado_alta_asegurado": tabulado_actual,
                "texto_envios_ya": preparado_envios.texto,
                "envios_ya_advertencias": preparado_envios.advertencias,
                "envios_ya_telefono_valido": preparado_envios.telefono_valido,
            }
            assistant_message_id = _guardar_mensaje(chat_id, "assistant", respuesta_actualizacion, metadata={"ui": ui_payload})
            return jsonify({
                "respuesta": respuesta_actualizacion,
                "chat_id": chat_id,
                "assistant_message_id": assistant_message_id,
                "propuesta_excel": None,
                "propuesta_metadato": None,
                **ui_payload,
            })

    # ======================================================
    # ACCIONES CONTEXTUALES — referencias al contenido anterior
    # ======================================================
    accion_contextual = chat_context_actions.procesar(mensaje, historial)
    if accion_contextual.atendido:
        ui_payload = {
            "propuesta_excel": None,
            "propuesta_metadato": accion_contextual.propuesta_metadato,
            **(accion_contextual.payload_extra or {}),
        }
        assistant_message_id = _guardar_mensaje(chat_id, "assistant", str(accion_contextual.respuesta), metadata={"ui": ui_payload})
        return jsonify({
            "respuesta": accion_contextual.respuesta,
            "chat_id": chat_id,
            "assistant_message_id": assistant_message_id,
            "archivo_adjunto": nombre_adjunto or None,
            "propuesta_excel": None,
            "propuesta_metadato": accion_contextual.propuesta_metadato,
            **accion_contextual.payload_extra,
        })

    # ======================================================
    # CONTEXTO DIRECTO
    # ======================================================
    # V20 Etapa 2: app.py ya no decide ni ejecuta búsquedas documentales.
    # El plan de ejecución y la precarga de fuentes viven en servicios_ia.py,
    # dentro del mismo request/cache que usa Sofia. Acá sólo viaja el contexto
    # explícito del adjunto cuando corresponde.
    contexto = contexto_adjunto

    # ======================================================
    # GEMINI
    # ======================================================

    propuesta_excel = None
    propuesta_metadato = None
    try:
        logger.info("CHAT[%s] Gemini inicio", getattr(g, "chat_request_id", "-"))
        resultado_ia = chat_ai.responder(
            mensaje, contexto, historial, adjunto=adjunto_actual, adjuntos=adjuntos_actuales
        )
        respuesta = resultado_ia.respuesta
        propuesta_excel = resultado_ia.propuesta_excel
        propuesta_metadato = resultado_ia.propuesta_metadato
        logger.info("CHAT[%s] Gemini fin %.2fs", getattr(g, "chat_request_id", "-"), resultado_ia.elapsed)
    except Exception as error:
        system_health.registrar_evento("ia", "error", "No se pudo responder", str(error))
        print("ERROR CHAT GEMINI:", error)
        if contexto:
            respuesta = (
                "Encontré información relacionada en el archivo adjunto, pero no pude "
                "completar el análisis con la IA en este momento. Intentá nuevamente."
            )
        else:
            respuesta = (
                "No pude completar la consulta con la IA en este momento. "
                "Intentá nuevamente en unos segundos."
            )

    ui_payload = {
        "propuesta_excel": propuesta_excel,
        "propuesta_metadato": propuesta_metadato,
    }
    assistant_message_id = _guardar_mensaje(chat_id, "assistant", str(respuesta), metadata={"ui": ui_payload})
    logger.info("CHAT[%s] etapa=respuesta_guardada chat_id=%s", getattr(g, "chat_request_id", "-"), chat_id)

    return jsonify({
        "respuesta": respuesta,
        "chat_id": chat_id,
        "assistant_message_id": assistant_message_id,
        "archivo_adjunto": nombre_adjunto or None,
        "propuesta_excel": propuesta_excel,
        "propuesta_metadato": propuesta_metadato,
    })


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

@app.route("/salud")
@requiere_admin
def salud_sistema():
    vista = str(request.args.get("vista") or "eventos").strip().lower()
    if vista not in {"eventos", "servicios"}:
        vista = "eventos"
    categoria = str(request.args.get("categoria") or "").strip() or None
    nivel = str(request.args.get("nivel") or "").strip() or None
    eventos = system_health.listar_eventos(categoria=categoria, nivel=nivel, dias=7)
    ultimas_24h = system_health.listar_eventos(nivel="error", dias=1)
    errores_ia_24h = sum(1 for e in ultimas_24h if e.get("categoria") == "ia")
    servicios_iniciales = None
    if vista == "servicios":
        # Sólo validación local al renderizar HTML. La comprobación real de red
        # se hace vía API después de cargar la vista y queda cacheada brevemente.
        servicios_iniciales = service_diagnostics.run_health_checks(
            probe_external=False, use_cache=True
        )
    return render_template(
        "salud.html",
        eventos=eventos,
        categoria=categoria or "",
        nivel=nivel or "",
        errores_ia_24h=errores_ia_24h,
        errores_24h=len(ultimas_24h),
        vista= vista,
        servicios_iniciales=servicios_iniciales,
    )


@app.route("/api/system/health", methods=["GET"])
@requiere_admin
def api_system_health():
    probe = str(request.args.get("probe") or "1").strip().lower() not in {"0", "false", "no"}
    refresh = str(request.args.get("refresh") or "0").strip().lower() in {"1", "true", "si", "yes"}
    resultado = service_diagnostics.run_health_checks(
        probe_external=probe,
        use_cache=not refresh,
    )
    return jsonify({"ok": True, **resultado})


@app.route("/manuales")
@requiere_login
def manuales():
    # Mantener /manuales como ruta principal para compatibilidad con favoritos y enlaces antiguos.
    return redirect(url_for("biblioteca"))


def _servir_pdf_r2(r2_key, nombre_visible, tipo="PDF"):
    """Adaptador HTTP de streaming; la validación/persistencia vive en library_service."""
    try:
        objeto = obtener_objeto_stream(r2_key)
        body = objeto["Body"]
        content_length = objeto.get("ContentLength")
        @stream_with_context
        def generar():
            try:
                while True:
                    bloque = body.read(1024 * 1024)
                    if not bloque:
                        break
                    yield bloque
            finally:
                body.close()
        headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": f'inline; filename="{nombre_visible}"',
            "Cache-Control": "private, max-age=300",
        }
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        return Response(generar(), headers=headers)
    except Exception as error:
        print(f"ERROR SIRVIENDO {tipo.upper()} R2:", error)
        return (f"No se pudo abrir el {tipo}.", 502)


@app.route("/biblioteca")
@requiere_login
def biblioteca():
    try:
        polizas = library_service.preparar_polizas(pg_listar_polizas())
    except Exception as error:
        print("ERROR LISTANDO POLIZAS:", error)
        polizas = []
    return render_template("biblioteca.html", manuales=manuales_companias(), polizas=polizas,
                           usuario=session["usuario"], usuario_rol=session.get("rol","usuario"),
                           usuario_es_admin=usuario_es_admin())

@app.route("/api/polizas", methods=["POST"])
@requiere_admin
def subir_poliza():
    resultado = library_service.subir_poliza(
        request.files.get("poliza"), max_bytes=MAX_PDF_FILE_SIZE_BYTES,
        upload=r2_subir_pdf, register=registrar_poliza, delete_r2=r2_eliminar_pdf
    )
    return jsonify(resultado.payload()), resultado.status

@app.route("/api/polizas/<path:nombre>", methods=["DELETE"])
@requiere_admin
def eliminar_poliza(nombre):
    resultado = library_service.eliminar_poliza(
        nombre, get_record=obtener_poliza_por_r2_key, delete_db=eliminar_poliza_pg,
        delete_r2=r2_eliminar_pdf, restore_db=registrar_poliza
    )
    return jsonify(resultado.payload()), resultado.status

@app.route("/polizas/<path:nombre>")
@requiere_login
def ver_poliza(nombre):
    r2_key = str(nombre or "").strip()
    if not library_service.validar_key_poliza(r2_key):
        return ("Póliza no encontrada",404)
    existente = obtener_poliza_por_r2_key(r2_key)
    if not existente:
        return ("Póliza no encontrada",404)
    return _servir_pdf_r2(r2_key, existente["nombre"], "póliza")

@app.route("/configuracion")
@requiere_login
def configuracion():
    config = cargar_configuracion()
    usuarios=[]
    if usuario_es_admin():
        try:
            usuarios = _user_store().listar()
        except Exception as error:
            print("ERROR listar usuarios:", error)
            usuarios = []
    return render_template("configuracion.html",config=config,usuario=session["usuario"],carpetas=obtener_companias(),usuarios=usuarios)

@app.route("/api/configuracion", methods=["POST"])
@requiere_admin
def guardar_configuracion():
    data = request.get_json(silent=True) or {}
    actual = cargar_configuracion()
    config, error = config_service.validar_y_construir_config(data, actual)
    if error:
        return jsonify(ok=False, error=error), 400
    try:
        config_service.guardar_configuracion(
            config,
            usar_pg=_config_usar_pg(),
            pg_guardar=pg_guardar_configuracion,
            config_file=CONFIG_FILE,
        )
        return jsonify(ok=True, config=config)
    except Exception as error_guardado:
        print("ERROR guardar_configuracion:", error_guardado)
        return jsonify(ok=False,error="No se pudo guardar la configuración."),500


@app.route("/api/usuarios", methods=["POST"])
@requiere_admin
def crear_usuario():
    data = request.get_json(silent=True) or {}
    usuario = str(data.get("usuario", "")).strip()
    password = str(data.get("password", ""))
    email = str(data.get("email", "")).strip()
    rol = str(data.get("rol", "usuario")).strip().lower()
    if not usuario: return jsonify(ok=False,error="El usuario es obligatorio."),400
    if not password: return jsonify(ok=False,error="La contraseña es obligatoria."),400
    if rol not in ROLES_VALIDOS: return jsonify(ok=False,error="Rol inválido."),400
    if not validar_email(email): return jsonify(ok=False,error="El correo electrónico no es válido."),400
    try:
        nuevo_id, error, status = _user_store().crear(usuario, password, email, rol)
        if error:
            return jsonify(ok=False,error=error), status
        return jsonify(ok=True, mensaje="Usuario creado correctamente.", id=nuevo_id)
    except Exception as exc:
        print("ERROR crear_usuario:", exc)
        return jsonify(ok=False,error="No se pudo crear el usuario."),500


@app.route("/api/usuarios/<int:usuario_id>", methods=["PUT"])
@requiere_admin
def editar_usuario(usuario_id):
    registro = obtener_usuario_por_id(usuario_id)
    if not registro: return jsonify(ok=False,error="Usuario no encontrado."),404
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip()
    rol = str(data.get("rol", registro["rol"])).strip().lower()
    password = str(data.get("password", ""))
    if not validar_email(email): return jsonify(ok=False,error="El correo electrónico no es válido."),400
    if rol not in ROLES_VALIDOS: return jsonify(ok=False,error="Rol inválido."),400
    if registro["protegido"]: rol = "admin"
    try:
        _user_store().actualizar(usuario_id, email, rol, password)
        return jsonify(ok=True,mensaje="Usuario actualizado correctamente.")
    except Exception as exc:
        print("ERROR editar_usuario:", exc)
        return jsonify(ok=False,error="No se pudo actualizar el usuario."),500


@app.route("/api/usuarios/<int:usuario_id>", methods=["DELETE"])
@requiere_admin
def eliminar_usuario(usuario_id):
    registro = obtener_usuario_por_id(usuario_id)
    if not registro: return jsonify(ok=False,error="Usuario no encontrado."),404
    if registro["protegido"]: return jsonify(ok=False,error="El administrador principal está protegido."),403
    if registro["usuario"] == session.get("usuario"): return jsonify(ok=False,error="No podés eliminar tu propia cuenta."),400
    try:
        _user_store().eliminar(usuario_id)
        return jsonify(ok=True,mensaje="Usuario eliminado correctamente.")
    except Exception as exc:
        print("ERROR eliminar_usuario:", exc)
        return jsonify(ok=False,error="No se pudo eliminar el usuario."),500


@app.route("/api/manuales/<slug>", methods=["POST"])
@requiere_admin
def subir_manual(slug):
    archivos = [a for a in request.files.getlist("manual") if a and a.filename]
    if not archivos:
        unico = request.files.get("manual")
        if unico and unico.filename:
            archivos = [unico]
    resultado = library_service.subir_manuales(
        slug, archivos, request.form.get("replace", ""),
        companias=MANUALES_COMPANIAS, slugger=slug_manual_compania,
        max_bytes=MAX_PDF_FILE_SIZE_BYTES, get_record=obtener_manual_por_r2_key,
        upload=r2_subir_pdf, delete_r2=r2_eliminar_pdf, register=registrar_manual,
        update=actualizar_manual, extract_text=extraer_texto_pdf_bytes,
        propose=_proponer_ficha_desde_manual,
    )
    return jsonify(resultado.payload()), resultado.status

@app.route("/api/manuales/<slug>/<path:nombre_archivo>", methods=["DELETE"])
@requiere_admin
def eliminar_manual(slug, nombre_archivo):
    resultado = library_service.eliminar_manual(
        slug, nombre_archivo, companias=MANUALES_COMPANIAS, slugger=slug_manual_compania,
        get_record=obtener_manual_por_r2_key, delete_db=eliminar_manual_pg,
        delete_r2=r2_eliminar_pdf, restore_db=registrar_manual,
    )
    return jsonify(resultado.payload()), resultado.status

@app.route("/manuales/<slug>/<path:nombre_archivo>")
@requiere_login
def ver_manual(slug, nombre_archivo):
    r2_key = str(nombre_archivo or "").strip()
    if not library_service.validar_key_manual(slug, r2_key, MANUALES_COMPANIAS, slug_manual_compania):
        return ("Manual no encontrado", 404)
    existente = obtener_manual_por_r2_key(r2_key)
    if not existente:
        return ("Manual no encontrado", 404)
    return _servir_pdf_r2(r2_key, existente["nombre"], "manual")


# ==========================================================
# LOGOUT
# ==========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ==========================================================
# CREAR ESTRUCTURA
# ==========================================================

def crear_estructura():
    MANUALES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        inicializar_postgres()
        print('NEON POSTGRESQL: tabla manuales verificada.')
    except Exception as error:
        print('NEON POSTGRESQL: no se pudo verificar la tabla manuales:', error)
    POLIZAS_DIR.mkdir(parents=True, exist_ok=True)
    # Las compañías de documentos deben coincidir exactamente con las 9
    # compañías habilitadas en la sección Manuales.
    companias = [
        "atm",
        "mercantil_andina",
        "federacion_patronal",
        "san_cristobal",
        "rivadavia",
        "euroamerica",
        "agrosalta",
        "triunfo",
        "prof",
    ]

    for compania in companias:
        (DOCUMENTOS_DIR / compania).mkdir(parents=True, exist_ok=True)


# ==========================================================
# INICIAR
# ==========================================================

inicializar_base_datos()

try:
    inicializar_postgres()
    print('NEON POSTGRESQL: tabla manuales verificada.')
except Exception as error:
    print('NEON POSTGRESQL: no se pudo verificar la tabla manuales al iniciar:', error)

try:
    estudio_ops.asegurar_tablas()
    print('ESTUDIO: tablas verificadas.')
except Exception as error:
    print('ESTUDIO: no se pudieron verificar las tablas:', error)



# ==========================================================
# OFICINAIA PLUS — Bandeja de pendientes + ficha desde texto
# ==========================================================

PLANTILLAS_METADATO = [
    {
        "id": "remolque",
        "titulo": "Remolque / asistencia — {COMPANIA} {PRODUCTO}",
        "contenido": (
            "COMPAÑÍA: {COMPANIA}\n"
            "PRODUCTO / PLAN: {PRODUCTO}\n\n"
            "Servicios de remolque al año:\n"
            "Kilómetros por servicio (ida + vuelta):\n"
            "Servicio especial (si aplica):\n"
            "Límites o exclusiones:\n"
            "Observaciones operativas:\n"
        ),
    },
    {
        "id": "cobertura",
        "titulo": "Cobertura — {COMPANIA} {PRODUCTO}",
        "contenido": (
            "COMPAÑÍA: {COMPANIA}\n"
            "PRODUCTO / PLAN: {PRODUCTO}\n\n"
            "Responsabilidad civil:\n"
            "Robo / hurto total:\n"
            "Incendio total:\n"
            "Daños parciales / total:\n"
            "Granizo / cristales:\n"
            "Franquicias:\n"
            "Exclusiones relevantes:\n"
        ),
    },
    {
        "id": "procedimiento",
        "titulo": "Procedimiento — {TEMA}",
        "contenido": (
            "TEMA: {TEMA}\n\n"
            "Cuándo aplica:\n"
            "Pasos a seguir:\n"
            "1.\n2.\n3.\n"
            "Documentación requerida:\n"
            "Contactos / teléfonos:\n"
            "Notas internas:\n"
        ),
    },
    {
        "id": "contacto",
        "titulo": "Contacto operativo — {COMPANIA}",
        "contenido": (
            "COMPAÑÍA: {COMPANIA}\n"
            "Área:\n"
            "Teléfono:\n"
            "Mail:\n"
            "Horario:\n"
            "Observaciones:\n"
        ),
    },
]


def _pendientes_usar_pg():
    """Con Neon los pendientes viven en Postgres y sobreviven redeploy."""
    return bool(runtime_config.get_text("DATABASE_URL"))


def _pending_store():
    return PendingStore(
        usar_pg=_pendientes_usar_pg,
        conectar_db=conectar_db,
        pg={
            "listar": pg_listar_pendientes,
            "contar": pg_contar_pendientes,
            "crear": pg_crear_pendiente,
            "editar": pg_editar_pendiente,
            "eliminar": pg_eliminar_pendiente,
        },
    )


@app.route("/api/pendientes", methods=["GET"])
@requiere_login
def api_listar_pendientes():
    estado = _pending_store().normalizar_estado(request.args.get("estado") or "pendiente")
    try:
        items, total = _pending_store().listar(session["usuario"], estado=estado)
        return jsonify({"ok": True, "pendientes": items, "total_pendientes": total})
    except Exception as error:
        print("ERROR api_listar_pendientes:", error)
        return jsonify({"ok": False, "error": "No se pudieron cargar los pendientes."}), 500


@app.route("/api/pendientes", methods=["POST"])
@requiere_login
def api_crear_pendiente():
    data = request.get_json(silent=True) or {}
    tipo = str(data.get("tipo") or "generico")
    titulo = str(data.get("titulo") or "Pendiente").strip()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    try:
        pid, total = _pending_store().crear(
            session["usuario"], tipo=tipo, titulo=titulo, payload=payload
        )
        return jsonify({"ok": True, "id": pid, "total_pendientes": total})
    except Exception as error:
        print("ERROR api_crear_pendiente:", error)
        return jsonify({"ok": False, "error": "No se pudo crear el pendiente."}), 500


@app.route("/api/pendientes/<int:pendiente_id>", methods=["PATCH"])
@requiere_login
def api_actualizar_pendiente(pendiente_id):
    data = request.get_json(silent=True) or {}

    estado = data.get("estado")
    if estado is not None:
        estado = str(estado).strip().lower()
        if not _pending_store().validar_estado(estado):
            return jsonify({"ok": False, "error": "Estado no válido."}), 400

    titulo = data.get("titulo")
    if titulo is not None:
        titulo = str(titulo).strip()
        if not titulo:
            return jsonify({"ok": False, "error": "El título no puede quedar vacío."}), 400

    tipo = data.get("tipo")
    if tipo is not None:
        tipo = str(tipo).strip().lower()

    payload = data.get("payload") if isinstance(data.get("payload"), dict) else None

    if estado is None and titulo is None and tipo is None and payload is None:
        return jsonify({"ok": False, "error": "No hay cambios para guardar."}), 400

    try:
        ok, total = _pending_store().editar(
            pendiente_id,
            session["usuario"],
            tipo=tipo,
            titulo=titulo,
            payload=payload,
            estado=estado,
        )
        if not ok:
            return jsonify({"ok": False, "error": "Pendiente no encontrado."}), 404
        return jsonify({"ok": True, "total_pendientes": total})
    except Exception as error:
        print("ERROR api_actualizar_pendiente:", error)
        return jsonify({"ok": False, "error": "No se pudo actualizar el pendiente."}), 500


@app.route("/api/pendientes/<int:pendiente_id>", methods=["DELETE"])
@requiere_login
def api_eliminar_pendiente(pendiente_id):
    try:
        ok, total = _pending_store().eliminar(pendiente_id, session["usuario"])
        if not ok:
            return jsonify({"ok": False, "error": "Pendiente no encontrado."}), 404
        return jsonify({"ok": True, "total_pendientes": total})
    except Exception as error:
        print("ERROR api_eliminar_pendiente:", error)
        return jsonify({"ok": False, "error": "No se pudo eliminar el pendiente."}), 500


@app.route("/api/plantillas-metadato", methods=["GET"])
@requiere_login
def api_plantillas_metadato():
    return jsonify({"ok": True, "plantillas": PLANTILLAS_METADATO})


@app.route("/api/ficha-desde-texto", methods=["POST"])
@requiere_login
def api_ficha_desde_texto():
    """Arma una ficha de metadato a partir de texto (respuesta de Sofia o extracto de PDF)."""
    data = request.get_json(silent=True) or {}
    texto = str(data.get("texto") or "").strip()
    titulo = str(data.get("titulo") or "").strip()
    if not texto:
        return jsonify({"ok": False, "error": "No hay texto para armar la ficha."}), 400
    if not titulo:
        # primeras palabras útiles
        linea = texto.split("\n", 1)[0].strip()
        titulo = (" ".join(linea.split())[:80] or "Ficha desde chat")
    # Normalizar un poco el contenido conservando información
    cuerpo = texto.strip()
    if len(cuerpo) > 12000:
        cuerpo = cuerpo[:12000] + "\n\n[Texto recortado por longitud]"
    return jsonify({
        "ok": True,
        "ficha": {
            "titulo": titulo[:200],
            "contenido": cuerpo,
        },
    })


@app.route("/api/validar-excel-fila", methods=["POST"])
@requiere_login
def api_validar_excel_fila():
    """Valida una propuesta antes de persistirla sin mezclar reglas con Flask."""
    data = request.get_json(silent=True) or {}
    libro_id = str(data.get("libro_id") or "1")
    campos = data.get("campos") if isinstance(data.get("campos"), dict) else {}
    try:
        return jsonify(_excel_records.validar_fila(libro_id=libro_id, campos=campos))
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        print("ERROR VALIDANDO FILA EXCEL:", error)
        return jsonify({"ok": False, "error": "No se pudo validar el registro."}), 500


# ==========================================================
# ESTUDIO — triage de siniestros (aislado de Seguros)
# ==========================================================

@app.route("/estudio")
@requiere_login
def estudio():
    return render_template("estudio.html", usuario=session["usuario"])


@app.route("/api/estudio/lotes", methods=["GET", "POST"])
@requiere_login
def estudio_lotes():
    usuario = session["usuario"]
    if request.method == "GET":
        return jsonify(ok=True, lotes=estudio_ops.listar_lotes(usuario))
    data = request.get_json(silent=True) or {}
    lote_id = estudio_ops.crear_lote(usuario, str(data.get("titulo") or ""))
    return jsonify(ok=True, id=lote_id)


@app.route("/api/estudio/lotes/<lote_id>", methods=["GET"])
@requiere_login
def estudio_lote(lote_id):
    usuario = session["usuario"]
    lote = estudio_ops.obtener_lote(lote_id, usuario)
    if not lote:
        return jsonify(ok=False, error="El análisis no existe."), 404
    return jsonify(ok=True, lote=lote, casos=estudio_ops.listar_casos(lote_id, usuario))


@app.route("/api/estudio/analizar", methods=["POST"])
@requiere_login
def estudio_analizar():
    usuario = session["usuario"]
    lote_id = str(request.form.get("lote_id") or "").strip()
    archivo = request.files.get("pdf")
    if not lote_id or not estudio_ops.obtener_lote(lote_id, usuario):
        return jsonify(ok=False, error="Falta un lote de análisis válido."), 400
    if not archivo or not archivo.filename:
        return jsonify(ok=False, error="Falta el PDF."), 400
    nombre = secure_filename(archivo.filename) or "siniestro.pdf"
    if not nombre.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Estudio acepta únicamente archivos PDF."), 400
    datos = archivo.read()
    try:
        caso = estudio_ops.analizar_pdf(usuario, lote_id, nombre, datos)
        return jsonify(ok=True, caso=caso)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    except Exception as error:
        logger.exception("ESTUDIO análisis fallido %s: %s", nombre, error)
        return jsonify(ok=False, error="No pude analizar este PDF. Podés continuar con el resto del lote y reintentar este archivo."), 502


@app.route("/api/estudio/casos/<caso_id>", methods=["PATCH"])
@requiere_login
def estudio_reclasificar(caso_id):
    data = request.get_json(silent=True) or {}
    caso = estudio_ops.reclasificar_caso(caso_id, session["usuario"], data.get("clasificacion"))
    if not caso:
        return jsonify(ok=False, error="Caso inexistente."), 404
    return jsonify(ok=True, caso=caso)


@app.route("/api/estudio/lotes/<lote_id>/descargar", methods=["GET"])
@requiere_login
def estudio_descargar_lote(lote_id):
    usuario = session["usuario"]
    if not estudio_ops.obtener_lote(lote_id, usuario):
        return jsonify(ok=False, error="El análisis no existe."), 404
    clasificacion = request.args.get("clasificacion")
    try:
        archivo = estudio_ops.generar_zip_lote(lote_id, usuario, clasificacion)
    except Exception as error:
        logger.exception("ESTUDIO no pudo generar ZIP: %s", error)
        return jsonify(ok=False, error="No pude preparar la descarga."), 500
    nombre = "ESTUDIO_ANALISIS.zip" if not clasificacion else f"ESTUDIO_{str(clasificacion).upper()}.zip"
    response = send_file(archivo, as_attachment=True, download_name=nombre, mimetype="application/zip")
    @response.call_on_close
    def _limpiar_zip():
        try:
            archivo.unlink(missing_ok=True)
        except Exception:
            pass
    return response


@app.route("/api/estudio/ejemplos", methods=["GET", "POST"])
@requiere_login
def estudio_ejemplos():
    usuario = session["usuario"]
    if request.method == "GET":
        return jsonify(ok=True, ejemplos=estudio_ops.listar_ejemplos(usuario))
    nombre = str(request.form.get("nombre") or "").strip()
    clasificacion = str(request.form.get("clasificacion") or "REVISAR")
    fundamento = str(request.form.get("fundamento") or "").strip()
    if not nombre or not fundamento:
        return jsonify(ok=False, error="Nombre y fundamento son obligatorios."), 400
    archivo = request.files.get("pdf")
    pdf_bytes = None
    nombre_archivo = ""
    if archivo and archivo.filename:
        nombre_archivo = secure_filename(archivo.filename) or "ejemplo.pdf"
        if not nombre_archivo.lower().endswith(".pdf"):
            return jsonify(ok=False, error="El ejemplo adjunto debe ser PDF."), 400
        pdf_bytes = archivo.read()
        if len(pdf_bytes) > 25 * 1024 * 1024:
            return jsonify(ok=False, error="El PDF de ejemplo puede pesar hasta 25 MB."), 413
    try:
        ejemplo = estudio_ops.crear_ejemplo(usuario, nombre, clasificacion, fundamento, pdf_bytes, nombre_archivo)
        return jsonify(ok=True, ejemplo=ejemplo)
    except Exception as error:
        logger.exception("ESTUDIO no pudo guardar ejemplo: %s", error)
        return jsonify(ok=False, error="No pude guardar el ejemplo."), 500


@app.route("/api/estudio/ejemplos/<ejemplo_id>", methods=["DELETE"])
@requiere_login
def estudio_eliminar_ejemplo(ejemplo_id):
    if not estudio_ops.eliminar_ejemplo(ejemplo_id, session["usuario"]):
        return jsonify(ok=False, error="Ejemplo inexistente."), 404
    return jsonify(ok=True)



# ==========================================================
# ENVÍOS MASIVOS — importador inteligente + salida EnvíosYA
# ==========================================================

@app.route("/api/chat/envios/reprocesar", methods=["POST"])
@requiere_login
def api_chat_envios_reprocesar():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "").strip()
    mapping = data.get("manual_mapping") if isinstance(data.get("manual_mapping"), dict) else {}
    try:
        fuentes = envios_masivos.recuperar_fuentes_pendientes(token)
        resultado = envios_masivos.procesar_bases(
            fuentes, manual_mapping=mapping, generar_archivo=False, token_pendiente=token
        )
        if resultado.get("requiere_mapeo"):
            return jsonify(ok=True, envios_chat={
                "estado": "mapeo", "token": token,
                "mapeos": resultado.get("mapeos") or [],
                "resumen": resultado.get("resumen") or {},
            })
        envios_masivos.eliminar_fuentes_pendientes(token)
        return jsonify(ok=True, envios_chat={
            "estado": "confirmar", "token": resultado.get("token") or token,
            "resumen": resultado.get("resumen") or {},
            "preview": resultado.get("preview") or [],
        })
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    except Exception as error:
        logger.exception("Reprocesamiento de planilla desde chat falló: %s", error)
        return jsonify(ok=False, error="No pude aplicar ese mapeo. Volvé a adjuntar la base."), 500


@app.route("/api/chat/envios/generar", methods=["POST"])
@requiere_login
def api_chat_envios_generar():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "").strip()
    try:
        archivo = envios_masivos.generar_exportacion_pendiente(token)
        return jsonify(
            ok=True, token=token, archivo=archivo.name,
            download_url=url_for("envios_masivos_descargar", token=token),
        )
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    except Exception as error:
        logger.exception("Generación CSV final para Envíos Ya falló: %s", error)
        return jsonify(ok=False, error="No pude generar el CSV. Volvé a preparar la base."), 500


@app.route("/envios-masivos")
@requiere_login
def envios_masivos_pagina():
    return render_template("envios_masivos.html", usuario=session["usuario"])


@app.route("/api/envios-masivos/procesar", methods=["POST"])
@requiere_login
def envios_masivos_procesar():
    inicio_envios = time.perf_counter()
    archivos = [a for a in request.files.getlist("bases") if a and a.filename]
    if not archivos:
        return jsonify(ok=False, error="Seleccioná al menos una base de datos."), 400
    payload = []
    try:
        for archivo in archivos:
            nombre = secure_filename(archivo.filename) or "base.xlsx"
            datos = archivo.read()
            if not datos:
                continue
            payload.append((nombre, datos))
        try:
            manual_mapping = json.loads(request.form.get("manual_mapping") or "{}")
            if not isinstance(manual_mapping, dict):
                manual_mapping = {}
        except Exception:
            manual_mapping = {}
        dedupe_mode = (request.form.get("dedupe_mode") or "all").strip().lower()
        if dedupe_mode not in {"all", "one"}:
            dedupe_mode = "all"
        resultado = envios_masivos.procesar_bases(
            payload,
            manual_mapping=manual_mapping,
            dedupe_mode=dedupe_mode,
        )
        logger.info(
            "ENVIOS MASIVOS listo archivos=%s bytes=%s exportables=%s revisar=%s tiempo=%.2fs",
            len(payload), sum(len(datos) for _, datos in payload),
            (resultado.get("resumen") or {}).get("exportables"),
            (resultado.get("resumen") or {}).get("revisar"),
            time.perf_counter() - inicio_envios,
        )
        return jsonify(ok=True, **resultado)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    except Exception as error:
        logger.exception("ENVIOS MASIVOS procesamiento fallido tras %.2fs: %s", time.perf_counter() - inicio_envios, error)
        return jsonify(ok=False, error="No pude terminar esta importación. El archivo original no se modifica; podés volver a procesarlo. Si se repite, revisá el log de Envíos Masivos."), 500


@app.route("/api/envios-masivos/descargar/<token>", methods=["GET"])
@requiere_login
def envios_masivos_descargar(token):
    archivo = envios_masivos.obtener_csv(token)
    if not archivo:
        return jsonify(ok=False, error="La exportación venció o no existe. Procesá la base nuevamente."), 404
    fecha = office_today().isoformat()
    return send_file(
        archivo,
        as_attachment=True,
        download_name=f"EnviosYA_{fecha}.csv",
        mimetype="text/csv; charset=utf-8",
    )

@app.route("/api/envios-masivos/descargar-notificaciones/<token>", methods=["GET"])
@requiere_login
def envios_masivos_descargar_notificaciones(token):
    archivo = envios_masivos.obtener_exportacion(token, "notificaciones")
    if not archivo:
        return jsonify(ok=False, error="La exportación venció o no existe. Procesá la base nuevamente."), 404
    return send_file(archivo, as_attachment=True, download_name="EnviosYA! - Notificaciones.csv", mimetype="text/csv; charset=utf-8")


@app.route("/api/envios-masivos/descargar-maestro/<token>", methods=["GET"])
@requiere_login
def envios_masivos_descargar_maestro(token):
    archivo = envios_masivos.obtener_exportacion(token, "maestro")
    if not archivo:
        return jsonify(ok=False, error="La exportación venció o no existe. Procesá la base nuevamente."), 404
    return send_file(archivo, as_attachment=True, download_name="OficinaIA - Base normalizada.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/pendientes")
@requiere_login
def pagina_pendientes():
    return render_template("pendientes.html", usuario=session["usuario"])

@app.route("/internet")
@requiere_login
def pagina_internet():
    return render_template("internet.html", usuario=session["usuario"])



if __name__ == "__main__":

    crear_estructura()

    print("")
    print(
        "===================================="
    )

    print(
        "     OFICINA SEGUROS INICIADA"
    )

    print(
        "===================================="
    )

    print(
        "Servidor: http://127.0.0.1:5000"
    )

    print("")

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )