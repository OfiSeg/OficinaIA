# -*- coding: utf-8 -*-
"""Parser determinístico para PDFs de cotización de Federación Patronal.

La intención es leer únicamente datos explícitos del PDF. No usa Gemini ni
infere prestaciones por nombres comerciales ambiguos. En particular, la grúa
se obtiene del campo SERVICIO DE GRUA de cada cotización y la franquicia de
Todo Riesgo se toma del propio documento.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
import unicodedata

import fitz


def _norm(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    valor = "".join(ch for ch in valor if not unicodedata.combining(ch))
    valor = valor.upper().replace("\r", "\n")
    valor = re.sub(r"[ \t]+", " ", valor)
    return valor


def _lineas(texto: str) -> list[str]:
    return [re.sub(r"\s+", " ", linea).strip() for linea in str(texto or "").splitlines() if linea.strip()]


def _money_decimal(texto: str) -> Decimal:
    limpio = str(texto or "").strip().replace("$", "").replace(" ", "")
    if not limpio:
        raise ValueError("Importe vacío")

    # PDFs de Federación mezclan estilo US para SA (18,810,000.00), enteros
    # simples para cuotas (111253) y estilo AR para franquicias ($3.582.440).
    if "," in limpio and "." in limpio:
        # El último separador define los decimales.
        if limpio.rfind(".") > limpio.rfind(","):
            limpio = limpio.replace(",", "")
        else:
            limpio = limpio.replace(".", "").replace(",", ".")
    elif "," in limpio:
        partes = limpio.split(",")
        if len(partes[-1]) in {1, 2} and len(partes) == 2:
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "." in limpio:
        partes = limpio.split(".")
        # 3.582.440 -> miles; 209418.66 -> decimales.
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            limpio = limpio.replace(".", "")
    try:
        return Decimal(limpio)
    except InvalidOperation as exc:
        raise ValueError(f"Importe inválido: {texto}") from exc


def _fmt_decimal(v: Decimal | None, decimales: bool = False) -> str:
    if v is None:
        return ""
    if decimales:
        q = v.quantize(Decimal("0.01"))
        entero, dec = f"{q:.2f}".split(".")
        return f"${int(entero):,}".replace(",", ".") + f",{dec}"
    entero = int(v.quantize(Decimal("1")))
    return "$" + f"{entero:,}".replace(",", ".")


def _buscar_bloque(page, predicado):
    for bloque in page.get_text("blocks"):
        texto = str(bloque[4] or "")
        if predicado(texto):
            return bloque
    return None


def _tabla_automotor(page) -> dict[str, str]:
    bloques = list(page.get_text("blocks"))
    labels_block = None
    for b in bloques:
        n = _norm(b[4])
        if "ZONA DE RIESGO" in n and "VEHICULOS" in n and "SERVICIO DE GRUA" in n:
            labels_block = b
            break
    if labels_block is None:
        return {}

    labels = _lineas(labels_block[4])
    x0, y0, x1, y1 = labels_block[:4]
    candidatos = []
    for b in bloques:
        bx0, by0, bx1, by1 = b[:4]
        # La columna numérica intermedia suele arrancar cerca de x=250; los
        # valores descriptivos reales de la tabla arrancan cerca de x=327.
        # PyMuPDF a veces divide esa columna descriptiva en dos bloques, por eso
        # reunimos TODOS los bloques derechos solapados y los concatenamos por Y.
        if bx0 < max(300.0, x1 + 65):
            continue
        solapa = min(y1, by1) - max(y0, by0)
        vals = _lineas(b[4])
        if solapa > 20 and vals:
            candidatos.append((by0, bx0, vals))
    if not candidatos:
        return {}
    candidatos.sort(key=lambda item: (item[0], item[1]))
    valores = []
    for _by0, _bx0, vals in candidatos:
        valores.extend(vals)
    limite = min(len(labels), len(valores))
    return {re.sub(r"\s+", " ", labels[i]).strip().upper(): valores[i] for i in range(limite)}


def _seccion(page) -> str:
    for b in page.get_text("blocks"):
        lineas = _lineas(b[4])
        if len(lineas) >= 2 and _norm(lineas[-1]).startswith("SECCION"):
            return lineas[0]
    texto = page.get_text("text") or ""
    n = _norm(texto)
    if "MOTOVEHICULOS" in n:
        return "MOTOVEHICULOS"
    if "AUTOMOTORES" in n:
        return "AUTOMOTORES"
    return ""


def _plan(page) -> tuple[str, str]:
    for b in page.get_text("blocks"):
        lineas = _lineas(b[4])
        if any(_norm(x).startswith("PLAN:") for x in lineas):
            candidatas = [x for x in lineas if not _norm(x).startswith("PLAN:")]
            if candidatas:
                bruto = candidatas[0]
                m = re.match(r"^\s*([A-Z0-9]+)\s*-", bruto, flags=re.I)
                codigo = (m.group(1) if m else bruto.split()[0]).upper().strip()
                if codigo in {"CNEW", "C_NEU", "CNEU"}:
                    codigo = "C"
                return codigo, bruto
    return "", ""


def _numero_cotizacion(texto: str) -> str:
    m = re.search(r"(?m)^\s*(\d{6,})\s*\n\s*Cotizaci[oó]n\b", texto, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r"Cotizaci[oó]n\s+(\d{6,})", texto, flags=re.I)
    return m.group(1) if m else ""


def _producto(texto: str) -> str:
    m = re.search(r"Producto:\s*([^\n]+)", texto, flags=re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _suma_asegurada(page) -> Decimal | None:
    words = page.get_text("words")
    # Ubicamos el rótulo por coordenadas y tomamos el primer importe justo debajo.
    for i, w in enumerate(words):
        x0, y0, x1, y1, txt = w[:5]
        if _norm(txt) != "SUMA":
            continue
        # "asegurada" debe estar en la misma línea y cerca.
        cerca = [z for z in words if abs(z[1] - y0) < 2.0 and z[0] >= x1 and _norm(z[4]).startswith("ASEGURADA")]
        if not cerca:
            continue
        candidates = []
        for z in words:
            zx0, zy0, zx1, zy1, ztxt = z[:5]
            if zy0 <= y1 or zy0 > y1 + 35:
                continue
            if zx0 < x0 - 10:
                continue
            if re.fullmatch(r"[\d.,]+", str(ztxt)) and any(ch.isdigit() for ch in str(ztxt)):
                try:
                    valor = _money_decimal(str(ztxt))
                except ValueError:
                    continue
                if valor >= Decimal("10000"):
                    candidates.append((zy0, zx0, valor))
        if candidates:
            candidates.sort()
            return candidates[0][2]
    return None


def _limite_rc(page) -> Decimal | None:
    for b in page.get_text("blocks"):
        if "LIMITE RESP. CIVIL" not in _norm(b[4]):
            continue
        m = re.search(r"\$\s*([\d.,]+)", str(b[4]), flags=re.I)
        if m:
            try:
                return _money_decimal(m.group(1))
            except ValueError:
                return None
    return None


def _cuotas(texto: str) -> tuple[int | None, Decimal | None]:
    m = re.search(r"(\d+)\s+cuotas?\s+de\s+\$\s*([\d.,]+)", texto, flags=re.I)
    if not m:
        return None, None
    try:
        return int(m.group(1)), _money_decimal(m.group(2))
    except ValueError:
        return int(m.group(1)), None


def _total_contado(texto: str) -> Decimal | None:
    m = re.search(r"total\s+al\s+contado,?\s+el\s+monto\s+es\s+de\s+\$\s*([\d.,]+)", texto, flags=re.I)
    if not m:
        return None
    try:
        return _money_decimal(m.group(1))
    except ValueError:
        return None


def _franquicia(tabla: dict[str, str]) -> tuple[int | None, Decimal | None, str]:
    descripcion = str(tabla.get("FRANQUICIA POR DAÑO") or "").strip()
    importe_raw = str(tabla.get("DESCRIPCION FRANQUICIA") or "").strip()
    pct = None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", descripcion)
    if m:
        try:
            pct = int(Decimal(m.group(1).replace(",", ".")))
        except Exception:
            pct = None
    importe = None
    if importe_raw and re.search(r"\d", importe_raw) and "NO " not in _norm(importe_raw):
        try:
            candidato = _money_decimal(importe_raw)
            importe = candidato if candidato > 0 else None
        except ValueError:
            importe = None
    return pct, importe, descripcion


def _grua(tabla: dict[str, str]) -> tuple[bool | None, str]:
    raw = str(tabla.get("SERVICIO DE GRUA") or "").strip()
    n = _norm(raw)
    if "CON SERV. DE GRUA" in n or "CON SERVICIO DE GRUA" in n:
        return True, raw
    if "SIN SERV. DE GRUA" in n or "SIN SERVICIO DE GRUA" in n:
        return False, raw
    return None, raw


def _cobertura(codigo: str, plan_nombre: str) -> tuple[str, str]:
    c = str(codigo or "").upper().strip()
    if c in {"A", "A4"}:
        return "Responsabilidad Civil", "Responsabilidad civil."
    if c == "B":
        return "Cobertura B", "Responsabilidad civil, incendio total, robo/hurto total y destrucción total por accidente."
    if c == "B1":
        return "Cobertura B1", "Responsabilidad civil, incendio total y robo/hurto total."
    if c == "C":
        return "Terceros Completo", "Responsabilidad civil, incendio total y parcial, robo total y parcial y destrucción total por accidente."
    if c == "C1":
        return "Terceros Completo", "Responsabilidad civil, incendio total y parcial y robo total y parcial."
    if c == "CF":
        return "Terceros Completo Full", "Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total por accidente. Cubre ruedas, vidrios, granizo y cerraduras."
    if c.startswith("TD"):
        return "Todo Riesgo", "Responsabilidad civil, incendio total y parcial, robo total y parcial, destrucción total y daños parciales por accidente."
    # No inventar: si aparece un código desconocido, conservar el nombre del PDF
    # como etiqueta y no crear un speech que el documento no confirma.
    return plan_nombre or c or "Cobertura", ""


def extraer_cotizacion_federacion(pdf_bytes: bytes) -> dict:
    if not pdf_bytes:
        raise ValueError("El PDF está vacío.")
    try:
        doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
    except Exception as exc:
        raise ValueError("No pude abrir el PDF de Federación Patronal.") from exc
    try:
        if doc.page_count < 1:
            raise ValueError("El PDF no contiene páginas.")
        paginas = [page.get_text("text") or "" for page in doc]
        texto = "\n".join(paginas)
        texto_norm = _norm(texto)
        es_federacion = "FEDERACION PATRONAL" in texto_norm and "COTIZACION" in texto_norm
        if not es_federacion:
            return {"es_federacion": False}

        page = doc[0]
        tabla = _tabla_automotor(page)
        codigo, plan_nombre = _plan(page)
        seccion = _seccion(page)
        producto = _producto(texto)
        suma = _suma_asegurada(page)
        limite_rc = _limite_rc(page)
        cantidad_cuotas, cuota = _cuotas(texto)
        contado = _total_contado(texto)
        franquicia_pct, franquicia_importe, franquicia_descripcion = _franquicia(tabla)
        grua, grua_raw = _grua(tabla)
        nombre_cliente, descripcion_cliente = _cobertura(codigo, plan_nombre)

        marca = str(tabla.get("MARCA") or "").strip()
        modelo = str(tabla.get("MODELO") or "").strip()
        anio = str(tabla.get("AÑO") or tabla.get("ANO") or "").strip()
        vehiculo = modelo or marca
        tipo_norm = _norm(seccion + " " + producto)
        # No usar ``"MOTO" in ...``: AUTOMOTORES también contiene esa secuencia.
        # Federación identifica las motos explícitamente como MOTOVEHICULOS.
        tipo_vehiculo = "moto" if re.search(r"\bMOTOVEHICULOS\b", tipo_norm) else "auto"

        return {
            "es_federacion": True,
            "compania": "Federación Patronal",
            "numero_cotizacion": _numero_cotizacion(texto),
            "seccion": seccion,
            "producto": producto,
            "tipo_vehiculo": tipo_vehiculo,
            "marca": marca,
            "modelo": modelo,
            "vehiculo": vehiculo,
            "anio": anio,
            "suma_asegurada": str(suma) if suma is not None else None,
            "suma_asegurada_formateada": _fmt_decimal(suma, False),
            "codigo": codigo,
            "codigo_visual": codigo,
            "nombre_plan": plan_nombre,
            "nombre_cliente": nombre_cliente,
            "descripcion_cliente": descripcion_cliente,
            "limite_rc": str(limite_rc) if limite_rc is not None else None,
            "limite_rc_formateado": _fmt_decimal(limite_rc, False),
            "servicio_grua": grua,
            "servicio_grua_texto": grua_raw,
            "franquicia_pct": franquicia_pct,
            "franquicia_importe": str(franquicia_importe) if franquicia_importe is not None else None,
            "franquicia_importe_formateado": _fmt_decimal(franquicia_importe, False),
            "franquicia_descripcion": franquicia_descripcion,
            "cantidad_cuotas": cantidad_cuotas,
            "precio_cuota": str(cuota) if cuota is not None else None,
            "precio_cuota_formateado": _fmt_decimal(cuota, False),
            "total_contado": str(contado) if contado is not None else None,
            "total_contado_formateado": _fmt_decimal(contado, False),
        }
    finally:
        doc.close()


__all__ = ["extraer_cotizacion_federacion"]
