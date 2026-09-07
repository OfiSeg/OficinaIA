"""Utilidades de matriz y persistencia del documento Word interno.

Los libros de Asegurados/Flotas ya no viven acá: Google Sheets es su única
fuente activa. Este módulo conserva sólo las reglas de limpieza de matrices
que reutiliza la UI y el documento Word interno.
"""
from pathlib import Path
from docx import Document


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


class OfficeDocumentsService:
    def __init__(self, *, word_file, usar_pg_documento,
                 pg_obtener_documento, pg_guardar_documento):
        self.word_file = Path(word_file)
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
                return contenido if contenido is not None else ""
            except Exception as error:
                print("ERROR leer_word_interno PG:", error)
                return ""
        self.asegurar_word()
        doc = Document(self.word_file)
        return "\n\n".join(p.text for p in doc.paragraphs)

    def guardar_word(self, contenido):
        if self.usar_pg_documento():
            self.pg_guardar_documento(str(contenido or "")); return
        doc = Document()
        for linea in str(contenido or "").splitlines():
            doc.add_paragraph(linea)
        doc.save(self.word_file)

    def generar_docx(self):
        if self.usar_pg_documento():
            contenido = self.leer_word(); doc = Document()
            for linea in contenido.splitlines():
                doc.add_paragraph(linea)
            doc.save(self.word_file)
        else:
            self.asegurar_word()
        return self.word_file
