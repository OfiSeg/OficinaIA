from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory,
)

from pathlib import Path
from functools import wraps
from pypdf import PdfReader
import re
import unicodedata
import os
import sqlite3
from contextlib import closing
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from docx import Document


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

app = Flask(__name__)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "OFICINA_SEGUROS_CAMBIAR_CLAVE")

BASE_DIR = Path(__file__).resolve().parent

DOCUMENTOS_DIR = BASE_DIR / "documentos"

NOTAS_FILE = BASE_DIR / "notas.json"
WORD_FILE = BASE_DIR / "documento_interno.docx"

# Planilla interna editable de Oficina IA.
EXCEL_FILE = BASE_DIR / "excel_interno.xlsx"

DOCUMENTOS_DIR.mkdir(
    exist_ok=True
)

CONFIG_FILE = BASE_DIR / "configuracion.json"
DB_FILE = BASE_DIR / "oficina.db"
ROLES_VALIDOS = {"admin", "usuario"}
USUARIO_ADMIN_PRINCIPAL = "admin"

MANUALES_DIR = BASE_DIR / "manuales_companias"
POLIZAS_DIR = BASE_DIR / "polizas"
MANUALES_DIR.mkdir(exist_ok=True)
POLIZAS_DIR.mkdir(exist_ok=True)

MANUALES_COMPANIAS = [
    "Mercantil Andina",
    "Federación Patronal",
    "ATM",
    "San Cristóbal",
    "Rivadavia",
    "EuroAmérica",
    "AgroSalta",
    "Triunfo",
    "PROF",
]

def slug_manual_compania(nombre):
    equivalencias = {
        "Mercantil Andina": "mercantil_andina",
        "Federación Patronal": "federacion_patronal",
        "ATM": "atm",
        "San Cristóbal": "san_cristobal",
        "Rivadavia": "rivadavia",
        "EuroAmérica": "euroamerica",
        "AgroSalta": "agrosalta",
        "Triunfo": "triunfo",
        "PROF": "prof",
    }
    return equivalencias[nombre]

def manuales_companias():
    """Lista los manuales persistidos sin mover ni sobrescribir archivos existentes."""
    resultado = []
    MANUALES_DIR.mkdir(exist_ok=True)
    for nombre in MANUALES_COMPANIAS:
        slug = slug_manual_compania(nombre)
        archivos = []
        legacy = MANUALES_DIR / f"{slug}.pdf"
        if legacy.is_file():
            archivos.append(legacy)
        archivos.extend(a for a in MANUALES_DIR.glob(f"{slug}__*.pdf") if a.is_file())
        archivos = sorted(archivos, key=lambda a: a.stat().st_mtime, reverse=True)
        resultado.append({
            "nombre": nombre,
            "slug": slug,
            "cargado": bool(archivos),
            "cantidad": len(archivos),
            "archivos": [
                {
                    "nombre": (a.name.split("__", 1)[1] if "__" in a.name else a.name),
                    "archivo": a.name,
                    "fecha": __import__("datetime").datetime.fromtimestamp(a.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
                }
                for a in archivos
            ],
        })
    return resultado


# ==========================================================
# USUARIOS Y AUTENTICACIÓN
# ==========================================================

def conectar_db():
    conexion = sqlite3.connect(DB_FILE)
    conexion.row_factory = sqlite3.Row
    return conexion

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
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(conversacion_id) REFERENCES conversaciones(id) ON DELETE CASCADE
        )""")
        columnas = {fila[1] for fila in db.execute("PRAGMA table_info(usuarios)").fetchall()}
        if "email" not in columnas: db.execute("ALTER TABLE usuarios ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        if "rol" not in columnas: db.execute("ALTER TABLE usuarios ADD COLUMN rol TEXT NOT NULL DEFAULT 'usuario'")
        if "protegido" not in columnas: db.execute("ALTER TABLE usuarios ADD COLUMN protegido INTEGER NOT NULL DEFAULT 0")
        admin = db.execute("SELECT id FROM usuarios WHERE usuario = ?", (USUARIO_ADMIN_PRINCIPAL,)).fetchone()
        if admin is None:
            db.execute("INSERT INTO usuarios (usuario,password,email,rol,protegido) VALUES (?,?,?,?,1)", ("admin", generate_password_hash("1234"), "", "admin"))
        else:
            db.execute("UPDATE usuarios SET rol='admin', protegido=1 WHERE usuario=?", (USUARIO_ADMIN_PRINCIPAL,))
        db.commit()

def obtener_usuario(usuario):
    with closing(conectar_db()) as db:
        return db.execute("SELECT id,usuario,password,email,rol,protegido FROM usuarios WHERE usuario=?", (usuario,)).fetchone()

def obtener_usuario_por_id(usuario_id):
    with closing(conectar_db()) as db:
        return db.execute("SELECT id,usuario,password,email,rol,protegido FROM usuarios WHERE id=?", (usuario_id,)).fetchone()

def usuario_es_admin():
    u=obtener_usuario(session.get("usuario", "")) if session.get("usuario") else None
    return bool(u and u["rol"] == "admin")

def validar_email(email):
    return not email or bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email))

def requiere_admin(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "usuario" not in session: return redirect(url_for("login"))
        if not usuario_es_admin(): return ("Acceso no autorizado", 403)
        return func(*args, **kwargs)
    return wrapper

@app.context_processor
def contexto_usuario():
    u=obtener_usuario(session.get("usuario", "")) if session.get("usuario") else None
    return {"usuario_rol": u["rol"] if u else None, "usuario_es_admin": bool(u and u["rol"] == "admin")}


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

    limpio = nombre.lower().strip()

    equivalencias = {

        "atm":
            "ATM",

        "federacion":
            "Federación Patronal",

        "rivadavia":
            "Rivadavia",

        "euroamerica":
            "EuroAmérica",

        "agrosalta":
            "AgroSalta",

        "triunfo":
            "Triunfo",

        "prof":
            "PROF",

        "mercantil":
            "Mercantil Andina",

        "mercantil_andina":
            "Mercantil Andina",

        "mercantilandina":
            "Mercantil Andina",

        "san_cristobal":
            "San Cristóbal",

        "sancristobal":
            "San Cristóbal",

        "federacion_patronal":
            "Federación Patronal",

        "federacionpatronal":
            "Federación Patronal",

        "la_segunda":
            "La Segunda",

        "lasegunda":
            "La Segunda",

        "rio_uruguay":
            "Río Uruguay",

        "riouruguay":
            "Río Uruguay",

        "sancor_seguros":
            "Sancor Seguros",

        "sancorseguros":
            "Sancor Seguros",

        "provincia":
            "Provincia Seguros"

    }

    if limpio in equivalencias:

        return equivalencias[limpio]

    return nombre.replace(
        "_",
        " "
    ).title()


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
# EXTRACCIÓN Y RETRIEVAL DE PDF
# ==========================================================

_PDF_CACHE = {}
_STOPWORDS_ES = {
    "para", "como", "cual", "cuál", "que", "qué", "del", "las", "los",
    "una", "uno", "unos", "unas", "por", "con", "sin", "sobre", "entre",
    "desde", "hacia", "esta", "este", "estas", "estos", "tiene", "tienen",
    "debe", "deben", "puedo", "puede", "pueden", "quiero", "necesito",
    "donde", "dónde", "cuando", "cuándo", "hay", "son", "es", "el", "la",
    "y", "o", "a", "en", "un", "al", "se", "su", "sus", "mi", "mis",
    "me", "te", "lo", "le", "por", "del", "ya", "más", "mas"
}


def _normalizar_busqueda(texto):
    texto = str(texto or "").lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()


def _tokens_busqueda(texto):
    normalizado = _normalizar_busqueda(texto)
    tokens = re.findall(r"[a-z0-9]+", normalizado)
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS_ES]


def _raiz_simple(token):
    """Pequeña normalización morfológica para español sin dependencias externas."""
    t = token.lower()
    for sufijo in (
        "amientos", "imientos", "aciones", "iciones", "amiento", "imiento",
        "mente", "ando", "iendo", "ados", "idas", "idos", "adas", "ados",
        "es", "os", "as", "o", "a", "e"
    ):
        if len(t) > len(sufijo) + 3 and t.endswith(sufijo):
            return t[:-len(sufijo)]
    return t


def extraer_paginas_pdf(ruta):
    """
    Devuelve el texto separado por página y conserva metadata útil para
    citar el origen. Se cachea por fecha de modificación para no releer
    todos los PDFs en cada pregunta.
    """
    ruta = Path(ruta)
    try:
        mtime = ruta.stat().st_mtime_ns
    except OSError:
        return []

    clave = str(ruta.resolve())
    cacheado = _PDF_CACHE.get(clave)
    if cacheado and cacheado.get("mtime") == mtime:
        return cacheado["paginas"]

    paginas = []

    try:
        lector = PdfReader(str(ruta))
        for numero, pagina in enumerate(lector.pages, start=1):
            try:
                contenido = pagina.extract_text() or ""
            except Exception as error:
                print(f"ERROR EXTRAYENDO PÁGINA {numero} DE PDF {ruta}: {error}")
                contenido = ""

            contenido = re.sub(r"[ \t]+", " ", contenido)
            contenido = re.sub(r"\n{3,}", "\n\n", contenido).strip()

            if contenido:
                paginas.append({
                    "pagina": numero,
                    "texto": contenido
                })

        if not paginas:
            print(
                f"PDF SIN TEXTO EXTRAÍBLE: {ruta}. "
                "Si es un PDF escaneado, necesita OCR para poder consultarse."
            )

    except Exception as error:
        print("ERROR LEYENDO PDF:", ruta, error)
        paginas = []

    _PDF_CACHE[clave] = {
        "mtime": mtime,
        "paginas": paginas
    }
    return paginas


def extraer_texto_pdf(ruta):
    """Compatibilidad con las funciones existentes que necesitan texto completo."""
    return "\n\n".join(p["texto"] for p in extraer_paginas_pdf(ruta))


def _crear_chunks_paginas(paginas, chunk_chars=1400, overlap=220):
    """
    Divide el texto en fragmentos pequeños conservando página.
    Evita enviar un PDF completo al modelo cuando sólo una parte es relevante.
    """
    chunks = []

    for pagina in paginas:
        texto = pagina["texto"]
        if len(texto) <= chunk_chars:
            chunks.append({
                "pagina": pagina["pagina"],
                "texto": texto
            })
            continue

        inicio = 0
        while inicio < len(texto):
            fin = min(len(texto), inicio + chunk_chars)

            # Preferimos cortar cerca de un salto de párrafo o frase.
            if fin < len(texto):
                corte = max(
                    texto.rfind("\n", inicio + 700, fin),
                    texto.rfind(". ", inicio + 700, fin),
                    texto.rfind("; ", inicio + 700, fin)
                )
                if corte > inicio + 700:
                    fin = corte + 1

            fragmento = texto[inicio:fin].strip()
            if fragmento:
                chunks.append({
                    "pagina": pagina["pagina"],
                    "texto": fragmento
                })

            if fin >= len(texto):
                break

            inicio = max(inicio + 1, fin - overlap)

    return chunks


def _puntuar_chunk(consulta, chunk):
    """
    Ranking híbrido local:
    - coincidencia exacta de términos;
    - frecuencia;
    - frases de varias palabras;
    - coincidencias morfológicas simples.
    """
    consulta_norm = _normalizar_busqueda(consulta)
    texto_norm = _normalizar_busqueda(chunk["texto"])
    tokens = _tokens_busqueda(consulta)

    if not tokens or not texto_norm:
        return 0

    puntuacion = 0

    # Frase completa: una señal muy fuerte.
    if len(consulta_norm) >= 8 and consulta_norm in texto_norm:
        puntuacion += 30

    # Pares consecutivos de términos.
    for i in range(len(tokens) - 1):
        frase = f"{tokens[i]} {tokens[i+1]}"
        if frase in texto_norm:
            puntuacion += 10

    palabras_texto = set(re.findall(r"[a-z0-9]+", texto_norm))
    raices_texto = {_raiz_simple(x) for x in palabras_texto}

    for token in tokens:
        if token in palabras_texto:
            # La primera aparición es más útil que repetir una palabra 30 veces.
            puntuacion += min(8, 2 + texto_norm.count(token))
        elif _raiz_simple(token) in raices_texto:
            puntuacion += 3

    return puntuacion


def _archivos_pdf_consultables():
    archivos = []

    if DOCUMENTOS_DIR.exists():
        archivos.extend(
            p for p in DOCUMENTOS_DIR.rglob("*.pdf")
            if p.is_file()
        )

    if MANUALES_DIR.exists():
        archivos.extend(
            p for p in MANUALES_DIR.glob("*.pdf")
            if p.is_file()
        )
    if POLIZAS_DIR.exists():
        archivos.extend(
            p for p in POLIZAS_DIR.glob("*.pdf")
            if p.is_file()
        )

    # Evitar duplicados si por alguna razón ambas rutas apuntan al mismo archivo.
    vistos = set()
    unicos = []
    for archivo in archivos:
        clave = str(archivo.resolve())
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(archivo)

    return unicos


def buscar_en_documentos(consulta, limite=12):
    """
    Busca en TODOS los PDFs disponibles y devuelve sólo los fragmentos más
    relevantes, en vez de mandar documentos completos al modelo.
    """
    resultados = []
    tokens = _tokens_busqueda(consulta)

    if not tokens:
        return resultados

    for archivo in _archivos_pdf_consultables():
        paginas = extraer_paginas_pdf(archivo)
        if not paginas:
            continue

        chunks = _crear_chunks_paginas(paginas)

        for chunk in chunks:
            puntuacion = _puntuar_chunk(consulta, chunk)
            if puntuacion <= 0:
                continue

            try:
                if archivo.parent.resolve() == MANUALES_DIR.resolve():
                    slug = archivo.name.split("__", 1)[0]
                    compania = next((c for c in MANUALES_COMPANIAS if slug_manual_compania(c) == slug), "")
                    nombre_archivo = archivo.name.split("__", 1)[1] if "__" in archivo.name else archivo.name
                    tipo = "manual"
                    ruta_relativa = archivo.name
                elif archivo.parent.resolve() == POLIZAS_DIR.resolve():
                    nombre_archivo = archivo.name
                    compania = "Biblioteca de pólizas"
                    tipo = "poliza"
                    ruta_relativa = archivo.name
                else:
                    relativa = archivo.relative_to(DOCUMENTOS_DIR)
                    partes = relativa.parts
                    compania_slug = partes[0] if partes else ""
                    compania = nombre_compania(compania_slug)
                    nombre_archivo = archivo.name
                    tipo = "documento"
                    ruta_relativa = str(relativa)
            except Exception:
                compania = ""
                nombre_archivo = archivo.name
                tipo = "documento"
                ruta_relativa = archivo.name

            resultados.append({
                "archivo": nombre_archivo,
                "compania": compania,
                "ruta": ruta_relativa,
                "coincidencias": puntuacion,
                "texto": chunk["texto"],
                "pagina": chunk["pagina"],
                "tipo": tipo
            })

    resultados.sort(
        key=lambda x: (
            x["coincidencias"],
            len(x.get("texto", ""))
        ),
        reverse=True
    )

    # Diversificar: no queremos que los 12 resultados sean todos del mismo PDF.
    seleccionados = []
    por_archivo = {}
    for resultado in resultados:
        clave = resultado["ruta"]
        cantidad = por_archivo.get(clave, 0)
        if cantidad >= 4:
            continue
        seleccionados.append(resultado)
        por_archivo[clave] = cantidad + 1
        if len(seleccionados) >= limite:
            break

    print(
        f"RETRIEVAL PDF: consulta={consulta!r} "
        f"archivos={len(_archivos_pdf_consultables())} "
        f"fragmentos={len(seleccionados)}"
    )

    return seleccionados


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

    return render_template(
        "documentos.html",
        carpetas=obtener_companias(),
        usuario=session["usuario"],
        usuario_rol=session.get("rol", "usuario")
    )


# ==========================================================
# VER CARPETA
# ==========================================================

@app.route(
    "/carpeta/<path:carpeta>"
)
@requiere_login
def ver_carpeta(carpeta):

    carpeta_path = (
        DOCUMENTOS_DIR /
        carpeta
    )

    if not carpeta_path.exists():

        return (
            "Compañía no encontrada",
            404
        )

    archivos = []

    for archivo in carpeta_path.rglob("*"):

        if archivo.is_file():

            archivos.append({

                "nombre":
                    archivo.name,

                "ruta":
                    str(
                        archivo.relative_to(
                            carpeta_path
                        )
                    ),

                "extension":
                    archivo.suffix.lower(),

                "tamaño":
                    round(
                        archivo.stat().st_size / 1024,
                        1
                    )

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

    carpeta_path = (
        DOCUMENTOS_DIR /
        carpeta
    )

    archivo_path = (
        carpeta_path /
        archivo
    )

    if not archivo_path.exists():

        return (
            "Archivo no encontrado",
            404
        )

    return send_from_directory(
        carpeta_path,
        archivo
    )


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

def _fila_vacia(fila):
    return not any(str(valor or "").strip() for valor in fila)


def _limpiar_filas_excel(filas):
    """Elimina filas completamente vacías. Conserva la primera fila como encabezado."""
    if not isinstance(filas, list):
        raise ValueError("La matriz no es válida.")
    filas = filas[:500]
    normalizadas = []
    for fila in filas:
        if not isinstance(fila, list):
            continue
        limpia = ["" if valor is None else str(valor) for valor in fila[:30]]
        normalizadas.append(limpia)
    if not normalizadas:
        return []
    encabezado = normalizadas[0]
    cuerpo = [fila for fila in normalizadas[1:] if not _fila_vacia(fila)]
    return [encabezado] + cuerpo


def asegurar_excel_interno():
    if not EXCEL_FILE.exists():
        wb = Workbook()
        ws = wb.active
        ws.title = "Datos"
        ws.append(["Dato", "Valor", "Observaciones"])
        wb.save(EXCEL_FILE)


def leer_excel_interno():
    asegurar_excel_interno()
    wb = load_workbook(EXCEL_FILE, data_only=False)
    ws = wb.active
    filas = [["" if value is None else str(value) for value in row] for row in ws.iter_rows(values_only=True)]
    filas = _limpiar_filas_excel(filas)
    columnas = max([len(f) for f in filas], default=1)
    columnas = max(1, min(columnas, 30))
    filas = [f[:columnas] + [""] * (columnas - len(f)) for f in filas]
    return {"hoja": ws.title, "filas": filas, "columnas": columnas}


def guardar_matriz_excel(filas, nombre_hoja="Datos"):
    filas = _limpiar_filas_excel(filas)
    max_cols = max([len(f) for f in filas], default=1)
    max_cols = min(max_cols, 30)
    wb = Workbook()
    ws = wb.active
    ws.title = (nombre_hoja or "Datos")[:31]
    for r, fila in enumerate(filas, start=1):
        for c, valor in enumerate(fila[:max_cols], start=1):
            if str(valor or "").strip():
                ws.cell(row=r, column=c, value=str(valor))
    for c in range(1, max_cols + 1):
        letra = get_column_letter(c)
        valores = [str(ws.cell(r, c).value or "") for r in range(1, min(ws.max_row, 30) + 1)]
        ancho = min(max([len(v) for v in valores] + [10]) + 2, 32)
        ws.column_dimensions[letra].width = ancho
    wb.save(EXCEL_FILE)


def asegurar_word_interno():
    if not WORD_FILE.exists():
        doc = Document()
        doc.add_paragraph("")
        doc.save(WORD_FILE)


def leer_word_interno():
    asegurar_word_interno()
    doc = Document(WORD_FILE)
    return "\n\n".join(p.text for p in doc.paragraphs)


def guardar_word_interno(contenido):
    doc = Document()
    for linea in str(contenido or "").splitlines():
        doc.add_paragraph(linea)
    doc.save(WORD_FILE)


@app.route("/notas")
@requiere_login
def notas():
    # Se conserva la URL para no romper marcadores antiguos; ahora muestra Excel + Word.
    return render_template("notas.html", usuario=session["usuario"], carpetas=obtener_companias())


@app.route("/api/excel", methods=["GET"])
@requiere_login
def api_excel():
    try:
        return jsonify({"ok": True, **leer_excel_interno()})
    except Exception as error:
        print("ERROR LEYENDO EXCEL INTERNO:", error)
        return jsonify({"ok": False, "error": "No se pudo leer la planilla."}), 500


@app.route("/api/excel", methods=["POST"])
@requiere_login
def api_excel_guardar():
    data = request.get_json(silent=True) or {}
    try:
        guardar_matriz_excel(data.get("filas", []), data.get("hoja", "Datos"))
        return jsonify({"ok": True, **leer_excel_interno()})
    except Exception as error:
        print("ERROR GUARDANDO EXCEL INTERNO:", error)
        return jsonify({"ok": False, "error": "No se pudo guardar la planilla."}), 500


@app.route("/api/excel/limpiar", methods=["POST"])
@requiere_login
def api_excel_limpiar():
    try:
        datos = leer_excel_interno()
        guardar_matriz_excel(datos["filas"], datos["hoja"])
        return jsonify({"ok": True, **leer_excel_interno()})
    except Exception as error:
        print("ERROR LIMPIANDO EXCEL:", error)
        return jsonify({"ok": False, "error": "No se pudieron eliminar las filas vacías."}), 500


@app.route("/api/excel/importar", methods=["POST"])
@requiere_login
def api_excel_importar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return jsonify({"ok": False, "error": "No se recibió ningún archivo."}), 400
    nombre = secure_filename(archivo.filename)
    if not nombre.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"ok": False, "error": "Usá un archivo Excel .xlsx o .xlsm."}), 400
    temporal = EXCEL_FILE.with_suffix(".upload.xlsx")
    try:
        archivo.save(temporal)
        wb = load_workbook(temporal, data_only=False)
        if not wb.sheetnames:
            raise ValueError("El Excel no contiene hojas.")
        ws = wb[wb.sheetnames[0]]
        filas = [["" if value is None else str(value) for value in row] for row in ws.iter_rows(values_only=True)]
        guardar_matriz_excel(filas, ws.title)
        return jsonify({"ok": True, **leer_excel_interno()})
    except Exception as error:
        print("ERROR IMPORTANDO EXCEL:", error)
        return jsonify({"ok": False, "error": "No se pudo importar el Excel."}), 400
    finally:
        try: temporal.unlink(missing_ok=True)
        except Exception: pass


@app.route("/excel/exportar")
@requiere_login
def excel_exportar():
    asegurar_excel_interno()
    return send_from_directory(EXCEL_FILE.parent, EXCEL_FILE.name, as_attachment=True, download_name="OficinaIA.xlsx")


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
    asegurar_word_interno()
    return send_from_directory(WORD_FILE.parent, WORD_FILE.name, as_attachment=True, download_name="OficinaIA.docx")



# ==========================================================
# CONVERSACIONES PERSISTENTES
# ==========================================================

def _crear_conversacion(usuario, titulo="Nueva conversación"):
    with closing(conectar_db()) as db:
        cur = db.execute(
            "INSERT INTO conversaciones (usuario,titulo) VALUES (?,?)",
            (usuario, titulo[:100] or "Nueva conversación")
        )
        db.commit()
        return cur.lastrowid

@app.route("/api/chats", methods=["GET"])
@requiere_login
def listar_chats():
    with closing(conectar_db()) as db:
        rows = db.execute(
            "SELECT id,titulo,creado_en,actualizado_en FROM conversaciones WHERE usuario=? ORDER BY actualizado_en DESC, id DESC",
            (session["usuario"],)
        ).fetchall()
        return jsonify({"ok": True, "chats":[dict(r) for r in rows]})

@app.route("/api/chats", methods=["POST"])
@requiere_login
def crear_chat():
    data=request.get_json(silent=True) or {}
    titulo=str(data.get("titulo","Nueva conversación")).strip()[:100] or "Nueva conversación"
    cid=_crear_conversacion(session["usuario"], titulo)
    return jsonify({"ok":True,"id":cid,"titulo":titulo})

@app.route("/api/chats/<int:chat_id>", methods=["GET"])
@requiere_login
def obtener_chat(chat_id):
    with closing(conectar_db()) as db:
        chat=db.execute("SELECT id,titulo FROM conversaciones WHERE id=? AND usuario=?",(chat_id,session["usuario"])).fetchone()
        if not chat: return jsonify({"ok":False,"error":"Conversación no encontrada."}),404
        mensajes=db.execute("SELECT id,rol,contenido,creado_en FROM mensajes WHERE conversacion_id=? ORDER BY id",(chat_id,)).fetchall()
        return jsonify({"ok":True,"chat":dict(chat),"mensajes":[dict(x) for x in mensajes]})

@app.route("/api/chats/<int:chat_id>", methods=["DELETE"])
@requiere_login
def eliminar_chat(chat_id):
    with closing(conectar_db()) as db:
        row=db.execute("SELECT id FROM conversaciones WHERE id=? AND usuario=?",(chat_id,session["usuario"])).fetchone()
        if not row: return jsonify({"ok":False,"error":"Conversación no encontrada."}),404
        db.execute("DELETE FROM mensajes WHERE conversacion_id=?",(chat_id,))
        db.execute("DELETE FROM conversaciones WHERE id=?",(chat_id,))
        db.commit()
    return jsonify({"ok":True})

# CHAT
# ==========================================================

@app.route(
    "/api/chat",
    methods=["POST"]
)
@requiere_login
def chat():

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "respuesta":
                "No recibí ningún mensaje."
        })

    mensaje = data.get(
        "mensaje",
        ""
    ).strip()

    chat_id = data.get("chat_id")
    try:
        chat_id = int(chat_id) if chat_id else None
    except (TypeError, ValueError):
        chat_id = None

    with closing(conectar_db()) as db:
        if chat_id:
            valido = db.execute("SELECT id FROM conversaciones WHERE id=? AND usuario=?",(chat_id,session["usuario"])).fetchone()
            if not valido:
                chat_id = None
        if not chat_id:
            titulo = " ".join(mensaje.split())[:58] or "Nueva conversación"
            cur=db.execute("INSERT INTO conversaciones (usuario,titulo) VALUES (?,?)",(session["usuario"],titulo))
            chat_id=cur.lastrowid
            db.commit()

    historial = data.get("historial") or []
    if not isinstance(historial, list):
        historial = []

    # Limitamos el historial para no consumir contexto innecesariamente.
    historial = [
        x for x in historial
        if isinstance(x, dict)
        and x.get("rol") in {"user", "assistant"}
        and str(x.get("contenido", "")).strip()
    ][-10:]

    if not mensaje:

        return jsonify({
            "respuesta":
                "Escribime una consulta."
        })

    with closing(conectar_db()) as db:
        db.execute("INSERT INTO mensajes (conversacion_id,rol,contenido) VALUES (?,?,?)",(chat_id,"user",mensaje))
        db.execute("UPDATE conversaciones SET actualizado_en=CURRENT_TIMESTAMP WHERE id=?",(chat_id,))
        db.commit()

    # ======================================================
    # BUSCAR EN PDF
    # ======================================================

    resultados_pdf = buscar_en_documentos(
        mensaje
    )

    contexto_pdf = ""

    for resultado in resultados_pdf:

        contexto_pdf += (
            "\n\n===== FRAGMENTO DE DOCUMENTO =====\n"
        )

        contexto_pdf += (
            "ARCHIVO: "
            + resultado.get("archivo", "")
            + "\n"
        )

        contexto_pdf += (
            "COMPAÑIA: "
            + resultado.get("compania", "")
            + "\n"
        )

        contexto_pdf += (
            "PAGINA: "
            + str(resultado.get("pagina", ""))
            + "\n"
        )

        contexto_pdf += (
            "TIPO: "
            + resultado.get("tipo", "documento")
            + "\n\n"
        )

        contexto_pdf += (
            resultado.get("texto", "")
            + "\n"
        )

    # ======================================================
    # BUSCAR EN GOOGLE SHEETS
    # ======================================================

    contexto_sheet = ""

    try:

        from servicios_ia import (
            buscar_en_google_sheet
        )

        resultados_sheet = (
            buscar_en_google_sheet(
                mensaje
            )
        )

        if resultados_sheet:

            contexto_sheet = (
                "\n\n===== GOOGLE SHEETS =====\n"
                + resultados_sheet
            )

    except Exception as error:

        print(
            "ERROR GOOGLE SHEETS:",
            error
        )

    # ======================================================
    # CONTEXTO COMPLETO
    # ======================================================

    contexto = (
        contexto_pdf
        + contexto_sheet
    )

    # ======================================================
    # GEMINI
    # ======================================================

    try:

        from servicios_ia import (
            consultar_gemini
        )

        respuesta = consultar_gemini(
            mensaje,
            contexto,
            historial=historial
        )

    except Exception as error:

        print(
            "ERROR CHAT GEMINI:",
            error
        )

        if contexto:

            respuesta = (
                "Encontré información "
                "relacionada en la oficina.\n\n"
                + contexto[:8000]
            )

        else:

            respuesta = (
                "No encontré información "
                "relacionada en los documentos "
                "ni en Google Sheets."
            )

    with closing(conectar_db()) as db:
        db.execute("INSERT INTO mensajes (conversacion_id,rol,contenido) VALUES (?,?,?)",(chat_id,"assistant",str(respuesta)))
        db.execute("UPDATE conversaciones SET actualizado_en=CURRENT_TIMESTAMP WHERE id=?",(chat_id,))
        db.commit()

    return jsonify({
        "respuesta": respuesta,
        "chat_id": chat_id
    })


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

@app.route("/manuales")
@requiere_login
def manuales():
    return redirect(url_for("biblioteca"))


@app.route("/biblioteca")
@requiere_login
def biblioteca():
    polizas = sorted(
        [{"archivo":p.name, "nombre":p.name, "fecha":__import__("datetime").datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
          "tamaño":round(p.stat().st_size/1024,1)} for p in POLIZAS_DIR.glob("*.pdf") if p.is_file()],
        key=lambda x:x["fecha"], reverse=True
    )
    return render_template("biblioteca.html", manuales=manuales_companias(), polizas=polizas,
                           usuario=session["usuario"], usuario_rol=session.get("rol","usuario"),
                           usuario_es_admin=usuario_es_admin())

@app.route("/api/polizas", methods=["POST"])
@requiere_admin
def subir_poliza():
    archivo=request.files.get("poliza")
    if not archivo or not archivo.filename:
        return jsonify(ok=False,error="Seleccioná un archivo PDF."),400
    nombre=secure_filename(Path(archivo.filename).name)
    if not nombre.lower().endswith(".pdf"):
        return jsonify(ok=False,error="El archivo debe ser un PDF."),400
    destino=POLIZAS_DIR/nombre
    if destino.exists():
        stem=destino.stem; suf=destino.suffix; n=2
        while destino.exists():
            destino=POLIZAS_DIR/f"{stem}_{n}{suf}"; n+=1
    temporal=POLIZAS_DIR/f".upload_{__import__('time').time_ns()}.tmp"
    try:
        archivo.save(temporal)
        if temporal.read_bytes()[:5] != b"%PDF-": raise ValueError("El archivo no parece ser un PDF válido.")
        PdfReader(str(temporal))
        temporal.replace(destino)
        return jsonify(ok=True,archivo=destino.name)
    except ValueError as e:
        temporal.unlink(missing_ok=True); return jsonify(ok=False,error=str(e)),400
    except Exception:
        temporal.unlink(missing_ok=True); return jsonify(ok=False,error="No se pudo guardar la póliza."),500

@app.route("/api/polizas/<path:nombre>", methods=["DELETE"])
@requiere_admin
def eliminar_poliza(nombre):
    archivo=(POLIZAS_DIR/Path(nombre).name).resolve()
    base=POLIZAS_DIR.resolve()
    if base not in archivo.parents or not archivo.exists() or archivo.suffix.lower()!=".pdf":
        return jsonify(ok=False,error="Póliza no encontrada."),404
    archivo.unlink()
    return jsonify(ok=True)

@app.route("/polizas/<path:nombre>")
@requiere_login
def ver_poliza(nombre):
    archivo=(POLIZAS_DIR/Path(nombre).name).resolve()
    base=POLIZAS_DIR.resolve()
    if base not in archivo.parents or not archivo.exists() or archivo.suffix.lower()!=".pdf":
        return ("Póliza no encontrada",404)
    return send_from_directory(POLIZAS_DIR,archivo.name,mimetype="application/pdf",as_attachment=False)

@app.route("/configuracion")
@requiere_login
def configuracion():
    config={"nombre_oficina":"Oficina Seguros","notificaciones":True}
    if CONFIG_FILE.exists():
        try:
            import json; config.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception: pass
    usuarios=[]
    if usuario_es_admin():
        with closing(conectar_db()) as db:
            usuarios=db.execute("SELECT id,usuario,email,rol,protegido FROM usuarios ORDER BY usuario COLLATE NOCASE").fetchall()
    return render_template("configuracion.html",config=config,usuario=session["usuario"],carpetas=obtener_companias(),usuarios=usuarios)

@app.route("/api/configuracion", methods=["POST"])
@requiere_login
def guardar_configuracion():
    data=request.get_json(silent=True) or {}
    config={"nombre_oficina":"Oficina Seguros","notificaciones":True}
    if CONFIG_FILE.exists():
        try:
            import json; config.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception: pass
    nombre=str(data.get("nombre_oficina",config["nombre_oficina"])).strip()
    if not nombre: return jsonify(ok=False,error="El nombre de la oficina no puede estar vacío."),400
    config["nombre_oficina"]=nombre; config["notificaciones"]=bool(data.get("notificaciones",config["notificaciones"]))
    try:
        import json; CONFIG_FILE.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding="utf-8")
        return jsonify(ok=True)
    except Exception: return jsonify(ok=False,error="No se pudo guardar la configuración."),500

@app.route("/api/usuarios", methods=["POST"])
@requiere_admin
def crear_usuario():
    data=request.get_json(silent=True) or {}
    usuario=str(data.get("usuario","")).strip(); password=str(data.get("password","")); email=str(data.get("email","")).strip(); rol=str(data.get("rol","usuario")).strip().lower()
    if not usuario: return jsonify(ok=False,error="El usuario es obligatorio."),400
    if not password: return jsonify(ok=False,error="La contraseña es obligatoria."),400
    if rol not in ROLES_VALIDOS: return jsonify(ok=False,error="Rol inválido."),400
    if not validar_email(email): return jsonify(ok=False,error="El correo electrónico no es válido."),400
    with closing(conectar_db()) as db:
        if db.execute("SELECT 1 FROM usuarios WHERE lower(usuario)=lower(?)",(usuario,)).fetchone(): return jsonify(ok=False,error="Ese usuario ya existe."),409
        db.execute("INSERT INTO usuarios (usuario,password,email,rol,protegido) VALUES (?,?,?,?,0)",(usuario,generate_password_hash(password),email,rol)); db.commit()
    return jsonify(ok=True,mensaje="Usuario creado correctamente.")

@app.route("/api/usuarios/<int:usuario_id>", methods=["PUT"])
@requiere_admin
def editar_usuario(usuario_id):
    registro=obtener_usuario_por_id(usuario_id)
    if not registro: return jsonify(ok=False,error="Usuario no encontrado."),404
    data=request.get_json(silent=True) or {}; email=str(data.get("email","")).strip(); rol=str(data.get("rol",registro["rol"])).strip().lower(); password=str(data.get("password",""))
    if not validar_email(email): return jsonify(ok=False,error="El correo electrónico no es válido."),400
    if rol not in ROLES_VALIDOS: return jsonify(ok=False,error="Rol inválido."),400
    if registro["protegido"]: rol="admin"
    with closing(conectar_db()) as db:
        db.execute("UPDATE usuarios SET email=?,rol=? WHERE id=?",(email,rol,usuario_id))
        if password: db.execute("UPDATE usuarios SET password=? WHERE id=?",(generate_password_hash(password),usuario_id))
        db.commit()
    return jsonify(ok=True,mensaje="Usuario actualizado correctamente.")

@app.route("/api/usuarios/<int:usuario_id>", methods=["DELETE"])
@requiere_admin
def eliminar_usuario(usuario_id):
    registro=obtener_usuario_por_id(usuario_id)
    if not registro: return jsonify(ok=False,error="Usuario no encontrado."),404
    if registro["protegido"]: return jsonify(ok=False,error="El administrador principal está protegido."),403
    if registro["usuario"]==session.get("usuario"): return jsonify(ok=False,error="No podés eliminar tu propia cuenta."),400
    with closing(conectar_db()) as db: db.execute("DELETE FROM usuarios WHERE id=?",(usuario_id,)); db.commit()
    return jsonify(ok=True,mensaje="Usuario eliminado correctamente.")


@app.route("/api/manuales/<slug>", methods=["POST"])
@requiere_admin
def subir_manual(slug):
    compania = next((c for c in MANUALES_COMPANIAS if slug_manual_compania(c) == slug), None)
    if not compania:
        return jsonify(ok=False, error="Compañía no válida."), 404

    archivo = request.files.get("manual")
    if not archivo or not archivo.filename:
        return jsonify(ok=False, error="Seleccioná un archivo PDF."), 400

    nombre_seguro = secure_filename(Path(archivo.filename).name)
    if not nombre_seguro or Path(nombre_seguro).suffix.lower() != ".pdf":
        return jsonify(ok=False, error="El archivo debe ser un PDF."), 400

    reemplazar = str(request.form.get("replace", "")).strip()
    if reemplazar:
        destino = (MANUALES_DIR / Path(reemplazar).name).resolve()
        base = MANUALES_DIR.resolve()
        if base not in destino.parents or destino.suffix.lower() != ".pdf" or not destino.exists() or not destino.name.startswith(slug + "__"):
            # También permitimos reemplazar un archivo legacy existente de esa compañía.
            legacy = (MANUALES_DIR / f"{slug}.pdf").resolve()
            if destino != legacy or not legacy.exists():
                return jsonify(ok=False, error="El manual a reemplazar no es válido."), 400
    else:
        base_nombre = Path(nombre_seguro).stem[:90] or "manual"
        destino = MANUALES_DIR / f"{slug}__{base_nombre}.pdf"
        n = 2
        while destino.exists():
            destino = MANUALES_DIR / f"{slug}__{base_nombre}_{n}.pdf"
            n += 1

    temporal = MANUALES_DIR / f".{slug}_{__import__('time').time_ns()}.uploading"
    try:
        archivo.save(temporal)
        with temporal.open("rb") as f:
            if f.read(5) != b"%PDF-":
                raise ValueError("El archivo no parece ser un PDF válido.")
        try:
            PdfReader(str(temporal))
        except Exception as exc:
            raise ValueError("No se pudo leer el PDF. Verificá que no esté dañado.") from exc
        temporal.replace(destino)
    except ValueError as exc:
        temporal.unlink(missing_ok=True)
        return jsonify(ok=False, error=str(exc)), 400
    except Exception:
        temporal.unlink(missing_ok=True)
        return jsonify(ok=False, error="No se pudo guardar el manual."), 500

    return jsonify(ok=True, mensaje=f"Manual de {compania} cargado correctamente.", archivo=destino.name)

@app.route("/api/manuales/<slug>/<path:nombre_archivo>", methods=["DELETE"])
@requiere_admin
def eliminar_manual(slug, nombre_archivo):
    if slug not in {slug_manual_compania(c) for c in MANUALES_COMPANIAS}:
        return jsonify(ok=False, error="Compañía no válida."), 404
    archivo = (MANUALES_DIR / Path(nombre_archivo).name).resolve()
    base = MANUALES_DIR.resolve()
    if base not in archivo.parents or archivo.suffix.lower() != ".pdf" or not archivo.exists():
        return jsonify(ok=False, error="Manual no encontrado."), 404
    if archivo.name != f"{slug}.pdf" and not archivo.name.startswith(slug + "__"):
        return jsonify(ok=False, error="Manual no válido para esa compañía."), 400
    try:
        archivo.unlink()
    except Exception:
        return jsonify(ok=False, error="No se pudo eliminar el manual."), 500
    return jsonify(ok=True)

@app.route("/manuales/<slug>/<path:nombre_archivo>")
@requiere_login
def ver_manual(slug, nombre_archivo):
    if slug not in {slug_manual_compania(c) for c in MANUALES_COMPANIAS}:
        return ("Manual no encontrado", 404)
    archivo = (MANUALES_DIR / nombre_archivo).resolve()
    base = MANUALES_DIR.resolve()
    es_archivo_compania = archivo.name == f"{slug}.pdf" or archivo.name.startswith(slug + "__")
    if base not in archivo.parents or not archivo.exists() or archivo.suffix.lower() != ".pdf" or not es_archivo_compania:
        return ("Manual no encontrado", 404)
    return send_from_directory(MANUALES_DIR, archivo.name, mimetype="application/pdf", as_attachment=False)


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