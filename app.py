from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory
)

from pathlib import Path
from functools import wraps
from pypdf import PdfReader
from datetime import datetime
import re


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

app = Flask(__name__)

app.secret_key = "OFICINA_SEGUROS_CAMBIAR_CLAVE"

BASE_DIR = Path(__file__).resolve().parent

DOCUMENTOS_DIR = BASE_DIR / "documentos"

NOTAS_FILE = BASE_DIR / "notas.json"

DOCUMENTOS_DIR.mkdir(
    exist_ok=True
)


# ==========================================================
# USUARIO
# ==========================================================

USUARIO_CORRECTO = "admin"

PASSWORD_CORRECTA = "1234"


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


# ==========================================================
# OBTENER COMPAÑÍAS
# ==========================================================

def obtener_companias():

    carpetas = []

    if not DOCUMENTOS_DIR.exists():

        return carpetas


    for elemento in DOCUMENTOS_DIR.iterdir():

        if elemento.is_dir():

            carpetas.append(
                elemento.name
            )


    return sorted(
        carpetas,
        key=lambda x:
            nombre_compania(x).lower()
    )


# ==========================================================
# EXTRAER TEXTO DE PDF
# ==========================================================

def extraer_texto_pdf(ruta):

    texto = ""

    try:

        lector = PdfReader(
            str(ruta)
        )


        for pagina in lector.pages:

            contenido = pagina.extract_text()


            if contenido:

                texto += (
                    contenido +
                    "\n"
                )


    except Exception as error:

        print(
            "ERROR LEYENDO PDF:",
            ruta,
            error
        )


    return texto


# ==========================================================
# BUSCAR DENTRO DE PDFs
# ==========================================================

def buscar_en_documentos(consulta):

    resultados = []

    consulta = consulta.lower().strip()


    if not consulta:

        return resultados


    palabras = re.findall(
        r"\w+",
        consulta
    )


    for archivo in DOCUMENTOS_DIR.rglob("*.pdf"):

        texto = extraer_texto_pdf(
            archivo
        )


        if not texto:

            continue


        texto_lower = texto.lower()


        coincidencias = 0


        for palabra in palabras:

            if len(palabra) < 3:

                continue


            coincidencias += (
                texto_lower.count(
                    palabra
                )
            )


        if coincidencias == 0:

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


        except Exception:

            compania = ""


        resultados.append({

            "archivo":
                archivo.name,

            "compania":
                nombre_compania(
                    compania
                ),

            "ruta":
                str(
                    relativa
                ),

            "coincidencias":
                coincidencias,

            "texto":
                texto

        })


    resultados.sort(
        key=lambda x:
            x["coincidencias"],
        reverse=True
    )


    return resultados


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


        if (
            usuario == USUARIO_CORRECTO
            and
            password == PASSWORD_CORRECTA
        ):

            session.clear()

            session["usuario"] = usuario

            return redirect(
                url_for("documentos")
            )


        error = (
            "Usuario o contraseña incorrectos."
        )


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
        usuario=session["usuario"]
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
        usuario=session["usuario"]
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
        usuario=session["usuario"]
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
# NOTAS
# ==========================================================

@app.route("/notas")

@requiere_login

def notas():

    contenido = ""


    if NOTAS_FILE.exists():

        try:

            contenido = NOTAS_FILE.read_text(
                encoding="utf-8"
            )

        except Exception:

            contenido = ""


    return render_template(
        "notas.html",
        contenido=contenido,
        usuario=session["usuario"]
    )


# ==========================================================
# GUARDAR NOTAS
# ==========================================================

@app.route(
    "/api/notas",
    methods=["POST"]
)

@requiere_login

def guardar_notas():

    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({
            "ok": False
        }), 400


    contenido = data.get(
        "contenido",
        ""
    )


    try:

        NOTAS_FILE.write_text(
            contenido,
            encoding="utf-8"
        )


        return jsonify({
            "ok": True
        })


    except Exception:

        return jsonify({
            "ok": False
        }), 500


# ==========================================================
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


    if not mensaje:

        return jsonify({

            "respuesta":
                "Escribime una consulta."

        })


    # ------------------------------------------------------
    # BUSCAR EN LOS PDF
    # ------------------------------------------------------

    resultados = buscar_en_documentos(
        mensaje
    )


    # ------------------------------------------------------
    # SI ENCONTRAMOS INFORMACIÓN
    # ------------------------------------------------------

    if resultados:

        respuesta = (
            "Encontré información relacionada "
            "en tus documentos.\n\n"
        )


        for resultado in resultados[:3]:

            texto = resultado["texto"]

            palabras = re.findall(
                r"\w+",
                mensaje.lower()
            )


            posiciones = []


            for palabra in palabras:

                if len(palabra) < 3:

                    continue


                posicion = (
                    texto.lower().find(
                        palabra
                    )
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
                posicion - 150
            )


            fin = min(
                len(texto),
                posicion + 650
            )


            fragmento = (
                texto[inicio:fin]
                .replace(
                    "\n",
                    " "
                )
            )


            respuesta += (

                f"📄 "
                f"{resultado['archivo']}\n"

                f"🏢 "
                f"{resultado['compania']}\n\n"

                f"{fragmento}\n\n"

                "────────────────────\n\n"

            )


    else:

        respuesta = (
            "No encontré coincidencias "
            "en los documentos cargados.\n\n"
            "Cuando conectemos la IA, "
            "voy a poder interpretar la "
            "pregunta y buscar información "
            "de forma mucho más inteligente."
        )


    return jsonify({

        "respuesta":
            respuesta

    })


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

    companias = [

        "ATM",

        "MercantilAndina",

        "SanCristobal",

        "FederacionPatronal",

        "LaSegunda",

        "RioUruguay",

        "SancorSeguros",

        "Provincia"

    ]


    for compania in companias:

        carpeta = (
            DOCUMENTOS_DIR /
            compania
        )


        carpeta.mkdir(
            parents=True,
            exist_ok=True
        )


# ==========================================================
# INICIAR
# ==========================================================

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