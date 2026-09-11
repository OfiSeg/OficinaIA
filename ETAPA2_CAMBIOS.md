# OficinaIA — ETAPA 2

Base: `OficinaIA_ETAPA1_CEDULA_PRODUCTOR_UI_FINAL.zip`.

## Objetivo

Corregir la familia de errores donde una consulta determinística sobre cartera funciona en un turno, pero un follow-up ambiguo vuelve a una búsqueda aproximada y puede seleccionar una fila real equivocada.

Caso guía: `¿cuántos emití hoy?` devuelve 1, pero `decime sus detalles` no puede terminar en una fila histórica sin fecha como GEREZ MATIAS.

## Cambios implementados

- Se agregó `office_time.py` para centralizar la fecha/hora comercial de OficinaIA en `America/Argentina/Buenos_Aires`.
- `servicios_ia.py` usa la fecha de oficina para el prompt y cálculos de año/antigüedad.
- Se agregó `buscar_registros_estructurados()` como recuperación determinística de filas reales, reutilizando `_filtrar_filas()`.
- Las filas sin fecha quedan excluidas de consultas temporales (`hoy`, `ayer`, rangos, etc.).
- `consultar_excel()` sigue existiendo como búsqueda abierta/fuzzy, pero ya no debe ser la base para afirmar relaciones temporales.
- Se agregó `excel_conversation_context.py` para manejar contexto activo de registros por chat usando filtros estructurados.
- El chat ahora intercepta antes de Gemini consultas temporales de conteo y follow-ups como `decime sus detalles`, `y la patente?`, `qué compañía?`, etc.
- Si el contexto activo devuelve 1 registro, se responde con ese registro.
- Si devuelve varios, el sistema muestra opciones y no elige arbitrariamente.
- Si no hay contexto activo, una consulta pronominal pide aclaración.
- `buscar_cliente_exactamente()` ya no depende solamente de `CLIENTE`; soporta `ASEGURADO`, `CLIENTE`, `NOMBRE` y `NOMBRE Y APELLIDO`.
- Se corrigió la semántica de `NUMERO`: sigue siendo teléfono/contacto histórico, no DNI ni número de póliza.
- `_coincidencia_identificador()` dejó de tratar `NUMERO` como identificador fuerte de póliza/DNI.
- Se agregó la herramienta `buscar_registros_estructurados` al contrato de tools para Gemini.
- Se reforzó el prompt de Excel para que use recuperación determinística en detalles exactos y no atribuya `emitida hoy` si no hay fecha.
- Se ajustó `chat_special.py` para que la intención explícita del usuario tenga prioridad sobre el tipo de adjunto.
- Una póliza adjunta con `qué cobertura tiene?` ya no dispara automáticamente el alta.
- Una cédula/licencia adjunta con pregunta puntual puede seguir al análisis general del turno en vez de ser secuestrada por la tarjeta completa.

## Validación ejecutada

- `VALIDACION_ADJUNTOS_MULTIPLES.py` → 12/12 OK
- `VALIDACION_ETAPA1_CEDULA_PRODUCTOR.py` → 7/7 OK
- `VALIDACION_ETAPA2_CONTEXTO_CARTERA.py` → 8/8 OK
- `VALIDACION_RESILIENCIA_GLOBAL.py` → 12/12 OK
- `VALIDACION_SALUD_SERVICIOS.py` → 7/7 OK
- `VALIDACION_V20_DNI_LICENCIA.py` → 13/13 OK
- `VALIDACION_V20_DOCUMENTOS_OPERATIVOS.py` → 11/11 OK
- `python -m compileall -q .` → OK

## Fuera de alcance de esta etapa

- No se implementó ARCA / CUIT.
- No se cambió la lógica funcional de reintentos de Gemini.
- No se refactorizó documentos múltiples.
- No se cambió el diseño visual de cédulas de la Etapa 1.
