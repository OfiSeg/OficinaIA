# OficinaIA — Cédula → Alta + diagnóstico Gemini

Fecha de trabajo: 2026-09-11/12
Base inicial de esta línea de trabajo: `OficinaIA_COTIZACION_ATM_CHAT_CSV_FINAL.zip`.
Última etapa aplicada sobre: `OficinaIA_CEDULA_ALTA_GEMINI_DIAGNOSTICADA.zip`.

## Cédula → Alta / asegurado

No se creó un segundo sistema de Alta.

Flujo final:

`Cédula → lectura/confirmación → Preparar alta → formulario Alta / asegurado existente → editar/completar → Guardar en Excel existente`

- La cédula aporta únicamente datos que realmente contiene y que tienen correspondencia con el Alta actual.
- No se inventan teléfono, compañía, medio de pago, precio, CP, póliza ni emisión.
- Los datos dudosos conservan una marca de revisión.
- La tarjeta de cédula mantiene recorte, alternativas e ingreso manual.
- La advertencia visual de lectura dudosa se reforzó sin agrandar la tarjeta.
- Si llegan cédula + póliza en el mismo turno, se arma **un único** Alta con ambos orígenes.
- Si dos fuentes difieren en un dato crítico, el Alta no elige en silencio: exige revisión.
- No hay guardado automático: la revisión humana sigue siendo obligatoria antes del Excel.

## Diagnóstico Gemini

### Causa de diseño encontrada

1. El chat interactivo originalmente arrancaba con un presupuesto lógico inferior al timeout máximo de una llamada Gemini. Una sola llamada lenta podía consumir todo el turno antes de dejar margen a un fallback útil.
2. Los documentos/cédulas trabajan con presupuestos mucho mayores; por eso una cédula podía terminar correctamente mientras un saludo simple fallaba.
3. La conversación trivial entraba al flujo general de OficinaIA con prompt grande, contexto y herramientas aunque no los necesitara.
4. El problema no se justificaba por un nombre de modelo retirado: los modelos configurados actualmente son `gemini-3.8-flash` y `gemini-3.5-flash-lite`.
5. Para 3.8 Flash, el razonamiento predeterminado es más costoso que lo necesario para una charla casual. El chat normal quedó configurado en `low` para priorizar latencia.

### Configuración actual aplicada

- Documentos/cédulas mantienen su ruta documental y sus presupuestos; no se reescribieron.
- Chat normal: timeout por llamada de **10 s** por defecto.
- Presupuesto total del chat: **35 s** por defecto.
- Chat normal: `thinking_level=low` por defecto, configurable.
- Saludos/charla trivial inequívoca usan una ruta mínima, sin prompt grande ni tools.
- Small talk prioriza `gemini-3.5-flash-lite` y, ante fallo transitorio, permite un segundo intento con `gemini-3.8-flash`.
- Cada intento de small talk tiene timeout de **5,5 s** por defecto.
- Si ambos intentos fallan, recién entonces usa un fallback local mínimo para no responder “Gemini no está disponible” ante un simple saludo.
- Operaciones normales mantienen hasta 3 intentos controlados y backoff; errores permanentes de autenticación/configuración fallan rápido.
- El gateway registra operación, modelo, intento, duración, categoría/código de error, tamaño aproximado de input y media, sin imprimir prompt completo ni API key.
- Se distinguen internamente `TIMEOUT`, `RATE_LIMIT`, `SERVICE_UNAVAILABLE`, `AUTH_ERROR`, `MODEL_UNAVAILABLE`, `INVALID_RESPONSE`, `JSON_ERROR`, etc.

## Qué NO se pudo comprobar aquí

El entorno de trabajo no tiene `GEMINI_API_KEY`, `google-genai` ni Flask instalados como runtime completo. Por eso no fue posible realizar una llamada real contra la cuenta/API del deploy ni medir latencia real de Render/Google.

Esto significa que el **arreglo de arquitectura, timeouts, rutas, retries y logging está validado localmente**, pero una causa externa como cuota, credencial, rate limit de la cuenta o red del deploy sólo puede confirmarse al ejecutar esta versión en el entorno real.

## Validación local

- `VALIDAR_TODO.py`: **TODO OK**.
- 18 validadores funcionales.
- `VALIDACION_CEDULA_ALTA_GEMINI.py`: 9/9 grupos OK.
- `VALIDACION_PULIDO_UI_ATM_GEMINI.py`: 9/9 grupos OK, incluyendo XLSX real → CSV Envíos Ya.
- `compileall`: OK.
- `node --check static/js/app.js`: OK.
