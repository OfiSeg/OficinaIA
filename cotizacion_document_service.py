"""Generación documental determinística de propuestas de cotización.

La plantilla Word es la fuente canónica. Este módulo NO consulta IA, NO relee
PDFs/imágenes y NO recalcula precios, descuentos ni franquicias: recibe datos
estructurados ya resueltos por el cotizador y sólo los maqueta.
"""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


MARCADOR = "{{COTIZACION}}"
ESTILOS_REQUERIDOS = (
    "Cotizacion Cuerpo",
    "Cotizacion Opcion",
    "Cotizacion Etiqueta",
    "Cotizacion Precio",
    "Cotizacion Nota",
    "Cotizacion Item",
    "Cotizacion Meta",
)
FORMATOS_SOPORTADOS = {"docx", "pdf", "png", "jpg"}
VALORES_VACIOS = {"", "undefined", "null", "none", "n/a", "na", "—"}
AZUL_INSTITUCIONAL = "102A56"

COMPANIA_DISPLAY = {
    "atm": "ATM",
    "federacion_patronal": "Federación Patronal",
    "mercantil_andina": "Mercantil Andina",
    "san_cristobal": "San Cristóbal",
    "agrosalta": "Agrosalta",
    "rivadavia": "Rivadavia",
    "allianz": "Allianz",
}


PERFIL_NOMBRE_COMERCIAL = {
    "RC": "RESPONSABILIDAD CIVIL",
    "B": "ROBO, INCENDIO Y ACCIDENTE TOTAL",
    "B1": "ROBO E INCENDIO TOTAL",
    "C": "TERCEROS COMPLETO",
    "C1": "TERCEROS COMPLETO",
    "C_PLUS": "TERCEROS COMPLETO PLUS",
    "LB": "ROBO E INCENDIO + ROBO PARCIAL AL AMPARO + ACCIDENTE TOTAL",
    "LB1": "ROBO E INCENDIO + ROBO PARCIAL AL AMPARO",
    "TODO_RIESGO": "TODO RIESGO",
    "TR": "TODO RIESGO",
}

ORDEN_COMERCIAL = {
    "RESPONSABILIDAD CIVIL": 10,
    "ROBO TOTAL": 20,
    "ROBO E INCENDIO TOTAL": 30,
    "ROBO E INCENDIO TOTAL Y/O PARCIAL": 35,
    "ROBO, INCENDIO Y ACCIDENTE TOTAL": 40,
    "ROBO E INCENDIO TOTAL Y/O PARCIAL + ACCIDENTE TOTAL": 50,
    "ROBO E INCENDIO + ROBO PARCIAL AL AMPARO": 57,
    "TERCEROS COMPLETO": 60,
    "ROBO E INCENDIO + ROBO PARCIAL AL AMPARO + ACCIDENTE TOTAL": 62,
    "TERCEROS COMPLETO PLUS": 70,
    "TERCEROS COMPLETO PREMIUM": 75,
    "TODO RIESGO": 80,
}


class CotizacionDocumentError(ValueError):
    """Error funcional de datos/plantilla."""


class CotizacionConversionError(RuntimeError):
    """Error de conversión DOCX → PDF/imagen."""


def _texto(valor, *, max_len=1200) -> str:
    texto = str(valor or "").replace("\x00", "").strip()
    if texto.lower() in VALORES_VACIOS:
        return ""
    # El renderer recibe datos, nunca Markdown. Si alguna fuente arrastra
    # delimitadores de formato, no deben terminar visibles en la carta.
    texto = texto.replace("**", "")
    return texto[:max_len]


def _normalizar_clave(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto).strip()
    return re.sub(r"\s+", " ", texto)


def _slug_archivo(valor: str, *, max_len=58) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")
    texto = re.sub(r"_+", "_", texto)
    return texto[:max_len].strip("_")


def _normalizar_moneda_visual(valor: str) -> str:
    """Uniforma sólo la presentación monetaria sin recalcular importes."""
    texto = _texto(valor, max_len=100)
    if not texto:
        return ""
    return re.sub(r"^\$\s+", "$", texto)


def _normalizar_porcentaje(valor: str) -> str:
    """Devuelve el porcentaje sin signo final para evitar duplicados como 2%%."""
    texto = _texto(valor, max_len=30).strip()
    if not texto:
        return ""
    return re.sub(r"(?:\s*%)+\s*$", "", texto).strip()


def normalizar_porcentaje(valor: str) -> str:
    """Normaliza 2, ``2%`` o ``2%%`` a la presentación comercial ``2%``."""
    limpio = _normalizar_porcentaje(valor)
    return f"{limpio}%" if limpio else ""


def _normalizar_beneficio_para_carta(texto: str) -> list[str]:
    """Normaliza vocabulario comercial sin agregar riesgos no presentes.

    Puede devolver más de un ítem únicamente cuando la fuente trae dos riesgos
    explícitos en la misma frase (por ejemplo destrucción total + daños
    parciales). Lo que no se reconoce se conserva limpio para no perder dato.
    """
    original = _texto(texto, max_len=650)
    if not original:
        return []
    clave = _normalizar_clave(original)

    if clave == "sin grua":
        return ["Sin grúa"]
    if clave in {"incluye grua", "grua", "servicio de grua", "asistencia de grua"}:
        return ["Incluye grúa"]

    if clave in {
        "destruccion total y danos parciales por accidente",
        "destruccion total por accidente y danos parciales por accidente",
    }:
        return ["Destrucción Total por Accidente", "Daños Parciales por Accidente"]
    if clave in {"destruccion total por accidente", "destruccion total accidente"}:
        return ["Destrucción Total por Accidente"]
    if clave in {"danos parciales por accidente", "danos parciales accidente"}:
        return ["Daños Parciales por Accidente"]

    if clave == "responsabilidad civil":
        return ["Responsabilidad Civil"]

    if clave in {
        "robo total y parcial",
        "robo hurto total y parcial",
        "robo y hurto total y parcial",
    }:
        return ["Robo/Hurto Total y Parcial"]
    if clave in {"robo total", "robo hurto total", "robo y hurto total", "hurto total"}:
        return ["Robo/Hurto Total"]
    if clave in {"incendio total y parcial", "incendio total parcial"}:
        return ["Incendio Total y Parcial"]
    if clave == "incendio total":
        return ["Incendio Total"]

    extras = ("rueda", "vidrio", "granizo", "cerradura")
    if all(token in clave for token in extras):
        salida = ["Ruedas, vidrios, granizo y cerraduras"]
        if "grua" in clave:
            salida.append("Incluye grúa")
        return salida

    return [original]


def _limpiar_nombre_tecnico(nombre: str) -> str:
    """Quita envoltorios/códigos cuando queda un nombre comercial útil."""
    original = _texto(nombre, max_len=180)
    if not original:
        return "Cobertura"
    limpio = original.strip()
    # "COBERTURA B0" no aporta un nombre comercial; se resolverá por riesgos.
    limpio = re.sub(r"^cobertura\s+", "", limpio, flags=re.I).strip()
    # D4 ALTA GAMA VIP ... -> ALTA GAMA VIP ...; no se hace para una palabra
    # aislada porque entonces perderíamos el único identificador disponible.
    m = re.match(r"^(?:[A-Z]{1,3}\d+(?:\.\d+)?|[A-Z]\d*[A-Z]?)\s+(.+)$", limpio, flags=re.I)
    if m and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", m.group(1)):
        limpio = m.group(1).strip()
    limpio = re.sub(r"\s*-\s*\d+(?:[.,]\d+)?\s*%+", "", limpio).strip(" -·")
    limpio = re.sub(r"\bC/\s*GRANIZO\b", "CON GRANIZO", limpio, flags=re.I)
    limpio = re.sub(r"\s*-\s*", " · ", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip(" ·-")
    return limpio or original


def _flags_riesgo(contenidos: list[dict], nombre: str) -> dict[str, bool]:
    beneficios = [c.get("texto", "") for c in contenidos if c.get("tipo") == "beneficio"]
    claves = {_normalizar_clave(x) for x in beneficios if x}
    nombre_key = _normalizar_clave(nombre)
    return {
        "rc": "responsabilidad civil" in claves or "responsabilidad civil" in nombre_key,
        "robo_total": any(k in claves for k in {"robo hurto total", "robo hurto total y parcial"}),
        "robo_parcial": "robo hurto total y parcial" in claves,
        "incendio_total": any(k in claves for k in {"incendio total", "incendio total y parcial"}),
        "incendio_parcial": "incendio total y parcial" in claves,
        "dt": "destruccion total por accidente" in claves,
        "dp": "danos parciales por accidente" in claves,
        "extras": "ruedas vidrios granizo y cerraduras" in claves,
    }


def normalizar_cobertura_para_carta(alternativa: dict) -> dict:
    """Uniforma una alternativa sin contradecir al cotizador.

    Regla de autoridad: si el frontend ya envía ``nombre_comercial`` y/o
    ``variante_comercial``, esos campos son canónicos. El renderer documental
    sólo normaliza tipografía y beneficios. La inferencia por riesgos queda como
    fallback para fuentes antiguas o incompletas.
    """
    alt = dict(alternativa or {})
    contenidos: list[dict] = []
    vistos_beneficios: set[str] = set()
    for item in alt.get("contenidos") or []:
        tipo = str(item.get("tipo") or "beneficio").lower() if isinstance(item, dict) else "beneficio"
        raw = item.get("texto") if isinstance(item, dict) else item
        if tipo == "nota":
            texto = _texto(raw, max_len=650)
            if texto:
                contenidos.append({"tipo": "nota", "texto": texto})
            continue
        for texto in _normalizar_beneficio_para_carta(raw):
            key = _normalizar_clave(texto)
            if key and key not in vistos_beneficios:
                vistos_beneficios.add(key)
                contenidos.append({"tipo": "beneficio", "texto": texto})
    alt["contenidos"] = contenidos

    original = _texto(alt.get("nombre"), max_len=180) or "Cobertura"
    comercial_explicit = _texto(alt.get("nombre_comercial"), max_len=180)
    variante_explicit = _texto(alt.get("variante_comercial"), max_len=120)
    familia = _texto(alt.get("familia"), max_len=80).upper()
    key = _normalizar_clave(original)
    flags = _flags_riesgo(contenidos, original)

    if comercial_explicit and not _normalizar_clave(comercial_explicit).startswith("cobertura "):
        nombre_base = _limpiar_nombre_tecnico(comercial_explicit).upper()
    elif familia in PERFIL_NOMBRE_COMERCIAL:
        nombre_base = PERFIL_NOMBRE_COMERCIAL[familia]
    elif flags["dp"] or "todo riesgo" in key:
        nombre_base = "TODO RIESGO"
    elif "terceros completo" in key and any(x in key for x in ("premium", "black", "vip")):
        nombre_base = "TERCEROS COMPLETO PREMIUM"
    elif "terceros completo" in key and "plus" in key:
        nombre_base = "TERCEROS COMPLETO PLUS"
    elif "terceros completo" in key:
        nombre_base = "TERCEROS COMPLETO"
    elif key == "responsabilidad civil":
        nombre_base = "RESPONSABILIDAD CIVIL"
    elif flags["robo_total"] and flags["incendio_total"] and flags["dt"]:
        if flags["robo_parcial"] or flags["incendio_parcial"]:
            if flags["rc"]:
                nombre_base = "TERCEROS COMPLETO PLUS" if flags["extras"] else "TERCEROS COMPLETO"
            else:
                nombre_base = "ROBO E INCENDIO TOTAL Y/O PARCIAL + ACCIDENTE TOTAL"
        else:
            nombre_base = "ROBO, INCENDIO Y ACCIDENTE TOTAL"
    elif flags["robo_total"] and flags["incendio_total"]:
        nombre_base = "ROBO E INCENDIO TOTAL"
    elif flags["robo_total"]:
        nombre_base = "ROBO TOTAL"
    elif flags["rc"] and not any(flags[x] for x in ("robo_total", "incendio_total", "dt", "dp")):
        nombre_base = "RESPONSABILIDAD CIVIL"
    elif flags["incendio_total"] and flags["incendio_parcial"]:
        nombre_base = "INCENDIO TOTAL Y PARCIAL"
    elif flags["incendio_total"]:
        nombre_base = "INCENDIO TOTAL"
    else:
        nombre_base = _limpiar_nombre_tecnico(original).upper()

    variantes: list[str] = []
    if variante_explicit:
        variantes.extend([x.strip().upper() for x in re.split(r"\s*[·|]\s*", variante_explicit) if x.strip()])

    franquicia_pct = normalizar_porcentaje(alt.get("franquicia_pct"))
    if nombre_base == "TODO RIESGO" and franquicia_pct and not any(_normalizar_clave(x).startswith("franquicia") for x in variantes):
        variantes.append(f"FRANQUICIA {franquicia_pct}")

    variante_grua = _normalizar_clave(alt.get("variante_grua"))
    if variante_grua in {"con grua", "sin grua"}:
        etiqueta_grua = "CON GRÚA" if variante_grua == "con grua" else "SIN GRÚA"
        if etiqueta_grua not in variantes:
            variantes.append(etiqueta_grua)
        alt["contenidos"] = [
            item for item in alt["contenidos"]
            if _normalizar_clave(item.get("texto")) not in {"incluye grua", "sin grua"}
        ]

    variantes = list(dict.fromkeys(variantes))
    alt["nombre_comercial"] = nombre_base
    alt["variante_comercial"] = " · ".join(variantes)
    alt["nombre"] = " · ".join([nombre_base, *variantes])
    alt["orden_comercial"] = ORDEN_COMERCIAL.get(nombre_base, 55)
    return alt


def catalogo_companias(logos_dir: Path) -> list[dict]:
    """Expone el catálogo del manifiesto sin duplicar nombres ni assets."""
    logos_dir = Path(logos_dir)
    manifest_path = logos_dir / "logos_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    aliases_por_key: dict[str, list[str]] = {}
    for alias, key in (manifest.get("aliases") or {}).items():
        if isinstance(key, str):
            aliases_por_key.setdefault(key, []).append(str(alias))
    preferidas = ["atm", "federacion_patronal", "mercantil_andina", "san_cristobal", "agrosalta", "rivadavia", "allianz"]
    salida = []
    for key in preferidas:
        info = manifest.get(key)
        if not isinstance(info, dict):
            continue
        filename = Path(str(info.get("file") or "")).name
        if not filename or not (logos_dir / filename).is_file():
            continue
        nombre = COMPANIA_DISPLAY.get(key, key.replace("_", " ").title())
        aliases = list(dict.fromkeys([nombre, key.replace("_", " "), *aliases_por_key.get(key, [])]))
        salida.append({"key": key, "nombre": nombre, "file": filename, "aliases": aliases})
    return salida


class CotizacionDocumentService:
    def __init__(self, *, template_path: Path, logos_dir: Path):
        self.template_path = Path(template_path)
        self.logos_dir = Path(logos_dir)
        self.manifest_path = self.logos_dir / "logos_manifest.json"
        self._manifest = self._cargar_manifest()
        self._aliases = self._construir_aliases()

    def _cargar_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            raise CotizacionDocumentError(f"No pude leer el manifiesto de logos: {exc}") from exc

    def _construir_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        raw = self._manifest.get("aliases") or {}
        if isinstance(raw, dict):
            for alias, key in raw.items():
                norm = _normalizar_clave(alias)
                if norm:
                    aliases[norm] = str(key or "").strip()
        # Las claves canónicas también son aliases válidos.
        for key, info in self._manifest.items():
            if key == "aliases" or not isinstance(info, dict):
                continue
            aliases.setdefault(_normalizar_clave(key), key)
            aliases.setdefault(_normalizar_clave(key.replace("_", " ")), key)
        return aliases

    def _resolver_clave_compania(self, compania: str) -> str | None:
        norm = _normalizar_clave(compania)
        if not norm:
            return None
        key = self._aliases.get(norm)
        if not key:
            # Fallback conservador por alias contenido, sin reglas de tamaño ni
            # heurísticas visuales por compañía.
            for alias, candidate in self._aliases.items():
                if len(alias) >= 4 and (norm == alias or norm.startswith(alias + " ") or alias in norm):
                    key = candidate
                    break
        return key if isinstance(self._manifest.get(key or ""), dict) else None

    def resolver_logo(self, compania: str) -> Path | None:
        key = self._resolver_clave_compania(compania)
        info = self._manifest.get(key or "")
        if not isinstance(info, dict):
            return None
        filename = Path(str(info.get("file") or "")).name
        if not filename:
            return None
        path = self.logos_dir / filename
        return path if path.exists() and path.is_file() else None

    def _clave_agrupacion_compania(self, compania: str) -> str:
        key = self._resolver_clave_compania(compania)
        if key:
            return f"asset:{key}"
        return f"texto:{_normalizar_clave(compania) or 'compania'}"

    def _nombre_visible_compania(self, compania: str) -> str:
        key = self._resolver_clave_compania(compania)
        if key and key in COMPANIA_DISPLAY:
            return COMPANIA_DISPLAY[key]
        return _texto(compania, max_len=120) or "Compañía"

    @staticmethod
    def _fila_repetible(row):
        tr_pr = row._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:tblHeader")) is None:
            header = OxmlElement("w:tblHeader")
            header.set(qn("w:val"), "true")
            tr_pr.append(header)

    @staticmethod
    def _fila_no_dividir(row):
        tr_pr = row._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:cantSplit")) is None:
            cant_split = OxmlElement("w:cantSplit")
            cant_split.set(qn("w:val"), "true")
            tr_pr.append(cant_split)

    @staticmethod
    def _margenes_celda(cell, *, top=0, start=0, bottom=0, end=0):
        tc_pr = cell._tc.get_or_add_tcPr()
        tc_mar = tc_pr.find(qn("w:tcMar"))
        if tc_mar is None:
            tc_mar = OxmlElement("w:tcMar")
            tc_pr.append(tc_mar)
        for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
            node = tc_mar.find(qn(f"w:{edge}"))
            if node is None:
                node = OxmlElement(f"w:{edge}")
                tc_mar.append(node)
            node.set(qn("w:w"), str(int(value)))
            node.set(qn("w:type"), "dxa")

    @staticmethod
    def _tabla_sin_bordes(table):
        tbl_pr = table._tbl.tblPr
        borders = tbl_pr.find(qn("w:tblBorders"))
        if borders is None:
            borders = OxmlElement("w:tblBorders")
            tbl_pr.append(borders)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            node = borders.find(qn(f"w:{edge}"))
            if node is None:
                node = OxmlElement(f"w:{edge}")
                borders.append(node)
            node.set(qn("w:val"), "nil")
        width = tbl_pr.find(qn("w:tblW"))
        if width is None:
            width = OxmlElement("w:tblW")
            tbl_pr.append(width)
        width.set(qn("w:w"), "5000")
        width.set(qn("w:type"), "pct")
        indent = tbl_pr.find(qn("w:tblInd"))
        if indent is None:
            indent = OxmlElement("w:tblInd")
            tbl_pr.append(indent)
        indent.set(qn("w:w"), "0")
        indent.set(qn("w:type"), "dxa")

    @staticmethod
    def _borde_inferior_celda(cell, *, color=AZUL_INSTITUCIONAL, size=5):
        tc_pr = cell._tc.get_or_add_tcPr()
        borders = tc_pr.find(qn("w:tcBorders"))
        if borders is None:
            borders = OxmlElement("w:tcBorders")
            tc_pr.append(borders)
        bottom = borders.find(qn("w:bottom"))
        if bottom is None:
            bottom = OxmlElement("w:bottom")
            borders.append(bottom)
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), str(int(size)))
        bottom.set(qn("w:space"), "0")
        bottom.set(qn("w:color"), color)

    @staticmethod
    def _fuente_run(run, *, name="Georgia", size=10.5, bold=False, color=AZUL_INSTITUCIONAL):
        run.font.name = name
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor.from_string(color)
        r_pr = run._r.get_or_add_rPr()
        r_fonts = r_pr.rFonts
        if r_fonts is None:
            r_fonts = OxmlElement("w:rFonts")
            r_pr.insert(0, r_fonts)
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            r_fonts.set(qn(f"w:{attr}"), name)

    def _encabezado_compania_en_tabla(self, table, compania: str, *, primera=False):
        row = table.rows[0]
        self._fila_repetible(row)
        self._fila_no_dividir(row)
        cell = row.cells[0]
        self._margenes_celda(cell, top=70 if primera else 100, bottom=65)
        self._borde_inferior_celda(cell, size=5)  # 0,625 pt

        p = cell.paragraphs[0]
        p.style = "Cotizacion Meta"
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.keep_with_next = True
        logo = self.resolver_logo(compania)
        if logo:
            # El logo ya identifica visualmente a la compañía. No repetimos su
            # nombre como texto en Word/PDF; evita encabezados redundantes y
            # deja más aire para las coberturas.
            p.add_run().add_picture(str(logo), height=Cm(0.65))
        else:
            # Fallback accesible para compañías sin asset conocido.
            run = p.add_run(self._nombre_visible_compania(compania).upper())
            self._fuente_run(run, size=10.5, bold=True)

    @staticmethod
    def _agregar_linea_meta_celda(cell, etiqueta: str, valor: str):
        p = cell.add_paragraph(style="Cotizacion Meta")
        r = p.add_run(etiqueta)
        r.bold = True
        p.add_run(f" · {valor}")
        return p

    def _agregar_cobertura_a_tabla(self, table, alt: dict, *, ultima=False):
        row = table.add_row()
        outer = row.cells[0]
        self._margenes_celda(outer, top=0, bottom=0)
        # La tabla exterior necesita poder paginar normalmente para que una
        # compañía extensa pueda empezar en la primera página. Cada cobertura
        # vive dentro de una tabla anidada de una sola fila no divisible: así
        # LibreOffice puede cortar ENTRE alternativas, pero no dentro de una.
        anchor = outer.paragraphs[0]
        anchor.paragraph_format.space_before = Pt(0)
        anchor.paragraph_format.space_after = Pt(0)
        anchor.paragraph_format.line_spacing = Pt(1)
        anchor.add_run("").font.size = Pt(1)
        nested = outer.add_table(rows=1, cols=1)
        self._tabla_sin_bordes(nested)
        nested.autofit = True
        nested_row = nested.rows[0]
        self._fila_no_dividir(nested_row)
        cell = nested_row.cells[0]
        self._margenes_celda(cell, top=85, bottom=40)
        if not ultima:
            self._borde_inferior_celda(cell, color="DCE4EC", size=2)

        titulo = cell.paragraphs[0]
        titulo.style = "Cotizacion Opcion"
        titulo.paragraph_format.space_before = Pt(0)
        titulo.paragraph_format.space_after = Pt(4)
        titulo.paragraph_format.keep_with_next = True
        titulo.add_run(alt["nombre"].upper())

        if alt["suma"]:
            p = self._agregar_linea_meta_celda(cell, "Suma asegurada", alt["suma"])
            p.paragraph_format.keep_with_next = True

        franquicia = " · ".join(
            x
            for x in (
                f"{alt['franquicia_pct']}%" if alt["franquicia_pct"] else "",
                alt["franquicia_importe"],
            )
            if x
        )
        if franquicia:
            p = self._agregar_linea_meta_celda(cell, "Franquicia", franquicia)
            p.paragraph_format.keep_with_next = True

        for contenido in alt["contenidos"]:
            if contenido["tipo"] == "nota":
                p = cell.add_paragraph(contenido["texto"], style="Cotizacion Nota")
            else:
                p = cell.add_paragraph(f"• {contenido['texto']}", style="Cotizacion Item")
            p.paragraph_format.keep_together = True
            p.paragraph_format.keep_with_next = True

        precios = []
        if alt["cuponera"] or alt["adherido"]:
            if alt["cuponera"]:
                precios.append(f"Precio cuponera · {alt['cuponera']}")
            if alt["adherido"]:
                precios.append(f"Precio adherido · {alt['adherido']}")
        elif alt["precio"]:
            precios.append(f"Precio por cuota · {alt['precio']}")

        for idx, texto in enumerate(precios):
            p = cell.add_paragraph(texto, style="Cotizacion Precio")
            p.paragraph_format.keep_together = True
            p.paragraph_format.keep_with_next = idx < len(precios) - 1
            if idx == len(precios) - 1:
                p.paragraph_format.space_after = Pt(4)

        # Si no hubo precio, el último párrafo sigue cerrando el bloque con aire.
        if not precios and cell.paragraphs:
            cell.paragraphs[-1].paragraph_format.keep_with_next = False
            cell.paragraphs[-1].paragraph_format.space_after = Pt(4)

        # python-docx mantiene un párrafo final obligatorio después de una
        # tabla anidada. Reducirlo evita introducir aire visual artificial.
        if outer.paragraphs:
            tail = outer.paragraphs[-1]
            tail.paragraph_format.space_before = Pt(0)
            tail.paragraph_format.space_after = Pt(0)
            tail.paragraph_format.line_spacing = Pt(1)
            if not tail.runs:
                tail.add_run("")
            for run in tail.runs:
                run.font.size = Pt(1)

    def _crear_tabla_compania(self, doc: Document, marker, grupo: dict, *, primera=False):
        table = doc.add_table(rows=1, cols=1)
        self._tabla_sin_bordes(table)
        table.autofit = True
        # Mover la tabla al marcador: la plantilla sigue siendo la dueña del
        # resto del documento y no se reconstruye ninguna parte fija.
        marker._p.addprevious(table._tbl)
        self._encabezado_compania_en_tabla(table, grupo["compania"], primera=primera)
        alternativas = grupo["alternativas"]
        for indice, alt in enumerate(alternativas):
            self._agregar_cobertura_a_tabla(table, alt, ultima=indice == len(alternativas) - 1)
        return table

    @staticmethod
    def _insertar_separador_estructural(marker):
        """Evita que Word/LibreOffice fusionen dos tablas de compañías.

        Es un separador estructural único entre secciones, no espaciado manual
        para forzar paginación. Mantiene una altura mínima y no contiene texto.
        """
        p = marker.insert_paragraph_before(style="Cotizacion Cuerpo")
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(1)
        run = p.add_run("")
        run.font.size = Pt(1)
        return p

    def validar_datos(self, datos: dict) -> dict:
        if not isinstance(datos, dict):
            raise CotizacionDocumentError("La cotización no tiene un formato válido.")
        alternativas = datos.get("alternativas")
        if not isinstance(alternativas, list) or not alternativas:
            raise CotizacionDocumentError("Elegí al menos una cobertura o alternativa.")
        if len(alternativas) > 50:
            raise CotizacionDocumentError("La cotización supera el máximo de 50 alternativas.")

        limpias = []
        for alt in alternativas:
            if not isinstance(alt, dict):
                continue
            compania = (
                _texto(alt.get("compania_confirmada"), max_len=120)
                or _texto(alt.get("compania"), max_len=120)
                or _texto(alt.get("compania_detectada"), max_len=120)
                or "Compañía"
            )
            nombre = _texto(alt.get("nombre"), max_len=180) or "Cobertura"
            contenidos = []
            raw_contenidos = alt.get("contenidos")
            if not isinstance(raw_contenidos, list):
                raw_contenidos = []
            for item in raw_contenidos[:40]:
                if isinstance(item, dict):
                    tipo = str(item.get("tipo") or "beneficio").strip().lower()
                    txt = _texto(item.get("texto"), max_len=650)
                else:
                    tipo = "beneficio"
                    txt = _texto(item, max_len=650)
                if not txt:
                    continue
                if tipo not in {"beneficio", "nota"}:
                    tipo = "beneficio"
                contenidos.append({"tipo": tipo, "texto": txt})

            limpia = {
                "compania": compania,
                "compania_detectada": _texto(alt.get("compania_detectada"), max_len=120),
                "compania_confirmada": _texto(alt.get("compania_confirmada"), max_len=120),
                "company_key": _texto(alt.get("company_key"), max_len=80),
                "codigo": _texto(alt.get("codigo"), max_len=60),
                "familia": _texto(alt.get("familia"), max_len=80),
                "nombre": nombre,
                "nombre_comercial": _texto(alt.get("nombre_comercial"), max_len=180),
                "variante_comercial": _texto(alt.get("variante_comercial"), max_len=120),
                "variante_grua": _texto(alt.get("variante_grua"), max_len=40),
                "suma": _normalizar_moneda_visual(alt.get("suma")),
                "franquicia_pct": _normalizar_porcentaje(alt.get("franquicia_pct")),
                "franquicia_importe": _normalizar_moneda_visual(alt.get("franquicia_importe")),
                "precio": _normalizar_moneda_visual(alt.get("precio")),
                "cuponera": _normalizar_moneda_visual(alt.get("cuponera")),
                "adherido": _normalizar_moneda_visual(alt.get("adherido")),
                "contenidos": contenidos,
            }
            limpias.append(normalizar_cobertura_para_carta(limpia))

        if not limpias:
            raise CotizacionDocumentError("No hay alternativas válidas para generar la carta.")
        return {
            "vehiculo": _texto(datos.get("vehiculo"), max_len=180),
            "alternativas": limpias,
        }

    def _validar_plantilla(self, doc: Document):
        if not self.template_path.exists():
            raise CotizacionDocumentError("No encuentro la plantilla institucional 'word final.docx'.")
        faltan = [name for name in ESTILOS_REQUERIDOS if name not in doc.styles]
        if faltan:
            raise CotizacionDocumentError("La plantilla no contiene los estilos requeridos: " + ", ".join(faltan))
        if not any(MARCADOR in p.text for p in doc.paragraphs):
            raise CotizacionDocumentError(f"La plantilla no contiene el marcador {MARCADOR}.")

    @staticmethod
    def _agregar_linea_meta(marker, etiqueta: str, valor: str, *, keep_with_next=False):
        p = marker.insert_paragraph_before(style="Cotizacion Meta")
        r = p.add_run(etiqueta)
        r.bold = True
        p.add_run(f" · {valor}")
        p.paragraph_format.keep_with_next = keep_with_next
        return p

    @staticmethod
    def _frame_pr_cierre(paragraph):
        """Ancla el cierre existente al pie de la última página.

        Al ser párrafos del cuerpo (no footer) aparece una sola vez. Dos
        párrafos consecutivos con el mismo framePr forman un único frame.
        LibreOffice respeta este patrón y lo posiciona en el pie de la página
        donde realmente cae el cierre, incluso en documentos multipágina.
        """
        ppr = paragraph._p.get_or_add_pPr()
        for old in ppr.findall(qn("w:framePr")):
            ppr.remove(old)
        frame = OxmlElement("w:framePr")
        frame.set(qn("w:wrap"), "notBeside")
        frame.set(qn("w:vAnchor"), "page")
        frame.set(qn("w:hAnchor"), "margin")
        frame.set(qn("w:yAlign"), "bottom")
        frame.set(qn("w:xAlign"), "center")
        frame.set(qn("w:hSpace"), "0")
        frame.set(qn("w:vSpace"), "0")
        ppr.insert(0, frame)

    def _aplicar_cierre_institucional(self, doc: Document, marker):
        paragraphs = list(doc.paragraphs)
        try:
            marker_idx = paragraphs.index(marker)
        except ValueError:
            marker_idx = -1
        posteriores = paragraphs[marker_idx + 1 :] if marker_idx >= 0 else paragraphs
        gracias = next((p for p in posteriores if p.text.strip() == "Gracias por elegirnos"), None)
        if not gracias:
            raise CotizacionDocumentError("La plantilla no contiene el cierre institucional esperado.")
        idx = paragraphs.index(gracias)
        seguros = next((p for p in paragraphs[idx + 1 :] if p.text.strip() == "Seguros San José"), None)
        if not seguros:
            raise CotizacionDocumentError("La plantilla no contiene la firma 'Seguros San José' del cierre.")
        self._frame_pr_cierre(gracias)
        self._frame_pr_cierre(seguros)

    def generar_docx(self, datos: dict, destino: Path) -> Path:
        datos = self.validar_datos(datos)
        if not self.template_path.exists():
            raise CotizacionDocumentError("No encuentro la plantilla institucional 'word final.docx'.")
        doc = Document(self.template_path)
        self._validar_plantilla(doc)
        marker = next(p for p in doc.paragraphs if MARCADOR in p.text)
        self._aplicar_cierre_institucional(doc, marker)

        # Una compañía se presenta como una sección. Agrupamos por identidad
        # canónica preservando el orden de primera aparición de cada compañía.
        # Dentro de la sección, las coberturas se ordenan por nivel comercial y
        # conservan el orden original cuando no pueden compararse objetivamente.
        grupos: list[dict] = []
        indice_grupo: dict[str, int] = {}
        for orden_original, alt in enumerate(datos["alternativas"]):
            alt = dict(alt)
            alt["_orden_original"] = orden_original
            clave = self._clave_agrupacion_compania(alt["compania"])
            pos = indice_grupo.get(clave)
            if pos is None:
                indice_grupo[clave] = len(grupos)
                grupos.append({"compania": alt["compania"], "alternativas": [alt]})
            else:
                grupos[pos]["alternativas"].append(alt)

        for group_idx, grupo in enumerate(grupos):
            grupo["alternativas"] = sorted(
                grupo["alternativas"],
                key=lambda alt: (int(alt.get("orden_comercial") or 55), int(alt.get("_orden_original") or 0)),
            )
            if group_idx:
                self._insertar_separador_estructural(marker)
            self._crear_tabla_compania(doc, marker, grupo, primera=(group_idx == 0))

        # El marcador es exclusivamente estructural y nunca debe quedar visible.
        parent = marker._element.getparent()
        parent.remove(marker._element)

        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        doc.save(destino)
        return destino

    @staticmethod
    def _libreoffice_bin() -> str | None:
        configurado = str(os.getenv("LIBREOFFICE_BIN") or "").strip()
        if configurado:
            path = shutil.which(configurado) or (configurado if Path(configurado).exists() else None)
            if path:
                return str(path)
        return shutil.which("libreoffice") or shutil.which("soffice")

    def convertir_pdf(self, docx_path: Path, output_dir: Path, *, timeout=75) -> Path:
        executable = self._libreoffice_bin()
        if not executable:
            raise CotizacionConversionError(
                "LibreOffice/soffice no está disponible en el servidor. El Word puede generarse, "
                "pero PDF/PNG/JPG requieren LibreOffice instalado."
            )
        docx_path = Path(docx_path).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        profile = output_dir / ".lo-profile"
        profile.mkdir(parents=True, exist_ok=True)
        cmd = [
            executable,
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(docx_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise CotizacionConversionError("LibreOffice tardó demasiado en convertir la cotización.") from exc
        pdf = output_dir / f"{docx_path.stem}.pdf"
        if result.returncode != 0 or not pdf.exists() or pdf.stat().st_size <= 0:
            detalle = (result.stderr or result.stdout or "").strip()
            if detalle:
                detalle = detalle[-600:]
            raise CotizacionConversionError("No pude convertir el Word a PDF." + (f" {detalle}" if detalle else ""))
        return pdf

    @staticmethod
    def generar_imagenes(pdf_path: Path, output_dir: Path, formato: str) -> list[Path]:
        formato = str(formato or "").lower()
        if formato not in {"png", "jpg"}:
            raise CotizacionDocumentError("Formato de imagen inválido.")
        try:
            import fitz
        except Exception as exc:
            raise CotizacionConversionError("PyMuPDF no está disponible para generar imágenes.") from exc
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        salidas: list[Path] = []
        with fitz.open(pdf_path) as pdf:
            for i, page in enumerate(pdf, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2.4, 2.4), alpha=False)
                out = output_dir / f"{pdf_path.stem}_{i:02d}.{formato}"
                if formato == "jpg":
                    out.write_bytes(pix.tobytes("jpeg", jpg_quality=94))
                else:
                    out.write_bytes(pix.tobytes("png"))
                salidas.append(out)
        if not salidas:
            raise CotizacionConversionError("El PDF no contiene páginas para exportar como imagen.")
        return salidas

    @staticmethod
    def nombre_base(datos: dict, fecha) -> str:
        vehiculo = _slug_archivo(_texto((datos or {}).get("vehiculo"), max_len=180))
        fecha_txt = fecha.strftime("%d-%m-%Y")
        if vehiculo:
            return f"Cotizacion_{vehiculo}_{fecha_txt}"
        return f"Cotizacion_Seguros_San_Jose_{fecha_txt}"


@lru_cache(maxsize=1)
def fuentes_requeridas_faltantes() -> tuple[str, ...]:
    """Detecta sustitución de fuentes en Linux para poder avisarla, no ocultarla.

    La generación DOCX nunca cambia los nombres Georgia/Aptos de la plantilla.
    Esta comprobación sólo sirve para que la conversión headless no sustituya
    tipografías silenciosamente cuando el host no las tiene instaladas.
    """
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return tuple()
    try:
        out = subprocess.run(
            [fc_list, ":", "family"], capture_output=True, text=True, timeout=8, check=False
        ).stdout
    except Exception:
        return tuple()
    families = set()
    for line in str(out or "").splitlines():
        for family in line.split(","):
            name = family.strip().lower()
            if name:
                families.add(name)
    requeridas = ("Georgia", "Aptos")
    return tuple(name for name in requeridas if name.lower() not in families)
