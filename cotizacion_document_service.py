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
from PIL import Image
from companias import catalogo_companias as catalogo_companias_canonico, nombre_compania, normalizar_compania


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
    """Porcentaje visual sin signo, estable y con decimal es-AR."""
    texto = _texto(valor, max_len=30).strip()
    if not texto:
        return ""
    limpio = re.sub(r"(?:\s*%)+\s*$", "", texto).strip().replace(" ", "")
    candidato = limpio.replace(",", ".")
    try:
        numero = float(candidato)
    except Exception:
        return limpio
    if not (numero > 0):
        return limpio
    visual = str(int(numero)) if numero.is_integer() else (f"{numero:g}").replace(".", ",")
    return visual


def normalizar_porcentaje(valor: str) -> str:
    """Normaliza 2, ``2%`` o ``2%%`` a la presentación comercial ``2%``."""
    limpio = _normalizar_porcentaje(valor)
    return f"{limpio}%" if limpio else ""


def _nota_franquicia_estandar(pct: str = "", importe: str = "") -> str:
    porcentaje = normalizar_porcentaje(pct)
    if porcentaje:
        return (
            "En caso de daño parcial, queda a cargo del asegurado una franquicia equivalente al "
            f"{porcentaje} de la suma asegurada. Todo gasto que supere ese importe queda a cargo de la compañía."
        )
    monto = _normalizar_moneda_visual(importe)
    if monto:
        return (
            f"En caso de daño parcial, queda a cargo del asegurado una franquicia de {monto}. "
            "Todo gasto que supere ese importe queda a cargo de la compañía."
        )
    return ""



def _es_nota_franquicia(texto: str) -> bool:
    clave = _normalizar_clave(texto)
    return bool(clave and "franquicia" in clave and (
        "queda a cargo del asegurado" in clave
        or clave.startswith("en caso de dano parcial")
        or clave.startswith("en caso de un dano parcial")
    ))


def normalizar_cobertura_para_carta(alternativa: dict) -> dict:
    """Sanea el contrato canónico sin reinterpretar la cobertura.

    La semántica comercial debe llegar resuelta por el cotizador/normalizador.
    Este renderer sólo limpia duplicados, normaliza formato de franquicia y
    conserva nombre/contenidos/variantes recibidos. Nunca infiere una familia,
    un nombre comercial ni prestaciones desde riesgos, códigos o textos legacy.
    """
    alt = dict(alternativa or {})
    contenidos: list[dict] = []
    vistos: set[tuple[str, str]] = set()
    for item in alt.get("contenidos") or []:
        tipo = str(item.get("tipo") or "beneficio").lower() if isinstance(item, dict) else "beneficio"
        raw = item.get("texto") if isinstance(item, dict) else item
        tipo = "nota" if tipo == "nota" else "beneficio"
        texto = _texto(raw, max_len=650)
        if not texto or _es_nota_franquicia(texto):
            continue
        key = (tipo, _normalizar_clave(texto))
        if key[1] and key not in vistos:
            vistos.add(key)
            contenidos.append({"tipo": tipo, "texto": texto})

    # El renderer valida contradicciones del contrato, pero no las corrige ni
    # reinterpreta. Si llegan, el error está aguas arriba y debe arreglarse allí.
    granizo_estado = _normalizar_clave(alt.get("granizo_estado"))
    if granizo_estado in {"no incluye", "sin granizo", "no", "no_incluye"}:
        if any(_normalizar_clave(x.get("texto")) in {"granizo", "incluye granizo"} for x in contenidos if x.get("tipo") == "beneficio"):
            raise CotizacionDocumentError("Contrato de cotización contradictorio: granizo excluido pero presente en contenidos.")
    variante_grua = _normalizar_clave(alt.get("variante_grua"))
    if variante_grua == "sin grua" and any(_normalizar_clave(x.get("texto")) == "incluye grua" for x in contenidos):
        raise CotizacionDocumentError("Contrato de cotización contradictorio: variante sin grúa pero contenidos incluyen grúa.")
    if variante_grua == "con grua" and any(_normalizar_clave(x.get("texto")) == "sin grua" for x in contenidos):
        raise CotizacionDocumentError("Contrato de cotización contradictorio: variante con grúa pero contenidos indican sin grúa.")

    nota_franquicia = _nota_franquicia_estandar(alt.get("franquicia_pct"), alt.get("franquicia_importe"))
    if nota_franquicia:
        key = ("nota", _normalizar_clave(nota_franquicia))
        if key not in vistos:
            contenidos.append({"tipo": "nota", "texto": nota_franquicia})

    nombre_comercial = (
        _texto(alt.get("nombre_comercial"), max_len=180)
        or _texto(alt.get("nombre"), max_len=180)
        or "Cobertura"
    )
    variante = _texto(alt.get("variante_comercial"), max_len=120)
    alt["contenidos"] = contenidos
    alt["nombre_comercial"] = nombre_comercial
    alt["variante_comercial"] = variante
    alt["nombre"] = " · ".join(x for x in (nombre_comercial, variante) if x)
    return alt


def catalogo_companias(logos_dir: Path, companias_config: list[dict] | None = None) -> list[dict]:
    """Catálogo universal para selectores de cotización.

    La identidad (código/nombre/aliases) sale de ``companias.py``. El manifiesto
    aporta únicamente el asset documental y la configuración puede agregar
    accesos/compañías visibles sin crear otra semántica paralela. Una compañía
    sin logo sigue siendo seleccionable; el Word usa su nombre como fallback.
    """
    logos_dir = Path(logos_dir)
    manifest_path = logos_dir / "logos_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except Exception:
        manifest = {}

    aliases_manifest = manifest.get("aliases") if isinstance(manifest.get("aliases"), dict) else {}
    alias_to_asset = {_normalizar_clave(alias): str(key) for alias, key in aliases_manifest.items() if str(key).strip()}

    items: dict[str, dict] = {}

    def agregar(nombre: str, *, codigo: str = "", key_hint: str = "", aliases=None, asistencia=None):
        nombre = str(nombre or "").strip()
        if not nombre:
            return
        codigo = str(codigo or normalizar_compania(nombre) or nombre).strip()
        display = nombre_compania(nombre) or nombre
        identity_key = _normalizar_clave(codigo) or _normalizar_clave(display)
        if not identity_key:
            return
        item = items.setdefault(identity_key, {
            "key": key_hint or re.sub(r"[^a-z0-9]+", "_", _normalizar_clave(display)).strip("_") or identity_key,
            "codigo": codigo,
            "nombre": display,
            "aliases": [],
            "file": "",
            "asistencia": dict(asistencia or {}) if isinstance(asistencia, dict) else {},
        })
        if isinstance(asistencia, dict) and asistencia and not item.get("asistencia"):
            item["asistencia"] = dict(asistencia)
        for alias in [display, nombre, *(aliases or [])]:
            alias = str(alias or "").strip()
            if alias and alias.casefold() not in {x.casefold() for x in item["aliases"]}:
                item["aliases"].append(alias)
        if key_hint and not item.get("key"):
            item["key"] = key_hint

    for base in catalogo_companias_canonico():
        agregar(
            base.get("nombre"),
            codigo=base.get("codigo"),
            aliases=base.get("aliases"),
            asistencia=base.get("asistencia"),
        )

    for cfg in companias_config or []:
        if isinstance(cfg, dict):
            agregar(cfg.get("nombre"), key_hint=str(cfg.get("id") or ""), aliases=cfg.get("aliases") or [])

    # Asociar asset por aliases/nombre, sin eliminar del catálogo las compañías
    # que todavía no tengan logo documental cargado.
    for item in items.values():
        asset_key = ""
        for alias in [item.get("nombre"), item.get("codigo"), *(item.get("aliases") or [])]:
            norm = _normalizar_clave(alias)
            if norm in alias_to_asset:
                asset_key = alias_to_asset[norm]
                break
        if not asset_key:
            candidate = str(item.get("key") or "").replace("-", "_")
            if isinstance(manifest.get(candidate), dict):
                asset_key = candidate
        info = manifest.get(asset_key) if asset_key else None
        if isinstance(info, dict):
            filename = Path(str(info.get("file") or "")).name
            if filename and (logos_dir / filename).is_file():
                item["file"] = filename
                item["key"] = asset_key

    preferidas = ["ATM", "FEDERACION", "MERCANTIL", "SAN CRISTOBAL", "AGS", "RIVADAVIA", "ALLIANZ"]
    orden = {codigo: idx for idx, codigo in enumerate(preferidas)}
    salida = sorted(items.values(), key=lambda x: (orden.get(str(x.get("codigo") or ""), 999), str(x.get("nombre") or "").casefold()))
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
        # El logo/manifiesto resuelve assets; la identidad visible sale del
        # registro canónico de compañías. Para una marca aún desconocida se
        # conserva el texto recibido, sin inventar una canonicalización.
        original = _texto(compania, max_len=120) or "Compañía"
        codigo = normalizar_compania(original)
        conocidos = {item["codigo"] for item in catalogo_companias_canonico()}
        return nombre_compania(original) if codigo in conocidos else original

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
    def _borde_inferior_parrafo(paragraph, *, color=AZUL_INSTITUCIONAL, size=5):
        """Dibuja la regla de compañía justo debajo del logo/nombre.

        La fila exterior también contiene la primera cobertura para evitar que
        el logo quede huérfano al final de una página; por eso el borde no puede
        vivir en la celda exterior (quedaría después de toda la cobertura).
        """
        p_pr = paragraph._p.get_or_add_pPr()
        p_bdr = p_pr.find(qn("w:pBdr"))
        if p_bdr is None:
            p_bdr = OxmlElement("w:pBdr")
            p_pr.append(p_bdr)
        bottom = p_bdr.find(qn("w:bottom"))
        if bottom is None:
            bottom = OxmlElement("w:bottom")
            p_bdr.append(bottom)
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), str(int(size)))
        bottom.set(qn("w:space"), "1")
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

    def _dimensiones_logo_cm(self, compania: str, logo: Path) -> tuple[float, float]:
        key = self._resolver_clave_compania(compania)
        info = self._manifest.get(key or "") if key else None
        info = info if isinstance(info, dict) else {}
        try:
            alto_cm = float(info.get("recommended_word_height_cm") or 0.65)
        except Exception:
            alto_cm = 0.65
        try:
            ancho_max_cm = float(info.get("recommended_word_max_width_cm") or 4.30)
        except Exception:
            ancho_max_cm = 4.30
        alto_cm = max(0.35, min(0.75, alto_cm))
        ancho_max_cm = max(1.6, min(5.0, ancho_max_cm))
        try:
            with Image.open(logo) as im:
                w, h = im.size
            proporcion = (float(w) / float(h)) if h else 1.0
        except Exception:
            proporcion = 1.0
        ancho_cm = alto_cm * proporcion
        if ancho_cm > ancho_max_cm:
            escala = ancho_max_cm / ancho_cm
            ancho_cm = ancho_max_cm
            alto_cm *= escala
        return ancho_cm, alto_cm

    def _encabezado_compania_en_celda(self, cell, compania: str, *, primera=False):
        self._margenes_celda(cell, top=70 if primera else 100, bottom=0)
        p = cell.paragraphs[0]
        p.style = "Cotizacion Meta"
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.keep_with_next = True
        self._borde_inferior_parrafo(p, size=5)
        logo = self.resolver_logo(compania)
        if logo:
            # Cada asset vive dentro de un slot óptico común. El manifiesto puede
            # ajustar únicamente el tamaño del asset, sin cambiar la plantilla.
            ancho_cm, alto_cm = self._dimensiones_logo_cm(compania, logo)
            p.add_run().add_picture(str(logo), width=Cm(ancho_cm), height=Cm(alto_cm))
        else:
            run = p.add_run(self._nombre_visible_compania(compania).upper())
            self._fuente_run(run, size=10.5, bold=True)


    @staticmethod
    def _agregar_linea_meta_celda(cell, etiqueta: str, valor: str):
        p = cell.add_paragraph(style="Cotizacion Meta")
        r = p.add_run(etiqueta)
        r.bold = True
        p.add_run(f" · {valor}")
        return p

    def _agregar_cobertura_en_celda(self, outer, alt: dict, *, ultima=False, despues_de_encabezado=False):
        self._margenes_celda(outer, top=0, bottom=0)
        if despues_de_encabezado:
            anchor = outer.add_paragraph()
        else:
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

        if not precios and cell.paragraphs:
            cell.paragraphs[-1].paragraph_format.keep_with_next = False
            cell.paragraphs[-1].paragraph_format.space_after = Pt(4)

        if outer.paragraphs:
            # python-docx conserva un párrafo final obligatorio después de una
            # tabla anidada. Reducirlo evita aire artificial entre bloques.
            tail = outer.paragraphs[-1]
            tail.paragraph_format.space_before = Pt(0)
            tail.paragraph_format.space_after = Pt(0)
            tail.paragraph_format.line_spacing = Pt(1)
            if not tail.runs:
                tail.add_run("")
            for run in tail.runs:
                run.font.size = Pt(1)

    def _agregar_cobertura_a_tabla(self, table, alt: dict, *, ultima=False):
        row = table.add_row()
        self._fila_no_dividir(row)
        self._agregar_cobertura_en_celda(row.cells[0], alt, ultima=ultima, despues_de_encabezado=False)


    def _crear_tabla_compania(self, doc: Document, marker, grupo: dict, *, primera=False):
        table = doc.add_table(rows=1, cols=1)
        self._tabla_sin_bordes(table)
        table.autofit = True
        marker._p.addprevious(table._tbl)
        alternativas = grupo["alternativas"]
        if not alternativas:
            return table

        # Encabezado + primera cobertura comparten una única fila indivisible.
        # Si no entran al final de una página, Word/LibreOffice mueve ambos a la
        # siguiente: nunca queda un logo huérfano ni se repite por tblHeader.
        first_row = table.rows[0]
        # La fila exterior puede fluir entre páginas. El encabezado conserva
        # keep_with_next y el bloque interno de cobertura sigue siendo
        # indivisible; así evitamos tanto logos huérfanos como media página
        # vacía por mover un bloque exterior completo.
        first_cell = first_row.cells[0]
        self._encabezado_compania_en_celda(first_cell, grupo["compania"], primera=primera)
        self._agregar_cobertura_en_celda(first_cell, alternativas[0], ultima=len(alternativas) == 1, despues_de_encabezado=True)

        for indice, alt in enumerate(alternativas[1:], start=1):
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
                "tiene_grua": alt.get("tiene_grua") if isinstance(alt.get("tiene_grua"), bool) else None,
                "granizo_estado": _texto(alt.get("granizo_estado"), max_len=24).upper(),
                "riesgos_detectados": [
                    str(x or "").strip().upper() for x in (alt.get("riesgos_detectados") or [])
                    if str(x or "").strip()
                ][:40],
                "beneficios_adicionales": [
                    _texto(x, max_len=650) for x in (alt.get("beneficios_adicionales") or [])
                    if _texto(x, max_len=650)
                ][:30],
                # Preservamos las condiciones técnicas originales como metadata.
                # No se imprimen automáticamente en la carta comercial, pero no
                # se pierden al pasar por el renderer documental.
                "detalle_tecnico": [
                    _texto(x, max_len=900) for x in (alt.get("detalle_tecnico") or [])
                    if _texto(x, max_len=900)
                ][:40],
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
        # Anclar al área útil (márgenes), no al borde físico de la hoja: evita
        # que LibreOffice recorte la firma al rasterizar PDF/JPG.
        frame.set(qn("w:vAnchor"), "margin")
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
        # El cierre institucional queda al pie únicamente de la última página.
        # No interviene en la paginación de las coberturas.
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
        if datos.get("vehiculo"):
            self._agregar_linea_meta(marker, "Vehículo", datos["vehiculo"], keep_with_next=True)

        # Una compañía se presenta como una sección. Agrupamos por identidad
        # canónica preservando el orden de primera aparición de cada compañía.
        # Dentro de cada sección se conserva el orden canónico recibido. El
        # renderer no vuelve a decidir jerarquía comercial.
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
        encontrado = shutil.which("libreoffice") or shutil.which("soffice")
        if encontrado:
            return encontrado
        # En Windows LibreOffice suele instalar soffice.exe sin agregarlo al
        # PATH. Cotizaciones usa la misma detección robusta que Documentos.
        if os.name == "nt":
            candidatos = [
                Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
                Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
            ]
            for candidato in candidatos:
                if candidato.exists():
                    return str(candidato)
        return None

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
