from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

import fitz
from google.genai import types

from ai_gateway import begin_request, generate_with_fallback, obtener_cliente_gemini, DEFAULT_MODELS
from storage_r2 import subir_pdf as r2_subir_pdf, eliminar_pdf as r2_eliminar_pdf, descargar_pdf_temporal

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "oficina.db"
LOCAL_DIR = BASE_DIR / "estudio_archivos"
LOCAL_DIR.mkdir(exist_ok=True)

CLASIFICACIONES = ("TOMAR", "REVISAR", "NO_TOMAR", "INCOMPLETO")
CARPETAS_CLASIFICACION = {
    "TOMAR": "TOMAR",
    "REVISAR": "REVISAR",
    "NO_TOMAR": "NO_TOMAR",
    "INCOMPLETO": "INCOMPLETOS",
}


def _usa_pg() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def _r2_configurado() -> bool:
    return all(os.getenv(k) for k in (
        "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"
    ))


def _pg_conn():
    import psycopg2
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def asegurar_tablas() -> None:
    if _usa_pg():
        with closing(_pg_conn()) as db:
            with db.cursor() as c:
                c.execute("""
                CREATE TABLE IF NOT EXISTS estudio_lotes (
                    id VARCHAR(40) PRIMARY KEY,
                    usuario VARCHAR(120) NOT NULL,
                    titulo VARCHAR(220) NOT NULL DEFAULT '',
                    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                c.execute("""
                CREATE TABLE IF NOT EXISTS estudio_casos (
                    id VARCHAR(40) PRIMARY KEY,
                    lote_id VARCHAR(40) NOT NULL REFERENCES estudio_lotes(id) ON DELETE CASCADE,
                    usuario VARCHAR(120) NOT NULL,
                    nombre_archivo VARCHAR(255) NOT NULL,
                    storage_key VARCHAR(700) NOT NULL,
                    tamano BIGINT NOT NULL DEFAULT 0,
                    clasificacion VARCHAR(20) NOT NULL DEFAULT 'INCOMPLETO',
                    titulo VARCHAR(250) NOT NULL DEFAULT '',
                    resumen TEXT NOT NULL DEFAULT '',
                    motivo TEXT NOT NULL DEFAULT '',
                    datos_json TEXT NOT NULL DEFAULT '{}',
                    normas_json TEXT NOT NULL DEFAULT '[]',
                    confianza INTEGER NOT NULL DEFAULT 0,
                    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                c.execute("CREATE INDEX IF NOT EXISTS idx_estudio_casos_lote ON estudio_casos(lote_id, clasificacion)")
                c.execute("""
                CREATE TABLE IF NOT EXISTS estudio_ejemplos (
                    id VARCHAR(40) PRIMARY KEY,
                    usuario VARCHAR(120) NOT NULL,
                    nombre VARCHAR(250) NOT NULL,
                    clasificacion VARCHAR(20) NOT NULL,
                    fundamento TEXT NOT NULL DEFAULT '',
                    nombre_archivo VARCHAR(255) NOT NULL DEFAULT '',
                    storage_key VARCHAR(700) NOT NULL DEFAULT '',
                    texto_extraido TEXT NOT NULL DEFAULT '',
                    activo BOOLEAN NOT NULL DEFAULT TRUE,
                    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
            db.commit()
        return

    with closing(sqlite3.connect(DB_FILE)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""CREATE TABLE IF NOT EXISTS estudio_lotes (
            id TEXT PRIMARY KEY, usuario TEXT NOT NULL, titulo TEXT NOT NULL DEFAULT '',
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS estudio_casos (
            id TEXT PRIMARY KEY, lote_id TEXT NOT NULL, usuario TEXT NOT NULL,
            nombre_archivo TEXT NOT NULL, storage_key TEXT NOT NULL, tamano INTEGER NOT NULL DEFAULT 0,
            clasificacion TEXT NOT NULL DEFAULT 'INCOMPLETO', titulo TEXT NOT NULL DEFAULT '',
            resumen TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '', datos_json TEXT NOT NULL DEFAULT '{}',
            normas_json TEXT NOT NULL DEFAULT '[]', confianza INTEGER NOT NULL DEFAULT 0,
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lote_id) REFERENCES estudio_lotes(id) ON DELETE CASCADE)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_estudio_casos_lote ON estudio_casos(lote_id, clasificacion)")
        db.execute("""CREATE TABLE IF NOT EXISTS estudio_ejemplos (
            id TEXT PRIMARY KEY, usuario TEXT NOT NULL, nombre TEXT NOT NULL, clasificacion TEXT NOT NULL,
            fundamento TEXT NOT NULL DEFAULT '', nombre_archivo TEXT NOT NULL DEFAULT '', storage_key TEXT NOT NULL DEFAULT '',
            texto_extraido TEXT NOT NULL DEFAULT '', activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.commit()


def _rows(sql_pg, sql_sq, params=()):
    asegurar_tablas()
    if _usa_pg():
        from psycopg2.extras import RealDictCursor
        with closing(_pg_conn()) as db:
            with db.cursor(cursor_factory=RealDictCursor) as c:
                c.execute(sql_pg, params)
                return [dict(x) for x in c.fetchall()]
    with closing(sqlite3.connect(DB_FILE)) as db:
        db.row_factory = sqlite3.Row
        return [dict(x) for x in db.execute(sql_sq, params).fetchall()]


def _one(sql_pg, sql_sq, params=()):
    rows = _rows(sql_pg, sql_sq, params)
    return rows[0] if rows else None


def crear_lote(usuario: str, titulo: str = "") -> str:
    asegurar_tablas(); lote_id = uuid.uuid4().hex
    if _usa_pg():
        with closing(_pg_conn()) as db:
            with db.cursor() as c:
                c.execute("INSERT INTO estudio_lotes(id,usuario,titulo) VALUES(%s,%s,%s)", (lote_id, usuario, titulo[:220]))
            db.commit()
    else:
        with closing(sqlite3.connect(DB_FILE)) as db:
            db.execute("INSERT INTO estudio_lotes(id,usuario,titulo) VALUES(?,?,?)", (lote_id, usuario, titulo[:220])); db.commit()
    return lote_id


def obtener_lote(lote_id: str, usuario: str):
    return _one(
        "SELECT * FROM estudio_lotes WHERE id=%s AND usuario=%s",
        "SELECT * FROM estudio_lotes WHERE id=? AND usuario=?", (lote_id, usuario))


def listar_lotes(usuario: str, limite: int = 20):
    return _rows(
        "SELECT l.*, COUNT(c.id) AS cantidad FROM estudio_lotes l LEFT JOIN estudio_casos c ON c.lote_id=l.id WHERE l.usuario=%s GROUP BY l.id ORDER BY l.creado_en DESC LIMIT %s",
        "SELECT l.*, COUNT(c.id) AS cantidad FROM estudio_lotes l LEFT JOIN estudio_casos c ON c.lote_id=l.id WHERE l.usuario=? GROUP BY l.id ORDER BY l.creado_en DESC LIMIT ?", (usuario, limite))


def guardar_archivo_pdf(datos: bytes, usuario: str, prefijo: str, nombre_archivo: str) -> str:
    key = f"estudio/{usuario}/{prefijo}/{uuid.uuid4().hex}_{_seguro_nombre(nombre_archivo)}"
    if _r2_configurado():
        r2_subir_pdf(io.BytesIO(datos), key, len(datos))
        return "r2:" + key
    rel = key.replace("/", "__")
    path = LOCAL_DIR / rel
    path.write_bytes(datos)
    return "local:" + rel


def ruta_archivo(storage_key: str) -> Path:
    if storage_key.startswith("r2:"):
        return descargar_pdf_temporal(storage_key[3:])
    if storage_key.startswith("local:"):
        return LOCAL_DIR / storage_key[6:]
    raise RuntimeError("Referencia de archivo de Estudio inválida.")


def borrar_archivo(storage_key: str) -> None:
    try:
        if storage_key.startswith("r2:"):
            r2_eliminar_pdf(storage_key[3:])
        elif storage_key.startswith("local:"):
            (LOCAL_DIR / storage_key[6:]).unlink(missing_ok=True)
    except Exception:
        pass


def _seguro_nombre(nombre: str) -> str:
    nombre = re.sub(r"[^A-Za-z0-9._-]+", "_", nombre or "documento.pdf")
    return nombre[-180:] or "documento.pdf"


def extraer_texto_pdf(datos: bytes, max_chars: int = 32000) -> str:
    partes, total = [], 0
    try:
        doc = fitz.open(stream=datos, filetype="pdf")
        try:
            for i in range(min(doc.page_count, 80)):
                if total >= max_chars: break
                t = (doc.load_page(i).get_text("text", sort=True) or "").strip()
                if t:
                    t = t[: max_chars-total]
                    partes.append(f"PÁGINA {i+1}\n{t}")
                    total += len(t)
        finally:
            doc.close()
    except Exception:
        return ""
    return "\n\n".join(partes)


def crear_ejemplo(usuario: str, nombre: str, clasificacion: str, fundamento: str, pdf_bytes: bytes | None, nombre_archivo: str = ""):
    asegurar_tablas(); clasificacion = _normalizar_clasificacion(clasificacion); ej_id = uuid.uuid4().hex
    storage_key = ""; texto = ""
    if pdf_bytes:
        storage_key = guardar_archivo_pdf(pdf_bytes, usuario, "ejemplos", nombre_archivo or "ejemplo.pdf")
        texto = extraer_texto_pdf(pdf_bytes, 24000)
    vals = (ej_id, usuario, (nombre or nombre_archivo or "Ejemplo")[:250], clasificacion, fundamento[:12000], nombre_archivo[:255], storage_key, texto[:30000])
    if _usa_pg():
        with closing(_pg_conn()) as db:
            with db.cursor() as c:
                c.execute("INSERT INTO estudio_ejemplos(id,usuario,nombre,clasificacion,fundamento,nombre_archivo,storage_key,texto_extraido) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", vals)
            db.commit()
    else:
        with closing(sqlite3.connect(DB_FILE)) as db:
            db.execute("INSERT INTO estudio_ejemplos(id,usuario,nombre,clasificacion,fundamento,nombre_archivo,storage_key,texto_extraido) VALUES(?,?,?,?,?,?,?,?)", vals); db.commit()
    return obtener_ejemplo(ej_id, usuario)


def listar_ejemplos(usuario: str):
    return _rows(
        "SELECT id,nombre,clasificacion,fundamento,nombre_archivo,activo,creado_en FROM estudio_ejemplos WHERE usuario=%s ORDER BY creado_en DESC",
        "SELECT id,nombre,clasificacion,fundamento,nombre_archivo,activo,creado_en FROM estudio_ejemplos WHERE usuario=? ORDER BY creado_en DESC", (usuario,))


def obtener_ejemplo(ej_id: str, usuario: str):
    return _one("SELECT * FROM estudio_ejemplos WHERE id=%s AND usuario=%s", "SELECT * FROM estudio_ejemplos WHERE id=? AND usuario=?", (ej_id, usuario))


def eliminar_ejemplo(ej_id: str, usuario: str) -> bool:
    ej = obtener_ejemplo(ej_id, usuario)
    if not ej: return False
    if _usa_pg():
        with closing(_pg_conn()) as db:
            with db.cursor() as c: c.execute("DELETE FROM estudio_ejemplos WHERE id=%s AND usuario=%s", (ej_id, usuario))
            db.commit()
    else:
        with closing(sqlite3.connect(DB_FILE)) as db:
            db.execute("DELETE FROM estudio_ejemplos WHERE id=? AND usuario=?", (ej_id, usuario)); db.commit()
    if ej.get("storage_key"): borrar_archivo(ej["storage_key"])
    return True


def _ejemplos_prompt(usuario: str, limite: int = 18) -> str:
    rows = _rows(
        "SELECT nombre,clasificacion,fundamento,texto_extraido FROM estudio_ejemplos WHERE usuario=%s AND activo=TRUE ORDER BY creado_en DESC LIMIT %s",
        "SELECT nombre,clasificacion,fundamento,texto_extraido FROM estudio_ejemplos WHERE usuario=? AND activo=1 ORDER BY creado_en DESC LIMIT ?", (usuario, limite))
    if not rows: return "No hay ejemplos humanos validados cargados todavía."
    out=[]
    for i,e in enumerate(rows,1):
        fuente=(e.get("texto_extraido") or "")[:3500]
        out.append(f"EJEMPLO {i} — {e.get('nombre')} — CLASIFICACIÓN HUMANA: {e.get('clasificacion')}\nFUNDAMENTO HUMANO: {e.get('fundamento') or 'Sin fundamento cargado.'}\nEXTRACTO DOCUMENTAL:\n{fuente or 'Sin texto extraíble.'}")
    return "\n\n".join(out)


def _normalizar_clasificacion(valor: str) -> str:
    v = str(valor or "").upper().replace(" ", "_").replace("-", "_")
    aliases={"SI":"TOMAR","SÍ":"TOMAR","BUENO":"TOMAR","NO":"NO_TOMAR","MALO":"NO_TOMAR","DUDOSO":"REVISAR","INCOMPLETOS":"INCOMPLETO"}
    v=aliases.get(v,v)
    return v if v in CLASIFICACIONES else "REVISAR"


def _guardar_caso_registro(usuario: str, lote_id: str, nombre_archivo: str, storage_key: str, tamano: int, data: dict) -> dict:
    clasificacion = _normalizar_clasificacion(data.get("clasificacion"))
    data["clasificacion"] = clasificacion
    confianza = data.get("confianza", 0)
    try: confianza = max(0, min(100, int(float(confianza))))
    except Exception: confianza = 0
    data["confianza"] = confianza
    caso_id = uuid.uuid4().hex
    titulo = str(data.get("titulo") or nombre_archivo)[:250]
    resumen = str(data.get("resumen") or "")[:20000]
    motivo = str(data.get("motivo") or "")[:20000]
    normas = data.get("normas_relevantes") if isinstance(data.get("normas_relevantes"), list) else []
    vals=(caso_id,lote_id,usuario,nombre_archivo[:255],storage_key,tamano,clasificacion,titulo,resumen,motivo,json.dumps(data,ensure_ascii=False),json.dumps(normas,ensure_ascii=False),confianza)
    if _usa_pg():
        with closing(_pg_conn()) as db:
            with db.cursor() as c:
                c.execute("INSERT INTO estudio_casos(id,lote_id,usuario,nombre_archivo,storage_key,tamano,clasificacion,titulo,resumen,motivo,datos_json,normas_json,confianza) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", vals)
            db.commit()
    else:
        with closing(sqlite3.connect(DB_FILE)) as db:
            db.execute("INSERT INTO estudio_casos(id,lote_id,usuario,nombre_archivo,storage_key,tamano,clasificacion,titulo,resumen,motivo,datos_json,normas_json,confianza) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", vals); db.commit()
    return caso_publico(obtener_caso(caso_id, usuario))


def _caso_incompleto_por_error(usuario: str, lote_id: str, nombre_archivo: str, storage_key: str, tamano: int, detalle: str) -> dict:
    data = {
        "clasificacion": "INCOMPLETO",
        "titulo": nombre_archivo,
        "resumen": "El PDF fue conservado, pero el análisis automático no pudo completarse.",
        "motivo": detalle,
        "hechos_documentados": [], "inferencias": [], "contacto": {}, "fecha_hecho": "", "lugar": "",
        "vehiculos": [], "companias": [], "numero_siniestro": "", "numero_poliza": "", "lesiones": [], "danos": [],
        "documentacion_detectada": [nombre_archivo], "documentacion_faltante": ["Reintentar el análisis automático o revisar manualmente."],
        "puntos_favorables": [], "puntos_desfavorables": [], "mecanica": "No analizada.",
        "criterio_juridico": "No evaluado por error técnico.", "normas_relevantes": [],
        "evaluacion_economica": "No evaluada.", "preguntas_para_llamada": [], "confianza": 0,
    }
    return _guardar_caso_registro(usuario, lote_id, nombre_archivo, storage_key, tamano, data)


def analizar_pdf(usuario: str, lote_id: str, nombre_archivo: str, datos_pdf: bytes) -> dict:
    if not obtener_lote(lote_id, usuario):
        raise ValueError("El lote de Estudio no existe.")
    if not datos_pdf or len(datos_pdf) < 100:
        raise ValueError("El PDF está vacío o dañado.")
    if len(datos_pdf) > 25 * 1024 * 1024:
        raise ValueError("Cada PDF puede pesar hasta 25 MB.")

    storage_key = guardar_archivo_pdf(datos_pdf, usuario, lote_id, nombre_archivo)
    texto_local = extraer_texto_pdf(datos_pdf, 26000)
    ejemplos = _ejemplos_prompt(usuario)
    cliente = obtener_cliente_gemini()
    if cliente is None:
        return _caso_incompleto_por_error(usuario, lote_id, nombre_archivo, storage_key, len(datos_pdf), "Gemini no está configurado en el servidor.")

    hoy = datetime.now().strftime("%d/%m/%Y")
    prompt = f"""
MODO ESTUDIO — ANÁLISIS PRELIMINAR DE RECLAMOS DE DAMNIFICADOS

Actuás como analista documental y de preclasificación del módulo ESTUDIO de OficinaIA para un estudio que evalúa potenciales reclamos de terceros/damnificados, principalmente por siniestros de tránsito en Argentina y especialmente en Provincia de Buenos Aires.
Fecha de análisis: {hoy}.

PERSPECTIVA OBLIGATORIA
- El estudio NO representa automáticamente al asegurado, conductor denunciado ni compañía que aparece en el PDF.
- Identificá primero quién sufrió el daño y podría ser el potencial reclamante/damnificado que el estudio podría representar.
- Si el PDF es una denuncia confeccionada por el asegurado, tratala como fuente documental y como versión de una parte. NO adoptes su defensa como objetivo del análisis.
- Identificá contra quién podría reclamar el damnificado, qué aseguradora interviene y qué fortalezas, obstáculos, prueba y documentación tendría un eventual reclamo.
- "A favor" y "En contra" SIEMPRE significan a favor o en contra de la viabilidad del eventual reclamo del damnificado, nunca de la defensa del asegurado/aseguradora salvo pedido expreso.

OBJETIVO
Leer el PDF completo, extraer los datos útiles y producir un TRIAGE PRELIMINAR que permita decidir rápidamente si el caso merece atención humana. No reemplazás la decisión de un abogado.

CLASIFICÁ ÚNICAMENTE EN:
- TOMAR: hay un potencial damnificado identificable y elementos suficientemente concretos para avanzar con contacto/revisión.
- REVISAR: puede existir una oportunidad, pero faltan elementos relevantes o hay responsabilidad, prueba, cobertura o conveniencia que requiere criterio humano.
- NO_TOMAR: existen razones suficientemente importantes y documentadas para no continuar según los criterios disponibles del estudio. No uses esta categoría por una duda menor o un faltante subsanable.
- INCOMPLETO: el documento no contiene realmente un siniestro/reclamo analizable o falta información esencial para evaluarlo.

CRITERIO DE ANÁLISIS
1. Separá internamente HECHOS DOCUMENTADOS, VERSIONES DE LAS PARTES e INFERENCIAS. No conviertas una declaración unilateral en un hecho objetivo.
2. Reconstruí la mecánica con lo que realmente surge del documento: prioridad, intersección, giro, alcance, maniobras, señalización, punto de impacto, peatones/ciclistas, etc. No inventes datos.
3. Evaluá la responsabilidad de forma preliminar desde la perspectiva del eventual reclamo del damnificado. Si es discutible, decilo y explicá qué prueba podría cambiar el análisis.
4. Responsabilidad probable y conveniencia de tomar el caso NO son sinónimos. Considerá también lesiones/daños, prueba, documentación, contraparte y aseguradora identificables, y viabilidad práctica/económica.
5. En lesiones y dinero no inventes diagnósticos, incapacidad ni montos. Si solo se informa una lesión sin respaldo médico, indicá que está pendiente de acreditación documental.
6. Podés considerar normativa argentina/provincial que conozcas, pero no inventes artículos, fallos ni jurisprudencia. Si no hay seguridad, indicá "requiere verificación jurídica".
7. Los EJEMPLOS INTERNOS fueron validados por humanos y sirven para aprender el criterio operativo del estudio. Usalos como antecedentes comparativos, no como jurisprudencia ni reglas universales. Nunca conviertas una conclusión previa tuya en antecedente válido sin validación humana.
8. Extraé todos los datos útiles visibles para identificar/contactar el caso: potencial damnificado, contraparte, nombres, DNI/CUIT, teléfonos, emails, domicilios, vehículos, patentes, aseguradoras, póliza, número de siniestro, fecha, hora y lugar.
9. El RESUMEN y MOTIVO deben ser breves y útiles. Evitá repetir la misma información en múltiples campos. La interfaz debe poder mostrar una lectura compacta del caso sin obligar a recorrer un informe largo.

EJEMPLOS INTERNOS VALIDADOS:
{ejemplos}

Devolvé SOLO JSON válido con estas claves exactas:
clasificacion, titulo, resumen, motivo, hechos_documentados, inferencias, contacto, fecha_hecho, lugar, vehiculos, companias, numero_siniestro, numero_poliza, lesiones, danos, documentacion_detectada, documentacion_faltante, puntos_favorables, puntos_desfavorables, mecanica, criterio_juridico, normas_relevantes, evaluacion_economica, preguntas_para_llamada, confianza.
Los campos de lista deben ser arrays. contacto debe ser objeto. confianza debe ser entero 0..100.
Mantené hechos_documentados, inferencias, puntos_favorables, puntos_desfavorables, faltantes y preguntas concisos: solo elementos que cambien la comprensión o decisión del caso.
"""

    partes = [types.Part.from_text(text=prompt), types.Part.from_bytes(data=datos_pdf, mime_type="application/pdf")]
    # Cada caso de Estudio es una operación independiente: comparte la misma
    # infraestructura de Gemini, pero no estado de ejecución con otro caso.
    begin_request()
    ultimo = None; respuesta = None
    try:
        respuesta, _modelo_usado = generate_with_fallback(
            client=cliente,
            models=DEFAULT_MODELS,
            contents=partes,
            config=types.GenerateContentConfig(temperature=0.05, max_output_tokens=6000, response_mime_type="application/json"),
            log_prefix="GEMINI /ESTUDIO",
        )
    except Exception as e:
        ultimo = e
    if respuesta is None:
        return _caso_incompleto_por_error(usuario, lote_id, nombre_archivo, storage_key, len(datos_pdf), "Gemini no estuvo disponible para completar el análisis. Reintentar este caso.")

    raw = (getattr(respuesta, "text", None) or "").strip()
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return _caso_incompleto_por_error(usuario, lote_id, nombre_archivo, storage_key, len(datos_pdf), "La respuesta de Gemini no pudo estructurarse. Reintentar este caso.")
        data = json.loads(m.group(0))

    return _guardar_caso_registro(usuario, lote_id, nombre_archivo, storage_key, len(datos_pdf), data)


def obtener_caso(caso_id: str, usuario: str):
    return _one("SELECT * FROM estudio_casos WHERE id=%s AND usuario=%s", "SELECT * FROM estudio_casos WHERE id=? AND usuario=?", (caso_id, usuario))


def listar_casos(lote_id: str, usuario: str):
    return [caso_publico(x) for x in _rows(
        "SELECT * FROM estudio_casos WHERE lote_id=%s AND usuario=%s ORDER BY creado_en,id",
        "SELECT * FROM estudio_casos WHERE lote_id=? AND usuario=? ORDER BY creado_en,id", (lote_id, usuario))]


def caso_publico(row: dict | None):
    if not row: return None
    d=dict(row)
    try: datos=json.loads(d.get("datos_json") or "{}")
    except Exception: datos={}
    d["datos"] = datos; d.pop("datos_json",None); d.pop("normas_json",None); d.pop("storage_key",None)
    if hasattr(d.get("creado_en"), "isoformat"): d["creado_en"] = d["creado_en"].isoformat()
    return d


def reclasificar_caso(caso_id: str, usuario: str, clasificacion: str):
    clasificacion = _normalizar_clasificacion(clasificacion)
    if _usa_pg():
        with closing(_pg_conn()) as db:
            with db.cursor() as c: c.execute("UPDATE estudio_casos SET clasificacion=%s WHERE id=%s AND usuario=%s", (clasificacion,caso_id,usuario)); ok=c.rowcount>0
            db.commit()
    else:
        with closing(sqlite3.connect(DB_FILE)) as db:
            cur=db.execute("UPDATE estudio_casos SET clasificacion=? WHERE id=? AND usuario=?", (clasificacion,caso_id,usuario)); ok=cur.rowcount>0; db.commit()
    return caso_publico(obtener_caso(caso_id,usuario)) if ok else None


def _fmt(v):
    if v is None or v == "" or v == [] or v == {}: return "No surge de la documentación."
    if isinstance(v, list): return "\n".join(f"  • {x}" for x in v) if v else "No surge de la documentación."
    if isinstance(v, dict): return "\n".join(f"  {k}: {val}" for k,val in v.items() if val not in (None,"",[])) or "No surge de la documentación."
    return str(v)


def construir_txt(lote: dict, casos: list[dict]) -> str:
    counts={c:0 for c in CLASIFICACIONES}
    for c in casos: counts[c.get("clasificacion","REVISAR")]=counts.get(c.get("clasificacion","REVISAR"),0)+1
    lineas=[
        "OFICINAIA · ESTUDIO — INFORME DE TRIAGE DE SINIESTROS",
        "="*68,
        f"Lote: {lote.get('titulo') or lote.get('id')}",
        f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Total de PDFs analizados: {len(casos)}",
        f"TOMAR: {counts.get('TOMAR',0)} | REVISAR: {counts.get('REVISAR',0)} | NO TOMAR: {counts.get('NO_TOMAR',0)} | INCOMPLETOS: {counts.get('INCOMPLETO',0)}",
        "",
        "IMPORTANTE: este informe es un triage preliminar asistido por IA. No reemplaza la revisión ni el criterio profesional del letrado. Los hechos documentados se distinguen de las inferencias y las normas no verificadas deben controlarse antes de usarse profesionalmente.",
        "",
    ]
    for i,c in enumerate(casos,1):
        d=c.get("datos") or {}
        lineas += [
            "#"*68,
            f"CASO {i:03d} — {c.get('clasificacion')}",
            f"Archivo original: {c.get('nombre_archivo')}",
            f"Título: {c.get('titulo') or c.get('nombre_archivo')}",
            f"Confianza del triage: {c.get('confianza',0)}%",
            "",
            "RESUMEN", _fmt(d.get("resumen") or c.get("resumen")), "",
            "POR QUÉ FUE CLASIFICADO ASÍ", _fmt(d.get("motivo") or c.get("motivo")), "",
            "INFORMACIÓN DE CONTACTO / IDENTIFICACIÓN", _fmt(d.get("contacto")),
            f"Número de siniestro: {_fmt(d.get('numero_siniestro'))}",
            f"Número de póliza: {_fmt(d.get('numero_poliza'))}",
            f"Compañía(s): {_fmt(d.get('companias'))}",
            f"Vehículo(s): {_fmt(d.get('vehiculos'))}",
            f"Fecha del hecho: {_fmt(d.get('fecha_hecho'))}",
            f"Lugar: {_fmt(d.get('lugar'))}", "",
            "HECHOS DOCUMENTADOS", _fmt(d.get("hechos_documentados")), "",
            "MECÁNICA", _fmt(d.get("mecanica")), "",
            "INFERENCIAS / PUNTOS A VERIFICAR", _fmt(d.get("inferencias")), "",
            "PUNTOS FAVORABLES", _fmt(d.get("puntos_favorables")), "",
            "PUNTOS DESFAVORABLES", _fmt(d.get("puntos_desfavorables")), "",
            "LESIONES", _fmt(d.get("lesiones")), "",
            "DAÑOS", _fmt(d.get("danos")), "",
            "DOCUMENTACIÓN DETECTADA", _fmt(d.get("documentacion_detectada")), "",
            "DOCUMENTACIÓN / INFORMACIÓN FALTANTE", _fmt(d.get("documentacion_faltante")), "",
            "CRITERIO JURÍDICO PRELIMINAR", _fmt(d.get("criterio_juridico")), "",
            "NORMAS / PRINCIPIOS MENCIONADOS", _fmt(d.get("normas_relevantes")), "",
            "EVALUACIÓN ECONÓMICA PRELIMINAR", _fmt(d.get("evaluacion_economica")), "",
            "PREGUNTAS SUGERIDAS PARA LA LLAMADA", _fmt(d.get("preguntas_para_llamada")), "",
        ]
    return "\n".join(lineas)


def generar_zip_lote(lote_id: str, usuario: str, solo: str | None = None) -> Path:
    lote=obtener_lote(lote_id, usuario)
    if not lote: raise ValueError("Lote inexistente.")
    casos=listar_casos(lote_id, usuario)
    if solo:
        solo=_normalizar_clasificacion(solo); casos=[c for c in casos if c.get("clasificacion")==solo]
    tmp=Path(tempfile.mkstemp(prefix="oficinaia_estudio_",suffix=".zip")[1])
    raiz = "ESTUDIO_ANALISIS" if not solo else f"ESTUDIO_{solo}"
    with zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{raiz}/RESUMEN_ANALISIS.txt", construir_txt(lote,casos).encode("utf-8-sig"))
        usados={}
        for c in casos:
            full=obtener_caso(c["id"],usuario)
            carpeta=CARPETAS_CLASIFICACION.get(c.get("clasificacion"),"REVISAR")
            base=_seguro_nombre(c.get("nombre_archivo") or "documento.pdf")
            k=(carpeta,base); usados[k]=usados.get(k,0)+1
            if usados[k]>1:
                stem,suf=Path(base).stem,Path(base).suffix
                base=f"{stem}_{usados[k]}{suf}"
            z.write(ruta_archivo(full["storage_key"]), arcname=f"{raiz}/{carpeta}/{base}")
    return tmp
