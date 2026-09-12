# -*- coding: utf-8 -*-
"""Parser determinístico para PDFs de cotización de La Mercantil Andina."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
import unicodedata

import fitz

from mercantil_coberturas import ORDEN_VISUAL, entrada


def _norm(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    valor = "".join(ch for ch in valor if not unicodedata.combining(ch))
    valor = valor.upper().replace("\r", "\n")
    valor = re.sub(r"[ \t]+", " ", valor)
    return valor


def _money_decimal(texto: str) -> Decimal:
    limpio = str(texto or "").strip().replace("$", "").replace(" ", "")
    if not limpio:
        raise ValueError("Importe vacío")
    # Formato AR: 1.234.567,89
    if "," in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    else:
        partes = limpio.split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            limpio = limpio.replace(".", "")
    try:
        return Decimal(limpio)
    except InvalidOperation as exc:
        raise ValueError(f"Importe inválido: {texto}") from exc


def _fmt_decimal(v: Decimal) -> str:
    q = v.quantize(Decimal("0.01"))
    entero, dec = f"{q:.2f}".split(".")
    entero = f"{int(entero):,}".replace(",", ".")
    return f"${entero},{dec}"


def _extraer_valor_despues(texto: str, etiqueta: str, patron_valor: str) -> str:
    m = re.search(rf"{etiqueta}\s*\n+\s*({patron_valor})", texto, flags=re.I)
    return m.group(1).strip() if m else ""


def _codigo_real_desde_encabezado(codigo_bruto: str) -> str:
    valor = re.sub(r"\s+", " ", str(codigo_bruto or "").strip().upper())
    if valor.startswith("D2 "):
        m = re.search(r"D2\s+(0020|0030|0040|0050)", valor)
        return f"D2 {m.group(1)}" if m else valor
    if valor in {"M BASICA", "M BÁSICA"}:
        return "M BASICA"
    if valor == "M PLUS":
        return "M PLUS"
    return valor


def extraer_cotizacion_mercantil(pdf_bytes: bytes) -> dict:
    if not pdf_bytes:
        raise ValueError("El PDF está vacío.")
    try:
        doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
    except Exception as exc:
        raise ValueError("No pude abrir el PDF de Mercantil.") from exc
    try:
        paginas = [page.get_text("text") or "" for page in doc]
    finally:
        doc.close()
    texto = "\n".join(paginas)
    texto_norm = _norm(texto)
    es_mercantil = "LA MERCANTIL ANDINA S.A." in texto_norm or "MERCANTIL ANDINA" in texto_norm
    if not es_mercantil:
        return {"es_mercantil": False, "coberturas": []}

    modelo = _extraer_valor_despues(texto, r"Datos de riesgo", r"[^\n]+")
    anio = _extraer_valor_despues(texto, r"AÑO DE FABRICACIÓN", r"\d{4}") or _extraer_valor_despues(texto_norm, r"ANO DE FABRICACION", r"\d{4}")
    suma_raw = _extraer_valor_despues(texto, r"SUMA ASEGURADA", r"\$?[\d\.]+(?:,\d{1,2})?")
    plan = _extraer_valor_despues(texto, r"VIGENCIA / PLAN DE PAGO", r"[^\n]+")
    suma = None
    if suma_raw:
        try:
            suma = _money_decimal(suma_raw)
        except ValueError:
            suma = None

    # Cada cobertura se reconoce desde "Cobertura X" hasta "Por cuota".
    cobertura_re = re.compile(
        r"Cobertura\s+(?P<codigo>D2\s+(?:0020|0030|0040|0050)|M\s+BASICA|M\s+PLUS|B3|B0|B1|B|A)\s*\n"
        r"(?P<bloque>.*?)(?=\nPor cuota)",
        flags=re.I | re.S,
    )
    encontradas = []
    vistos = set()
    for m in cobertura_re.finditer(texto):
        real = _codigo_real_desde_encabezado(m.group("codigo"))
        if real in vistos:
            continue
        vistos.add(real)
        cat = entrada(real)
        if not cat:
            continue
        bloque = re.sub(r"\s+", " ", m.group("bloque")).strip()
        precios = re.findall(r"\$\s*([\d\.]+,\d{2})", bloque)
        if not precios:
            continue
        precio_raw = "$" + precios[-1]
        precio = _money_decimal(precio_raw)
        franquicia_pct = cat.get("franquicia_pct")
        franquicia_importe = None
        if cat.get("tipo") == "todo_riesgo":
            fm = re.search(r"FRANQUICIA\s+(\d+)\s*%\s*\(\$\s*([\d\.]+(?:,\d{2})?)\)", bloque, flags=re.I)
            if fm:
                franquicia_pct = int(fm.group(1))
                franquicia_importe = _money_decimal("$" + fm.group(2))
        tooltip = f"{cat['nombre_cliente']} — {cat['descripcion_cliente']}"
        if franquicia_pct:
            extra = f" Franquicia {franquicia_pct}%"
            if franquicia_importe is not None:
                extra += f" · {_fmt_decimal(franquicia_importe)}"
            tooltip += " —" + extra
        encontradas.append({
            "codigo_real": real,
            "codigo_visual": cat["codigo_visual"],
            "nombre_cliente": cat["nombre_cliente"],
            "descripcion_cliente": cat["descripcion_cliente"],
            "tipo_cobertura": cat["tipo"],
            "precio_base": str(precio),
            "precio_base_formateado": _fmt_decimal(precio),
            "max_descuento": int(cat["max_descuento"]),
            "descuento_default": int(cat["max_descuento"]),
            "franquicia_pct": franquicia_pct,
            "franquicia_importe": str(franquicia_importe) if franquicia_importe is not None else None,
            "franquicia_importe_formateado": _fmt_decimal(franquicia_importe) if franquicia_importe is not None else "",
            "tooltip": tooltip,
        })

    orden = {codigo: i for i, codigo in enumerate(ORDEN_VISUAL)}
    encontradas.sort(key=lambda x: orden.get(x["codigo_real"], 999))
    return {
        "es_mercantil": True,
        "compania": "Mercantil Andina",
        "modelo": modelo,
        "anio": anio,
        "suma_asegurada": str(suma) if suma is not None else None,
        "suma_asegurada_formateada": _fmt_decimal(suma) if suma is not None else "",
        "plan_pago": plan,
        "coberturas": encontradas,
        "cantidad": len(encontradas),
    }


__all__ = ["extraer_cotizacion_mercantil"]
