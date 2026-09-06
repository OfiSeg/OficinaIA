"""Reglas de dominio para altas y validaciones sobre los Excel internos.

V20 Etapa 18. Este módulo no conoce Flask, request, session ni rutas.
La persistencia concreta se inyecta mediante callbacks de lectura/escritura.
"""
import re
import unicodedata


def normalizar_encabezado(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", texto.lower())


def construir_fila_excel(campos_fila, indices, cantidad_columnas, libro_id):
    """Mapea un dict de campos (asegurado, patente, marca_modelo, etc.) a una
    fila del Excel real, usando los encabezados/alias existentes.

    Extraída de la propuesta manual (`/api/excel/agregar-fila`) para poder
    reutilizarse también desde el guardado autónomo de `/flota`: ambos casos
    necesitan exactamente el mismo mapeo de columnas.
    """
    normalizar = normalizar_encabezado
    fila_nueva = [""] * cantidad_columnas

    alias = {
        normalizar("dominio"): "patente",
        normalizar("chapa"): "patente",
        normalizar("marca/modelo"): "marca_modelo",
        normalizar("marca_modelo"): "marca_modelo",
        normalizar("marca - modelo"): "marca_modelo",
        normalizar("vehiculo"): "vehiculo",
        normalizar("descripcion del vehiculo"): "vehiculo",
        normalizar("anio"): "año",
        normalizar("uso del vehiculo"): "uso",
        normalizar("suma asegurada"): "suma",
        normalizar("suma_asegurada"): "suma",
        normalizar("asegurado"): "asegurado",
        normalizar("domicilio"): "domicilio",
        normalizar("localidad"): "localidad",
        normalizar("cp"): "codigo postal",
        normalizar("codigo postal"): "codigo postal",
        normalizar("cia"): "compania",
        normalizar("compania"): "compania",
        normalizar("compañia"): "compania",
        normalizar("aseguradora"): "compania",
        normalizar("telefono"): "telefono",
        normalizar("teléfono"): "telefono",
    }
    campos_canonicos = {}
    for clave, valor in campos_fila.items():
        clave_normalizada = normalizar(clave)
        canonico = alias.get(clave_normalizada, str(clave or "").strip())
        if clave_normalizada in {
            normalizar("patente"),
            normalizar("dominio"),
            normalizar("chapa"),
        }:
            canonico = "PATENTE"
        campos_canonicos[normalizar(canonico)] = str(valor or "").strip()

    marca_modelo = str(campos_fila.get("marca_modelo") or "").strip()
    marca = str(campos_fila.get("marca") or "").strip()
    modelo = str(campos_fila.get("modelo") or "").strip()
    vehiculo = str(campos_fila.get("vehiculo") or "").strip()
    if marca_modelo:
        vehiculo = marca_modelo
    elif marca and modelo:
        vehiculo = f"{marca} {modelo}".strip()
    if vehiculo:
        campos_canonicos.setdefault(normalizar("vehiculo"), vehiculo)
        campos_canonicos.setdefault(normalizar("marca/modelo"), vehiculo)
        campos_canonicos.setdefault(normalizar("marca_modelo"), vehiculo)

    for campo, valor in campos_fila.items():
        clave = str(campo or "").strip()
        canonico = alias.get(normalizar(clave), clave)
        if normalizar(canonico) not in campos_canonicos:
            campos_canonicos[normalizar(canonico)] = str(valor or "").strip()

    if libro_id == "1":
        indice_asegurado = indices.get(normalizar("ASEGURADO"))
        indice_numero = indices.get(normalizar("NUMERO"))
        indice_patente = indices.get(normalizar("PATENTE"))
        asegurado = campos_canonicos.get(normalizar("ASEGURADO"), "")
        numero = campos_canonicos.get(normalizar("NUMERO"), "")
        patente = campos_canonicos.get(normalizar("PATENTE"), "")

        if not asegurado:
            raise ValueError(
                "Antes de guardar, el registro necesita al menos el nombre del ASEGURADO."
            )
        if not numero and not patente:
            raise ValueError(
                "Antes de guardar, indicá al menos NUMERO (DNI/póliza) o PATENTE."
            )
        if indice_asegurado is None:
            raise ValueError("El Excel no tiene la columna ASEGURADO.")
        if indice_numero is None and indice_patente is None:
            raise ValueError(
                "El Excel no tiene NUMERO ni PATENTE para identificar el registro."
            )

    for campo, valor in campos_canonicos.items():
        indice = indices.get(campo)
        if indice is not None:
            fila_nueva[indice] = valor

    if libro_id == "2":
        for encabezado, indice in indices.items():
            if encabezado in {
                normalizar("patente"),
                normalizar("dominio"),
                normalizar("chapa"),
            }:
                fila_nueva[indice] = campos_canonicos.get(
                    normalizar("patente"), fila_nueva[indice]
                )
            elif encabezado in {
                normalizar("marca"),
                normalizar("marca del vehiculo"),
            }:
                fila_nueva[indice] = str(
                    campos_fila.get("marca") or fila_nueva[indice]
                ).strip()
            elif encabezado in {
                normalizar("modelo"),
                normalizar("modelo del vehiculo"),
            }:
                fila_nueva[indice] = str(
                    campos_fila.get("modelo") or fila_nueva[indice]
                ).strip()
            elif encabezado in {
                normalizar("marca/modelo"),
                normalizar("marca_modelo"),
                normalizar("marca - modelo"),
                normalizar("vehiculo"),
                normalizar("descripcion del vehiculo"),
            }:
                fila_nueva[indice] = vehiculo or fila_nueva[indice]
            elif encabezado in {normalizar("asegurado"), normalizar("nombre asegurado")}:
                fila_nueva[indice] = campos_canonicos.get(normalizar("asegurado"), fila_nueva[indice])
            elif encabezado in {normalizar("domicilio"), normalizar("direccion")}:
                fila_nueva[indice] = campos_canonicos.get(normalizar("domicilio"), fila_nueva[indice])
            elif encabezado in {normalizar("localidad"), normalizar("ciudad")}:
                fila_nueva[indice] = campos_canonicos.get(normalizar("localidad"), fila_nueva[indice])
            elif encabezado in {normalizar("cp"), normalizar("codigo postal")}:
                fila_nueva[indice] = campos_canonicos.get(normalizar("cp"), fila_nueva[indice])
            elif encabezado in {normalizar("año"), normalizar("anio")}:
                fila_nueva[indice] = campos_canonicos.get(
                    normalizar("año"), fila_nueva[indice]
                )
            elif encabezado in {
                normalizar("uso"),
                normalizar("uso del vehiculo"),
            }:
                fila_nueva[indice] = campos_canonicos.get(
                    normalizar("uso"), fila_nueva[indice]
                )
            elif encabezado in {
                normalizar("suma"),
                normalizar("suma asegurada"),
            }:
                fila_nueva[indice] = campos_canonicos.get(
                    normalizar("suma"), fila_nueva[indice]
                )
            elif encabezado == normalizar("cobertura"):
                fila_nueva[indice] = campos_canonicos.get(
                    normalizar("cobertura"), fila_nueva[indice]
                )
            elif encabezado in {normalizar("motor")}:
                fila_nueva[indice] = campos_canonicos.get(normalizar("motor"), fila_nueva[indice])
            elif encabezado in {normalizar("chasis")}:
                fila_nueva[indice] = campos_canonicos.get(normalizar("chasis"), fila_nueva[indice])

    if not any(str(valor).strip() for valor in fila_nueva):
        raise ValueError(
            "Ninguno de los campos propuestos coincide con las columnas existentes del Excel."
        )
    return fila_nueva


class ExcelRecordService:
    """Altas/validaciones lógicas sobre libros, con persistencia inyectada."""

    def __init__(self, *, libros_excel, leer_excel, guardar_excel):
        self.libros_excel = libros_excel
        self.leer_excel = leer_excel
        self.guardar_excel = guardar_excel

    def _validar_libro(self, libro_id):
        libro_id = str(libro_id or "1")
        if libro_id not in self.libros_excel:
            raise ValueError("Libro de Excel no válido.")
        return libro_id

    def agregar(self, *, libro_id="1", campos=None, filas=None, tipo_propuesta=""):
        libro_id = self._validar_libro(libro_id)
        es_flota = str(tipo_propuesta or "").strip().lower() == "flota"

        if es_flota:
            if not isinstance(filas, list) or not filas:
                raise ValueError("No se recibieron vehículos para agregar.")
            if not all(isinstance(fila, dict) and fila for fila in filas):
                raise ValueError("La propuesta de flota contiene vehículos inválidos.")
        elif not isinstance(campos, dict) or not campos:
            raise ValueError("No se recibieron campos para agregar.")

        datos = self.leer_excel(libro_id)
        filas_actuales = list(datos.get("filas") or [])
        hoja_actual = datos.get("hoja", "Datos")
        if not filas_actuales:
            raise ValueError("El Excel interno no tiene encabezados.")

        encabezados = filas_actuales[0]
        cantidad_columnas = max(len(encabezados), 1)
        indices = {
            normalizar_encabezado(encabezado): i
            for i, encabezado in enumerate(encabezados)
            if normalizar_encabezado(encabezado)
        }

        propuestas = filas if es_flota else [campos]
        nuevas = [
            construir_fila_excel(fila, indices, cantidad_columnas, libro_id)
            for fila in propuestas
        ]
        self.guardar_excel(filas_actuales + nuevas, hoja_actual, libro_id=libro_id)
        actualizado = self.leer_excel(libro_id)
        return {
            "libro_id": libro_id,
            "filas_agregadas": len(nuevas),
            "datos": actualizado,
        }

    def validar_fila(self, *, libro_id="1", campos=None):
        libro_id = self._validar_libro(libro_id)
        campos = dict(campos or {})
        avisos = []
        errores = []

        def norm(v):
            return str(v or "").strip()

        patente_limpia = ""
        if libro_id == "1":
            aseg = norm(campos.get("ASEGURADO") or campos.get("asegurado"))
            num = norm(campos.get("NUMERO") or campos.get("numero"))
            pat = norm(campos.get("PATENTE") or campos.get("patente"))
            cia = norm(campos.get("CIA") or campos.get("cia"))
            if not aseg:
                errores.append("Falta ASEGURADO.")
            if not num and not pat:
                errores.append("Completá NUMERO (DNI/póliza) o PATENTE.")
            if pat:
                limpio = re.sub(r"[^A-Za-z0-9]", "", pat).upper()
                if len(limpio) < 6 or len(limpio) > 8:
                    avisos.append(f"La patente '{pat}' tiene un formato poco habitual.")
                campos["PATENTE"] = limpio or pat
                patente_limpia = limpio
            if not cia:
                avisos.append("CIA vacío: conviene completarlo para búsquedas futuras.")
        else:
            pat = norm(campos.get("patente") or campos.get("PATENTE"))
            if not pat:
                errores.append("Falta patente del vehículo.")
            else:
                limpio = re.sub(r"[^A-Za-z0-9]", "", pat).upper()
                if len(limpio) < 6 or len(limpio) > 8:
                    avisos.append(f"La patente '{pat}' tiene un formato poco habitual.")
                campos["patente"] = limpio or pat
                patente_limpia = limpio

        # Aviso de duplicado, deliberadamente no bloqueante.
        if patente_limpia and not errores:
            try:
                datos = self.leer_excel(libro_id)
                filas = datos.get("filas") or []
                if filas:
                    headers = [str(h or "").strip().upper() for h in filas[0]]
                    idx_pat = next((i for i, h in enumerate(headers) if h in ("PATENTE", "DOMINIO", "CHAPA")), None)
                    if idx_pat is not None:
                        for row in filas[1:]:
                            if idx_pat >= len(row):
                                continue
                            existente = re.sub(r"[^A-Za-z0-9]", "", str(row[idx_pat] or "")).upper()
                            if existente and existente == patente_limpia:
                                avisos.append(
                                    f"La patente {patente_limpia} ya figura en el Excel. "
                                    "Revisá si es un duplicado antes de guardar."
                                )
                                break
            except Exception as error:
                # La validación debe seguir siendo liviana/no bloqueante si falla
                # solamente la comprobación de duplicados.
                print("ADVERTENCIA validar patente duplicada:", error)

        return {
            "ok": not errores,
            "errores": errores,
            "avisos": avisos,
            "campos": campos,
        }
