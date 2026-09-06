"""Dominio /flota aislado de Flask y del router principal del chat.

V20 Etapa 5: parsing, fusión, deduplicación, tabulado y ciclo de una flota
viven acá. La persistencia se inyecta mediante ``store``; este módulo no conoce
sesión, request, rutas HTTP ni base de datos concreta.
"""

import json
import re

from ai_gateway import generate_with_fallback, obtener_cliente_gemini, DEFAULT_MODELS
from domain_prompts import FLOTA_SYSTEM_INSTRUCTION

def _dividir_marca_modelo_flota(marca_modelo):
    """Igual que _dividir_marca_modelo, pero para flotas de camiones/
    acoplados: acá "primera palabra = marca" falla con marcas de dos
    palabras (M. BENZ, SOLA Y BRUSA). Probamos contra una lista de marcas
    conocidas del rubro transporte antes de caer al split simple."""
    texto = str(marca_modelo or "").strip()
    if not texto:
        return "", ""
    texto_norm = texto.upper()
    for marca in _MARCAS_TRANSPORTE_CONOCIDAS:
        if texto_norm == marca or texto_norm.startswith(marca + " "):
            modelo = texto[len(marca):].strip()
            return marca, modelo
    partes = texto.split(" ", 1)
    return partes[0], (partes[1].strip() if len(partes) > 1 else "")


_MARCAS_TRANSPORTE_CONOCIDAS = sorted(
    [
        "M. BENZ", "MERCEDES BENZ", "SCANIA", "FORD", "RANDON", "SOLA Y BRUSA",
        "ULTRANS", "FIAT", "IVECO", "VOLKSWAGEN", "VOLVO", "AGRALE", "DAF",
        "HYUNDAI", "MAN", "TOYOTA", "CHEVROLET",
    ],
    key=len,
    reverse=True,
)

# Enumerados fijos del formato de flota de La Segunda: es una tabla sin
# etiquetas por campo, pero con columnas en orden constante, así que se
# puede anclar con estos valores conocidos en vez de depender de Gemini.
_LASEGUNDA_TIPOS = [
    "SEMI-REMOLQUE", "ACOPLADO", "CAMION", "CAMIÓN",
    "P GI H/1000Kg", "P GII +1000Kg", "P GII H/1000Kg",
    "AUT/FAM/M.VAN", "JEEP/CAM.FAM",
]
_LASEGUNDA_CARROCERIAS = [
    "FURGON DE FABRICA", "FURGÓN DE FABRICA", "GRANEL", "ABIERTA", "CERRADA",
    "CARGAS GENERALES", "CON BARANDAS", "SEDAN", "RURAL", "DOBLE CABINA",
]
_LASEGUNDA_USOS = ["COMER.H/4 TT LD", "CARG PELIG L.D.", "COMERCIAL LD", "PARTICULAR"]


def _alt_regex(lista):
    return "|".join(re.escape(x) for x in sorted(lista, key=len, reverse=True))


_PATRON_LASEGUNDA = re.compile(
    r"(?P<tipo>" + _alt_regex(_LASEGUNDA_TIPOS) + r")\s+"
    r"(?P<carroceria>" + _alt_regex(_LASEGUNDA_CARROCERIAS) + r")\s+"
    r"(?P<marca_modelo>.+?)\s+"
    r"(?P<anio>(?:19|20)\d{2})\s+"
    r"(?P<uso>" + _alt_regex(_LASEGUNDA_USOS) + r")\s+"
    r"(?P<patente>[A-Z0-9]{6,7})\s+"
    r"(?P<motor>\S+)\s+"
    r"(?P<chasis>\S+)\s+"
    r"\$(?P<limite>[\d,]+\.\d{2})\s+"
    r"(?P<plan>\d{2})\s+"
    r"\$(?P<suma>[\d,]+\.\d{2})\s+"
    r"(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)",
    re.IGNORECASE,
)

# Variante de respaldo: algunas filas (típicamente IVECO/FIAT) traen motor
# y chasis pegados sin espacio en el texto original de la póliza (bug del
# parser de origen de La Segunda). En vez de perder toda la fila, se
# captura el bloque motor+chasis como un solo token y se marca "sospechoso"
# para que se revise/separe a mano en vez de asumir un corte automático.
_PATRON_LASEGUNDA_MOTOR_CHASIS_PEGADO = re.compile(
    r"(?P<tipo>" + _alt_regex(_LASEGUNDA_TIPOS) + r")\s+"
    r"(?P<carroceria>" + _alt_regex(_LASEGUNDA_CARROCERIAS) + r")\s+"
    r"(?P<marca_modelo>.+?)\s+"
    r"(?P<anio>(?:19|20)\d{2})\s+"
    r"(?P<uso>" + _alt_regex(_LASEGUNDA_USOS) + r")\s+"
    r"(?P<patente>[A-Z0-9]{6,7})\s+"
    r"(?P<motor_chasis>\S{15,})\s+"
    r"\$(?P<limite>[\d,]+\.\d{2})\s+"
    r"(?P<plan>\d{2})\s+"
    r"\$(?P<suma>[\d,]+\.\d{2})\s+"
    r"(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)\s+(?:SI|--)",
    re.IGNORECASE,
)


def _parece_formato_lasegunda(texto):
    """Heurística barata para decidir si vale la pena probar este parser:
    el formato de La Segunda no tiene etiquetas de campo, pero sí trae al
    menos 2 de los enumerados fijos (tipo/carrocería/uso) + varios importes
    en pesos con el patrón típico de la planilla."""
    texto_norm = texto.upper()
    hits = sum(1 for t in _LASEGUNDA_TIPOS if t in texto_norm)
    hits += sum(1 for u in _LASEGUNDA_USOS if u in texto_norm)
    tiene_importes = len(re.findall(r"\$[\d,]+\.\d{2}", texto)) >= 2
    return hits >= 2 and tiene_importes


def _lasegunda_conteo_bloques(texto):
    """Cuenta cuántas filas de vehículo debería haber en el texto, contando
    ocurrencias de los TIPO fijos (SEMI-REMOLQUE, ACOPLADO, CAMION...) que
    marcan el arranque de cada fila en el formato de La Segunda. Sirve para
    detectar si _parsear_flota_lasegunda se salteó alguna (p.ej. porque
    motor y chasis vinieron pegados sin espacio, como pasó con el Fiat) sin
    tener que revisar el Excel fila por fila."""
    texto_norm = re.sub(r"\s+", " ", str(texto or "")).upper()
    patron_tipo = re.compile(r"\b(?:" + _alt_regex(_LASEGUNDA_TIPOS) + r")\b")
    return len(patron_tipo.findall(texto_norm))


# Marca el FINAL de cada fila de La Segunda: los 6 flags fijos SI/-- de
# coberturas puntuales, seguidos opcionalmente del importe de costo
# mensual que a veces viene pegado justo después en el mismo renglón.
# Se usa como límite de fila en vez del TIPO/CARROCERÍA del principio
# porque los vehículos PARTICULARES no traen esas dos columnas: si se
# ancla el corte solo por TIPO, el texto de un auto particular queda
# pegado a la fila del camión anterior y termina mezclado con ella (el
# caso del Fiat Strada + Ford Bronco fusionados en una sola celda).
_PATRON_TERMINADOR_FILA_LASEGUNDA = re.compile(
    r"(?:SI|--)(?:\s+(?:SI|--)){5}(?:\s+\$[\d,]+\.\d+)?",
    re.IGNORECASE,
)


def _dividir_filas_lasegunda(texto_plano):
    """Divide el texto (ya aplanado a una sola línea) en un bloque por
    fila de vehículo, cortando después de cada terminador de fila. Cada
    bloque resultante se procesa después de forma AISLADA, así un error
    de lectura en una fila (campos pegados, formato distinto) no puede
    arrastrar texto hacia la fila vecina."""
    terminadores = list(_PATRON_TERMINADOR_FILA_LASEGUNDA.finditer(texto_plano))
    if not terminadores:
        return [texto_plano] if texto_plano.strip() else []
    bloques = []
    inicio = 0
    for term in terminadores:
        bloque = texto_plano[inicio:term.end()].strip()
        # Un bloque que es sólo guiones/espacios (el separador
        # "----------" del formato de La Segunda cuando queda aislado
        # entre dos filas) no es un vehículo: se descarta para no
        # generar un vehículo fantasma "sin_parsear" vacío.
        if bloque and re.sub(r"[-\s]+", "", bloque):
            bloques.append(bloque)
        inicio = term.end()
    resto = texto_plano[inicio:].strip()
    if resto and re.sub(r"[-\s]+", "", resto):
        bloques.append(resto)
    return bloques


def _parsear_flota_lasegunda(texto):
    """Parser determinístico para el formato tabular de La Segunda (sin
    etiquetas por campo, columnas fijas). Devuelve una lista de vehículos
    en el mismo formato que usa el resto de /flota, o [] si no matchea
    nada (en ese caso el llamador sigue con el flujo normal).

    Primero se corta el texto en bloques por fila (ver
    `_dividir_filas_lasegunda`) y recién después se aplica el regex de
    campos a cada bloque por separado. Una fila que no matchea el patrón
    estricto de camión (típicamente un vehículo PARTICULAR, sin
    TIPO/CARROCERÍA) no se pierde ni se mezcla con la vecina: queda como
    fila "sin parsear" con el texto crudo, para completar a mano."""
    texto_plano = re.sub(r"\s+", " ", str(texto or "")).strip()
    vehiculos = []
    for bloque in _dividir_filas_lasegunda(texto_plano):
        m = _PATRON_LASEGUNDA.search(bloque)
        if m:
            marca, modelo = _dividir_marca_modelo_flota(m.group("marca_modelo"))
            vehiculos.append({
                "patente": m.group("patente").upper(),
                "marca_modelo": m.group("marca_modelo").strip(),
                "marca": marca,
                "modelo": modelo,
                "año": m.group("anio"),
                "motor": m.group("motor"),
                "chasis": m.group("chasis"),
                "uso": m.group("uso"),
                "suma_asegurada": m.group("suma"),
                # La Segunda no trae un texto de cobertura tipo "TODO
                # RIESGO": tiene un código de Plan + 6 flags SI/-- de
                # coberturas puntuales. Dejamos cobertura vacía a
                # propósito en vez de inventar una equivalencia; se
                # completa a mano si hace falta.
                "cobertura": "",
            })
            continue
        m2 = _PATRON_LASEGUNDA_MOTOR_CHASIS_PEGADO.search(bloque)
        if m2:
            marca, modelo = _dividir_marca_modelo_flota(m2.group("marca_modelo"))
            vehiculos.append({
                "patente": m2.group("patente").upper(),
                "marca_modelo": m2.group("marca_modelo").strip(),
                "marca": marca,
                "modelo": modelo,
                "año": m2.group("anio"),
                "motor": "",
                # Motor y chasis venían pegados sin espacio en el texto
                # original: se deja el bloque completo en chasis (no se
                # adivina dónde cortar) y se marca sospechoso para que
                # se revise/separe a mano antes de pegar en Excel.
                "chasis": m2.group("motor_chasis"),
                "uso": m2.group("uso"),
                "suma_asegurada": m2.group("suma"),
                "cobertura": "",
                "sospechoso": True,
                "motivo_sospecha": "Motor y chasis pegados sin espacio en el texto original — separar a mano.",
            })
        else:
            vehiculos.append({
                "patente": "",
                "marca_modelo": bloque,
                "marca": "",
                "modelo": "",
                "año": "",
                "motor": "",
                "chasis": "",
                "uso": "",
                "suma_asegurada": "",
                "cobertura": "",
                "sin_parsear": True,
            })
    return vehiculos


def interpretar_flota_a_json(texto):
    """Interpreta una o varias descripciones de vehículos de una póliza.

    Primero intenta extraer de forma determinista los campos que vienen con
    etiquetas explícitas en el frente de póliza. Gemini queda como respaldo
    para textos que no respeten ese formato.
    """
    texto = str(texto or "").replace("\r", "")

    campos = (
        "patente", "marca_modelo", "marca", "modelo", "año", "motor",
        "chasis", "uso", "suma_asegurada", "cobertura",
        "asegurado", "domicilio", "localidad", "cp"
    )

    def limpiar_valor(valor):
        return re.sub(r"\s+", " ", str(valor or "")).strip(" \t\n:;,-")

    def campo_etiquetado(bloque, etiqueta, etiquetas_siguientes):
        patron = rf"{re.escape(etiqueta)}\s*:\s*(.*?)(?=\s+(?:{'|'.join(re.escape(x) for x in etiquetas_siguientes)})\s*:|$)"
        m = re.search(patron, bloque, flags=re.IGNORECASE | re.DOTALL)
        return limpiar_valor(m.group(1)) if m else ""

    # FORMATO LA SEGUNDA: tabla sin etiquetas por campo, columnas fijas
    # (ver _parsear_flota_lasegunda). Se intenta ANTES del formato con
    # etiquetas, porque si el texto matchea este patrón tabular no va a
    # tener "DESCRIPCIÓN DEL VEHÍCULO ASEGURADO:" para lo otro.
    if _parece_formato_lasegunda(texto):
        vehiculos_lasegunda = _parsear_flota_lasegunda(texto)
        if vehiculos_lasegunda:
            resultado = {"vehiculos": vehiculos_lasegunda}
            sin_parsear = [v for v in vehiculos_lasegunda if v.get("sin_parsear")]
            sospechosos = [v for v in vehiculos_lasegunda if v.get("sospechoso")]
            avisos = []
            if sin_parsear:
                avisos.append(
                    f"{len(sin_parsear)} fila(s) no matchearon el patrón de camión/acoplado "
                    "conocido y quedaron con el texto original en MARCA/MODELO — completá "
                    "esas a mano."
                )
            if sospechosos:
                avisos.append(
                    f"{len(sospechosos)} fila(s) tenían motor y chasis pegados sin espacio en "
                    "el texto original: quedaron juntos en la columna CHASIS — separalos a "
                    "mano antes de pegar."
                )
            total_ok = len(vehiculos_lasegunda) - len(sin_parsear) - len(sospechosos)
            if avisos:
                resultado["aviso_conteo"] = (
                    f"Ojo: de {len(vehiculos_lasegunda)} vehículo(s) detectados, {total_ok} se "
                    "cargaron completos. " + " ".join(avisos)
                )
            return resultado

    # Cada aparición de "DESCRIPCIÓN DEL <VEHÍCULO/AUTOMOTOR/RODADO/UNIDAD>
    # ASEGURADO" marca un vehículo. Distintas compañías usan palabras
    # distintas para lo mismo en el frente de póliza, así que el marcador
    # acepta las variantes más comunes en vez de exigir "VEHÍCULO" literal.
    marcadores = list(re.finditer(
        r"DESCRIPCI[ÓO]N\s+DEL\s+"
        r"(?:VEH[ÍI]CULO|AUTOMOTOR|AUTOM[ÓO]VIL|RODADO|UNIDAD|AUTO|COCHE)\s+"
        r"ASEGURAD[OA]\s*:",
        texto,
        flags=re.IGNORECASE,
    ))

    if marcadores:
        vehiculos = []
        etiquetas = [
            "TIPO", "MARCA/MODELO", "AÑO", "PATENTE", "MOTOR", "CHASIS",
            "AUTO/JEEP/SUV PARTICULARES Y FAMILIARES (1-1-1)",
            "USO DEL VEHÍCULO", "USO DEL VEHICULO", "SUMA ASEGURADA", "COBERTURA",
        ]
        for i, marcador in enumerate(marcadores):
            fin = marcadores[i + 1].start() if i + 1 < len(marcadores) else len(texto)
            bloque = texto[marcador.end():fin]
            # Normalizamos sinónimos de "VEHÍCULO" dentro de la etiqueta
            # "USO DEL ..." para no tener que duplicar cada regex de más
            # abajo por cada variante (automotor, rodado, unidad, etc.).
            bloque = re.sub(
                r"USO\s+DEL\s+(?:AUTOMOTOR|AUTOM[ÓO]VIL|RODADO|UNIDAD|AUTO|COCHE)",
                "USO DEL VEHICULO",
                bloque,
                flags=re.IGNORECASE,
            )
            etiquetas_campos = [
                "TIPO", "MARCA/MODELO", "AÑO", "PATENTE", "MOTOR", "CHASIS",
                "USO DEL VEHÍCULO", "USO DEL VEHICULO", "SUMA ASEGURADA", "COBERTURA"
            ]
            marca_modelo = campo_etiquetado(bloque, "MARCA/MODELO", [
                "AÑO", "PATENTE", "MOTOR", "CHASIS", "USO DEL VEHÍCULO",
                "USO DEL VEHICULO", "SUMA ASEGURADA", "COBERTURA"
            ])
            patente = campo_etiquetado(bloque, "PATENTE", [
                "MOTOR", "CHASIS", "USO DEL VEHÍCULO", "USO DEL VEHICULO",
                "SUMA ASEGURADA", "COBERTURA"
            ])
            anio = campo_etiquetado(bloque, "AÑO", [
                "PATENTE", "MOTOR", "CHASIS", "USO DEL VEHÍCULO",
                "USO DEL VEHICULO", "SUMA ASEGURADA", "COBERTURA"
            ])
            motor = campo_etiquetado(bloque, "MOTOR", [
                "CHASIS", "USO DEL VEHÍCULO", "USO DEL VEHICULO",
                "SUMA ASEGURADA", "COBERTURA"
            ])
            m_chasis = re.search(
                r"CHASIS\s*:\s*(.*?)(?=\s+AUTO/JEEP/SUV\s+PARTICULARES\s+Y\s+FAMILIARES\s+\(1-1-1\)|\s+USO\s+DEL\s+VEH[ÍI]CULO\s*:|\s+SUMA\s+ASEGURADA\s*:|\s+COBERTURA\s*:|$)",
                bloque,
                flags=re.IGNORECASE | re.DOTALL,
            )
            chasis = limpiar_valor(m_chasis.group(1)) if m_chasis else ""
            uso = campo_etiquetado(bloque, "USO DEL VEHÍCULO", ["SUMA ASEGURADA", "COBERTURA"])
            if not uso:
                uso = campo_etiquetado(bloque, "USO DEL VEHICULO", ["SUMA ASEGURADA", "COBERTURA"])
            suma = campo_etiquetado(bloque, "SUMA ASEGURADA", ["COBERTURA"])
            cobertura = campo_etiquetado(bloque, "COBERTURA", [])
            # Los frentes pueden traer pie de página después de COBERTURA.
            cobertura = re.split(
                r"\s+-\s+(?:Advertencia\b|\d{4,}\s+Tel\.?|Tel\.?\s*:|Provincia\b|Condición\b|ASEGURADO\b|PRODUCTOR\b)",
                cobertura,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()


            # MARCA/MODELO se conserva EXACTAMENTE como figura en la póliza.
            # No se separa en marca y modelo para no alterar el dato original.
            vehiculo = {
                "patente": patente,
                "marca_modelo": marca_modelo,
                "marca": "",
                "modelo": "",
                "año": anio,
                "motor": motor,
                "chasis": chasis,
                "uso": uso,
                "suma_asegurada": suma,
                "cobertura": cobertura,
            }
            if any(vehiculo[k] for k in ("patente", "marca_modelo", "año", "motor", "chasis")):
                vehiculos.append(vehiculo)

        # Datos generales del asegurado: se aplican a todos los vehículos.
        # El CP se obtiene del bloque de cabecera si está presente como (NNNN)
        # o junto a una localidad/código postal explícito.
        cabecera = texto[:marcadores[0].start()]
        cp = ""
        m_cp = re.search(r"(?:\(|\b)(\d{4})\)?\b", cabecera)
        if m_cp:
            cp = m_cp.group(1)
        m_cp2 = re.search(r"(?:C[ÓO]D(?:IGO)?\s*POSTAL|CP)\s*:?\s*(\d{4})", cabecera, re.IGNORECASE)
        if m_cp2:
            cp = m_cp2.group(1)

        # En muchos frentes el nombre del asegurado aparece en la cabecera
        # antes del domicilio. Intentamos extraerlo sin tocar los datos de los
        # vehículos. Si no hay suficiente estructura, dejamos el campo vacío
        # antes que inventarlo.
        asegurado = ""
        domicilio = ""
        localidad = ""
        cabecera_limpia = re.sub(r"^/flota\s*", "", cabecera, flags=re.IGNORECASE).strip()
        cabecera_limpia = re.sub(r"\s+", " ", cabecera_limpia)

        # Caso habitual: NOMBRE + CALLE + ALTURA + LOCALIDAD + DNI/IVA + (CP).
        # Para no confundir nombre y calle, buscamos un número de altura y
        # usamos el segmento anterior como candidato. Si hay una etiqueta
        # explícita, ésta tiene prioridad.
        m_aseg_et = re.search(r"(?:ASEGURADO|TOMADOR)\s*:\s*([^:]{2,100})", cabecera_limpia, re.IGNORECASE)
        if m_aseg_et and limpiar_valor(m_aseg_et.group(1)):
            asegurado = limpiar_valor(m_aseg_et.group(1))

        if not asegurado:
            # Casos frecuentes de domicilios cuyo nombre de calle es fácilmente
            # identificable en el texto corrido (LA RIOJA, AVENIDA, CALLE, etc.).
            m_aseg_calle = re.search(
                r"^(.+?)\s+(?=(?:LA\s+RIOJA|AV(?:ENIDA)?|CALLE|RUTA|BARRIO)\b[^0-9]{0,50}\s+\d{1,6}\b)",
                cabecera_limpia,
                re.IGNORECASE,
            )
            if m_aseg_calle:
                asegurado = limpiar_valor(m_aseg_calle.group(1))

        if not asegurado:
            # El formato de ejemplo del frente usa tres palabras para el
            # nombre antes de la calle. Preferimos esa estructura cuando está
            # seguida por una calle + altura.
            m_aseg = re.search(
                r"^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ'’-]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ'’-]+){1,4})\s+(?=[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .'-]{2,40}\s+\d{1,6}\b)",
                cabecera_limpia,
                re.IGNORECASE,
            )
            if m_aseg:
                asegurado = limpiar_valor(m_aseg.group(1))

        # Extraer domicilio/localidad si la cabecera tiene una calle + altura.
        if asegurado:
            resto = cabecera_limpia[len(asegurado):].strip()
        else:
            resto = cabecera_limpia
        m_dir = re.search(
            r"^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .'-]{2,50}?)\s+(\d{1,6})\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .'-]{2,40}?)(?=\s+\d{6,11}\b|\s+CONSUMIDOR\b|\s+RESPONSABLE\b|\s+\(|$)",
            resto,
            re.IGNORECASE,
        )
        if m_dir:
            domicilio = limpiar_valor(f"{m_dir.group(1)} {m_dir.group(2)}")
            localidad = limpiar_valor(m_dir.group(3))


        for v in vehiculos:
            v["asegurado"] = asegurado
            v["domicilio"] = domicilio
            v["localidad"] = localidad
            v["cp"] = cp

        return {"vehiculos": vehiculos}

    # Fallback Gemini para formatos no estructurados.
    from google.genai import types

    cliente = obtener_cliente_gemini()
    if cliente is None:
        raise RuntimeError("La IA todavía no está configurada. Falta GEMINI_API_KEY.")

    instruccion = FLOTA_SYSTEM_INSTRUCTION

    ultimo_error = None
    try:
        config = types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=4000,
            response_mime_type="application/json",
            system_instruction=instruccion.strip(),
        )
        respuesta, _modelo_usado = generate_with_fallback(
            client=cliente,
            models=DEFAULT_MODELS,
            contents=texto.strip(),
            config=config,
            log_prefix="GEMINI /FLOTA",
        )
        bruto = str(getattr(respuesta, "text", "") or "").strip()
        if not bruto:
            raise ValueError("Gemini no devolvió JSON.")
        datos = json.loads(bruto)
        vehiculos = datos.get("vehiculos")
        if not isinstance(vehiculos, list):
            raise ValueError("Gemini no devolvió la lista de vehículos.")
        salida = []
        sospechosos = 0
        for v in vehiculos:
            if not isinstance(v, dict):
                continue
            fila = {k: limpiar_valor(v.get(k, "")) for k in campos}
            if v.get("sospechoso"):
                fila["sospechoso"] = True
                fila["motivo_sospecha"] = limpiar_valor(v.get("motivo_sospecha", ""))
                sospechosos += 1
            salida.append(fila)
        resultado = {"vehiculos": salida}
        if sospechosos:
            palabra = "vehículo" if sospechosos == 1 else "vehículos"
            resultado["aviso_conteo"] = (
                f"Ojo: {sospechosos} {palabra} de los {len(salida)} que encontré "
                "conviene revisarlos antes de pasarlos al Excel, porque algunos datos "
                "no se leyeron del todo bien."
            )
        return resultado
    except Exception as error:
        ultimo_error = error
        print("ERROR GEMINI /FLOTA:", error)
    raise RuntimeError(f"No pude interpretar el frente de póliza como JSON: {ultimo_error}")


# ==========================================================
# /FLOTA — CONTEXTO PERSISTENTE, FUSIÓN, DEDUP Y AUTOGUARDADO
# ==========================================================
#
# Estas funciones implementan el comportamiento pedido para /flota:
# la flota vive en `flotas_activas` (una fila por conversación) y cada
# mensaje nuevo ENRIQUECE ese estado en vez de arrancar de cero. Los
# vehículos se identifican por patente/chasis (o por ITEM si no hay
# ninguno de los dos) para no crear duplicados, se guardan en el Excel
# real apenas tienen algo mínimamente identificable, y las correcciones
# posteriores ("el 7 es C3") pisan la fila ya guardada en vez de agregar
# una nueva.

CAMPOS_VEHICULO = (
    "patente", "marca_modelo", "marca", "modelo", "año", "motor",
    "chasis", "uso", "suma_asegurada", "cobertura",
)

_ETIQUETAS_CAMPO_NATURAL = {
    "patente": ("patente", "dominio", "chapa"),
    "chasis": ("chasis",),
    "motor": ("motor",),
    "suma_asegurada": ("suma asegurada", "suma"),
    "año": ("año", "anio", "modelo año", "año modelo"),
    "uso": ("uso",),
    "cobertura": ("cobertura",),
}


def _vacio(valor):
    return not str(valor or "").strip()


def _normalizar_identificador(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def _vehiculo_nuevo_vacio(item):
    vehiculo = {campo: "" for campo in CAMPOS_VEHICULO}
    vehiculo["item"] = item
    vehiculo["fila_excel"] = None
    return vehiculo


def _mismo_vehiculo(existente, nuevo):
    """True si `nuevo` describe el mismo vehículo físico que `existente`,
    usando patente o chasis como identificador confiable (Sección 22)."""
    pat_a = _normalizar_identificador(existente.get("patente"))
    pat_b = _normalizar_identificador(nuevo.get("patente"))
    if pat_a and pat_b:
        return pat_a == pat_b
    cha_a = _normalizar_identificador(existente.get("chasis"))
    cha_b = _normalizar_identificador(nuevo.get("chasis"))
    if cha_a and cha_b:
        return cha_a == cha_b
    return False


def _fusionar_campos_vehiculo(existente, nuevo):
    """Completa campos vacíos con datos nuevos. Nunca pisa un dato ya
    presente con uno vacío; si llega un valor distinto para un campo ya
    completo, lo actualiza (se asume que es una corrección del usuario,
    Sección 20/21) salvo que sea idéntico."""
    cambio = False
    for campo in CAMPOS_VEHICULO:
        valor_nuevo = str(nuevo.get(campo, "") or "").strip()
        if not valor_nuevo:
            continue
        if valor_nuevo != str(existente.get(campo, "") or "").strip():
            existente[campo] = valor_nuevo
            cambio = True
    return cambio


def _vehiculo_guardable(vehiculo):
    """Mínimo para que un registro ya tenga sentido guardado en el Excel
    (Sección 15/20): algo que lo identifique (patente o chasis) o al menos
    la descripción del vehículo."""
    return bool(
        str(vehiculo.get("patente") or "").strip()
        or str(vehiculo.get("chasis") or "").strip()
        or str(vehiculo.get("marca_modelo") or "").strip()
    )


_CAMPOS_RELEVANTES_PARA_COMPLETITUD = (
    "patente", "marca_modelo", "año", "motor", "chasis", "uso", "suma_asegurada", "cobertura",
)


def _campos_pendientes_vehiculo(vehiculo):
    # "marca" y "modelo" quedan afuera del reporte de faltantes: el extractor
    # siempre trabaja con "marca_modelo" combinado (Sección 30) y nunca llena
    # esos dos por separado, así que reportarlos como "faltantes" sería ruido.
    return [c for c in _CAMPOS_RELEVANTES_PARA_COMPLETITUD if _vacio(vehiculo.get(c))]


# Patente argentina vieja (AAA000) o Mercosur (AA000AA). Sirve para marcar
# como sospechosa una patente que no matchea ninguno de los dos formatos —
# típicamente señal de que el parser agarró un pedazo de otro campo.
_PATENTE_VIEJA = re.compile(r"^[A-Z]{3}\d{3}$")
_PATENTE_MERCOSUR = re.compile(r"^[A-Z]{2}\d{3}[A-Z]{2}$")

# Motor/chasis reales rondan entre 8 y 20 caracteres. Por encima de este
# largo, lo más probable es que dos campos hayan quedado pegados sin
# espacio en el texto original (el caso del Fiat de la flota de La
# Segunda: motor+chasis llegaron como un solo bloque de 30+ caracteres).
_LARGO_MOTOR_CHASIS_SOSPECHOSO = 30


def _patente_formato_valido(patente):
    p = re.sub(r"\s+", "", str(patente or "").strip().upper())
    if not p:
        return True  # patente vacía ya se reporta aparte como campo pendiente
    return bool(_PATENTE_VIEJA.match(p) or _PATENTE_MERCOSUR.match(p))


def _vehiculo_avisos(vehiculo):
    """Chequeos baratos (regex, sin Gemini) para detectar filas que
    probablemente tengan un problema de LECTURA (no de dato faltante):
    patente con formato raro, o motor/chasis con longitud fuera de lo
    normal. No corrige nada solo; da una pista de qué revisar antes de
    pegar en el Excel."""
    avisos = []
    if vehiculo.get("sin_parsear"):
        avisos.append("fila no reconocida por el parser (revisar formato/columnas)")
    if not _patente_formato_valido(vehiculo.get("patente")):
        avisos.append("patente con formato raro")
    for campo, etiqueta in (("motor", "motor"), ("chasis", "chasis")):
        if len(str(vehiculo.get(campo) or "")) > _LARGO_MOTOR_CHASIS_SOSPECHOSO:
            avisos.append(f"{etiqueta} con longitud fuera de lo normal (¿campos pegados?)")
    return avisos


def _fusionar_flota(estado_flota, datos_generales_nuevos, vehiculos_nuevos):
    """Aplica la Sección 21/22/23: completa datos generales, y para cada
    vehículo nuevo busca coincidencia por patente/chasis antes de decidir
    si actualiza uno existente o agrega uno nuevo con el próximo ITEM."""
    datos_generales = estado_flota.setdefault("datos_generales", {})
    for campo, valor in (datos_generales_nuevos or {}).items():
        valor = str(valor or "").strip()
        if valor and _vacio(datos_generales.get(campo)):
            datos_generales[campo] = valor

    vehiculos = estado_flota.setdefault("vehiculos", [])
    tocados = set()
    for nuevo in vehiculos_nuevos or []:
        nuevo = {campo: str(nuevo.get(campo, "") or "").strip() for campo in CAMPOS_VEHICULO}
        if not any(nuevo.values()):
            continue
        coincidencia = next((v for v in vehiculos if _mismo_vehiculo(v, nuevo)), None)
        if coincidencia is not None:
            _fusionar_campos_vehiculo(coincidencia, nuevo)
            tocados.add(coincidencia["item"])
        else:
            item = (max((v["item"] for v in vehiculos), default=0)) + 1
            registro = _vehiculo_nuevo_vacio(item)
            _fusionar_campos_vehiculo(registro, nuevo)
            vehiculos.append(registro)
            tocados.add(item)
    return tocados


_PATRON_ACTUALIZACION_ETIQUETADA = re.compile(
    r"\b(?:la\s+)?(patente|dominio|chapa|chasis|motor|suma\s+asegurada|suma|"
    r"cobertura|a[ñn]o|uso)\s+(?:del|de(?:l)?\s+veh[íi]culo)\s+(\d{1,3})\s+"
    r"(?:es|son|queda|qued[oó])\s*:?\s*(.+?)(?:[.;]|$|\by\b)",
    re.IGNORECASE,
)

_PATRON_ACTUALIZACION_POR_ITEM = re.compile(
    r"\b(?:el|al|vehiculo|veh[íi]culo|unidad)\s*(?:n[úu]mero)?\s*(\d{1,3})\b\s*"
    r"(?:es|son|tiene|tambi[ée]n|queda|qued[oó])?\s*[:\-]?\s*"
    r"(.*?)(?=(?:\s*(?:,|\by\b)\s*(?:el|al|vehiculo|veh[íi]culo|unidad)\s*\d)|[.;]|$)",
    re.IGNORECASE,
)


def _campo_por_etiqueta(etiqueta):
    etiqueta = etiqueta.lower().strip()
    for campo, alias in _ETIQUETAS_CAMPO_NATURAL.items():
        if etiqueta in alias:
            return campo
    return None


def _adivinar_campo_por_valor(valor):
    valor = valor.strip()
    if re.fullmatch(r"[A-Z]{1,2}\s?-?\s?\d{1,3}", valor, re.IGNORECASE):
        return "cobertura"
    if re.fullmatch(r"[A-Z]{2,3}\s?\d{3}\s?[A-Z]{0,2}", valor, re.IGNORECASE):
        return "patente"
    if re.fullmatch(r"\d{4}", valor):
        return "año"
    return None


def _extraer_campo_explicito(resto):
    """Si el texto empieza nombrando el campo ('cobertura C3', 'patente
    AB123CD'), lo separa del valor en vez de guardar la etiqueta pegada al
    dato (evita guardar 'cobertura C3' como si fuera el valor)."""
    m = re.match(
        r"^(patente|dominio|chapa|chasis|motor|suma\s+asegurada|suma|cobertura|a[ñn]o|uso)\s*[:\-]?\s*(.+)$",
        resto,
        re.IGNORECASE,
    )
    if not m:
        return None, resto
    campo = _campo_por_etiqueta(m.group(1))
    return campo, m.group(2).strip()


def _detectar_actualizaciones_naturales(mensaje):
    """Lee frases como 'el 7 tiene C3', 'la patente del 8 es AB123CD' o
    'el 4 es C3 y el 18 también' y devuelve una lista de
    {item, campo, valor}. No inventa: si no puede determinar el campo con
    confianza, descarta esa coincidencia en vez de adivinar mal (Sección 16)."""
    actualizaciones = []
    ultimo_valor = None
    ultimo_campo = None

    for m in _PATRON_ACTUALIZACION_ETIQUETADA.finditer(mensaje):
        etiqueta, item, valor = m.group(1), int(m.group(2)), m.group(3).strip(" .")
        campo = _campo_por_etiqueta(etiqueta)
        if campo and valor:
            actualizaciones.append({"item": item, "campo": campo, "valor": valor})

    if actualizaciones:
        return actualizaciones

    for m in _PATRON_ACTUALIZACION_POR_ITEM.finditer(mensaje):
        item = int(m.group(1))
        resto = (m.group(2) or "").strip(" .:-")
        if not resto or resto.lower() in {"tambien", "también"}:
            if ultimo_valor and ultimo_campo:
                actualizaciones.append({"item": item, "campo": ultimo_campo, "valor": ultimo_valor})
            continue
        campo_explicito, valor_sin_etiqueta = _extraer_campo_explicito(resto)
        if campo_explicito:
            campo, valor = campo_explicito, valor_sin_etiqueta
        else:
            campo, valor = (_adivinar_campo_por_valor(resto) or "cobertura"), resto
        actualizaciones.append({"item": item, "campo": campo, "valor": valor})
        ultimo_valor, ultimo_campo = valor, campo

    return actualizaciones


def _aplicar_actualizaciones_naturales(estado_flota, mensaje):
    actualizaciones = _detectar_actualizaciones_naturales(mensaje)
    if not actualizaciones:
        return set()
    vehiculos = estado_flota.setdefault("vehiculos", [])
    por_item = {v["item"]: v for v in vehiculos}
    tocados = set()
    for cambio in actualizaciones:
        vehiculo = por_item.get(cambio["item"])
        if vehiculo is None:
            continue
        vehiculo[cambio["campo"]] = cambio["valor"]
        tocados.add(cambio["item"])
    return tocados


def _campos_flota_a_datos_generales(campos_flota):
    """interpretar_flota_a_json ya adjunta asegurado/domicilio/localidad/cp
    a cada vehículo; acá los desprendemos para que vivan una sola vez a
    nivel flota (Sección 8), no repetidos por vehículo."""
    vehiculos = campos_flota.get("vehiculos") or []
    datos_generales = {}
    if vehiculos:
        primero = vehiculos[0]
        for campo in ("asegurado", "domicilio", "localidad", "cp"):
            if primero.get(campo):
                datos_generales[campo] = primero[campo]
    return datos_generales


def _dividir_marca_modelo(marca_modelo):
    """El extractor guarda MARCA/MODELO combinado tal como figura en la
    póliza (Sección 30) para no alterar el dato original. La planilla de
    flotas, en cambio, tiene columnas separadas MARCA y MODELO. Acá lo
    partimos SOLO para volcarlo al bloque tabulado: la primera palabra se
    asume marca, el resto modelo. Es una heurística simple a propósito —
    cualquier caso raro se corrige a mano en el bloque antes de pegar."""
    texto = str(marca_modelo or "").strip()
    if not texto:
        return "", ""
    partes = texto.split(" ", 1)
    marca = partes[0]
    modelo = partes[1].strip() if len(partes) > 1 else ""
    return marca, modelo


# Orden EXACTO de columnas de la fila 16 de la planilla de flotas
# (excel/flotas), sólo las columnas que la IA completa. COSTO MENSUAL,
# PREMIO ANUAL y la SUMA ASEGURADA de "COMPETENCIA" son de cotización
# manual y no se tocan.
_COLUMNAS_TSV_FLOTA = (
    "ITEM", "MARCA", "MODELO", "AÑO", "COBERTURA SOLICITADA", "USO",
    "MOTOR", "CHASIS", "ACCESORIO", "PATENTE", "SUMA ASEGURADA",
)


def _normalizar_suma_asegurada(valor):
    """Dos frentes de póliza de compañías distintas casi nunca escriben la
    suma asegurada igual: una la pone como "$ 15.000.000,00", otra como
    "ARS 15000000", otra sin símbolo. El extractor guarda el valor tal cual
    vino (para no perder el dato original), pero para el bloque que se pega
    en Excel conviene sacarle cualquier símbolo de moneda y espacio interno:
    así entra como número real sin importar de qué compañía salió, en vez
    de depender de que cada frente use el mismo formato que La Segunda."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    texto = re.sub(r"(?i)^\s*(ars|usd|u\$s|\$)\s*", "", texto)
    return re.sub(r"\s+", "", texto)


def _armar_bloque_tsv_flota(vehiculos):
    """Arma el bloque de texto separado por TABULADORES (uno por vehículo),
    en el mismo orden de columnas que la fila 16 de la planilla de flotas.
    Este bloque es lo que el usuario copia y pega directo en Excel a partir
    de la fila del ITEM correspondiente — Excel interpreta cada \\t como un
    salto de columna, así que las celdas quedan alineadas solas."""
    lineas = []
    for indice, vehiculo in enumerate(vehiculos, start=1):
        if not _vehiculo_guardable(vehiculo):
            continue
        # Si el extractor de origen ya calculó marca/modelo separados (caso
        # La Segunda, con marcas de dos palabras como "M. BENZ"), se
        # respetan tal cual. Sólo se recalcula con la heurística genérica
        # cuando no vinieron ya resueltos (formato con etiquetas).
        if vehiculo.get("marca") or vehiculo.get("modelo"):
            marca, modelo = vehiculo.get("marca", ""), vehiculo.get("modelo", "")
        else:
            marca, modelo = _dividir_marca_modelo_flota(vehiculo.get("marca_modelo"))
        fila = {
            "ITEM": str(vehiculo.get("item") or indice),
            "MARCA": marca,
            "MODELO": modelo,
            "AÑO": vehiculo.get("año", ""),
            "COBERTURA SOLICITADA": vehiculo.get("cobertura", ""),
            "USO": vehiculo.get("uso", ""),
            "MOTOR": vehiculo.get("motor", ""),
            "CHASIS": vehiculo.get("chasis", ""),
            "ACCESORIO": "",
            "PATENTE": vehiculo.get("patente", ""),
            "SUMA ASEGURADA": _normalizar_suma_asegurada(vehiculo.get("suma_asegurada", "")),
        }
        valores = [str(fila[col] or "").strip() for col in _COLUMNAS_TSV_FLOTA]
        lineas.append("\t".join(valores))
    return "\n".join(lineas)


def _listar_numeros(items, conector="y"):
    """Arma "16, 30, 32 y 36" a partir de una lista de números/strings."""
    items = [str(i) for i in items]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {conector} " + items[-1]


def _resumen_estado_flota(estado_flota, items_tocados_ahora, con_error, es_primera_vez, aviso_conteo=None):
    """Arma el mensaje que Sofia le muestra al usuario después de procesar
    una póliza de flota. /flota no escribe el archivo real, sólo arma el
    bloque tabulado; acá se cuenta en lenguaje simple qué se encontró, qué
    conviene revisar y qué falta, sin tecnicismos ni jerga interna."""
    vehiculos = estado_flota.get("vehiculos") or []
    total = len(vehiculos)
    tocados_ahora = len(items_tocados_ahora) if items_tocados_ahora else 0
    pendientes = [v for v in vehiculos if _campos_pendientes_vehiculo(v) and _vehiculo_guardable(v)]
    sospechosos = [v for v in vehiculos if _vehiculo_guardable(v) and _vehiculo_avisos(v)]

    partes = []

    if tocados_ahora:
        if es_primera_vez:
            palabra = "vehículo" if total == 1 else "vehículos"
            partes.append(f"La póliza se cargó y encontré {total} {palabra}.")
        else:
            palabra = "vehículo" if tocados_ahora == 1 else "vehículos"
            partes.append(f"Sumé {tocados_ahora} {palabra} más. Ahora hay {total} en total.")
    elif total and es_primera_vez:
        partes.append(f"Encontré {total} vehículos, pero todavía no tienen datos suficientes para armar el bloque.")
    elif not total:
        partes.append(
            "Empecé a cargar la flota. Pasame los datos de la póliza y los vehículos, "
            "todos juntos o de a poco, como te resulte más cómodo."
        )

    if con_error:
        singular = len(con_error) == 1
        articulo, palabra = ("El", "vehículo") if singular else ("Los", "vehículos")
        numeros = _listar_numeros([i for i, _ in con_error])
        verbo = "tuvo" if singular else "tuvieron"
        partes.append(f"{articulo} {palabra} {numeros} {verbo} un problema puntual, pero no afectó al resto.")

    if sospechosos:
        singular = len(sospechosos) == 1
        articulo, palabra = ("El", "vehículo") if singular else ("Los", "vehículos")
        numeros = _listar_numeros([v["item"] for v in sospechosos])
        verbo = "conviene revisarlo" if singular else "conviene revisarlos"
        partes.append(
            f"{articulo} {palabra} {numeros} {verbo} porque algunos datos parecen estar mal separados."
        )

    if pendientes:
        campos_faltantes = set()
        for v in pendientes:
            campos_faltantes.update(_campos_pendientes_vehiculo(v))
        if len(pendientes) <= 3:
            singular = len(pendientes) == 1
            articulo, palabra = ("Al", "vehículo") if singular else ("A los", "vehículos")
            numeros = _listar_numeros([v["item"] for v in pendientes])
            verbo = "le falta" if singular else "les falta"
            partes.append(f"{articulo} {palabra} {numeros} todavía {verbo} algún dato. Pasámelo cuando lo tengas y actualizo el bloque.")
        else:
            ejemplo = sorted(campos_faltantes)[0] if campos_faltantes else "algún dato"
            partes.append(
                f"Además, hay {len(pendientes)} vehículos a los que todavía les falta "
                f"algún dato (por ejemplo, {ejemplo}). Pasámelos cuando los tengas y actualizo el bloque."
            )

    if not partes:
        partes.append(
            "Flota iniciada. Pasame los datos generales de la póliza y/o los vehículos "
            "(podés mandarlos todos juntos, en tandas, o uno por uno)."
        )

    return " ".join(partes)


def _flota_parece_continuacion_explicita(mensaje):
    """Reconoce sólo continuaciones inequívocas de una flota previa.

    V16: tener una fila en flotas_activas ya no habilita a /flota a mirar
    todos los mensajes del chat. El estado puede persistir como snapshot,
    pero la ejecución sólo se reactiva cuando el mensaje actual lo pide de
    forma clara. Así un "hola", un PDF nuevo o una consulta normal nunca
    quedan secuestrados por una operación anterior.
    """
    texto = str(mensaje or "").strip()
    if not texto:
        return False
    if re.match(r"^/flota\b", texto, re.IGNORECASE):
        return True

    patrones = (
        r"^(?:el|la|los|las)?\s*(?:veh[ií]culo\s*)?\d+\b",
        r"\b(?:veh[ií]culo|item|ítem)\s*#?\d+\b",
        r"\b(?:sum[aá]|sumame|agreg[aá]|agregame|correg[ií]|corregime|actualiz[aá]|actualizame|cambi[aá]|cambiame)\b.*\b(?:flota|veh[ií]culo|patente|chasis|motor|cobertura|suma|uso)\b",
        r"\b(?:cerrar|cerr[aá]|terminar|termin[aá]|finalizar|finaliz[aá])\s+(?:la\s+)?flota\b",
        r"\bflota\s+(?:completa|lista|terminada)\b",
    )
    return any(re.search(p, texto, re.IGNORECASE) for p in patrones)


def procesar_turno(chat_id, mensaje, contexto_pdf_adjunto, store):
    """Punto central del flujo /flota persistente. Devuelve
    (respuesta, True, bloque_tsv) si el mensaje fue absorbido por la tarea
    de flota, o (None, False, None) si no tiene nada que ver y debe seguir
    el flujo normal (Gemini / otros comandos).

    IMPORTANTE (rediseño): /flota YA NO escribe directo en excel/flotas.xlsx.
    Sólo interpreta el/los frente(s) de póliza pegados, acumula el contexto
    de la flota en `flotas_activas` (para poder seguir sumando vehículos en
    mensajes sucesivos) y devuelve un bloque de texto separado por
    TABULADORES con TODOS los vehículos detectados hasta el momento, listo
    para copiar y pegar manualmente en el Excel. El usuario revisa el
    bloque, corrige lo que haga falta y pega — así ningún error de lectura
    llega al Excel real sin que se vea antes."""

    es_comando_flota = bool(re.match(r"^/flota\b", mensaje, re.IGNORECASE))
    es_continuacion_explicita = _flota_parece_continuacion_explicita(mensaje)

    # V16: no consultamos siquiera el snapshot de flota para mensajes normales.
    # Persistir datos no significa mantener una operación ejecutándose.
    if not es_comando_flota and not es_continuacion_explicita:
        return None, False, None

    estado_flota = store.obtener(chat_id)
    es_primera_vez = estado_flota is None

    # Una frase con aspecto de corrección de flota, pero sin una flota previa,
    # no abre una tarea por accidente: sólo /flota inicia una nueva.
    if not es_comando_flota and estado_flota is None:
        return None, False, None

    if not es_comando_flota and estado_flota is not None and estado_flota.get("estado") == "completada":
        return None, False, None

    if es_comando_flota:
        texto_flota = re.sub(r"^/flota\s*", "", mensaje, count=1, flags=re.IGNORECASE).strip()
    else:
        texto_flota = mensaje.strip()

    if re.match(r"^(termin(a|ar|amos|é)|listo|finaliza(r)?|cerrar\s+flota|flota\s+completa)\b", texto_flota, re.IGNORECASE) and estado_flota:
        vehiculos = estado_flota.get("vehiculos") or []
        bloque_final = _armar_bloque_tsv_flota(vehiculos)
        store.guardar(chat_id, "completada", estado_flota.get("libro_id", "2"), estado_flota.get("datos_generales", {}), vehiculos)
        return (
            f"Flota cerrada con {len(vehiculos)} vehículo(s). Te dejo el bloque completo abajo para "
            "copiar y pegar en el Excel. Si aparece más información después, escribí /flota de nuevo "
            "y la sumo.",
            True,
            bloque_final or None,
        )

    if estado_flota is None:
        estado_flota = {"estado": "nueva", "libro_id": "2", "datos_generales": {}, "vehiculos": []}

    fuente = texto_flota
    if contexto_pdf_adjunto:
        fuente = f"{texto_flota}\n\n{contexto_pdf_adjunto}".strip() if texto_flota else contexto_pdf_adjunto

    tocados = set()

    # Las correcciones/updates cortos en lenguaje natural ("el 7 es C3") se
    # intentan primero y son baratos (regex, sin llamar a nada externo). El
    # parser de "volcado de vehículos" (interpretar_flota_a_json, que puede
    # caer a Gemini si el texto no trae etiquetas explícitas) sólo se invoca
    # cuando el mensaje realmente parece traer datos de póliza/vehículos, no
    # en cada corrección puntual — para no gastar una llamada a Gemini de
    # más ni arriesgarse a que reinterprete mal una frase corta.
    if not es_comando_flota:
        tocados |= _aplicar_actualizaciones_naturales(estado_flota, mensaje)

    parece_volcado_vehiculos = (
        es_comando_flota
        or bool(contexto_pdf_adjunto)
        or re.search(r"DESCRIPCI[ÓO]N\s+DEL\s+VEH[ÍI]CULO", fuente, re.IGNORECASE)
        or len(fuente) > 200
    )

    aviso_conteo = None
    if fuente and not tocados and parece_volcado_vehiculos:
        try:
            campos_flota = interpretar_flota_a_json(fuente)
            vehiculos_nuevos = campos_flota.get("vehiculos") or []
        except Exception as error:
            print("ERROR PROCESANDO /FLOTA:", error)
            vehiculos_nuevos = []
            campos_flota = {}
        if vehiculos_nuevos:
            datos_generales_nuevos = _campos_flota_a_datos_generales(campos_flota)
            tocados |= _fusionar_flota(estado_flota, datos_generales_nuevos, vehiculos_nuevos)
        aviso_conteo = campos_flota.get("aviso_conteo")

    if not tocados and not fuente and es_comando_flota:
        # "/flota" pelado: si es la primera vez, arrancamos la tarea. Si ya
        # había una flota activa, sólo informamos el estado (Sección 40).
        estado_flota["estado"] = estado_flota.get("estado") or "nueva"
        store.guardar(chat_id, estado_flota["estado"], estado_flota.get("libro_id", "2"), estado_flota["datos_generales"], estado_flota["vehiculos"])
        if es_primera_vez:
            return (
                "Entendido, arranco una flota nueva. Pasame los datos generales de la póliza "
                "(asegurado, número de póliza, compañía, etc.) y los vehículos — en el orden y de "
                "a la cantidad que te resulte más cómoda, todos juntos o de a tandas. Cuando tenga "
                "algo, te devuelvo el bloque tabulado para copiar y pegar en el Excel.",
                True,
                None,
            )
        bloque = _armar_bloque_tsv_flota(estado_flota["vehiculos"])
        return _resumen_estado_flota(estado_flota, [], [], es_primera_vez=False), True, (bloque or None)

    if not tocados and not es_comando_flota:
        # No era ni un dato de flota ni una actualización reconocible:
        # dejamos pasar el mensaje al flujo normal (puede ser una pregunta
        # sin relación, Sección 27).
        return None, False, None

    # Ya NO se escribe directo en excel/flotas.xlsx (Sección rediseño): se
    # arma el bloque tabulado con TODOS los vehículos acumulados hasta acá
    # para que el usuario lo copie y pegue a mano, revisando antes de tocar
    # el Excel real.
    estado_flota["estado"] = "en_progreso" if estado_flota["vehiculos"] else "nueva"
    store.guardar(
        chat_id,
        estado_flota["estado"],
        estado_flota.get("libro_id", "2"),
        estado_flota["datos_generales"],
        estado_flota["vehiculos"],
    )

    bloque = _armar_bloque_tsv_flota(estado_flota["vehiculos"])
    respuesta = _resumen_estado_flota(estado_flota, tocados, [], es_primera_vez, aviso_conteo=aviso_conteo)
    return respuesta, True, (bloque or None)


