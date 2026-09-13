"""Utilidades de matriz y persistencia del documento Word interno.

Los libros de Asegurados/Flotas ya no viven acá: Google Sheets es su única
fuente activa. Este módulo conserva sólo las reglas de limpieza de matrices
que reutiliza la UI y el documento Word interno.

El editor Word guarda HTML simple para conservar formato. El DOCX se genera
al guardar/exportar usando únicamente python-docx; no depende de servicios
externos ni cambia la lógica de los libros Excel.
"""
from pathlib import Path
from html import escape
from html.parser import HTMLParser
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.shared import Pt, RGBColor


def fila_vacia(fila):
    return not any(str(valor or "").strip() for valor in fila)


def normalizar_matriz_excel(filas):
    if not isinstance(filas, list):
        raise ValueError("La matriz no es válida.")
    normalizadas = []
    for fila in filas[:5000]:
        if not isinstance(fila, list):
            continue
        normalizadas.append(["" if valor is None else str(valor) for valor in fila[:30]])
    return normalizadas


def limpiar_filas_excel(filas, conservar_vacias=False):
    normalizadas = normalizar_matriz_excel(filas)
    if not normalizadas:
        return []
    if conservar_vacias:
        return normalizadas
    encabezado = normalizadas[0]
    cuerpo = [fila for fila in normalizadas[1:] if not fila_vacia(fila)]
    return [encabezado] + cuerpo


def limpiar_columnas_excel(filas):
    filas = normalizar_matriz_excel(filas)
    if not filas:
        return []
    max_cols = max((len(f) for f in filas), default=0)
    if not max_cols:
        return filas
    vivas = [
        c for c in range(max_cols)
        if any(str(f[c] if c < len(f) else "").strip() for f in filas)
    ]
    if not vivas:
        return [[""]]
    return [[fila[c] if c < len(fila) else "" for c in vivas] for fila in filas]


def _parece_html(valor: str) -> bool:
    return bool(re.search(r"</?(?:p|div|h[1-6]|ul|ol|li|span|strong|b|em|i|u|s|strike|br)\b", valor or "", re.I))


def _texto_a_html(valor: str) -> str:
    texto = str(valor or "")
    if _parece_html(texto):
        return texto
    bloques = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
    return "".join(f"<p>{escape(b).replace(chr(10), '<br>')}</p>" for b in bloques) or "<p><br></p>"


def _css_dict(raw: str) -> dict[str, str]:
    out = {}
    for parte in str(raw or "").split(";"):
        if ":" not in parte:
            continue
        k, v = parte.split(":", 1)
        out[k.strip().lower()] = v.strip()
    return out


def _rgb(valor):
    if not valor:
        return None
    v = str(valor).strip().lower()
    nombres = {
        "black": "000000", "white": "ffffff", "red": "ff0000", "blue": "0000ff",
        "green": "008000", "yellow": "ffff00", "orange": "ffa500", "purple": "800080",
        "gray": "808080", "grey": "808080", "teal": "008080",
    }
    v = nombres.get(v, v)
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        v = v[1:]
    elif re.fullmatch(r"#[0-9a-f]{3}", v):
        v = "".join(c * 2 for c in v[1:])
    else:
        m = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v)
        if m:
            return tuple(max(0, min(255, int(x))) for x in m.groups())
        return None
    return tuple(int(v[i:i+2], 16) for i in (0, 2, 4))


class _WordHTMLParser(HTMLParser):
    """Traductor conservador de HTML del editor a python-docx."""

    def __init__(self, doc: Document):
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self.paragraph = None
        self.styles = [{}]
        self.list_stack = []

    def _new_paragraph(self, tag="p", attrs=None):
        attrs = dict(attrs or [])
        style_name = None
        if tag == "li":
            style_name = "List Number" if (self.list_stack and self.list_stack[-1] == "ol") else "List Bullet"
        try:
            self.paragraph = self.doc.add_paragraph(style=style_name) if style_name else self.doc.add_paragraph()
        except Exception:
            self.paragraph = self.doc.add_paragraph()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            try:
                self.paragraph.style = f"Heading {min(int(tag[1]), 3)}"
            except Exception:
                pass
        css = _css_dict(attrs.get("style", ""))
        align = css.get("text-align", "").lower()
        aligns = {
            "left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }
        if align in aligns:
            self.paragraph.alignment = aligns[align]

    def _push_style(self, tag, attrs):
        attrs = dict(attrs or [])
        st = dict(self.styles[-1])
        if tag in {"strong", "b"}: st["bold"] = True
        if tag in {"em", "i"}: st["italic"] = True
        if tag == "u": st["underline"] = True
        if tag in {"s", "strike"}: st["strike"] = True
        css = _css_dict(attrs.get("style", ""))
        if tag == "font":
            if attrs.get("face"): st["font"] = attrs.get("face")
            if attrs.get("color"): st["color"] = attrs.get("color")
            if attrs.get("size"):
                try:
                    # Escala HTML histórica 1..7, aproximada en puntos.
                    st["size_pt"] = {1:8,2:10,3:12,4:14,5:18,6:24,7:36}.get(int(attrs.get("size")), 12)
                except Exception:
                    pass
        if css.get("font-weight", "").lower() in {"bold", "600", "700", "800", "900"}: st["bold"] = True
        if css.get("font-style", "").lower() == "italic": st["italic"] = True
        deco = css.get("text-decoration", "").lower()
        if "underline" in deco: st["underline"] = True
        if "line-through" in deco: st["strike"] = True
        if "color" in css: st["color"] = css["color"]
        if "background-color" in css: st["background"] = css["background-color"]
        if "font-family" in css: st["font"] = css["font-family"].split(",")[0].strip(" '\"")
        if "font-size" in css:
            m = re.search(r"([0-9.]+)\s*(px|pt)?", css["font-size"])
            if m:
                size = float(m.group(1)); unit = m.group(2) or "px"
                st["size_pt"] = size if unit == "pt" else size * 0.75
        self.styles.append(st)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"ul", "ol"}:
            self.list_stack.append(tag); return
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._new_paragraph(tag, attrs)
        if tag == "br":
            if self.paragraph is None: self._new_paragraph()
            self.paragraph.add_run().add_break(); return
        self._push_style(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"ul", "ol"}:
            if self.list_stack: self.list_stack.pop()
            return
        if len(self.styles) > 1:
            self.styles.pop()
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.paragraph = None

    def handle_data(self, data):
        if not data:
            return
        if self.paragraph is None:
            self._new_paragraph()
        run = self.paragraph.add_run(data)
        st = self.styles[-1]
        run.bold = bool(st.get("bold"))
        run.italic = bool(st.get("italic"))
        run.underline = bool(st.get("underline"))
        run.font.strike = bool(st.get("strike"))
        if st.get("font"):
            run.font.name = st["font"]
        if st.get("size_pt"):
            run.font.size = Pt(max(6, min(72, st["size_pt"])))
        color = _rgb(st.get("color"))
        if color:
            run.font.color.rgb = RGBColor(*color)
        bg = str(st.get("background") or "").lower()
        if bg and bg not in {"transparent", "none"}:
            # Word sólo admite una paleta fija para highlight; amarillo es el fallback más legible.
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def _documento_desde_html(html: str) -> Document:
    doc = Document()
    # Quitar el párrafo vacío inicial sólo si el parser termina agregando contenido.
    parser = _WordHTMLParser(doc)
    parser.feed(_texto_a_html(html))
    parser.close()
    if not doc.paragraphs:
        doc.add_paragraph("")
    return doc


class OfficeDocumentsService:
    def __init__(self, *, word_file, usar_pg_documento,
                 pg_obtener_documento, pg_guardar_documento):
        self.word_file = Path(word_file)
        self.word_html_file = self.word_file.with_suffix(".html")
        self.usar_pg_documento = usar_pg_documento
        self.pg_obtener_documento = pg_obtener_documento
        self.pg_guardar_documento = pg_guardar_documento

    def asegurar_word(self):
        if not self.word_file.exists():
            doc = Document(); doc.add_paragraph(""); doc.save(self.word_file)

    def leer_word(self):
        if self.usar_pg_documento():
            try:
                contenido = self.pg_obtener_documento()
                return _texto_a_html(contenido if contenido is not None else "")
            except Exception as error:
                print("ERROR leer_word_interno PG:", error)
                return "<p><br></p>"
        if self.word_html_file.exists():
            try:
                return _texto_a_html(self.word_html_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        self.asegurar_word()
        doc = Document(self.word_file)
        texto = "\n\n".join(p.text for p in doc.paragraphs)
        return _texto_a_html(texto)

    def guardar_word(self, contenido):
        html = _texto_a_html(str(contenido or ""))
        if self.usar_pg_documento():
            self.pg_guardar_documento(html)
            return
        self.word_html_file.write_text(html, encoding="utf-8")
        doc = _documento_desde_html(html)
        doc.save(self.word_file)

    def generar_docx(self):
        html = self.leer_word()
        doc = _documento_desde_html(html)
        doc.save(self.word_file)
        return self.word_file
