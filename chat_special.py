"""Handlers especiales previos a Sofia.

Extiende el router V20 sin reemplazarlo: /coti abre Cotizaciones y /flota conserva prioridad;
los adjuntos operativos se clasifican como cédula/DNI/licencia/póliza/otro y disparan su
pipeline natural sin exigir comandos.
"""
from dataclasses import dataclass, field
import re

import alta_ops
import flota_ops
import cedula_ops
import personal_document_ops
import document_grouping
from document_classifier import clasificar_adjunto, clasificar_adjuntos
from atm_cotizador import respuesta_chat_atm
import atm_quote_service


@dataclass
class SpecialResult:
    atendido: bool = False
    respuesta: str | None = None
    payload_extra: dict = field(default_factory=dict)
    handler: str | None = None


def _es_pedido_envio(mensaje: str) -> bool:
    n = str(mensaje or "").strip().lower()
    return bool(re.search(
        r"\b(?:mand(?:a|ale|alo|ar)|envi(?:a|ale|alo|ar)|reenvi(?:a|ar)|mail|correo|whatsapp)\b",
        n,
        re.I,
    ))


def _mensaje_default_adjunto(mensaje: str) -> bool:
    n = str(mensaje or "").strip().lower()
    return n in {
        alta_ops.MENSAJE_PDF_POR_DEFECTO.lower(),
        "analizá esta imagen según su contenido.",
        "analiza esta imagen según su contenido.",
        "procesá este archivo.",
        "procesa este archivo.",
        "procesá estos documentos y combiná frente/dorso sólo si corresponden al mismo documento.",
        "procesa estos documentos y combina frente/dorso solo si corresponden al mismo documento.",
    }



def _es_pedido_procesamiento_documental(mensaje: str) -> bool:
    """True cuando el usuario quiere el flujo operativo completo del adjunto.

    Preguntas puntuales como "¿qué cobertura tiene?" o "¿cuándo vence?"
    deben quedar para el análisis general del turno, no ser secuestradas por
    la acción por defecto de cédula/póliza.
    """
    n = str(mensaje or "").strip().lower()
    if _mensaje_default_adjunto(n):
        return True
    if re.search(r"\b(?:proces(?:a|á)|analiz(?:a|á)|le(?:e|é)|extra(?:e|é)|sac(?:a|á))\b", n):
        if not re.search(r"\b(?:cuando vence|cu[aá]ndo vence|que cobertura|qu[eé] cobertura|que clases|qu[eé] clases|cuanto paga|cu[aá]nto paga)\b", n):
            return True
    if re.search(r"\b(?:alta|cargar|guardar|registrar|registro)\b", n):
        return True
    return False


def _es_consulta_puntual_sobre_adjunto(mensaje: str) -> bool:
    n = str(mensaje or "").strip().lower()
    if not n or _mensaje_default_adjunto(n):
        return False
    return bool(re.search(
        r"\b(?:cuando vence|cu[aá]ndo vence|vencimiento|que cobertura|qu[eé] cobertura|cobertura tiene|que clases|qu[eé] clases|clases tiene|cuanto paga|cu[aá]nto paga|que datos|qu[eé] datos|motor|chasis|dominio|patente)\b",
        n,
        re.I,
    ))

def _conviene_rescate_cedula(adjunto, clasificacion, mensaje: str) -> bool:
    """Decide si vale la pena probar el lector especializado tras un 'otro'.

    Una foto de WhatsApp no tiene capa textual, por lo que una clasificación
    visual equivocada no debe descartarla. En PDF priorizamos scans y documentos
    cortos con señales vehiculares para no mandar manuales largos al pipeline de
    cédula innecesariamente.
    """
    if adjunto is None or not _mensaje_default_adjunto(mensaje):
        return False
    tipo = str(getattr(adjunto, "tipo", "") or "")
    if tipo not in {"imagen", "pdf"}:
        return False
    if clasificacion is None or clasificacion.tipo_documento != "otro":
        return False
    if tipo == "imagen":
        return True

    contexto = str(getattr(adjunto, "contexto", "") or "").strip()
    if not contexto:
        return True  # PDF escaneado: la visión es la única evidencia disponible.
    n = contexto.upper()
    señales = sum(1 for token in (
        "CEDULA", "CÉDULA", "DNRPA", "DOMINIO", "TITULAR",
        "MOTOR", "CHASIS", "CHASSIS", "MOTOVEHICULO", "AUTOMOTOR",
    ) if token in n)
    if señales >= 2:
        return True
    # Las cédulas digitales suelen ser documentos cortos; un manual largo no.
    if len(contexto) <= 1800 and getattr(clasificacion, "fuente", "") == "gemini_error":
        return True
    return False


def _resultado_cedula(adjunto, clasificacion, on_stage=None, *, confirmada=False):
    if on_stage:
        on_stage("cedula_inicio")
    resultado = cedula_ops.procesar_cedula(adjunto, clasificacion_confirmada=confirmada)
    print(
        "CEDULA lectura",
        f"motor={resultado.datos.get('estado_motor')}",
        f"chasis={resultado.datos.get('estado_chasis')}",
    )
    if on_stage:
        on_stage("cedula_resuelta")
    return SpecialResult(
        atendido=True,
        respuesta=cedula_ops.resumen_cedula(resultado),
        payload_extra={
            "tipo_documento": "cedula",
            "clasificacion_confianza": getattr(clasificacion, "confianza", None),
            "cedula_detectada": resultado.datos,
            "cedula_advertencias": resultado.advertencias,
            # No crea otro Alta: sólo prepara el prefill para abrir, a demanda,
            # el mismo formulario/guardado que ya usa una póliza.
            "borrador_alta_desde_cedula": alta_ops.campos_alta_desde_cedula(resultado.datos),
            "alta_revisiones": alta_ops.revisiones_alta_desde_cedula(resultado.datos),
        },
        handler="cedula",
    )


def _resultado_cedula_y_poliza(cedula_adjunto, cedula_clasificacion, poliza_adjunto, poliza_clasificacion, on_stage=None):
    """Dos entradas, un único Alta existente. Si una lectura falla, conserva la otra."""
    resultado_cedula = None
    propuesta_poliza = None
    error_cedula = None
    error_poliza = None

    try:
        if on_stage:
            on_stage("cedula_inicio")
        resultado_cedula = cedula_ops.procesar_cedula(cedula_adjunto, clasificacion_confirmada=True)
        if on_stage:
            on_stage("cedula_resuelta")
    except Exception as exc:
        error_cedula = exc
        print("AVISO CEDULA EN ALTA COMBINADA:", exc)

    try:
        contexto = str(getattr(poliza_adjunto, "contexto", "") or "").strip()
        propuesta_poliza = (
            alta_ops.interpretar_poliza_a_json(contexto)
            if contexto
            else alta_ops.interpretar_poliza_adjunto(poliza_adjunto)
        )
    except Exception as exc:
        error_poliza = exc
        print("AVISO POLIZA EN ALTA COMBINADA:", exc)

    if resultado_cedula is not None and propuesta_poliza is not None:
        columnas = alta_ops.propuesta_a_columnas(propuesta_poliza)
        campos_poliza = alta_ops.a_campos_guardar_asegurado(columnas)
        campos, revisiones, conflictos = alta_ops.fusionar_alta_con_cedula(
            campos_poliza, resultado_cedula.datos
        )
        advertencias_cedula = list(resultado_cedula.advertencias or [])
        advertencias_cedula.extend(conflictos)
        respuesta = "Cédula y póliza detectadas. Preparé un único alta con los datos de ambos documentos para revisar antes de guardar."
        return SpecialResult(
            True,
            respuesta,
            {
                "tipo_documento": "cedula+poliza",
                "cedula_detectada": resultado_cedula.datos,
                "cedula_advertencias": list(dict.fromkeys(advertencias_cedula)),
                "propuesta_alta_asegurado": columnas,
                "campos_guardar_alta_asegurado": campos,
                "tabulado_alta_asegurado": alta_ops.armar_tabulado_desde_campos(campos),
                "alta_revisiones": revisiones,
                "alta_origen": "cedula+poliza",
            },
            "alta",
        )

    if propuesta_poliza is not None:
        columnas = alta_ops.propuesta_a_columnas(propuesta_poliza)
        campos = alta_ops.a_campos_guardar_asegurado(columnas)
        return SpecialResult(
            True,
            "Póliza detectada. No pude aprovechar la cédula en este intento, pero preparé el alta de la póliza para revisar.",
            {
                "tipo_documento": "poliza",
                "propuesta_alta_asegurado": columnas,
                "campos_guardar_alta_asegurado": campos,
                "tabulado_alta_asegurado": alta_ops.armar_tabulado(columnas),
                "alta_revisiones": {},
                "alta_origen": "poliza",
            },
            "alta",
        )

    if resultado_cedula is not None:
        return SpecialResult(
            True,
            "Cédula detectada. No pude aprovechar la póliza en este intento; podés preparar el alta desde la cédula y completar los campos faltantes.",
            {
                "tipo_documento": "cedula",
                "cedula_detectada": resultado_cedula.datos,
                "cedula_advertencias": resultado_cedula.advertencias,
                "borrador_alta_desde_cedula": alta_ops.campos_alta_desde_cedula(resultado_cedula.datos),
                "alta_revisiones": alta_ops.revisiones_alta_desde_cedula(resultado_cedula.datos),
            },
            "cedula",
        )

    raise RuntimeError(
        "No pude leer ni la cédula ni la póliza del conjunto. "
        f"cedula={type(error_cedula).__name__ if error_cedula else '-'} "
        f"poliza={type(error_poliza).__name__ if error_poliza else '-'}"
    )


def _resultado_personal(adjuntos, tipo, clasificacion, on_stage=None, *, advertencia_extra=""):
    if on_stage:
        on_stage("documento_personal_inicio")
    resultado = personal_document_ops.procesar_documento_personal(adjuntos, tipo_hint=tipo)
    if advertencia_extra:
        resultado.advertencias.insert(0, advertencia_extra)
    if on_stage:
        on_stage("documento_personal_resuelto")
    return SpecialResult(
        atendido=True,
        respuesta=personal_document_ops.resumen_documento_personal(resultado),
        payload_extra={
            "tipo_documento": tipo,
            "clasificacion_confianza": getattr(clasificacion, "confianza", None),
            "documento_personal_detectado": resultado.datos,
            "documento_personal_advertencias": resultado.advertencias,
        },
        handler="documento_personal",
    )


def _clasificar_con_cache(adjunto):
    if adjunto is None:
        return None
    cached = getattr(adjunto, "_clasificacion_documento", None)
    if cached is not None:
        return cached
    c = clasificar_adjunto(adjunto)
    try:
        setattr(adjunto, "_clasificacion_documento", c)
    except Exception:
        pass
    return c


def procesar(*, chat_id, mensaje, contexto_pdf, flota_store, adjunto=None, adjuntos=None, adjunto_anterior=None, on_stage=None):
    # /coti ya NO tiene calculadora propia: es un atajo a la única UI de Cotizaciones.
    if re.match(r"^/coti(?:\s|$)", str(mensaje or "").strip(), re.I):
        return SpecialResult(
            True,
            "Abrí Cotizaciones.",
            {"abrir_cotizador_atm": True},
            "atm_cotizador",
        )

    # Consulta textual ATM rápida y determinística, sin Gemini. Se conserva como
    # compatibilidad, pero la interfaz principal es el módulo visual.
    respuesta_atm = respuesta_chat_atm(mensaje)
    if respuesta_atm is not None:
        return SpecialResult(True, str(respuesta_atm), {}, "atm_cotizador")

    if on_stage:
        on_stage("flota_router")
    respuesta_flota, atendido_flota, tabulado_flota = flota_ops.procesar_turno(
        chat_id, mensaje, contexto_pdf, flota_store
    )
    if atendido_flota:
        return SpecialResult(
            True, str(respuesta_flota), {"tabulado_flota": tabulado_flota}, "flota"
        )

    es_alta_explicito = bool(re.match(r"^/alta\b", str(mensaje or ""), re.I))
    mensaje_norm = str(mensaje or "").strip().lower()
    es_otro_comando = bool(mensaje_norm.startswith("/") and not es_alta_explicito)
    puede_auto = bool(adjunto is not None and not es_otro_comando and not _es_pedido_envio(mensaje))
    pedido_procesamiento_documental = _es_pedido_procesamiento_documental(mensaje)
    consulta_puntual_adjunto = _es_consulta_puntual_sobre_adjunto(mensaje)

    adjuntos_actuales = [a for a in (adjuntos or ([adjunto] if adjunto is not None else [])) if a is not None]
    clasificaciones = []
    clasificacion = None
    if puede_auto and not es_alta_explicito and len(adjuntos_actuales) <= 2:
        if on_stage:
            on_stage("adjunto_clasificador")
        for item in adjuntos_actuales:
            c = _clasificar_con_cache(item)
            clasificaciones.append(c)
            print(
                "ADJUNTO clasificado",
                f"tipo={c.tipo_documento}",
                f"confianza={c.confianza}",
                f"fuente={c.fuente}",
            )
            if c.error:
                print("AVISO CLASIFICADOR ADJUNTO:", c.error)
        clasificacion = clasificaciones[0] if clasificaciones else None
    elif puede_auto and len(adjuntos_actuales) > 2:
        # Más de dos archivos son una colección general, no frente/dorso. Evitamos
        # gastar una llamada de clasificación por archivo y, sobre todo, evitamos
        # que un handler especializado consuma sólo una parte del conjunto.
        if on_stage:
            on_stage("adjunto_coleccion_multiple")

    plan = document_grouping.planificar(adjuntos_actuales, clasificaciones) if clasificaciones else None

    # Cédula + póliza en el mismo turno: no mandamos ambos al chat genérico.
    # Reutilizamos los dos lectores existentes y terminamos en UN solo formulario
    # de Alta / asegurado. Nunca se crean dos altas ni se guarda automáticamente.
    if (
        puede_auto and pedido_procesamiento_documental and not consulta_puntual_adjunto
        and len(adjuntos_actuales) == 2 and len(clasificaciones) == 2
    ):
        tipos = [str(getattr(c, "tipo_documento", "") or "") for c in clasificaciones]
        if set(tipos) == {"cedula", "poliza"}:
            try:
                idx_cedula = tipos.index("cedula")
                idx_poliza = tipos.index("poliza")
                return _resultado_cedula_y_poliza(
                    adjuntos_actuales[idx_cedula], clasificaciones[idx_cedula],
                    adjuntos_actuales[idx_poliza], clasificaciones[idx_poliza],
                    on_stage,
                )
            except Exception as exc:
                print("ERROR ALTA COMBINADA CEDULA+POLIZA:", exc)
                # Si ambas lecturas fallan, no secuestrar el turno: continúa por
                # el flujo multimodal general y conserva todos los adjuntos.

    # Captura del cotizador ATM: reutiliza la clasificación visual que ya se iba
    # a hacer para una imagen. Sólo si esa clasificación dice ATM ejecutamos la
    # extracción especializada; no agrega una llamada previa a cédulas/pólizas.
    if (
        puede_auto
        and len(adjuntos_actuales) == 1
        and clasificacion is not None
        and getattr(clasificacion, "tipo_documento", "") == "cotizacion_atm"
        and pedido_procesamiento_documental
        and not consulta_puntual_adjunto
    ):
        try:
            if on_stage:
                on_stage("atm_captura_inicio")
            lectura = atm_quote_service.extraer_cotizacion_atm(adjuntos_actuales[0])
            if on_stage:
                on_stage("atm_captura_resuelta")
            if lectura.get("es_cotizacion_atm"):
                cantidad = len(lectura.get("coberturas") or [])
                texto = (
                    f"Detecté una cotización ATM con {cantidad} cobertura(s). "
                    "Abrí el cotizador para que elijas cuáles ofrecer."
                    if cantidad
                    else "Detecté la cotización ATM, pero necesito que revises los precios antes de continuar."
                )
                return SpecialResult(
                    True, texto,
                    {"abrir_cotizador_atm": True, "atm_cotizacion_detectada": lectura},
                    "atm_cotizador",
                )
        except Exception as exc:
            print("ERROR COTIZACION ATM CAPTURA:", exc)
            return SpecialResult(
                True,
                "Detecté una captura de cotización ATM, pero no pude terminar la lectura. Podés abrir Cotizaciones y reintentar la captura.",
                {"abrir_cotizador_atm": True, "atm_cotizacion_error": True},
                "atm_cotizador",
            )
    # Si la planificación de dos archivos concluyó que son documentos distintos
    # o que sólo uno encaja en un handler individual, no descartamos el resto.
    # El turno completo continúa por Sofia multimodal. Frente/dorso compatible
    # conserva su plan especializado de dos caras.
    if (
        len(adjuntos_actuales) > 1 and plan is not None and not plan.candidato_multicara
        and len(plan.adjuntos) < len(adjuntos_actuales)
    ):
        plan = None

    # Si dos caras llegaron juntas pero ambas quedaron como ``otro`` por una
    # clasificación visual débil, hacemos UN rescate con el mismo clasificador
    # observándolas como conjunto. El extractor seguirá confirmando identidad y
    # compatibilidad antes de unir datos.
    if (
        puede_auto and len(adjuntos_actuales) == 2 and plan is not None and plan.tipo == "otro"
        and _mensaje_default_adjunto(mensaje)
    ):
        try:
            c_grupo = clasificar_adjuntos(adjuntos_actuales)
            if c_grupo.tipo_documento in {"dni", "licencia", "cedula"}:
                plan = document_grouping.GroupingPlan(
                    c_grupo.tipo_documento, adjuntos_actuales[:2], [c_grupo, c_grupo], True,
                    "rescate visual conjunto",
                )
                clasificacion = c_grupo
        except Exception as exc:
            print("AVISO CLASIFICADOR CONJUNTO:", exc)

    # Frente/dorso en turnos consecutivos: el adjunto anterior se considera
    # sólo como candidato y nunca se fusiona sin validación del extractor.
    # Importante: la cara actual puede ser un dorso que por sí solo quedó como
    # ``otro``; por eso no exigimos que el plan actual ya conozca el tipo.
    if puede_auto and len(adjuntos_actuales) == 1 and adjunto_anterior is not None and clasificaciones:
        try:
            c_prev = _clasificar_con_cache(adjunto_anterior)
            candidato = document_grouping.planificar(
                [adjunto_anterior, adjuntos_actuales[0]], [c_prev, clasificaciones[0]]
            )
            if candidato.candidato_multicara and candidato.tipo in {"dni", "licencia", "cedula"}:
                plan = candidato
                clasificacion = c_prev if c_prev.tipo_documento == candidato.tipo else clasificacion
        except Exception as exc:
            print("AVISO AGRUPAMIENTO FRENTE/DORSO:", exc)

    # DNI / licencia comparten un extractor reutilizable de datos personales.
    if pedido_procesamiento_documental and not consulta_puntual_adjunto and plan is not None and plan.tipo in {"dni", "licencia"}:
        try:
            return _resultado_personal(plan.adjuntos, plan.tipo, plan.clasificaciones[-1] if plan.clasificaciones else clasificacion, on_stage)
        except personal_document_ops.DocumentosIncompatiblesError as exc:
            # Seguridad: nunca fusionar dos personas/documentos distintos. Si hay
            # un adjunto actual claro, lo procesamos solo y avisamos que no unimos.
            print("AVISO DOCUMENTOS PERSONALES NO COMBINADOS:", exc)
            actual = adjuntos_actuales[-1]
            c_actual = clasificaciones[-1]
            tipo_actual = str(getattr(c_actual, "tipo_documento", "") or "")
            if tipo_actual in {"dni", "licencia"}:
                try:
                    return _resultado_personal(
                        [actual], tipo_actual, c_actual, on_stage,
                        advertencia_extra="No combiné las imágenes porque podrían corresponder a documentos o titulares diferentes.",
                    )
                except Exception:
                    pass
            return SpecialResult(
                True,
                "Las imágenes podrían corresponder a documentos diferentes. Revisá antes de combinar.",
                {"tipo_documento": plan.tipo, "documento_personal_error_union": True},
                "documento_personal",
            )
        except personal_document_ops.NotPersonalDocumentError:
            # No secuestrar un adjunto ambiguo: continúa con los demás handlers.
            pass
        except Exception as exc:
            print("ERROR DOCUMENTO PERSONAL:", exc)
            return SpecialResult(
                True,
                "Detecté documentación personal, pero no pude completar la lectura en este intento. Reintentá el archivo; si persiste, revisá Gemini.",
                {"tipo_documento": plan.tipo, "documento_personal_error": True},
                "documento_personal",
            )

    if pedido_procesamiento_documental and not consulta_puntual_adjunto and plan is not None and plan.tipo == "cedula":
        try:
            cedula_input = plan.adjuntos if plan.candidato_multicara else plan.adjuntos[0]
            c_cedula = plan.clasificaciones[-1] if plan.clasificaciones else clasificacion
            return _resultado_cedula(cedula_input, c_cedula, on_stage, confirmada=True)
        except cedula_ops.CedulasIncompatiblesError as exc:
            print("AVISO CEDULAS NO COMBINADAS:", exc)
            # No mezclar vehículos distintos: si el adjunto actual es una cédula
            # reconocida, procesarlo solo y avisar.
            actual = adjuntos_actuales[-1]
            c_actual = clasificaciones[-1]
            try:
                r = _resultado_cedula(actual, c_actual, on_stage, confirmada=True)
                r.payload_extra["cedula_advertencias"] = [
                    "No combiné las imágenes porque no pude confirmar que fueran frente/dorso del mismo vehículo.",
                    *list(r.payload_extra.get("cedula_advertencias") or []),
                ]
                return r
            except Exception:
                return SpecialResult(True, "Las imágenes parecen corresponder a cédulas diferentes. No las combiné.", {"tipo_documento": "cedula"}, "cedula")
        except Exception as exc:
            # Ya sabemos que es cédula. Si la lectura general realmente falla,
            # informamos el problema sin disfrazarlo como mala foto cuando fue
            # un error técnico de IA.
            print("ERROR PROCESANDO CEDULA:", exc)
            return SpecialResult(
                atendido=True,
                respuesta=(
                    "Cédula detectada, pero la lectura de motor/chasis no pudo completarse en este intento. "
                    "Reintentá el mismo archivo; si vuelve a pasar, revisá el estado de Gemini."
                ),
                payload_extra={
                    "tipo_documento": "cedula",
                    "clasificacion_confianza": getattr(c_cedula, "confianza", None),
                    "cedula_error": True,
                },
                handler="cedula",
            )

    # RESCATE: antes la clasificación visual podía fallar y el sistema devolvía
    # inmediatamente "no pude clasificar". Ahora, si el clasificador falló o
    # quedó con baja confianza sobre un adjunto sin intención textual específica,
    # se intenta UNA lectura de cédula. El propio lector confirma es_cedula antes
    # de activar la card. Si no lo es, se deja continuar a Sofia normalmente.
    if puede_auto and len(adjuntos_actuales) == 1 and _conviene_rescate_cedula(adjunto, clasificacion, mensaje):
        try:
            return _resultado_cedula(adjunto, clasificacion, on_stage, confirmada=False)
        except cedula_ops.NotCedulaError:
            pass
        except Exception as exc:
            print("AVISO RESCATE CEDULA FALLIDO:", exc)
            # No secuestrar el adjunto: Sofia todavía puede analizarlo.

    # Alta individual: explícita o póliza detectada automáticamente.
    mensaje_para_alta = mensaje
    alta_automatica = False
    es_poliza_clasificada = bool(plan is not None and plan.tipo == "poliza")
    if (
        not es_alta_explicito
        and not es_otro_comando
        and not _es_pedido_envio(mensaje)
        and pedido_procesamiento_documental
        and not consulta_puntual_adjunto
        and (es_poliza_clasificada or (contexto_pdf and alta_ops.pdf_parece_poliza_individual(contexto_pdf)))
    ):
        texto_extra = "" if _mensaje_default_adjunto(mensaje) else str(mensaje or "").strip()
        mensaje_para_alta = ("/alta " + texto_extra).strip()
        alta_automatica = True

    if on_stage:
        on_stage("alta_router")
    respuesta_alta, atendido_alta, propuesta_alta = alta_ops.procesar(
        mensaje_para_alta,
        contexto_pdf,
        automatico=alta_automatica,
        adjunto=(plan.adjuntos[0] if plan is not None and plan.tipo == "poliza" and plan.adjuntos else adjunto),
    )
    if atendido_alta:
        if alta_automatica:
            print("ALTA poliza detectada automaticamente")
        campos = alta_ops.a_campos_guardar_asegurado(propuesta_alta) if propuesta_alta else None
        return SpecialResult(
            atendido=True,
            respuesta=str(respuesta_alta),
            payload_extra={
                "tipo_documento": "poliza" if propuesta_alta else None,
                "clasificacion_confianza": getattr(clasificacion, "confianza", None),
                "propuesta_alta_asegurado": propuesta_alta,
                "tabulado_alta_asegurado": alta_ops.armar_tabulado(propuesta_alta) if propuesta_alta else None,
                "campos_guardar_alta_asegurado": campos,
                "alta_revisiones": {},
                "alta_origen": "poliza",
            },
            handler="alta",
        )

    return SpecialResult()
