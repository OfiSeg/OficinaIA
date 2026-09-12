from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from openpyxl import Workbook, load_workbook
from envios_ya_utils import normalizar_telefono_argentina as _normalizar_telefono_argentina_compartido
from office_time import office_today, office_year

BASE_DIR = Path(__file__).resolve().parent
PLANTILLA_ENVIOSYA = BASE_DIR / "plantillas" / "enviosya_contactos.xlsx"
TMP_DIR = Path(tempfile.gettempdir()) / "oficinaia_envios_masivos"
TMP_DIR.mkdir(parents=True, exist_ok=True)
TTL_TEMP_SEGUNDOS = 60 * 60
MAX_ARCHIVOS = 12
MAX_FILAS_POR_ARCHIVO = 120_000

CAMPOS_SALIDA = [
    "apellido", "nombre", "dni", "celular", "localidad", "compania",
    "patente", "marca", "modelo", "anio", "cliente", "vencimiento",
]

ALIASES_CAMPOS = {
    "apellido": {"apellido", "apellidos", "surname", "last name"},
    "nombre": {"nombre", "nombres", "first name", "name"},
    "nombre_completo": {"nombre completo", "apellido y nombre", "apellido nombre", "apellidos y nombres", "cliente nombre", "razon social", "razón social", "titular", "cliente", "asegurado"},
    "dni": {"dni", "documento", "nro doc", "nro. doc", "nro documento", "numero documento", "número documento", "doc"},
    "celular": {"celular", "telefono", "teléfono", "telefono celular", "teléfono celular", "tel celular", "tel", "movil", "móvil", "whatsapp", "whatsapp contacto", "cel", "nro celular", "nro. celular", "numero celular", "número celular", "numero", "número"},
    "localidad": {"localidad", "ciudad", "city", "poblacion", "población"},
    "cp": {"cp", "codigo postal", "código postal", "cod postal", "postal", "cpa"},
    "direccion": {"direccion", "dirección", "domicilio", "calle", "address"},
    "compania": {"compania", "compañia", "compañía", "aseguradora", "cia", "cia seguro", "compania seguro"},
    "patente": {"patente", "dominio", "chapa", "registration", "matricula", "matrícula"},
    "marca": {"marca", "brand"},
    "modelo": {"modelo", "model"},
    "anio": {"año", "anio", "year", "modelo año", "modelo anio"},
    "cliente": {"cliente", "productor", "organizador", "broker"},
    "vencimiento": {"vencimiento", "fecha vencimiento", "vigencia hasta", "hasta", "renovacion", "renovación"},
    "poliza": {"poliza", "póliza", "nro poliza", "nro. poliza", "numero poliza", "número póliza", "policy", "policy number"},
    "provincia": {"provincia", "province", "estado"},
    "pais": {"pais", "país", "country"},
    "fecha_origen": {"fecha", "fecha origen", "fecha alta", "alta"},
    "email": {"email", "e-mail", "mail", "correo", "correo electronico", "correo electrónico"},
    "tipo": {"tipo", "ramo", "producto", "categoria", "categoría", "segmento"},
}

TIPOS_CONOCIDOS = {
    "VEHICULAR", "AUTOMOTOR", "AUTO", "MOTO", "COMERCIO", "DOMICILIO",
    "HOGAR", "FLOTA", "OBJETO", "RC", "RESPONSABILIDAD CIVIL", "AP",
    "ACCIDENTES PERSONALES", "CONSORCIO", "BICICLETA",
}

NOMBRES_COMUNES = {
    "ABEL", "ABRAHAM", "ADRIAN", "ADRIANA", "AGUSTIN", "AGUSTINA", "ALAN", "ALBERTO", "ALEJANDRA", "ALEJANDRO",
    "ALEXIS", "ALICIA", "ALMA", "AMALIA", "AMANDA", "AMELIA", "ANA", "ANDREA", "ANDRES", "ANGEL", "ANGELA", "ANTONELA",
    "ANTONIA", "ANTONIO", "ARIEL", "ARMANDO", "BEATRIZ", "BELEN", "BENJAMIN", "BERNARDO", "BRENDA", "BRIAN", "BRUNO",
    "CAMILA", "CARINA", "CARLA", "CARLOS", "CARMEN", "CAROLINA", "CATALINA", "CECILIA", "CESAR", "CLAUDIA", "CLAUDIO",
    "CRISTIAN", "CRISTINA", "DANIEL", "DANIELA", "DARIO", "DAVID", "DEBORA", "DIEGO", "EDGARDO", "EDITH", "EDUARDO",
    "ELENA", "ELIAS", "EMILIA", "EMILIANO", "EMILIO", "ENRIQUE", "ESTEBAN", "EUGENIA", "EZEQUIEL", "FABIANA", "FABIAN",
    "FABIO", "FACUNDO", "FEDERICO", "FELIPE", "FERNANDA", "FERNANDO", "FLORENCIA", "FRANCO", "GABRIEL", "GABRIELA",
    "GERMAN", "GLADIS", "GLORIA", "GONZALO", "GRACIELA", "GRISELDA", "GUADALUPE", "GUILLERMO", "GUSTAVO", "HECTOR",
    "HERNAN", "HILDA", "HORACIO", "HUGO", "INES", "ISABEL", "IVAN", "JAVIER", "JESICA", "JOAQUIN", "JORGE", "JOSE",
    "JOSEFINA", "JUAN", "JUANA", "JULIA", "JULIANA", "JULIO", "KAREN", "KARINA", "LAURA", "LEANDRO", "LEONARDO",
    "LETICIA", "LILIANA", "LORENA", "LOURDES", "LUCAS", "LUCIANA", "LUCIANO", "LUIS", "LUISA", "LUZ", "MAGALI",
    "MANUEL", "MARCELA", "MARCELO", "MARCOS", "MARGARITA", "MARIA", "MARIANA", "MARIANO", "MARIELA", "MARINA", "MARIO",
    "MARTA", "MARTIN", "MATIAS", "MAURICIO", "MAXIMILIANO", "MELANIE", "MERCEDES", "MICAELA", "MIGUEL", "MILAGROS",
    "MIRTA", "MONICA", "NAHUEL", "NATALIA", "NESTOR", "NICOLAS", "NOELIA", "NORMA", "OSCAR", "PABLO", "PAMELA",
    "PATRICIA", "PAULA", "PEDRO", "RAFAEL", "RAMIRO", "RAMON", "RAUL", "REBECA", "RICARDO", "ROBERTO", "ROCIO",
    "RODOLFO", "RODRIGO", "ROMINA", "ROSA", "ROSANA", "RUBEN", "SABRINA", "SANDRA", "SANTIAGO", "SARA", "SEBASTIAN",
    "SERGIO", "SILVANA", "SILVIA", "SOFIA", "SOL", "SONIA", "STELLA", "SUSANA", "TAMARA", "TATIANA", "VALENTINA",
    "VALERIA", "VERONICA", "VICTOR", "VICTORIA", "VIVIANA", "WALTER", "YANINA",
}

COMPANIAS_FILENAME = {
    "ALLIANZ": "ALLIANZ",
    "ATM": "ATM SEGUROS",
    "AGROSALTA": "AGROSALTA SEGUROS",
    "FEDERACION PATRONAL": "FEDERACION PATRONAL",
    "FEDERACIÓN PATRONAL": "FEDERACION PATRONAL",
    "MERCANTIL ANDINA": "MERCANTIL ANDINA",
    "SAN CRISTOBAL": "SAN CRISTOBAL",
    "SAN CRISTÓBAL": "SAN CRISTOBAL",
    "RIVADAVIA": "RIVADAVIA",
    "TRIUNFO": "TRIUNFO SEGUROS",
    "PROF": "PROF SEGUROS",
    "EUROAMERICA": "EUROAMERICA",
    "EUROAMÉRICA": "EUROAMERICA",
}


def _norm_texto(v: Any) -> str:
    s = str(v or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s.upper().strip()


def _texto_limpio(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"\s+", " ", str(v).strip())


def _reparar_texto_fuente(v: Any, campo: str = "") -> tuple[str, bool, bool]:
    """Limpia daños conocidos de bases heredadas sin tocar datos sensibles.

    En la muestra Allianz el propio XLSX de origen trae '#' en lugar de Ñ
    (MU#OZ, CA#UELAS, etc.). Sólo se repara en campos de texto humano donde
    ese carácter no tiene uso normal. Si queda U+FFFD (�), se marca para
    revisión en vez de inventar el carácter original.
    """
    texto = _texto_limpio(v)
    reparado = False
    campos_naturales = {
        "apellido", "nombre", "nombre_completo", "localidad", "direccion",
        "provincia", "cliente", "marca", "modelo", "tipo",
    }
    if campo in campos_naturales and "#" in texto:
        texto = texto.replace("#", "Ñ")
        reparado = True
    danado = "�" in texto
    return texto, reparado, danado


def _digits(v: Any) -> str:
    s = _texto_limpio(v)
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return re.sub(r"\D", "", s)


def normalizar_telefono_argentina(valor: Any) -> tuple[str, str]:
    """Compatibilidad pública: delega en la regla canónica compartida."""
    return _normalizar_telefono_argentina_compartido(valor)


def normalizar_celular_envios_masivos(valor: Any) -> tuple[str, str]:
    """Limpieza conservadora para el CSV masivo.

    En este flujo el Excel es fuente de verdad: se eliminan sólo caracteres
    visuales y nunca se agregan/quitan prefijos telefónicos.
    """
    texto = _texto_limpio(valor)
    if not texto:
        return "", "Sin celular"
    # Evita .0 proveniente de celdas numéricas y notación científica visible.
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    digitos = re.sub(r"\D", "", texto)
    if not digitos:
        return "", "Sin celular"
    if len(digitos) < 6:
        return "", "Celular demasiado corto"
    if len(digitos) > 16:
        return "", "Celular demasiado largo"
    return digitos, ""


def _mapping_suficiente(mapping: dict[int, str]) -> bool:
    campos = set(mapping.values())
    return "celular" in campos and (("apellido" in campos and "nombre" in campos) or "nombre_completo" in campos)


def _aplicar_mapping_manual(mapping: dict[int, str], manual: dict[str, Any] | None) -> dict[int, str]:
    if not manual:
        return mapping
    out = {i: c for i, c in mapping.items() if c not in {"apellido", "nombre", "nombre_completo", "celular"}}
    for campo in ("apellido", "nombre", "nombre_completo", "celular"):
        raw = manual.get(campo)
        if raw in (None, "", -1, "-1"):
            continue
        try:
            idx = int(raw)
        except Exception:
            continue
        out[idx] = campo
    return out


def _opciones_columnas(headers: list[Any], data_rows: list[list[Any]]) -> list[dict[str, Any]]:
    ancho = max([len(headers)] + [len(r) for r in data_rows[:20]] + [0])
    out = []
    for idx in range(ancho):
        titulo = _texto_limpio(headers[idx]) if idx < len(headers) else ""
        muestras = []
        for r in data_rows[:8]:
            if idx < len(r):
                v = _texto_limpio(r[idx])
                if v and v not in muestras:
                    muestras.append(v[:50])
            if len(muestras) >= 2:
                break
        label = titulo or f"Columna {idx + 1}"
        if muestras:
            label += " · " + " / ".join(muestras)
        out.append({"index": idx, "label": label})
    return out


def _es_email(v: Any) -> bool:
    s = _texto_limpio(v)
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", s))


def _es_patente(v: Any) -> bool:
    s = re.sub(r"[^A-Z0-9]", "", _norm_texto(v))
    return bool(re.fullmatch(r"(?:[A-Z]{3}\d{3}|[A-Z]{2}\d{3}[A-Z]{2}|\d{3}[A-Z]{3})", s))


def _es_anio(v: Any) -> bool:
    s = _digits(v)
    if not s:
        return False
    try:
        n = int(s)
    except Exception:
        return False
    return 1900 <= n <= office_year() + 2


def _excel_serial_fecha(v: Any) -> date | None:
    try:
        n = float(v)
    except Exception:
        return None
    if 20_000 <= n <= 70_000:
        return date(1899, 12, 30) + timedelta(days=int(n))
    return None


def _parse_fecha(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    serial = _excel_serial_fecha(v)
    if serial:
        return serial
    s = _texto_limpio(v)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _parece_dni(v: Any) -> bool:
    d = _digits(v)
    return 7 <= len(d) <= 8


def _parece_cp(v: Any) -> bool:
    s = _norm_texto(v).replace(" ", "")
    return bool(re.fullmatch(r"\d{4}", s) or re.fullmatch(r"[A-Z]\d{4}[A-Z]{3}", s))


def _parece_direccion(v: Any) -> bool:
    s = _norm_texto(v)
    return bool(re.search(r"\d", s) and re.search(r"[A-Z]", s) and len(s) >= 6)


def _parece_tipo(v: Any) -> bool:
    return _norm_texto(v) in TIPOS_CONOCIDOS


def _nombre_score(v: Any) -> float:
    s = _norm_texto(v)
    if not s or re.search(r"\d|@", s):
        return 0.0
    tokens = [x for x in re.split(r"\s+", s) if x]
    if not (2 <= len(tokens) <= 7):
        return 0.0
    comunes = sum(1 for t in tokens if t in NOMBRES_COMUNES)
    score = 0.25 + min(0.6, comunes * 0.3)
    if len(tokens) >= 3:
        score += 0.1
    return min(score, 1.0)


def separar_nombre_completo(valor: Any) -> tuple[str, str]:
    original = re.sub(r"\s+", " ", _texto_limpio(valor)).strip(" ,;")
    if not original:
        return "", ""
    if "," in original:
        izq, der = original.split(",", 1)
        return izq.strip(), der.strip()
    tokens = original.split()
    if len(tokens) == 1:
        return tokens[0], ""

    norm_tokens = [_norm_texto(x) for x in tokens]
    limite = None
    # Buscamos el primer nombre reconocible; permite apellidos compuestos.
    for i in range(1, len(tokens)):
        if norm_tokens[i] in NOMBRES_COMUNES:
            limite = i
            break
    if limite is None:
        limite = 1
    return " ".join(tokens[:limite]), " ".join(tokens[limite:])


def _detectar_compania_filename(nombre: str) -> str:
    n = _norm_texto(Path(nombre).stem).replace("_", " ").replace("-", " ")
    for clave, salida in COMPANIAS_FILENAME.items():
        if _norm_texto(clave) in n:
            return salida
    return ""


def _canon_header(v: Any) -> str:
    s = _norm_texto(v).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def _campo_por_header(v: Any) -> str | None:
    h = _canon_header(v)
    if not h:
        return None
    for campo, aliases in ALIASES_CAMPOS.items():
        for alias in aliases:
            if h == _canon_header(alias):
                return campo
    return None


def _fila_es_header(row: list[Any]) -> bool:
    detectados = [c for c in (_campo_por_header(v) for v in row) if c]
    fuertes = {"celular", "dni", "patente", "vencimiento", "email", "localidad", "nombre", "apellido", "nombre_completo"}
    return len(detectados) >= 2 or any(c in fuertes for c in detectados)


def _inferir_columnas(rows: list[list[Any]]) -> dict[int, str]:
    if not rows:
        return {}
    ancho = max(len(r) for r in rows)
    muestras = rows[:250]
    scores: dict[int, dict[str, float]] = {}
    for idx in range(ancho):
        vals = [r[idx] for r in muestras if idx < len(r) and _texto_limpio(r[idx])]
        if not vals:
            continue
        n = len(vals)
        metricas = {
            "email": sum(_es_email(v) for v in vals) / n,
            "celular": sum(bool(normalizar_telefono_argentina(v)[0]) for v in vals) / n,
            "patente": sum(_es_patente(v) for v in vals) / n,
            "anio": sum(_es_anio(v) for v in vals) / n,
            "fecha_origen": sum(bool(_parse_fecha(v)) for v in vals) / n,
            "dni": sum(_parece_dni(v) for v in vals) / n,
            "cp": sum(_parece_cp(v) for v in vals) / n,
            "direccion": sum(_parece_direccion(v) for v in vals) / n,
            "tipo": sum(_parece_tipo(v) for v in vals) / n,
            "nombre_completo": sum(_nombre_score(v) for v in vals) / n,
        }
        # Una columna de teléfono válida no debe terminar etiquetada DNI/CP.
        if metricas["celular"] >= 0.65:
            metricas["dni"] *= 0.1
            metricas["cp"] *= 0.1
        scores[idx] = metricas

    mapping: dict[int, str] = {}
    usados: set[str] = set()
    prioridad = ["email", "celular", "patente", "tipo", "fecha_origen", "anio", "cp", "dni", "direccion", "nombre_completo"]
    umbral = {"email": .55, "celular": .55, "patente": .45, "tipo": .45, "fecha_origen": .55, "anio": .55, "cp": .65, "dni": .65, "direccion": .55, "nombre_completo": .42}
    for campo in prioridad:
        candidatos = [(idx, sc.get(campo, 0.0)) for idx, sc in scores.items() if idx not in mapping]
        if candidatos:
            idx, puntaje = max(candidatos, key=lambda x: x[1])
            if puntaje >= umbral[campo] and campo not in usados:
                mapping[idx] = campo
                usados.add(campo)

    # Texto remanente: normalmente localidad en bases sin encabezado.
    for idx in range(ancho):
        if idx in mapping:
            continue
        vals = [_texto_limpio(r[idx]) for r in muestras if idx < len(r) and _texto_limpio(r[idx])]
        if not vals:
            continue
        alfab = [v for v in vals if not re.search(r"\d|@", v)]
        if len(alfab) / len(vals) >= .8:
            avg_tokens = sum(len(v.split()) for v in alfab) / len(alfab)
            if avg_tokens <= 3.0 and "localidad" not in usados:
                mapping[idx] = "localidad"
                usados.add("localidad")
                break
    return mapping


def _mapear_con_gemini(rows: list[list[Any]], mapping_actual: dict[int, str]) -> dict[int, str]:
    """Fallback muy acotado: sólo mapea columnas, jamás procesa 40k filas con IA."""
    if any(v == "celular" for v in mapping_actual.values()) and any(v in {"nombre", "nombre_completo"} for v in mapping_actual.values()):
        return mapping_actual
    try:
        from ai_gateway import begin_request, generate_with_fallback, obtener_cliente_gemini, DEFAULT_MODELS
        from google.genai import types
        from resilience import parse_json_object
        cliente = obtener_cliente_gemini()
        if not cliente:
            return mapping_actual
        muestra = [[_texto_limpio(v)[:90] for v in r] for r in rows[:12]]
        prompt = (
            "Mapeá columnas de una base de contactos a estos campos canónicos: "
            "apellido,nombre,nombre_completo,dni,celular,localidad,cp,direccion,compania,patente,marca,modelo,anio,cliente,vencimiento,fecha_origen,email,tipo,poliza,provincia,pais. "
            "Respondé SOLO JSON con claves que sean índices de columna base 0 y valores campos canónicos. "
            "No inventes: si una columna es ambigua, omitila. Muestra:\n" + json.dumps(muestra, ensure_ascii=False)
        )
        begin_request()
        try:
            r, _modelo_usado = generate_with_fallback(
                client=cliente,
                models=DEFAULT_MODELS[:2],
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
                log_prefix="GEMINI /ENVIOS",
                response_validator=lambda resp: parse_json_object(getattr(resp, "text", "")),
            )
            data = parse_json_object(r.text or "{}")
            out = dict(mapping_actual)
            validos = set(ALIASES_CAMPOS)
            for k, v in data.items():
                try:
                    i = int(k)
                except Exception:
                    continue
                if str(v) in validos and i not in out:
                    out[i] = str(v)
            return out
        except Exception:
            pass
    except Exception:
        pass
    return mapping_actual


def _leer_xlsx(datos: bytes) -> tuple[list[list[Any]], str]:
    wb = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    try:
        ws = wb.active
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if i > MAX_FILAS_POR_ARCHIVO:
                raise ValueError(f"La base supera el máximo de {MAX_FILAS_POR_ARCHIVO:,} filas por archivo.")
            vals = list(row)
            if any(_texto_limpio(v) for v in vals):
                rows.append(vals)
        return rows, ws.title
    finally:
        wb.close()


def _leer_csv(datos: bytes) -> tuple[list[list[Any]], str]:
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = datos.decode(enc)
            break
        except Exception:
            continue
    if texto is None:
        raise ValueError("No pude leer la codificación del CSV.")
    muestra = texto[:8192]
    try:
        dialect = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
    except Exception:
        dialect = csv.excel
        dialect.delimiter = ";"
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(texto), dialect), start=1):
        if i > MAX_FILAS_POR_ARCHIVO:
            raise ValueError(f"La base supera el máximo de {MAX_FILAS_POR_ARCHIVO:,} filas por archivo.")
        if any(_texto_limpio(v) for v in row):
            rows.append(row)
    return rows, "CSV"


def _leer_archivo(nombre: str, datos: bytes) -> tuple[list[list[Any]], str]:
    ext = Path(nombre).suffix.lower()
    if ext in {".xlsx", ".xlsm"}:
        return _leer_xlsx(datos)
    if ext == ".csv":
        return _leer_csv(datos)
    if ext == ".xls":
        raise ValueError("El formato .xls antiguo no está soportado. Guardalo como .xlsx y volvé a subirlo.")
    raise ValueError("Formato no soportado. Usá Excel .xlsx/.xlsm o CSV.")


def _valor(row: list[Any], mapping: dict[int, str], campo: str) -> Any:
    for idx, c in mapping.items():
        if c == campo and idx < len(row):
            return row[idx]
    return ""


def _normalizar_registro(row: list[Any], mapping: dict[int, str], fuente: str, compania_fuente: str = "", fecha_modo: str = "actual", usar_compania_fuente: bool = False) -> dict[str, Any]:
    """Normaliza sólo los cuatro datos necesarios para Envíos Masivos."""
    nombre, _, bad_nombre = _reparar_texto_fuente(_valor(row, mapping, "nombre"), "nombre")
    apellido, _, bad_apellido = _reparar_texto_fuente(_valor(row, mapping, "apellido"), "apellido")
    nombre_completo, _, bad_completo = _reparar_texto_fuente(_valor(row, mapping, "nombre_completo"), "nombre_completo")
    if nombre_completo and not (nombre and apellido):
        ap2, no2 = separar_nombre_completo(nombre_completo)
        apellido = apellido or ap2
        nombre = nombre or no2

    celular_original = _texto_limpio(_valor(row, mapping, "celular"))
    celular, error_tel = normalizar_celular_envios_masivos(celular_original)
    fecha_fuente = _parse_fecha(_valor(row, mapping, "fecha_origen"))
    fecha_iso = fecha_fuente.isoformat() if fecha_fuente else office_today().isoformat()
    incompletos = []
    if not apellido:
        incompletos.append("apellido")
    if not nombre:
        incompletos.append("nombre")
    if not celular:
        incompletos.append("celular")
    texto_danado = any((bad_nombre, bad_apellido, bad_completo))
    if texto_danado:
        incompletos.append("texto ilegible")

    return {
        "apellido": apellido,
        "nombre": nombre,
        "nombre_completo": nombre_completo or f"{apellido} {nombre}".strip(),
        "celular_original": celular_original,
        "celular": celular,
        "telefono_error": error_tel,
        "fecha": fecha_iso,
        "fuente": fuente,
        "texto_danado": texto_danado,
        "incompletos": incompletos,
        "estado": "VALIDO" if not incompletos else "REVISAR",
    }


def _score_riqueza(r: dict[str, Any]) -> int:
    return sum(1 for c in ("apellido", "nombre", "celular") if _texto_limpio(r.get(c)))


def _limpiar_temporales() -> None:
    ahora = time.time()
    try:
        for p in TMP_DIR.glob("envios_*.*"):
            if ahora - p.stat().st_mtime > TTL_TEMP_SEGUNDOS:
                p.unlink(missing_ok=True)
    except Exception:
        pass


def generar_csv_envios_ya(registros: list[dict[str, Any]], token: str) -> Path:
    """Genera el CSV rígido confirmado de Envíos Ya.

    Sin encabezados. Cada registro tiene exactamente 10 posiciones:
    apellido,nombre,celular,fecha,XXX,XXX,XXX,,XXX,
    """
    salida = TMP_DIR / f"envios_{token}.csv"
    with salida.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=",", lineterminator="\r\n")
        for r in registros:
            fila = [
                _texto_limpio(r.get("apellido")),
                _texto_limpio(r.get("nombre")),
                _texto_limpio(r.get("celular")),
                _texto_limpio(r.get("fecha")) or office_today().isoformat(),
                "XXX", "XXX", "XXX", "", "XXX", "",
            ]
            if len(fila) != 10:
                raise RuntimeError("Fila inválida: Envíos Ya requiere exactamente 10 campos.")
            writer.writerow(fila)

    # Verificación posterior real del archivo generado.
    with salida.open("r", encoding="utf-8", newline="") as f:
        filas = list(csv.reader(f, delimiter=","))
    for i, fila in enumerate(filas, start=1):
        if len(fila) != 10:
            salida.unlink(missing_ok=True)
            raise RuntimeError(f"CSV inválido: la fila {i} no contiene 10 campos.")
        if fila[4:7] != ["XXX", "XXX", "XXX"] or fila[8] != "XXX":
            salida.unlink(missing_ok=True)
            raise RuntimeError(f"CSV inválido: posiciones reservadas incorrectas en fila {i}.")
        if fila[7] != "" or fila[9] != "":
            salida.unlink(missing_ok=True)
            raise RuntimeError(f"CSV inválido: patente/póliza deben quedar vacías en fila {i}.")
    return salida


def _detectar_duplicados(registros: list[dict[str, Any]]) -> int:
    vistos: set[str] = set()
    duplicados = 0
    for r in registros:
        tel = _texto_limpio(r.get("celular"))
        if not tel:
            continue
        if tel in vistos:
            duplicados += 1
        else:
            vistos.add(tel)
    return duplicados


def _pending_path(token: str) -> Path:
    seguro = re.sub(r"[^a-f0-9]", "", str(token or "").lower())[:64]
    if not seguro:
        raise ValueError("Token pendiente inválido.")
    return TMP_DIR / f"envios_pending_{seguro}.json"


def _guardar_exportacion_pendiente(token: str, registros: list[dict[str, Any]]) -> Path:
    ruta = _pending_path(token)
    payload = {"creado": time.time(), "registros": registros}
    ruta.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return ruta


def generar_exportacion_pendiente(token: str) -> Path:
    _limpiar_temporales()
    ruta = _pending_path(token)
    if not ruta.is_file():
        raise ValueError("La preparación venció o no existe. Volvé a adjuntar la base.")
    try:
        payload = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("No pude recuperar la preparación de contactos.") from exc
    registros = payload.get("registros") if isinstance(payload, dict) else None
    if not isinstance(registros, list):
        raise ValueError("La preparación de contactos no es válida.")
    salida = generar_csv_envios_ya(registros, token)
    ruta.unlink(missing_ok=True)
    return salida


def guardar_fuentes_pendientes(archivos: list[tuple[str, bytes]]) -> str:
    _limpiar_temporales()
    token = uuid.uuid4().hex
    ruta = TMP_DIR / f"envios_sources_{token}.json"
    serial = []
    import base64
    for nombre, datos in archivos:
        serial.append({"nombre": str(nombre), "datos": base64.b64encode(bytes(datos)).decode("ascii")})
    ruta.write_text(json.dumps({"creado": time.time(), "archivos": serial}), encoding="utf-8")
    return token


def recuperar_fuentes_pendientes(token: str) -> list[tuple[str, bytes]]:
    seguro = re.sub(r"[^a-f0-9]", "", str(token or "").lower())[:64]
    ruta = TMP_DIR / f"envios_sources_{seguro}.json"
    if not ruta.is_file():
        raise ValueError("La preparación venció o no existe. Volvé a adjuntar la base.")
    try:
        import base64
        payload = json.loads(ruta.read_text(encoding="utf-8"))
        salida = []
        for item in payload.get("archivos") or []:
            salida.append((str(item.get("nombre") or "base.csv"), base64.b64decode(item.get("datos") or "")))
        return salida
    except Exception as exc:
        raise ValueError("No pude recuperar la base pendiente.") from exc


def eliminar_fuentes_pendientes(token: str) -> None:
    seguro = re.sub(r"[^a-f0-9]", "", str(token or "").lower())[:64]
    if seguro:
        (TMP_DIR / f"envios_sources_{seguro}.json").unlink(missing_ok=True)


def procesar_bases(
    archivos: list[tuple[str, bytes]],
    fecha_modo: str = "actual",
    usar_compania_fuente: bool = False,
    manual_mapping: dict[str, Any] | None = None,
    dedupe_mode: str = "all",
    *,
    generar_archivo: bool = True,
    token_pendiente: str | None = None,
) -> dict[str, Any]:
    _limpiar_temporales()
    if not archivos:
        raise ValueError("Seleccioná al menos una planilla.")
    if len(archivos) > MAX_ARCHIVOS:
        raise ValueError(f"Podés procesar hasta {MAX_ARCHIVOS} archivos por lote.")

    manual_mapping = manual_mapping or {}
    todos: list[dict[str, Any]] = []
    info_archivos: list[dict[str, Any]] = []
    mapping_requests: list[dict[str, Any]] = []
    total_entrada = 0

    for file_index, (nombre, datos) in enumerate(archivos):
        rows, hoja = _leer_archivo(nombre, datos)
        if not rows:
            info_archivos.append({"nombre": nombre, "filas": 0, "estado": "vacío", "columnas": {}})
            continue

        tiene_header = _fila_es_header(rows[0])
        if tiene_header:
            headers = rows[0]
            data_rows = rows[1:]
            mapping = {i: c for i, v in enumerate(headers) if (c := _campo_por_header(v))}
        else:
            headers = []
            data_rows = rows
            mapping = _inferir_columnas(data_rows)

        # Este módulo no manda la planilla completa a Gemini. El mapeo dudoso
        # se resuelve explícitamente con el productor.
        mapping = _aplicar_mapping_manual(mapping, manual_mapping.get(str(file_index)) or manual_mapping.get(file_index))

        if not _mapping_suficiente(mapping):
            mapping_requests.append({
                "file_index": file_index,
                "nombre": nombre,
                "columnas": _opciones_columnas(headers, data_rows),
                "detectado": {campo: idx for idx, campo in mapping.items() if campo in {"apellido", "nombre", "nombre_completo", "celular"}},
                "acepta_nombre_completo": True,
            })
            info_archivos.append({
                "nombre": nombre,
                "hoja": hoja,
                "filas": len(data_rows),
                "encabezados": bool(tiene_header),
                "columnas": {str(i + 1): campo for i, campo in sorted(mapping.items())},
                "estado": "mapear",
            })
            continue

        total_entrada += len(data_rows)
        for row in data_rows:
            if not any(_texto_limpio(v) for v in row):
                continue
            reg = _normalizar_registro(row, mapping, nombre)
            # Filas de relleno sin datos reales no generan registro.
            if not any((reg.get("nombre_completo"), reg.get("celular_original"))):
                continue
            todos.append(reg)

        info_archivos.append({
            "nombre": nombre,
            "hoja": hoja,
            "filas": len(data_rows),
            "encabezados": bool(tiene_header),
            "columnas": {str(i + 1): campo for i, campo in sorted(mapping.items()) if campo in {"apellido", "nombre", "nombre_completo", "celular"}},
            "estado": "listo",
        })

    if mapping_requests:
        return {
            "requiere_mapeo": True,
            "mapeos": mapping_requests,
            "archivos": info_archivos,
            "resumen": {"filas_entrada": total_entrada, "contactos_detectados": len(todos)},
        }

    validos = [r for r in todos if r.get("estado") == "VALIDO"]
    invalidos = [r for r in todos if r.get("estado") != "VALIDO"]
    duplicados = _detectar_duplicados(validos)

    if dedupe_mode == "one":
        por_tel: dict[str, dict[str, Any]] = {}
        for r in validos:
            tel = r.get("celular") or ""
            actual = por_tel.get(tel)
            if actual is None or _score_riqueza(r) > _score_riqueza(actual):
                por_tel[tel] = r
        exportables = list(por_tel.values())
    else:
        exportables = list(validos)

    exportables.sort(key=lambda r: (_norm_texto(r.get("apellido")), _norm_texto(r.get("nombre")), _texto_limpio(r.get("celular"))))
    token = token_pendiente or uuid.uuid4().hex
    salida = generar_csv_envios_ya(exportables, token) if generar_archivo else None
    if not generar_archivo:
        _guardar_exportacion_pendiente(token, exportables)

    preview: list[dict[str, Any]] = []
    for r in exportables[:120]:
        preview.append({
            "apellido": r.get("apellido", ""), "nombre": r.get("nombre", ""),
            "celular": r.get("celular", ""), "fecha": r.get("fecha", ""),
            "fuente": r.get("fuente", ""), "estado": "VALIDO", "motivo": "",
        })
    for r in invalidos[:80]:
        motivos = list(r.get("incompletos") or [])
        if r.get("telefono_error") and "celular" in motivos:
            motivos.append(r.get("telefono_error"))
        preview.append({
            "apellido": r.get("apellido", ""), "nombre": r.get("nombre", ""),
            "celular": r.get("celular_original", ""), "fecha": r.get("fecha", ""),
            "fuente": r.get("fuente", ""), "estado": "REVISAR",
            "motivo": ", ".join(dict.fromkeys(motivos)) or "Datos incompletos",
        })

    return {
        "requiere_mapeo": False,
        "token": token,
        "archivo": salida.name if salida is not None else None,
        "fecha": office_today().isoformat(),
        "resumen": {
            "filas_entrada": total_entrada,
            "contactos_detectados": len(todos),
            "exportables": len(exportables),
            "revisar": len(invalidos),
            "duplicados": duplicados,
            "omitidos_sin_celular": sum(1 for r in invalidos if not r.get("celular")),
        },
        "archivos": info_archivos,
        "preview": preview,
        "dedupe_mode": dedupe_mode,
    }


def obtener_exportacion(token: str, tipo: str = "csv") -> Path | None:
    if not re.fullmatch(r"[a-f0-9]{32}", str(token or "")):
        return None
    if tipo not in {"csv", "contactos"}:
        return None
    p = TMP_DIR / f"envios_{token}.csv"
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > TTL_TEMP_SEGUNDOS:
        p.unlink(missing_ok=True)
        return None
    return p


def obtener_csv(token: str) -> Path | None:
    return obtener_exportacion(token, "csv")


def obtener_excel(token: str) -> Path | None:
    """Alias legado del endpoint histórico; ahora devuelve el CSV final."""
    return obtener_csv(token)
