from pathlib import Path
import os
import re
import unicodedata
import fitz

from database_pg import listar_manuales, listar_polizas as pg_listar_polizas
from storage_r2 import descargar_pdf_temporal
from companias import nombre_compania, aliases_companias

BASE_DIR = Path(__file__).resolve().parent
DOCUMENTOS_DIR = BASE_DIR / "documentos"

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

MANUALES_MAX_CANDIDATOS_GENERAL = int(os.getenv("MANUALES_MAX_CANDIDATOS_GENERAL", "12"))
MANUALES_MAX_CANDIDATOS_CIA = int(os.getenv("MANUALES_MAX_CANDIDATOS_CIA", "10"))
MANUALES_MAX_ARCHIVOS_CON_CIA = int(os.getenv("MANUALES_MAX_ARCHIVOS_CON_CIA", "6"))
MANUALES_MAX_ARCHIVOS_GENERAL = int(os.getenv("MANUALES_MAX_ARCHIVOS_GENERAL", "3"))

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

def _companias_mencionadas_local(texto):
    """Detecta compañías sin depender de servicios_ia ni Flask."""
    norm = _normalizar_busqueda(texto)
    compact = re.sub(r"[^a-z0-9]+", "", norm)
    salida = set()
    for alias, (_codigo, display) in aliases_companias().items():
        alias_norm = _normalizar_busqueda(alias)
        if not alias_norm:
            continue
        if len(alias_norm) <= 3:
            if re.search(rf"\b{re.escape(alias_norm)}\b", norm):
                salida.add(display)
        elif re.search(rf"\b{re.escape(alias_norm)}\b", norm):
            salida.add(display)
        elif re.sub(r"[^a-z0-9]+", "", alias_norm) in compact:
            salida.add(display)
    return salida

# ==========================================================
# EXTRACCIÓN Y RETRIEVAL DE PDF
# ==========================================================

# Límites de memoria para Render.
MAX_PDF_PAGES_INDEX = 80
MAX_PDF_TEXT_CHARS_INDEX = 120_000
MAX_PDF_FILE_SIZE_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES_CHAT = 30
MAX_PDF_TEXT_CHARS_CHAT = 40_000

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
    Extrae texto de un PDF de forma controlada para Render.
    Usa PyMuPDF en lugar de pypdf porque consume menos memoria en PDFs
    complejos. No conserva todos los PDFs procesados en una caché global.
    """
    ruta = Path(ruta)
    try:
        if not ruta.exists() or not ruta.is_file():
            return []
        if ruta.stat().st_size > MAX_PDF_FILE_SIZE_BYTES:
            print(f"PDF OMITIDO POR TAMAÑO: {ruta}")
            return []
    except OSError:
        return []

    paginas = []
    total_chars = 0

    try:
        documento = fitz.open(str(ruta))
        try:
            total_paginas = min(documento.page_count, MAX_PDF_PAGES_INDEX)

            for indice in range(total_paginas):
                if total_chars >= MAX_PDF_TEXT_CHARS_INDEX:
                    break

                try:
                    pagina = documento.load_page(indice)
                    contenido = pagina.get_text("text", sort=True) or ""
                    # Liberamos la referencia de página inmediatamente.
                    del pagina
                except Exception as error:
                    print(
                        f"ERROR EXTRAYENDO PÁGINA {indice + 1} DE PDF {ruta}: {error}"
                    )
                    continue

                contenido = re.sub(r"[ \t]+", " ", contenido)
                contenido = re.sub(r"\n{3,}", "\n\n", contenido).strip()

                if not contenido:
                    continue

                restante = MAX_PDF_TEXT_CHARS_INDEX - total_chars
                if len(contenido) > restante:
                    contenido = contenido[:restante]

                if contenido:
                    paginas.append({
                        "pagina": indice + 1,
                        "texto": contenido
                    })
                    total_chars += len(contenido)

        finally:
            documento.close()

        if not paginas:
            print(
                f"PDF SIN TEXTO EXTRAÍBLE: {ruta}. "
                "Si es un PDF escaneado, necesita OCR para poder consultarse."
            )

    except Exception as error:
        print("ERROR LEYENDO PDF CON PYMUPDF:", ruta, error)
        paginas = []

    return paginas

def extraer_texto_pdf(ruta):
    """Compatibilidad con las funciones existentes que necesitan texto completo."""
    return "\n\n".join(p["texto"] for p in extraer_paginas_pdf(ruta))


def extraer_texto_pdf_bytes(datos, max_paginas=25, max_chars=25_000):
    """Extrae texto desde bytes de un PDF (upload en memoria). P1.7 / Tanda B."""
    if not datos:
        return ""
    paginas = []
    total = 0
    try:
        documento = fitz.open(stream=datos, filetype="pdf")
        try:
            n = min(documento.page_count, max_paginas)
            for i in range(n):
                if total >= max_chars:
                    break
                try:
                    pagina = documento.load_page(i)
                    contenido = pagina.get_text("text", sort=True) or ""
                    del pagina
                except Exception:
                    continue
                contenido = re.sub(r"[ \t]+", " ", contenido)
                contenido = re.sub(r"\n{3,}", "\n\n", contenido).strip()
                if not contenido:
                    continue
                restante = max_chars - total
                if len(contenido) > restante:
                    contenido = contenido[:restante]
                paginas.append(contenido)
                total += len(contenido)
        finally:
            documento.close()
    except Exception as error:
        print("ERROR extraer_texto_pdf_bytes:", error)
        return ""
    return "\n\n".join(paginas)


def _proponer_ficha_desde_manual(texto, compania="", nombre_archivo=""):
    """
    Arma una ficha sugerida a partir del texto de un manual/póliza (P1.7).
    Heurística léxica: prioriza remolque/asistencia/cobertura/límites.
    No usa LLM (latencia/costo). El humano confirma antes de guardar.
    """
    texto = (texto or "").strip()
    if not texto or len(texto) < 40:
        return None

    compania = (compania or "").strip()
    nombre = (nombre_archivo or "").strip()
    if nombre.lower().endswith(".pdf"):
        nombre = nombre[:-4]

    lineas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    keywords = (
        "remolque", "grúa", "grua", "asistencia", "auxilio", "cobertura",
        "límite", "limite", "franquicia", "terceros", "all risk", "casco",
        "km", "kilómetro", "kilometro", "servicio", "exclusión", "exclusion",
        "suma asegurada", "deducible", "responsabilidad civil",
    )
    bullets = []
    vistos = set()
    for ln in lineas:
        low = ln.lower()
        if any(k in low for k in keywords):
            if len(ln) < 12 or len(ln) > 400:
                continue
            clave = re.sub(r"\s+", " ", low)[:120]
            if clave in vistos:
                continue
            vistos.add(clave)
            bullets.append("• " + ln)
            if len(bullets) >= 18:
                break

    if not bullets:
        for ln in lineas:
            if len(ln) < 20 or len(ln) > 300:
                continue
            if re.match(r"^(página|page|confidential|www\.|http)", ln, re.I):
                continue
            bullets.append("• " + ln)
            if len(bullets) >= 10:
                break

    if not bullets:
        return None

    if compania:
        titulo = f"{compania} — {nombre}" if nombre else f"Manual {compania}"
    else:
        titulo = nombre or "Ficha desde manual"
    titulo = titulo[:200]

    cuerpo_parts = []
    if compania:
        cuerpo_parts.append(f"Compañía: {compania}")
    if nombre:
        cuerpo_parts.append(f"Fuente: {nombre}.pdf")
    cuerpo_parts.append("")
    cuerpo_parts.append("Extracto operativo (revisar y completar):")
    cuerpo_parts.extend(bullets)
    cuerpo = "\n".join(cuerpo_parts)
    if len(cuerpo) > 12000:
        cuerpo = cuerpo[:12000] + "\n\n[Texto recortado por longitud]"

    return {"titulo": titulo, "contenido": cuerpo}


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


def _manuales_r2_por_ruta(consulta="", max_manuales=None):
    """
    Prepara una cantidad acotada de manuales R2 por consulta.

    Si la consulta menciona una compañía, primero se restringe el universo a
    los manuales de esa compañía usando el mismo detector de aliases que usa
    servicios_ia._companias_mencionadas(). Recién después se aplica el orden
    por nombre. Si no hay compañía explícita, se conserva el filtro por nombre
    para no descargar todo R2 en cada request.

    Con compañía identificada se prioriza cobertura completa de ese universo;
    el límite opcional sólo se usa si se configura explícitamente y es mayor
    que cero. Esto aumenta la lectura de PDFs de una compañía, pero evita que
    un manual correcto quede fuera por el nombre de archivo y mantiene el
    universo de trabajo controlado frente a un barrido global.
    """
    mapa = {}
    try:
        manuales = listar_manuales()

        # Detector local: DocumentSearch no depende de Sofia ni de Flask.
        companias_detectadas = _companias_mencionadas_local(consulta)

        slug_por_canon = {
            "mercantil andina": "mercantil_andina",
            "mercantilandina": "mercantil_andina",
            "federacion patronal": "federacion_patronal",
            "federacion": "federacion_patronal",
            "atm": "atm",
            "san cristobal": "san_cristobal",
            "sancristobal": "san_cristobal",
            "rivadavia": "rivadavia",
            "euroamerica": "euroamerica",
            "euro america": "euroamerica",
            "agrosalta": "agrosalta",
            "ags": "agrosalta",
            "triunfo": "triunfo",
            "prof": "prof",
        }

        # Algunos aliases del detector tienen una forma compacta distinta
        # (ej. "mercantilandina"). Se resuelven contra la misma compañía.
        slug_companias = set()
        for canon in companias_detectadas:
            canon_norm = _normalizar_busqueda(canon)
            slug = slug_por_canon.get(canon_norm)
            if slug:
                slug_companias.add(slug)
                continue
            compact = re.sub(r"[^a-z0-9]+", "", canon_norm)
            for nombre, slug_candidato in slug_por_canon.items():
                if compact == re.sub(r"[^a-z0-9]+", "", nombre):
                    slug_companias.add(slug_candidato)
                    break

        candidatos = []
        for fila in manuales:
            nombre = str(fila.get("nombre") or "")
            r2_key = str(fila.get("r2_key") or "")
            if not r2_key:
                continue

            partes = r2_key.split("/")
            slug = partes[1] if len(partes) > 1 else ""

            if slug_companias:
                # Con compañía explícita, los manuales de otras compañías no
                # compiten en absoluto por el contexto final.
                if slug not in slug_companias:
                    continue
                score = 0
            else:
                texto_nombre = _normalizar_busqueda(f"{nombre} {r2_key}")
                tokens = set(_tokens_busqueda(consulta))
                score = sum(1 for token in tokens if token in texto_nombre)

            candidatos.append((score, nombre, fila))

        candidatos.sort(key=lambda x: (x[0], x[1].lower()), reverse=True)

        if slug_companias:
            # Si la compañía está identificada, por defecto se revisan todos
            # sus manuales. Sólo un límite > 0 impuesto por configuración
            # reduce ese universo de forma explícita. 0 o None = sin tope.
            limite = max_manuales
            if limite is None:
                limite = MANUALES_MAX_CANDIDATOS_CIA
            seleccion = candidatos if not limite else candidatos[:limite]
        else:
            limite = max_manuales
            if limite is None:
                limite = MANUALES_MAX_CANDIDATOS_GENERAL
            seleccion = candidatos[:max(0, limite)]

        for score, _, fila in seleccion:
            r2_key = str(fila.get("r2_key") or "")
            try:
                path = descargar_pdf_temporal(r2_key)
            except Exception as error:
                print(f"ERROR PREPARANDO MANUAL R2 {r2_key}: {error}")
                continue

            mapa[str(path.resolve())] = fila

    except Exception as error:
        print("ERROR CONSULTANDO MANUALES R2:", error)

    return mapa


def _polizas_r2_por_ruta(consulta="", max_polizas=8):
    """
    Descarga a caché temporal una cantidad acotada de pólizas de R2,
    priorizadas por coincidencia de nombre con la consulta, para que
    buscar_en_documentos() pueda indexarlas igual que a los manuales.
    """
    mapa = {}
    try:
        polizas = pg_listar_polizas()
        tokens = set(_tokens_busqueda(consulta))

        candidatos = []
        for fila in polizas:
            nombre = str(fila.get("nombre") or "")
            r2_key = str(fila.get("r2_key") or "")
            if not r2_key:
                continue
            texto_nombre = _normalizar_busqueda(nombre)
            score = sum(1 for token in tokens if token in texto_nombre)
            candidatos.append((score, nombre, fila))

        candidatos.sort(key=lambda x: (x[0], x[1].lower()), reverse=True)
        limite = max_polizas if max_polizas else len(candidatos)
        seleccion = candidatos[:max(0, limite)]

        for score, _, fila in seleccion:
            r2_key = str(fila.get("r2_key") or "")
            try:
                path = descargar_pdf_temporal(r2_key)
            except Exception as error:
                print(f"ERROR PREPARANDO POLIZA R2 {r2_key}: {error}")
                continue
            mapa[str(path.resolve())] = fila

    except Exception as error:
        print("ERROR CONSULTANDO POLIZAS R2:", error)

    return mapa


def buscar_en_documentos(consulta, limite=16):
    """
    Recuperación por relevancia de PDFs.

    - Con compañía identificada, primero se acota R2 a esa compañía y se
      permite que compitan hasta MANUALES_MAX_ARCHIVOS_CON_CIA archivos.
    - Sin compañía identificada, se conserva un tope menor para no disparar
      descargas, memoria y costo en Render.
    - La cantidad total de fragmentos sigue limitada por ``limite`` y cada
      archivo conserva su máximo de 4/8 fragmentos según complejidad.
    """
    resultados = []
    tokens = _tokens_busqueda(consulta)

    if not tokens:
        return resultados

    companias_detectadas = _companias_mencionadas_local(consulta)

    r2_por_ruta = _manuales_r2_por_ruta(consulta)
    r2_por_ruta.update(_polizas_r2_por_ruta(consulta))

    archivos_locales = []
    if DOCUMENTOS_DIR.exists():
        archivos_locales.extend(
            p for p in DOCUMENTOS_DIR.rglob("*.pdf") if p.is_file()
        )

    archivos = archivos_locales + [Path(ruta) for ruta in r2_por_ruta]
    cantidad_archivos = len(archivos)

    for archivo in archivos:
        paginas = extraer_paginas_pdf(archivo)
        if not paginas:
            continue

        chunks = _crear_chunks_paginas(paginas)

        for chunk in chunks:
            puntuacion = _puntuar_chunk(consulta, chunk)
            if puntuacion <= 0:
                continue

            try:
                ruta_clave = str(archivo.resolve())

                if ruta_clave in r2_por_ruta:
                    fila = r2_por_ruta[ruta_clave]
                    r2_key = str(fila.get("r2_key") or "")

                    if r2_key.startswith("polizas/"):
                        nombre_archivo = fila.get("nombre") or archivo.name
                        compania = "Biblioteca de pólizas"
                        tipo = "poliza"
                        ruta_relativa = r2_key
                    else:
                        partes = r2_key.split("/")
                        slug = partes[1] if len(partes) > 1 else ""
                        compania = next(
                            (c for c in MANUALES_COMPANIAS
                             if slug_manual_compania(c) == slug),
                            "",
                        )
                        nombre_archivo = fila.get("nombre") or archivo.name
                        tipo = "manual"
                        ruta_relativa = r2_key

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
                "tipo": tipo,
            })

    resultados.sort(
        key=lambda x: (
            x["coincidencias"],
            len(x.get("texto", ""))
        ),
        reverse=True
    )

    # La detección de compañía define cuántos archivos pueden competir.
    # El límite total de fragmentos sigue siendo ``limite``.
    max_archivos = (
        MANUALES_MAX_ARCHIVOS_CON_CIA
        if companias_detectadas
        else MANUALES_MAX_ARCHIVOS_GENERAL
    )

    seleccionados = []
    por_archivo = {}
    archivos_permitidos = []

    tokens_consulta = _tokens_busqueda(consulta)
    es_compleja = len(tokens_consulta) >= 8 or any(
        palabra in _normalizar_busqueda(consulta)
        for palabra in (
            "como", "cómo", "procedimiento", "documentacion",
            "documentación", "requisitos", "condiciones", "pasos",
            "explicame", "detalle", "completo",
        )
    )
    max_por_archivo = 8 if es_compleja else 4

    for resultado in resultados:
        clave = resultado["ruta"]
        if clave not in archivos_permitidos:
            if len(archivos_permitidos) >= max_archivos:
                continue
            archivos_permitidos.append(clave)

        cantidad = por_archivo.get(clave, 0)
        if cantidad >= max_por_archivo:
            continue

        seleccionados.append(resultado)
        por_archivo[clave] = cantidad + 1
        if len(seleccionados) >= limite:
            break

    print(
        f"RETRIEVAL PDF: consulta={consulta!r} "
        f"companias={sorted(companias_detectadas)} "
        f"archivos_procesados={cantidad_archivos} "
        f"archivos_seleccionados={len(archivos_permitidos)} "
        f"fragmentos={len(seleccionados)}"
    )

    return seleccionados

