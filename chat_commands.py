"""Comandos determinísticos del chat que no necesitan Gemini.

V20 Etapa 6: separa parsing/presentación de /envios ya y /guardar asegurado
fuera de app.py. No conoce Flask, session, DB ni archivos: recibe dependencias.
"""
from dataclasses import dataclass, field
import re

from companias import normalizar_compania


@dataclass
class CommandResult:
    atendido: bool = False
    respuesta: str | None = None
    propuesta_excel: dict | None = None
    texto_envios_ya: str | None = None
    libro_id: str | None = None
    payload_extra: dict = field(default_factory=dict)


def normalizar_patente(valor):
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def normalizar_telefono(valor):
    return re.sub(r"\D", "", str(valor or ""))


def buscar_asegurado_por_patente(patente_buscada, *, leer_excel, normalizar_encabezado, libro_id="1"):
    patente_norm = normalizar_patente(patente_buscada)
    if not patente_norm:
        return None
    datos = leer_excel(libro_id)
    filas = datos.get("filas") or []
    if not filas:
        return None
    encabezados = filas[0]
    indices = {
        normalizar_encabezado(encabezado): i
        for i, encabezado in enumerate(encabezados)
        if normalizar_encabezado(encabezado)
    }
    indice_patente = indices.get(normalizar_encabezado("PATENTE"))
    if indice_patente is None:
        return None
    for fila in filas[1:]:
        valor = fila[indice_patente] if indice_patente < len(fila) else ""
        if normalizar_patente(valor) == patente_norm:
            return {encabezados[i]: (fila[i] if i < len(fila) else "") for i in range(len(encabezados))}
    return None


def armar_texto_envios_ya(datos, *, normalizar_encabezado):
    def obtener(*claves):
        for clave in claves:
            objetivo = normalizar_encabezado(clave)
            for k, v in datos.items():
                if normalizar_encabezado(k) == objetivo and str(v or "").strip():
                    return str(v).strip()
        return ""

    nombre = obtener("ASEGURADO", "nombre asegurado")
    telefono = normalizar_telefono(obtener("TELEFONO"))
    vehiculo = obtener("VEHICULO", "marca_modelo", "marca/modelo")
    patente = obtener("PATENTE", "dominio", "chapa").upper()
    cia = obtener("CIA", "compañia", "compania")
    aviso = f" (ojo: tiene {len(telefono)} dígitos, revisá que sea correcto)" if telefono and len(telefono) != 10 else ""
    return (
        f"NOMBRE Y APELLIDO: {nombre}\n"
        f"TELEFONO: {telefono}{aviso}\n"
        f"VEHICULO: {vehiculo}\n"
        f"PATENTE: {patente}\n"
        f"COMPAÑIA: {cia}"
    )


def parsear_envios_ya(mensaje):
    texto = str(mensaje or "").strip()
    m = re.match(r"^/envios\s+ya\b\s*(.*)$", texto, re.IGNORECASE)
    if not m:
        return None
    resto = re.sub(r"^\(([^)]*)\)$", r"\1", m.group(1).strip()).strip("'\" ")
    if not resto:
        return {"error": "Usá el formato /envios ya (patente), indicando la patente del vehículo."}
    return {"patente": resto}


def parsear_guardar_asegurado(mensaje):
    texto = str(mensaje or "").strip()
    patron = re.compile(r"^/guardar\s+asegurado\b", re.IGNORECASE)
    if not patron.match(texto):
        return None
    resto = patron.sub("", texto, count=1).strip()
    campos = ("ASEGURADO", "NUMERO", "VEHICULO", "PATENTE", "CIA", "MEDIO DE PAGO", "CP", "MAIL", "TELEFONO")
    libro_id = "1"
    sufijo = re.search(r"(?:,\s*|\s+)([12])\s*$", resto)
    if sufijo:
        libro_id = sufijo.group(1)
        resto = resto[:sufijo.start()].rstrip(" ,")
    valores = re.findall(r"\(([^)]*)\)", resto)
    if valores:
        if len(valores) > len(campos):
            return {"error": "El comando tiene más campos de los esperados."}
        valores = [v.strip() for v in valores]
    elif "," in resto:
        valores = [v.strip() for v in resto.split(",")]
        if len(valores) > len(campos):
            return {"error": "El comando tiene más campos de los esperados."}
    else:
        return {"error": "Usá el formato /guardar asegurado (asegurado) (numero) (vehiculo) (patente) (cia) (medio de pago) (cp) (mail) (telefono opcional)."}

    propuesta = {campo: (valores[i] if i < len(valores) else "") for i, campo in enumerate(campos)}
    placeholders = {"ASEGURADO":"asegurado","NUMERO":"numero","VEHICULO":"vehiculo","PATENTE":"patente","CIA":"cia","MEDIO DE PAGO":"medio de pago","CP":"cp","MAIL":"mail","TELEFONO":"telefono"}
    for campo, placeholder in placeholders.items():
        if propuesta[campo].strip().lower() == placeholder:
            propuesta[campo] = ""
    propuesta["CIA"] = normalizar_compania(propuesta.get("CIA", ""))
    propuesta["ENVIOS YA"] = ""
    return {"propuesta": propuesta, "libro_id": libro_id, "valida": bool(propuesta["ASEGURADO"] and (propuesta["NUMERO"] or propuesta["PATENTE"]))}


def procesar(mensaje, *, leer_excel, normalizar_encabezado, libros_excel):
    envios = parsear_envios_ya(mensaje)
    if envios is not None:
        if envios.get("error"):
            return CommandResult(True, envios["error"])
        fila = buscar_asegurado_por_patente(envios["patente"], leer_excel=leer_excel, normalizar_encabezado=normalizar_encabezado)
        if fila is None:
            return CommandResult(True, f"No encontré ningún asegurado con la patente {envios['patente'].upper()} en el Excel. Revisá que esté bien escrita o que el asegurado ya esté guardado.")
        return CommandResult(True, "Te dejo los datos listos para pegar en Envíos Ya:", texto_envios_ya=armar_texto_envios_ya(fila, normalizar_encabezado=normalizar_encabezado))

    guardar = parsear_guardar_asegurado(mensaje)
    if guardar is None:
        return CommandResult()
    if guardar.get("error"):
        return CommandResult(True, guardar["error"])
    libro_id = str(guardar.get("libro_id") or "1")
    libro = libros_excel[libro_id]
    p = guardar["propuesta"]
    respuesta = (
        f"Voy a guardar este asegurado en Excel {libro_id} ({libro['nombre']}):\n\n"
        f"ASEGURADO: {p.get('ASEGURADO','')}\nNUMERO: {p.get('NUMERO','')}\nVEHICULO: {p.get('VEHICULO','')}\n"
        f"PATENTE: {p.get('PATENTE','')}\nCIA: {p.get('CIA','')}\nMEDIO DE PAGO: {p.get('MEDIO DE PAGO','')}\n"
        f"CP: {p.get('CP','')}\nMAIL: {p.get('MAIL','')}\n\n¿Confirmás?"
    )
    propuesta = dict(p)
    propuesta["LIBRO_ID"] = libro_id
    return CommandResult(True, respuesta, propuesta_excel=propuesta, libro_id=libro_id)
