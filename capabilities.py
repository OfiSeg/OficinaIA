"""Manifiesto central de capacidades actuales de OficinaIA.

Este módulo es deliberadamente simple: describe qué funcionalidades reales
existen en la versión actual para que el asistente pueda explicarlas sin quedar
congelado en una descripción vieja. No ejecuta acciones operativas, no consulta
Gemini y no expone valores de entorno.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Iterable

import runtime_config


CAPABILITIES: dict[str, dict] = {
    "consulta_cartera": {
        "enabled": True,
        "requires_config": ("SHEET_ID_ASEGURADOS", "GOOGLE_SHEETS_CREDENTIALS_JSON"),
        "label": "Consultar cartera",
        "description": (
            "Puede consultar la cartera interna por lenguaje natural: buscar asegurados, "
            "patentes, compañías, registros y detalles sin abrir la planilla."
        ),
    },
    "conteos_y_fechas": {
        "enabled": True,
        "requires_config": ("SHEET_ID_ASEGURADOS", "GOOGLE_SHEETS_CREDENTIALS_JSON"),
        "label": "Conteos y fechas",
        "description": (
            "Puede contar registros, asegurados únicos y emisiones por rangos como hoy, "
            "ayer, esta semana o este mes mediante filtros determinísticos."
        ),
    },
    "estadisticas": {
        "enabled": True,
        "requires_config": ("SHEET_ID_ASEGURADOS", "GOOGLE_SHEETS_CREDENTIALS_JSON"),
        "label": "Estadísticas",
        "description": (
            "Puede generar estadísticas, rankings, porcentajes, campos vacíos, duplicados "
            "y clasificaciones de autos, motos y otros riesgos sobre todo el dataset."
        ),
    },
    "analisis_archivos": {
        "enabled": True,
        "label": "Analizar archivos",
        "description": (
            "Puede recibir imágenes, PDFs, TXT y múltiples archivos en el chat, reconocer "
            "el tipo documental y analizar el contenido visible o textual."
        ),
    },
    "documentos_multiples": {
        "enabled": True,
        "label": "Documentos múltiples",
        "description": (
            "Puede trabajar con varios adjuntos en un mismo mensaje, separar documentos "
            "distintos y combinar frente/dorso sólo cuando exista evidencia suficiente."
        ),
    },
    "lectura_cedulas": {
        "enabled": True,
        "label": "Leer cédulas",
        "description": (
            "Puede reconocer cédulas vehiculares, extraer dominio, titular, vehículo, "
            "motor, chasis, vencimiento, uso y control cuando estén visibles."
        ),
    },
    "ambiguedad_cedulas": {
        "enabled": True,
        "label": "Revisión de cédulas",
        "description": (
            "Puede comparar lecturas de campos críticos de cédulas, marcar posiciones "
            "dudosas en motor, chasis o dominio y pedir confirmación del productor."
        ),
    },
    "lectura_dni_licencia": {
        "enabled": True,
        "label": "Leer DNI/licencias",
        "description": (
            "Puede leer documentación personal soportada, incluyendo licencias con clases, "
            "vencimientos, otorgamiento y observaciones visibles."
        ),
    },
    "lectura_polizas": {
        "enabled": True,
        "label": "Analizar pólizas",
        "description": (
            "Puede analizar pólizas y extraer datos relevantes como asegurado, compañía, "
            "número de póliza, vehículo, patente, cobertura y medio de pago cuando figuren."
        ),
    },
    "alta_desde_poliza": {
        "enabled": True,
        "requires_config": ("SHEET_ID_ASEGURADOS", "GOOGLE_SHEETS_CREDENTIALS_JSON"),
        "label": "Alta desde póliza",
        "description": (
            "Puede transformar una póliza compatible en una propuesta de alta, mostrar la "
            "fila tabulada y permitir revisión antes de guardar."
        ),
    },
    "guardar_excel": {
        "enabled": True,
        "requires_config": ("SHEET_ID_ASEGURADOS", "GOOGLE_SHEETS_CREDENTIALS_JSON"),
        "label": "Guardar en planilla",
        "description": (
            "Puede guardar registros aprobados por el productor en la planilla interna "
            "cuando la fuente de Google Sheets está configurada."
        ),
    },
    "envios_ya": {
        "enabled": True,
        "label": "Envíos Ya",
        "description": (
            "Puede preparar/copiar datos normalizados para Envíos Ya dentro del flujo de alta, "
            "dejando los campos manuales cuando corresponda."
        ),
    },
    "manuales_metadatos": {
        "enabled": True,
        "label": "Manuales y fichas internas",
        "description": (
            "Puede consultar manuales, PDFs y fichas internas sobre coberturas, requisitos, "
            "procedimientos, límites y condiciones de compañías."
        ),
    },
    "comparar_companias": {
        "enabled": True,
        "label": "Comparar compañías",
        "description": (
            "Puede comparar evidencia interna entre compañías para ayudar a decidir dónde "
            "colocar un riesgo, sin interpretar falta de evidencia como aceptación o rechazo."
        ),
    },
    "estudio": {
        "enabled": True,
        "label": "Estudio",
        "description": (
            "Puede usar las funciones disponibles de la sección Estudio para análisis y "
            "antecedentes internos validados por personas."
        ),
    },
    "redaccion_mail": {
        "enabled": True,
        "label": "Redactar comunicaciones",
        "description": (
            "Puede redactar mails, mensajes, notas, tickets y comunicaciones de oficina con "
            "tono claro y adecuado para clientes o compañías."
        ),
    },
    "envio_mail": {
        "enabled": True,
        "requires_config": (
            "GMAIL_SENDER_EMAIL",
            "GMAIL_OAUTH_CLIENT_ID",
            "GMAIL_OAUTH_CLIENT_SECRET",
            "GMAIL_OAUTH_REFRESH_TOKEN",
        ),
        "label": "Enviar mails",
        "description": (
            "Puede enviar mails reales desde OficinaIA sólo si la integración Gmail está "
            "configurada y el usuario lo pide explícitamente."
        ),
    },

    "resolver_cuit_arca": {
        "enabled": True,
        "requires_padron_arca": True,
        "label": "Resolver CUIT/CUIL",
        "description": (
            "Puede resolver CUIT/CUIL a partir de un DNI utilizando el padrón ARCA "
            "cargado internamente, sin inventar resultados ni depender de Gemini como base de datos."
        ),
    },
    "buscar_personas_arca": {
        "enabled": True,
        "requires_padron_arca": True,
        "label": "Buscar personas en ARCA",
        "description": (
            "Puede buscar personas reales por apellido y nombre dentro del padrón ARCA "
            "y mostrar hasta 10 candidatos reales para que el productor decida."
        ),
    },
    "cuit_desde_archivo": {
        "enabled": True,
        "requires_padron_arca": True,
        "label": "CUIT desde documentación",
        "description": (
            "Puede extraer DNI/nombre de documentación compatible y consultar ARCA "
            "cuando el usuario lo pida o el flujo operativo lo requiera."
        ),
    },
    "salud": {
        "enabled": True,
        "label": "Salud del sistema",
        "description": (
            "Puede mostrar diagnósticos y eventos operativos de Salud sin impedir que el resto "
            "del sistema continúe funcionando cuando un servicio secundario falla."
        ),
    },
}


def _runtime_ready(required: Iterable[str] | None) -> bool:
    required = tuple(required or ())
    if not required:
        return True
    return runtime_config.configured(required)


def capability_is_available(capability_id: str) -> bool:
    item = CAPABILITIES.get(str(capability_id or "")) or {}
    return bool(item.get("enabled")) and _runtime_ready(item.get("requires_config"))


def get_capabilities(*, include_unavailable: bool = True) -> dict[str, dict]:
    """Devuelve una copia segura del manifiesto con estado de runtime.

    ``enabled`` describe que la funcionalidad existe en el código. ``available``
    describe si además la configuración externa necesaria está completa en este
    proceso. Ninguno de los dos expone secretos.
    """
    salida: dict[str, dict] = {}
    for key, item in CAPABILITIES.items():
        data = deepcopy(item)
        data["id"] = key
        padron_ok = True
        if data.get("requires_padron_arca"):
            try:
                import arca_service
                padron_ok = arca_service.padron_disponible()
            except Exception:
                padron_ok = False
        data["available"] = bool(data.get("enabled")) and _runtime_ready(data.get("requires_config")) and padron_ok
        data["requires_config"] = tuple(data.get("requires_config") or ())
        data["requires_padron_arca"] = bool(data.get("requires_padron_arca"))
        if include_unavailable or data["available"]:
            salida[key] = data
    return salida


def capabilities_for_prompt() -> str:
    """Texto breve para el system prompt.

    El objetivo es que el asistente explique funcionalidades reales con lenguaje
    humano, diferencie asistencia de ejecución y no prometa integraciones cuya
    configuración falte en este runtime.
    """
    capacidades = get_capabilities(include_unavailable=True)
    disponibles = [c for c in capacidades.values() if c.get("available")]
    no_disponibles = [c for c in capacidades.values() if c.get("enabled") and not c.get("available")]

    partes = [
        "CAPACIDADES ACTUALES DE OFICINAIA:",
        "Usá esta lista como fuente central para explicar qué puede hacer el sistema. ",
        "No muestres claves internas, no inventes funciones y no digas que una acción externa está disponible si figura como no disponible por configuración.",
        "Diferenciá siempre entre informar, preparar/asistir y ejecutar una acción real.",
        "",
        "Funciones disponibles:",
    ]
    if disponibles:
        for cap in disponibles:
            partes.append(f"- {cap.get('label')}: {cap.get('description')}")
    else:
        partes.append("- No hay integraciones operativas configuradas en este proceso; podés responder y redactar, pero no prometas consultas o acciones externas.")

    if no_disponibles:
        partes.extend([
            "",
            "Funciones implementadas pero no disponibles en este runtime por configuración incompleta:",
        ])
        for cap in no_disponibles:
            partes.append(f"- {cap.get('label')}: no ofrecer como acción ejecutable hasta completar su configuración.")

    partes.extend([
        "",
        "Cuando el usuario pregunte 'qué podés hacer', explicalo con ejemplos concretos de oficina y adaptá la respuesta al nivel de detalle pedido.",
        "No respondas con un inventario técnico interminable salvo que el usuario pida explayarse.",
    ])
    return "\n".join(partes)
